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
}