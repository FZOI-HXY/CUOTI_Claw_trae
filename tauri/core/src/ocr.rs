//! PaddleOCR 云 API 服务封装
//! 复刻原项目 async submit → poll → download → parse 流程
//! 支持 VL 模型直接输出结构化 Markdown

use reqwest::header::{HeaderMap, HeaderValue, AUTHORIZATION, CONTENT_TYPE};
use reqwest::multipart::{Form, Part};
use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use url::Url;

use crate::error::{Error, Result};

const DEFAULT_POLL_INTERVAL: u64 = 5;
const DEFAULT_POLL_MAX_RETRIES: u32 = 60;

// 错误码映射（来自原项目）
fn map_error_code(code: i32) -> &'static str {
    match code {
        401 => "Token无效，请检查 access_token",
        10001 => "空文件，请检查文件内容",
        10002 => "文件URL无法识别，请检查URL有效性",
        10003 => "文件大小超限（本地文件≤50MB，文件链接≤200MB）",
        10004 => "文件格式不支持，请检查文件类型",
        10005 => "文件内容无法解析",
        10006 => "文件页数超过限制（单次≤1000页）",
        10007 => "模型参数错误，请检查模型名称",
        10008 => "请求参数错误，请检查 optionalPayload",
        10009 => "同一 batchId 任务数超限（≤100条）",
        10010 => "任务队列已满，请稍后重试",
        11001 => "jobId 不存在，请检查 jobId",
        11002 => "job 已过期，请重新提交",
        12001 => "每日页数上限，请查看配额说明",
        12002 => "请求频率过高，请降低频率",
        _ => "未知错误",
    }
}

#[derive(Debug, Deserialize)]
struct ApiResponse<T> {
    code: Option<i32>,
    #[allow(dead_code)]
    error_msg: Option<String>,
    data: T,
}

#[derive(Debug, Deserialize)]
pub enum PollState {
    #[serde(rename = "pending")]
    Pending,
    #[serde(rename = "running")]
    Running,
    #[serde(rename = "done")]
    Done,
    #[serde(rename = "failed")]
    Failed,
    #[serde(other)]
    Other,
}

#[derive(Debug, Deserialize)]
pub struct Progress {
    pub extracted_pages: Option<i32>,
    pub total_pages: Option<i32>,
}

#[derive(Debug, Deserialize)]
pub struct ResultUrl {
    pub json_url: Option<String>,
    pub markdown_url: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct PollResult {
    pub state: PollState,
    pub progress: Option<Progress>,
    pub result_url: Option<ResultUrl>,
    pub error_msg: Option<String>,
}

/// PaddleOCR 提取结果
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OcrResult {
    pub success: bool,
    pub job_id: String,
    pub markdown_text: String,
    pub images: HashMap<String, String>,
    pub json_text: Option<String>,
    pub error: Option<String>,
}

#[derive(Clone)]
pub struct PaddleOcrService {
    job_url: String,
    api_key: String,
    model: String,
    client: Client,
}

impl PaddleOcrService {
    pub fn new(api_url: String, api_key: String, model: Option<String>) -> Self {
        let job_url = api_url.trim_end_matches('/').to_string();
        let model = model.unwrap_or_else(|| "PaddleOCR-VL-1.6".to_string());
        let client = Client::builder()
            .connect_timeout(std::time::Duration::from_secs(10))
            .timeout(std::time::Duration::from_secs(60))
            .build()
            .expect("build client");
        Self {
            job_url,
            api_key,
            model,
            client,
        }
    }

    pub fn is_configured(&self) -> bool {
        !self.api_key.is_empty() && !self.job_url.is_empty()
    }

    fn build_headers(&self, content_type: Option<&str>) -> HeaderMap {
        let mut headers = HeaderMap::new();
        if let Ok(v) = HeaderValue::from_str(&format!("Bearer {}", self.api_key)) {
            headers.insert(AUTHORIZATION, v);
        }
        if let Some(ct) = content_type {
            if let Ok(v) = HeaderValue::from_str(ct) {
                headers.insert(CONTENT_TYPE, v);
            }
        }
        headers
    }

