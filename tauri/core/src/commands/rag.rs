//! RAG 命令编排：组装 embedder / cleaner，调用 rag 服务

use crate::cleaner::LlmCleaner;
use crate::embedder::{self, ApiEmbedder, Embedder};
use crate::error::{Error, Result};
use crate::models::{RagAnswer, RagSource};
use crate::rag::{self, IndexSummary};

use super::{config, AppState};

/// 问答/检索输入的最大长度上限（字符），防止超长输入造成 token 浪费
const MAX_QUERY_LEN: usize = 2000;

/// 云端嵌入维度（text-embedding-v4 默认 1024，质量更高，作为主用）。
/// 本地 bge-small-zh-v1.5 为 512 维轻量兜底，二者维度不同，切换 provider 后需重建索引。
const API_EMBED_DIM: usize = 1024;

/// 按配置选择嵌入器：`embed_provider=api` 走百炼云端，否则用本地 fastembed。
/// base_url/api_key 复用 LLM 配置（同一百炼业务空间），模型名用 `embed_model`。
pub async fn current_embedder(state: &AppState) -> Result<Box<dyn Embedder>> {
    let (provider, model) = config::get_embed_config(state).await?;
    if provider == "api" {
        let llm = config::get_llm_config(state).await?;
        if llm.base_url.is_empty() || llm.api_key.is_empty() {
            return Err(Error::Cleaner(
                "使用 API 嵌入需先在设置中配置 LLM base_url 与 api_key".into(),
            ));
        }
        Ok(Box::new(ApiEmbedder::new(
            &llm.base_url,
            &llm.api_key,
            &model,
            API_EMBED_DIM,
        )))
    } else {
        Ok(Box::new(embedder::local_embedder().await?.clone()))
    }
}

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
    let embedder = current_embedder(state).await?;
    if config::get_rerank_enabled(state).await {
        rag::ask_with_rerank(
            state,
            embedder.as_ref(),
            embedder::local_reranker().await?,
            &cleaner,
            &question,
            top_k,
        )
        .await
    } else {
        rag::ask(state, embedder.as_ref(), &cleaner, &question, top_k).await
    }
}

/// 为所有错题建立向量索引，返回索引数量
pub async fn index(state: &AppState) -> Result<usize> {
    let embedder = current_embedder(state).await?;
    rag::index_all(state, embedder.as_ref()).await
}

/// 增量索引：仅处理无向量或已过期的错题
pub async fn index_incremental(state: &AppState) -> Result<IndexSummary> {
    let embedder = current_embedder(state).await?;
    rag::index_incremental(state, embedder.as_ref()).await
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
    let embedder = current_embedder(state).await?;
    rag::retrieve(state, embedder.as_ref(), &query, top_k).await
}