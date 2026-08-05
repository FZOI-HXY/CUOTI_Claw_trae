//! LLM 清洗（RAG 扩展点）
//! 将 OCR 输出的结构化 Markdown 通过 LLM 规范化为固定 JSON 错题结构。
//! 通过 trait 抽象，后续可扩展完整 RAG 向量检索。

use async_trait::async_trait;
use serde_json::{json, Value};

use crate::error::{Error, Result};
use crate::models::{CleanedQuestion, LlmConfig};

/// 清洗器抽象：后续可扩展为本地向量检索 + LLM 的 RAG 实现
#[async_trait]
pub trait Cleaner: Send + Sync {
    /// 将 OCR 文本规范化为错题草稿
    async fn clean(&self, ocr_text: &str) -> Result<CleanedQuestion>;
    /// 基于检索上下文回答用户问题（RAG 问答）
    async fn ask(&self, question: &str, context: &str) -> Result<String>;
}

/// OpenAI 兼容 LLM 清洗实现
pub struct LlmCleaner {
    base_url: String,
    api_key: String,
    model: String,
}

impl LlmCleaner {
    pub fn new(config: &LlmConfig) -> Self {
        Self {
            base_url: config.base_url.trim_end_matches('/').to_string(),
            api_key: config.api_key.clone(),
            model: config.model.clone(),
        }
    }

    /// 校验配置：api_key/base_url 非空，且 base_url 仅允许 http(s) 协议
    fn check_config(&self) -> Result<()> {
        if self.api_key.is_empty() || self.base_url.is_empty() {
            return Err(Error::Cleaner("LLM 未配置".into()));
        }
        if !self.base_url.starts_with("https://") && !self.base_url.starts_with("http://") {
            return Err(Error::Cleaner(format!(
                "LLM base_url 必须使用 http(s) 协议: {}",
                &self.base_url[..self.base_url.len().min(60)]
            )));
        }
        Ok(())
    }

    /// 带超时的 HTTP 客户端，避免请求无限挂起
    fn client() -> reqwest::Client {
        reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(60))
            .build()
            .unwrap_or_default()
    }

    /// 截断错误响应体，避免把超长（可能含敏感信息）内容回传
    fn truncate(msg: &str) -> String {
        let m: String = msg.chars().take(200).collect();
        if msg.chars().count() > 200 {
            m + "...(truncated)"
        } else {
            m
        }
    }

    fn build_prompt(ocr_text: &str) -> String {
        format!(
            r#"你是一个错题整理助手。请把下面 OCR 识别出的题目文本，提取为严格的 JSON 对象，不要输出任何其他内容。

JSON 字段（全部可选，缺失就用 null）：
- qtype: "single"|"multiple"|"judge"|"fill"|"answer"
- title: 题干
- options: 选项数组，如 ["A. xxx","B. xxx"]
- answer: 正确答案
- analysis: 解析
- difficulty: 1-5 整数
- subject: 科目
- chapter: 知识点
- tags: 标签数组

OCR 文本：
{ocr}
"#,
            ocr = ocr_text
        )
    }

    fn build_ask_prompt(question: &str, context: &str) -> String {
        format!(
            r#"参考以下错题上下文回答用户的问题。

相关错题：
{context}

用户问题：
{question}

请给出清晰、有条理的回答，并在适当处标注引用来源（如 [1]）。"#,
            context = context,
            question = question
        )
    }
}