    /// optionalPayload 按模型类型设置参数（参考原项目）
    fn optional_payload(&self) -> serde_json::Value {
        // VL 模型和 Structure 模型
        if self.model.starts_with("PaddleOCR-VL") || self.model == "PP-StructureV3" {
            serde_json::json!({
                "useDocOrientationClassify": false,
                "useDocUnwarping": false,
                "useChartRecognition": false,
            })
        } else {
            // 纯 OCR
            serde_json::json!({
                "useDocOrientationClassify": false,
                "useDocUnwarping": false,
                "useTextlineOrientation": false,
            })
        }
    }

    // SSRF 防护（同原项目 _validate_result_url / _is_internal_ip）
    fn validate_result_url(url: &str) -> Result<()> {
        if url.is_empty() {
            return Err(Error::Ocr("结果 URL 为空".into()));
        }
        if !url.starts_with("https://") && !url.starts_with("http://") {
            return Err(Error::Ocr(format!(
                "结果 URL 必须使用 http(s) 协议: {}",
                &url[..url.len().min(80)]
            )));
        }
        let parsed = match Url::parse(url) {
            Ok(u) => u,
            Err(e) => return Err(Error::Ocr(format!("结果 URL 解析失败: {}", e)))
        };
        let host = match parsed.host_str() {
            Some(h) if !h.is_empty() => h,
            _ => return Err(Error::Ocr("结果 URL 主机名无效".into())),
        };
        // 简单检查 localhost 和内网网段（完整实现需 DNS 解析，这里做基本防护）
        if is_local_host(host) {
            return Err(Error::Ocr(format!(
                "结果 URL 不允许指向内网地址或 localhost: {}",
                &url[..url.len().min(80)]
            )));
        }
        Ok(())
    }

    /// 提交异步任务（multipart 本地文件）
    pub async fn submit_task(
        &self,
        image_data: Vec<u8>,
        filename: &str,
        page_ranges: Option<&str>,
        batch_id: Option<&str>,
    ) -> Result<String> {
        // optionalPayload 需要序列化为 JSON string 在 multipart
        let payload = self.optional_payload();
        let payload_str = serde_json::to_string(&payload)
            .map_err(|e| Error::Ocr(format!("序列化 payload 失败: {}", e)))?;

        let file_part = Part::bytes(image_data)
            .file_name(filename.to_string())
            .mime_str("image/*")
            .map_err(|e| Error::Ocr(format!("构建文件 part 失败: {}", e)))?;

        let mut form = Form::new()
            .text("model", self.model.clone())
            .text("optionalPayload", payload_str);
        if let Some(p) = page_ranges {
            form = form.text("pageRanges", p.to_string());
        }
        if let Some(b) = batch_id {
            form = form.text("batchId", b.to_string());
        }
        form = form.part("file", file_part);

        let url = format!("{}/api/v2/ocr/jobs", self.job_url);
        let request = self
            .client
            .post(&url)
            .headers(self.build_headers(None))
            .multipart(form);

        let response = request.send().await.map_err(|e| {
            Error::Network(format!("提交 OCR 任务网络错误: {}", e))
        })?;

        if !response.status().is_success() {
            let status = response.status();
            let msg = response.text().await.unwrap_or_default();
            return Err(Error::Ocr(format!("提交失败 HTTP {}: {}", status, msg)));
        }

        let resp: ApiResponse<serde_json::Value> = response
            .json()
            .await
            .map_err(|e| Error::Ocr(format!("解析响应失败: {}", e)))?;

        if let Some(code) = resp.code {
            if code != 0 {
                let msg = map_error_code(code);
                return Err(Error::Ocr(format!("[{}] {}", code, msg)));
            }
        }

        let job_id = resp.data.get("jobId").and_then(|v| v.as_str());
        match job_id {
            Some(jid) => Ok(jid.to_string()),
            None => {
                let error_msg = resp
                    .data
                    .get("errorMsg")
                    .and_then(|v| v.as_str())
                    .unwrap_or("jobId 为空");
                Err(Error::Ocr(format!("API 返回异常: {}", error_msg)))
            }
        }
    }

