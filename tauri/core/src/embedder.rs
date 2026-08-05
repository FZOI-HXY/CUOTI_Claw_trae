//! 嵌入层：trait 抽象 + 本地 fastembed 实现 + 检索纯逻辑

use async_trait::async_trait;

use crate::error::{Error, Result};

/// 文本嵌入抽象：本地或 API 提供方
#[async_trait]
pub trait Embedder: Send + Sync {
    async fn embed(&self, texts: &[String]) -> Result<Vec<Vec<f32>>>;
    fn dim(&self) -> usize;
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