#[async_trait]
impl Cleaner for LlmCleaner {
    async fn clean(&self, ocr_text: &str) -> Result<CleanedQuestion> {
        self.check_config()?;

        let client = Self::client();
        let url = format!("{}/chat/completions", self.base_url);
        let body = json!({
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你只输出 JSON。"},
                {"role": "user", "content": Self::build_prompt(ocr_text)}
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"}
        });

        let resp = client
            .post(&url)
            .bearer_auth(&self.api_key)
            .json(&body)
            .send()
            .await
            .map_err(|e| Error::Cleaner(format!("调用 LLM 失败: {}", e)))?;

        if !resp.status().is_success() {
            let status = resp.status();
            let msg = resp.text().await.unwrap_or_default();
            return Err(Error::Cleaner(format!("LLM HTTP {}: {}", status, Self::truncate(&msg))));
        }

        let json: Value = resp
            .json()
            .await
            .map_err(|e| Error::Cleaner(format!("解析 LLM 响应失败: {}", e)))?;

        let content = json
            .get("choices")
            .and_then(|c| c.as_array())
            .and_then(|c| c.first())
            .and_then(|c| c.get("message"))
            .and_then(|m| m.get("content"))
            .and_then(|c| c.as_str())
            .ok_or_else(|| Error::Cleaner("LLM 响应缺少 content".into()))?;

        // 提取 JSON（可能被 markdown 代码块包裹）
        let cleaned_str = extract_json(content);

        let parsed: Value = serde_json::from_str(&cleaned_str)
            .map_err(|e| Error::Cleaner(format!("LLM 输出不是合法 JSON: {}", e)))?;

        let get = |key: &str| parsed.get(key).and_then(|v| v.as_str()).map(|s| s.to_string());
        let get_i64 = |key: &str| parsed.get(key).and_then(|v| v.as_i64());
        let get_arr = |key: &str| {
            parsed
                .get(key)
                .and_then(|v| v.as_array())
                .map(|arr| {
                    arr.iter()
                        .filter_map(|x| x.as_str().map(|s| s.to_string()))
                        .collect()
                })
        };

        Ok(CleanedQuestion {
            qtype: get("qtype"),
            title: get("title"),
            options: get_arr("options"),
            answer: get("answer"),
            analysis: get("analysis"),
            difficulty: get_i64("difficulty"),
            subject: get("subject"),
            chapter: get("chapter"),
            tags: get_arr("tags"),
        })
    }

    async fn ask(&self, question: &str, context: &str) -> Result<String> {
        self.check_config()?;

        let client = Self::client();
        let url = format!("{}/chat/completions", self.base_url);
        let body = json!({
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是错题辅导助手，基于给定题目上下文回答用户问题，需引用相关题目。若上下文不足以回答，请明确说明。"},
                {"role": "user", "content": Self::build_ask_prompt(question, context)}
            ],
            "temperature": 0.3
        });

        let resp = client
            .post(&url)
            .bearer_auth(&self.api_key)
            .json(&body)
            .send()
            .await
            .map_err(|e| Error::Cleaner(format!("调用 LLM 失败: {}", e)))?;

        if !resp.status().is_success() {
            let status = resp.status();
            let msg = resp.text().await.unwrap_or_default();
            return Err(Error::Cleaner(format!("LLM HTTP {}: {}", status, Self::truncate(&msg))));
        }

        let json: Value = resp
            .json()
            .await
            .map_err(|e| Error::Cleaner(format!("解析 LLM 响应失败: {}", e)))?;

        json.get("choices")
            .and_then(|c| c.as_array())
            .and_then(|c| c.first())
            .and_then(|c| c.get("message"))
            .and_then(|m| m.get("content"))
            .and_then(|c| c.as_str())
            .map(|s| s.to_string())
            .ok_or_else(|| Error::Cleaner("LLM 响应缺少 content".into()))
    }
}

/// 从 LLM 输出中提取 JSON 对象（去除 ```json 包裹等）
pub fn extract_json(content: &str) -> &str {
    let trimmed = content.trim();
    // 去掉 markdown 代码块围栏
    if trimmed.starts_with("```") {
        if let Some(start) = trimmed.find('{') {
            if let Some(end) = trimmed.rfind('}') {
                return &trimmed[start..=end];
            }
        }
    }
    // 直接包含 { } 的情况
    if let Some(start) = trimmed.find('{') {
        if let Some(end) = trimmed.rfind('}') {
            if end >= start {
                return &trimmed[start..=end];
            }
        }
    }
    trimmed
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_extract_json_from_code_block() {
        let s = "```json\n{\"qtype\":\"single\"}\n```";
        let out = extract_json(s);
        assert_eq!(out.replace(" ", ""), "{\"qtype\":\"single\"}");
    }

    #[test]
    fn test_extract_json_plain() {
        let s = "{\"title\":\"hello\"}";
        assert_eq!(extract_json(s), s);
    }

    #[test]
    fn test_build_ask_prompt_contains_context_and_question() {
        let prompt = LlmCleaner::build_ask_prompt("一元二次方程怎么解？", "[1] 题目: 解方程 x^2-5x+6=0");
        assert!(prompt.contains("x^2-5x+6=0"));
        assert!(prompt.contains("一元二次方程怎么解？"));
    }
}