    /// 单次轮询任务状态
    pub async fn poll_once(&self, job_id: &str) -> Result<PollResult> {
        let url = format!("{}/api/v2/ocr/jobs/{}", self.job_url, job_id);
        let response = self
            .client
            .get(&url)
            .headers(self.build_headers(None))
            .send()
            .await
            .map_err(|e| Error::Network(format!("轮询网络错误: {}", e)))?;

        if !response.status().is_success() {
            let status = response.status();
            let msg = response.text().await.unwrap_or_default();
            return Err(Error::Ocr(format!("轮询失败 HTTP {}: {}", status, msg)));
        }

        let resp: ApiResponse<serde_json::Value> = response
            .json()
            .await
            .map_err(|e| Error::Ocr(format!("解析轮询响应失败: {}", e)))?;

        if let Some(code) = resp.code {
            if code != 0 {
                let msg = map_error_code(code);
                return Err(Error::Ocr(format!("[{}] {}", code, msg)));
            }
        }

        let state: PollState = serde_json::from_value(resp.data.clone())
            .unwrap_or_else(|_| PollState::Other);
        let progress = resp.data.get("extractProgress").and_then(|v| {
            serde_json::from_value(v.clone()).ok()
        });
        let result_url = resp.data.get("resultUrl").and_then(|v| {
            serde_json::from_value(v.clone()).ok()
        });

        let error_msg = resp
            .data
            .get("errorMsg")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());

        Ok(PollResult {
            state,
            progress,
            result_url,
            error_msg,
        })
    }

    async fn download_text(&self, url: &str) -> Result<String> {
        Self::validate_result_url(url)?;
        // SSRF 增强：解析 DNS，防止主机名重绑定到内网地址
        reject_local_dns(url).await?;
        let resp = self
            .client
            .get(url)
            .header("Cache-Control", "no-cache, no-store")
            .send()
            .await
            .map_err(|e| Error::Network(format!("下载结果失败: {}", e)))?;
        resp.text().await.map_err(|e| {
            Error::Network(format!("读取结果失败: {}", e))
        })
    }

    /// 解析 JSON/JSONL 结果提取 Markdown 文本
    pub fn extract_result(json_text: &str, markdown_text: Option<&str>) -> OcrResult {
        // 优先直接使用返回的 markdown_text
        if let Some(md) = markdown_text {
            if !md.is_empty() {
                return OcrResult {
                    success: true,
                    job_id: "".into(),
                    markdown_text: md.to_string(),
                    images: HashMap::new(),
                    json_text: Some(json_text.to_string()),
                    error: None,
                };
            }
        }

        let mut extracted_md = Vec::new();
        let mut all_images = HashMap::new();

        // 先试标准 JSON
        if let Ok(obj) = serde_json::from_str::<serde_json::Value>(json_text) {
            Self::extract_from_obj(&obj, &mut extracted_md, &mut all_images);
        } else {
            // 试 JSONL 每行
            for line in json_text.lines() {
                let line = line.trim();
                if line.is_empty() {
                    continue;
                }
                if let Ok(obj) = serde_json::from_str::<serde_json::Value>(line) {
                    Self::extract_from_obj(&obj, &mut extracted_md, &mut all_images);
                }
            }
        }

        let markdown = extracted_md.join("\n\n");
        let error = if markdown.is_empty() && all_images.is_empty() {
            Some("未提取到有效的 OCR 数据".into())
        } else {
            None
        };
        OcrResult {
            success: !markdown.is_empty() || !all_images.is_empty(),
            job_id: "".into(),
            markdown_text: markdown,
            images: all_images,
            json_text: Some(json_text.to_string()),
            error,
        }
    }

