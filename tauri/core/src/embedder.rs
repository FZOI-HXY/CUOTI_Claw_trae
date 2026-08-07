//! 嵌入层：trait 抽象 + 本地 fastembed 实现 + 检索纯逻辑

use std::sync::Arc;

use async_trait::async_trait;
use fastembed::{
    EmbeddingModel, InitOptions, RerankInitOptions, RerankerModel, TextEmbedding, TextRerank,
};
use tokio::sync::OnceCell;

use crate::error::{Error, Result};

/// 文本嵌入抽象：本地或 API 提供方
#[async_trait]
pub trait Embedder: Send + Sync {
    async fn embed(&self, texts: &[String]) -> Result<Vec<Vec<f32>>>;
    fn dim(&self) -> usize;
}

/// 本地 fastembed 嵌入实现（bge-small-zh-v1.5，CPU/ONNX）
#[derive(Clone)]
pub struct LocalEmbedder {
    model: Arc<TextEmbedding>,
    dim: usize,
}

impl LocalEmbedder {
    pub async fn new() -> Result<Self> {
        let (model, dim) = tokio::task::spawn_blocking(|| {
            let model = TextEmbedding::try_new(InitOptions::new(EmbeddingModel::BGESmallZHV15))
                .map_err(|e| Error::Cleaner(format!("加载嵌入模型失败: {}", e)))?;
            // fastembed 4.x 未暴露 dim()，用一次空嵌入确定输出维度
            let dim = model
                .embed(vec!["".to_string()], None)
                .map_err(|e| Error::Cleaner(format!("嵌入失败: {}", e)))?
                .first()
                .map(|v| v.len())
                .unwrap_or(0);
            Ok::<_, Error>((Arc::new(model), dim))
        })
        .await
        .map_err(|e| Error::Cleaner(format!("嵌入模型线程失败: {}", e)))??;

        Ok(Self { model, dim })
    }
}

#[async_trait]
impl Embedder for LocalEmbedder {
    async fn embed(&self, texts: &[String]) -> Result<Vec<Vec<f32>>> {
        let model = Arc::clone(&self.model);
        let texts = texts.to_vec();
        tokio::task::spawn_blocking(move || model.embed(texts, None))
            .await
            .map_err(|e| Error::Cleaner(format!("嵌入线程失败: {}", e)))?
            .map_err(|e| Error::Cleaner(format!("嵌入失败: {}", e)))
    }

    fn dim(&self) -> usize {
        self.dim
    }
}

/// 交叉编码重排抽象：对 query 与候选文档打分排序（cross-encoder）
#[async_trait]
pub trait Reranker: Send + Sync {
    /// 返回与 documents 一一对应的相关性分数（越高越相关）
    async fn rerank(&self, query: &str, documents: &[String]) -> Result<Vec<f32>>;
}

/// 本地 fastembed 重排实现（bge-reranker-base，中英双语，CPU/ONNX）
#[derive(Clone)]
pub struct LocalReranker {
    model: Arc<TextRerank>,
}

impl LocalReranker {
    pub async fn new() -> Result<Self> {
        let model = tokio::task::spawn_blocking(|| {
            TextRerank::try_new(RerankInitOptions::new(RerankerModel::BGERerankerBase))
                .map_err(|e| Error::Cleaner(format!("加载重排模型失败: {}", e)))
        })
        .await
        .map_err(|e| Error::Cleaner(format!("重排模型线程失败: {}", e)))??;
        Ok(Self {
            model: Arc::new(model),
        })
    }
}

#[async_trait]
impl Reranker for LocalReranker {
    async fn rerank(&self, query: &str, documents: &[String]) -> Result<Vec<f32>> {
        let model = Arc::clone(&self.model);
        let query = query.to_string();
        let documents = documents.to_vec();
        tokio::task::spawn_blocking(move || {
            let results = model
                .rerank(query, documents.clone(), false, None)
                .map_err(|e| Error::Cleaner(format!("重排失败: {}", e)))?;
            // fastembed 返回按分数降序的索引结果，需还原为与原文档对应的顺序
            let mut scores = vec![0.0f32; documents.len()];
            for r in &results {
                if r.index < scores.len() {
                    scores[r.index] = r.score;
                }
            }
            Ok(scores)
        })
        .await
        .map_err(|e| Error::Cleaner(format!("重排线程失败: {}", e)))?
    }
}

