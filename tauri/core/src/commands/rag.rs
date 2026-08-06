//! RAG 命令编排：组装 embedder / cleaner，调用 rag 服务

use crate::cleaner::LlmCleaner;
use crate::embedder;
use crate::error::Result;
use crate::models::{RagAnswer, RagSource};
use crate::rag::{self, IndexSummary};

use super::{config, AppState};

/// 问答/检索输入的最大长度上限（字符），防止超长输入造成 token 浪费
const MAX_QUERY_LEN: usize = 2000;

/// 问答：检索 + LLM 生成
pub async fn ask(state: &AppState, question: String, top_k: Option<usize>) -> Result<RagAnswer> {
    let top_k = top_k.unwrap_or(5).clamp(1, 20);
    if question.chars().count() > MAX_QUERY_LEN {
        return Err(crate::error::Error::Cleaner(format!(
            "问题过长，最多 {} 字",
            MAX_QUERY_LEN
        )));
    }
    let llm_cfg = config::get_llm_config(state).await?;
    let cleaner = LlmCleaner::new(&llm_cfg);
    rag::ask_with_rerank(
        state,
        embedder::local_embedder().await?,
        embedder::local_reranker().await?,
        &cleaner,
        &question,
        top_k,
    )
    .await
}

/// 为所有错题建立向量索引，返回索引数量
pub async fn index(state: &AppState) -> Result<usize> {
    rag::index_all(state, embedder::local_embedder().await?).await
}

/// 增量索引：仅处理无向量或已过期的错题
pub async fn index_incremental(state: &AppState) -> Result<IndexSummary> {
    rag::index_incremental(state, embedder::local_embedder().await?).await
}

/// 纯语义检索（供调试/后续语义搜索）
pub async fn retrieve(state: &AppState, query: String, top_k: Option<usize>) -> Result<Vec<RagSource>> {
    let top_k = top_k.unwrap_or(5).clamp(1, 20);
    if query.chars().count() > MAX_QUERY_LEN {
        return Err(crate::error::Error::Cleaner(format!(
            "查询过长，最多 {} 字",
            MAX_QUERY_LEN
        )));
    }
    rag::retrieve(state, embedder::local_embedder().await?, &query, top_k).await
}