    fn extract_from_obj(
        obj: &serde_json::Value,
        extracted_md: &mut Vec<String>,
        images: &mut HashMap<String, String>,
    ) {
        let result = obj.get("result").unwrap_or(obj);

        // VL / Structure → layoutParsingResults[] → item.markdown.text
        if let Some(items) = result.get("layoutParsingResults").and_then(|v| v.as_array()) {
            for (idx, item) in items.iter().enumerate() {
                let markdown = item
                    .get("markdown")
                    .or_else(|| item.get("prunedResult").and_then(|p| p.get("markdown")));
                if let Some(md) = markdown {
                    if let Some(text) = md.get("text").and_then(|t| t.as_str()) {
                        if !text.is_empty() {
                            extracted_md.push(text.to_string());
                        }
                    }
                    if let Some(img_map) = md.get("images").and_then(|i| i.as_object()) {
                        for (k, v) in img_map {
                            if let Some(url) = v.as_str() {
                                images.insert(format!("img_{}_{}", idx, k), url.to_string());
                            }
                        }
                    }
                }
            }
        } else if let Some(items) = result.get("ocrResults").and_then(|v| v.as_array()) {
            // PP-OCRv6/v5 → ocrResults[]
            for item in items.iter() {
                if let Some(text) = item.get("ocrImage").and_then(|t| t.as_str()) {
                    if !text.is_empty() {
                        extracted_md.push(text.to_string());
                    }
                }
            }
        }
    }

    /// 提交任务并轮询直到完成
    pub async fn submit_and_poll(
        &self,
        image_data: Vec<u8>,
        filename: &str,
    ) -> Result<OcrResult> {
        let job_id = self.submit_task(image_data, filename, None, None).await?;
        let mut retries = 0;
        let max_retries = DEFAULT_POLL_MAX_RETRIES;
        let interval = DEFAULT_POLL_INTERVAL;

        while retries < max_retries {
            let poll = self.poll_once(&job_id).await?;
            match poll.state {
                PollState::Done => {
                    if let Some(urls) = poll.result_url {
                        let mut json_text = None;
                        let mut markdown_text = None;

                        if let Some(json_url) = urls.json_url.filter(|u| !u.is_empty()) {
                            json_text = Some(self.download_text(&json_url).await?);
                        }
                        if let Some(md_url) = urls.markdown_url.filter(|u| !u.is_empty()) {
                            markdown_text = Some(self.download_text(&md_url).await?);
                        }

                        let mut result = Self::extract_result(
                            json_text.as_deref().unwrap_or(""),
                            markdown_text.as_deref(),
                        );
                        result.job_id = job_id;
                        return Ok(result);
                    } else {
                        return Err(Error::Ocr("完成后无结果 URL".into()));
                    }
                }
                PollState::Failed => {
                    let msg = poll
                        .error_msg
                        .unwrap_or_else(|| "任务失败".into());
                    return Err(Error::Ocr(msg));
                }
                PollState::Pending | PollState::Running => {
                    retries += 1;
                    tokio::time::sleep(std::time::Duration::from_secs(interval)).await;
                }
                PollState::Other => {
                    retries += 1;
                    tokio::time::sleep(std::time::Duration::from_secs(interval)).await;
                }
            }
        }

        Err(Error::Ocr(format!(
            "轮询超时，超过 {} 次重试",
            max_retries
        )))
    }
}

/// 判断主机是否为 localhost 或内网地址（基本防护，完整实现需 DNS 解析）
fn is_local_host(host: &str) -> bool {
    if host == "localhost" || host.ends_with(".local") || host == "127.0.0.1" {
        return true;
    }
    // 内网网段
    if host.starts_with("10.")
        || host.starts_with("172.16.")
        || host.starts_with("172.17.")
        || host.starts_with("172.18.")
        || host.starts_with("172.19.")
        || host.starts_with("172.2")
        || host.starts_with("172.30.")
        || host.starts_with("172.31.")
        || host.starts_with("192.168.")
        || host.starts_with("169.254.")
    {
        return true;
    }
    // IPv6 本地地址
    host.starts_with("::1") || host.starts_with("fd") && host.contains(':')
}