/// 云端 OpenAI 兼容 Embedding 实现（阿里云百炼等）。
/// 仅持有请求所需配置，每次嵌入新建 HTTP 客户端，无本地模型加载。
pub struct ApiEmbedder {
    base_url: String,
    api_key: String,
    model: String,
    dim: usize,
}

impl ApiEmbedder {
    pub fn new(base_url: &str, api_key: &str, model: &str, dim: usize) -> Self {
        Self {
            base_url: base_url.trim_end_matches('/').to_string(),
            api_key: api_key.to_string(),
            model: model.to_string(),
            dim,
        }
    }

    /// 带超时的 HTTP 客户端，避免请求无限挂起
    fn client() -> reqwest::Client {
        reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(60))
            .build()
            .unwrap_or_default()
    }
}

#[async_trait]
impl Embedder for ApiEmbedder {
    async fn embed(&self, texts: &[String]) -> Result<Vec<Vec<f32>>> {
        if texts.is_empty() {
            return Ok(Vec::new());
        }
        let client = Self::client();
        let url = format!("{}/embeddings", self.base_url);
        let body = serde_json::json!({
            "model": self.model,
            "input": texts,
            "dimensions": self.dim,
            "encoding_format": "float"
        });
        let resp = client
            .post(&url)
            .bearer_auth(&self.api_key)
            .json(&body)
            .send()
            .await
            .map_err(|e| Error::Cleaner(format!("调用向量 API 失败: {}", e)))?;
        if !resp.status().is_success() {
            let status = resp.status();
            let msg = resp.text().await.unwrap_or_default();
            return Err(Error::Cleaner(format!(
                "向量 API HTTP {}: {}",
                status,
                msg.chars().take(200).collect::<String>()
            )));
        }
        let text = resp
            .text()
            .await
            .map_err(|e| Error::Cleaner(format!("读取向量响应失败: {}", e)))?;
        parse_embeddings_response(&text)
    }

    fn dim(&self) -> usize {
        self.dim
    }
}

/// 解析 OpenAI 兼容 embeddings 响应 → 向量列表。
/// 纯函数便于单测：`{"data":[{"embedding":[...],"index":0},...]}`。
pub fn parse_embeddings_response(json: &str) -> Result<Vec<Vec<f32>>> {
    let v: serde_json::Value = serde_json::from_str(json)
        .map_err(|e| Error::Cleaner(format!("解析向量响应失败: {}", e)))?;
    let data = v
        .get("data")
        .and_then(|d| d.as_array())
        .ok_or_else(|| Error::Cleaner("向量响应缺少 data".into()))?;
    let mut out = Vec::with_capacity(data.len());
    for item in data {
        let emb = item
            .get("embedding")
            .and_then(|e| e.as_array())
            .ok_or_else(|| Error::Cleaner("向量条目缺少 embedding".into()))?;
        let vec: Vec<f32> = emb
            .iter()
            .filter_map(|x| x.as_f64().map(|f| f as f32))
            .collect();
        if vec.is_empty() {
            return Err(Error::Cleaner("向量条目为空".into()));
        }
        out.push(vec);
    }
    Ok(out)
}

/// 全局单例：整个应用只加载一次本地重排模型
static LOCAL_RERANKER: OnceCell<LocalReranker> = OnceCell::const_new();

/// 获取本地重排器单例（懒加载）
pub async fn local_reranker() -> Result<&'static LocalReranker> {
    LOCAL_RERANKER.get_or_try_init(LocalReranker::new).await
}

/// 全局单例：整个应用只加载一次本地模型
static LOCAL_EMBEDDER: OnceCell<LocalEmbedder> = OnceCell::const_new();

/// 获取本地嵌入器单例（懒加载）
pub async fn local_embedder() -> Result<&'static LocalEmbedder> {
    LOCAL_EMBEDDER.get_or_try_init(LocalEmbedder::new).await
}