/// 判断 IP 是否为内网/环回/链路本地/未指定地址（DNS 解析后的 IP 校验用）
fn is_private_ip(ip: &std::net::IpAddr) -> bool {
    match ip {
        std::net::IpAddr::V4(v4) => {
            v4.is_private()
                || v4.is_loopback()
                || v4.is_link_local()
                || v4.is_broadcast()
                || v4.is_unspecified()
        }
        std::net::IpAddr::V6(v6) => {
            v6.is_loopback() || v6.is_unspecified() || v6.is_unique_local()
        }
    }
}

/// 解析主机名并拒绝解析到内网/环回/链路本地地址的 URL（防 DNS 重绑定）。
/// IP 字面量已在 `validate_result_url` 静态校验，这里只处理主机名。
async fn reject_local_dns(url: &str) -> Result<()> {
    let parsed = Url::parse(url).map_err(|e| Error::Ocr(format!("结果 URL 解析失败: {}", e)))?;
    let host = parsed.host_str().unwrap_or("");
    // IP 字面量已由静态校验处理，跳过
    if host.parse::<std::net::IpAddr>().is_ok() {
        return Ok(());
    }
    let port = parsed.port_or_known_default().unwrap_or(443);
    let addrs = tokio::net::lookup_host((host, port))
        .await
        .map_err(|e| Error::Ocr(format!("结果 URL 主机 DNS 解析失败: {}", e)))?;
    for addr in addrs {
        if is_private_ip(&addr.ip()) {
            return Err(Error::Ocr(format!(
                "结果 URL 解析到内网地址，已拒绝: {}",
                host
            )));
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    // ---- 错误码映射 ----
    #[test]
    fn test_map_error_code_known() {
        assert_eq!(map_error_code(401), "Token无效，请检查 access_token");
        assert_eq!(map_error_code(10001), "空文件，请检查文件内容");
        assert_eq!(map_error_code(10007), "模型参数错误，请检查模型名称");
        assert_eq!(map_error_code(12001), "每日页数上限，请查看配额说明");
    }

    #[test]
    fn test_map_error_code_unknown() {
        assert_eq!(map_error_code(99999), "未知错误");
    }

    // ---- SSRF 防护：is_local_host ----
    #[test]
    fn test_is_local_host_true_cases() {
        assert!(is_local_host("localhost"));
        assert!(is_local_host("127.0.0.1"));
        assert!(is_local_host("myhost.local"));
        assert!(is_local_host("10.0.0.1"));
        assert!(is_local_host("192.168.1.1"));
        assert!(is_local_host("172.16.0.1"));
        assert!(is_local_host("172.31.255.255"));
        assert!(is_local_host("169.254.169.254"));
        assert!(is_local_host("::1"));
    }

    #[test]
    fn test_is_local_host_false_cases() {
        assert!(!is_local_host("example.com"));
        assert!(!is_local_host("8.8.8.8"));
        assert!(!is_local_host("api.paddle.com"));
        assert!(!is_local_host("172.32.0.1")); // 172.32 不在内网段
        assert!(!is_local_host("203.0.113.7"));
    }

    // ---- SSRF 增强：is_private_ip ----
    #[test]
    fn test_is_private_ip_true() {
        use std::net::IpAddr;
        for ip in [
            "127.0.0.1",
            "10.0.0.1",
            "192.168.1.1",
            "172.16.0.1",
            "172.31.255.255",
            "169.254.1.1",
            "0.0.0.0",
            "::1",
        ] {
            assert!(is_private_ip(&ip.parse::<IpAddr>().unwrap()), "{}", ip);
        }
    }

    #[test]
    fn test_is_private_ip_false() {
        use std::net::IpAddr;
        for ip in ["8.8.8.8", "1.1.1.1", "172.32.0.1", "203.0.113.7"] {
            assert!(!is_private_ip(&ip.parse::<IpAddr>().unwrap()), "{}", ip);
        }
    }

    // ---- SSRF 防护：validate_result_url ----
    #[test]
    fn test_validate_result_url_rejects_empty() {
        assert!(PaddleOcrService::validate_result_url("").is_err());
    }

    #[test]
    fn test_validate_result_url_rejects_non_http() {
        assert!(PaddleOcrService::validate_result_url("ftp://example.com/x").is_err());
    }

    #[test]
    fn test_validate_result_url_rejects_localhost() {
        assert!(PaddleOcrService::validate_result_url("https://localhost:8080/result").is_err());
        assert!(PaddleOcrService::validate_result_url("http://127.0.0.1/result").is_err());
    }

    #[test]
    fn test_validate_result_url_rejects_internal_ip() {
        assert!(PaddleOcrService::validate_result_url("http://192.168.1.10/result").is_err());
        assert!(PaddleOcrService::validate_result_url("http://10.0.0.5/result").is_err());
    }

    #[test]
    fn test_validate_result_url_rejects_invalid_url() {
        assert!(PaddleOcrService::validate_result_url("://bad").is_err());
    }

    #[test]
    fn test_validate_result_url_accepts_external_https() {
        assert!(PaddleOcrService::validate_result_url("https://paddle-external.com/result.json").is_ok());
    }

    // ---- extract_result 分支 ----
    #[test]
    fn test_extract_uses_markdown_text_directly() {
        let r = PaddleOcrService::extract_result("{}", Some("# 直接结果"));
        assert!(r.success);
        assert_eq!(r.markdown_text, "# 直接结果");
    }

    #[test]
    fn test_extract_single_json_vl_structure() {
        let json = r##"{"result":{"layoutParsingResults":[{"markdown":{"text":"# 题目\nx=2"}}]}}"##;
        let r = PaddleOcrService::extract_result(json, None);
        assert!(r.success);
        assert!(r.markdown_text.contains("x=2"));
    }

    #[test]
    fn test_extract_jsonl_multiple_lines() {
        let jsonl = r#"
{"result":{"layoutParsingResults":[{"markdown":{"text":"第一段"}}]}}
{"result":{"layoutParsingResults":[{"markdown":{"text":"第二段"}}]}}
"#;
        let r = PaddleOcrService::extract_result(jsonl, None);
        assert!(r.success);
        assert!(r.markdown_text.contains("第一段"));
        assert!(r.markdown_text.contains("第二段"));
    }

    #[test]
    fn test_extract_ocr_results_pp_ocr() {
        let json = r##"{"result":{"ocrResults":[{"ocrImage":"纯文本行A"},{"ocrImage":"纯文本行B"}]}}"##;
        let r = PaddleOcrService::extract_result(json, None);
        assert!(r.success);
        assert!(r.markdown_text.contains("纯文本行A"));
        assert!(r.markdown_text.contains("纯文本行B"));
    }

    #[test]
    fn test_extract_images() {
        let json = r##"{"result":{"layoutParsingResults":[{"markdown":{"text":"图","images":{"1":"https://img.example.com/a.png"}}}]}}"##;
        let r = PaddleOcrService::extract_result(json, None);
        assert!(r.success);
        assert_eq!(r.images.len(), 1);
        assert!(r.images.values().any(|u| u == "https://img.example.com/a.png"));
    }

    #[test]
    fn test_extract_empty_gives_error() {
        let r = PaddleOcrService::extract_result("{\"noop\":true}", None);
        assert!(!r.success);
        assert!(r.error.is_some());
    }

    // ---- optional_payload 模型分支 ----
    #[test]
    fn test_optional_payload_vl_model() {
        let svc = PaddleOcrService::new("http://x".into(), "k".into(), Some("PaddleOCR-VL-1.6".into()));
        let p = svc.optional_payload();
        assert!(p.get("useDocUnwarping").is_some());
        assert!(p.get("useTextlineOrientation").is_none());
    }

    #[test]
    fn test_optional_payload_pure_ocr() {
        let svc = PaddleOcrService::new("http://x".into(), "k".into(), Some("PaddleOCRv6".into()));
        let p = svc.optional_payload();
        // 纯 OCR 分支：有 useTextlineOrientation，无 useChartRecognition
        assert!(p.get("useTextlineOrientation").is_some());
        assert!(p.get("useChartRecognition").is_none());
    }
}