/// 余弦相似度（空向量或维度不一致返回 0）
pub fn cosine_similarity(a: &[f32], b: &[f32]) -> f32 {
    if a.len() != b.len() || a.is_empty() {
        return 0.0;
    }
    let mut dot = 0.0f32;
    let mut na = 0.0f32;
    let mut nb = 0.0f32;
    for i in 0..a.len() {
        dot += a[i] * b[i];
        na += a[i] * a[i];
        nb += b[i] * b[i];
    }
    if na == 0.0 || nb == 0.0 {
        return 0.0;
    }
    dot / (na.sqrt() * nb.sqrt())
}

/// 取相似度最高的前 k 个（返回 (id, score)，按 score 降序）
pub fn top_k_scores(scores: Vec<(i64, f32)>, k: usize) -> Vec<(i64, f32)> {
    let mut v = scores;
    v.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    v.truncate(k);
    v
}

/// f32 向量 → BLOB（little-endian）
pub fn encode_vec(v: &[f32]) -> Vec<u8> {
    let mut bytes = Vec::with_capacity(v.len() * 4);
    for x in v {
        bytes.extend_from_slice(&x.to_le_bytes());
    }
    bytes
}

/// BLOB → f32 向量
pub fn decode_vec(bytes: &[u8]) -> Vec<f32> {
    bytes
        .chunks_exact(4)
        .map(|c| f32::from_le_bytes([c[0], c[1], c[2], c[3]]))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_cosine_identical() {
        let a = [1.0, 2.0, 3.0];
        assert!((cosine_similarity(&a, &a) - 1.0).abs() < 1e-6);
    }

    #[test]
    fn test_cosine_orthogonal_is_zero() {
        let a = [1.0, 0.0];
        let b = [0.0, 1.0];
        assert!(cosine_similarity(&a, &b).abs() < 1e-6);
    }

    #[test]
    fn test_cosine_opposite_is_negative_one() {
        let a = [1.0, 2.0];
        let b = [-1.0, -2.0];
        assert!((cosine_similarity(&a, &b) + 1.0).abs() < 1e-6);
    }

    #[test]
    fn test_cosine_zero_vector_returns_zero() {
        assert_eq!(cosine_similarity(&[0.0, 0.0], &[1.0, 1.0]), 0.0);
    }

    #[test]
    fn test_top_k_sorted_desc_and_truncated() {
        let scores = vec![(1, 0.3), (2, 0.9), (3, 0.5), (4, 0.7)];
        let top = top_k_scores(scores, 2);
        assert_eq!(top, vec![(2, 0.9), (4, 0.7)]);
    }

    #[test]
    fn test_vec_codec_roundtrip() {
        let v = vec![1.5, -2.25, 0.0, 3.0];
        assert_eq!(decode_vec(&encode_vec(&v)), v);
    }

    #[test]
    fn test_parse_embeddings_response_ok() {
        let json = r#"{"data":[{"embedding":[0.1,0.2,-0.3],"index":0,"object":"embedding"}],"model":"text-embedding-v4","object":"list"}"#;
        let out = parse_embeddings_response(json).unwrap();
        assert_eq!(out, vec![vec![0.1f32, 0.2, -0.3]]);
    }

    #[test]
    fn test_parse_embeddings_response_empty() {
        let json = r#"{"data":[],"object":"list"}"#;
        let out = parse_embeddings_response(json).unwrap();
        assert!(out.is_empty());
    }

    #[test]
    fn test_parse_embeddings_response_missing_data() {
        let json = r#"{"error":"bad"}"#;
        assert!(parse_embeddings_response(json).is_err());
    }

    #[test]
    fn test_parse_embeddings_response_empty_embedding_is_err() {
        let json = r#"{"data":[{"embedding":[],"index":0}]}"#;
        assert!(parse_embeddings_response(json).is_err());
    }

    #[test]
    fn test_api_embedder_dim_and_url_trim() {
        let e = ApiEmbedder::new("https://x.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/", "k", "text-embedding-v4", 512);
        assert_eq!(e.dim(), 512);
        assert!(!e.base_url.ends_with('/'));
    }
}