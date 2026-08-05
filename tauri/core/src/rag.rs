//! RAG 检索与编排：建索引、语义检索、问答
//! 不持有 embedder/cleaner，由调用方注入，便于测试。

use crate::commands::question;
use crate::commands::AppState;
use crate::embedder::{cosine_similarity, decode_vec, encode_vec, top_k_scores, Embedder};
use crate::error::Result;
use crate::models::{QuestionFilter, RagAnswer, RagSource};

/// 拼接题目文本作为嵌入输入
fn question_text(q: &crate::models::Question) -> String {
    let mut parts = vec![q.title.clone()];
    if let Some(o) = &q.options {
        parts.push(o.clone());
    }
    if let Some(a) = &q.answer {
        parts.push(a.clone());
    }
    if let Some(an) = &q.analysis {
        parts.push(an.clone());
    }
    parts.join("\n")
}

/// 嵌入模型标识
const EMBED_MODEL: &str = "local:bge-small-zh-v1.5";

/// 增量索引结果
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct IndexSummary {
    /// 本次成功索引的数量
    pub indexed: usize,
    /// 无需索引（已是最新）或嵌入失败被跳过的数量
    pub skipped: usize,
}

/// 为单道题生成嵌入并入库（upsert，记录题目更新时间以便增量检测）
async fn upsert_embedding(
    state: &AppState,
    q: &crate::models::Question,
    embedder: &dyn Embedder,
) -> Result<bool> {
    let text = question_text(q);
    let vec = match embedder.embed(&[text]).await {
        Ok(mut v) if !v.is_empty() => v.remove(0),
        _ => return Ok(false),
    };
    sqlx::query(
        "INSERT INTO question_embeddings (question_id, model, vector, updated_at)
         VALUES (?, ?, ?, ?)
         ON CONFLICT(question_id) DO UPDATE SET
           model = excluded.model, vector = excluded.vector, updated_at = excluded.updated_at",
    )
    .bind(q.id)
    .bind(EMBED_MODEL)
    .bind(encode_vec(&vec))
    .bind(&q.updated_at)
    .execute(&state.pool)
    .await?;
    Ok(true)
}

/// 为所有题目生成嵌入并入库，返回成功索引数量
pub async fn index_all(state: &AppState, embedder: &dyn Embedder) -> Result<usize> {
    let questions = question::list_questions(state, &QuestionFilter::default()).await?;
    let mut indexed = 0usize;
    for q in questions {
        if upsert_embedding(state, &q, embedder).await? {
            indexed += 1;
        }
    }
    Ok(indexed)
}

/// 增量索引：仅处理「无向量」或「向量早于题目更新」的题目
pub async fn index_incremental(
    state: &AppState,
    embedder: &dyn Embedder,
) -> Result<IndexSummary> {
    let ids = sqlx::query_scalar::<_, i64>(
        "SELECT q.id FROM questions q
         LEFT JOIN question_embeddings e ON e.question_id = q.id
         WHERE e.question_id IS NULL OR e.updated_at < q.updated_at",
    )
    .fetch_all(&state.pool)
    .await?;
    let total: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM questions")
        .fetch_one(&state.pool)
        .await?;

    let mut indexed = 0usize;
    for id in ids {
        if let Ok(q) = question::get_by_id(state, id).await {
            if upsert_embedding(state, &q, embedder).await? {
                indexed += 1;
            }
        }
    }
    Ok(IndexSummary {
        indexed,
        skipped: (total as usize).saturating_sub(indexed),
    })
}

/// 语义检索：查询向量化 → 余弦相似度 → top_k
pub async fn retrieve(
    state: &AppState,
    embedder: &dyn Embedder,
    query: &str,
    top_k: usize,
) -> Result<Vec<RagSource>> {
    let qvec = match embedder.embed(&[query.to_string()]).await {
        Ok(mut v) if !v.is_empty() => v.remove(0),
        _ => return Ok(Vec::new()),
    };

    let rows = sqlx::query_as::<_, EmbeddingRow>("SELECT question_id, vector FROM question_embeddings")
        .fetch_all(&state.pool)
        .await?;

    let scores: Vec<(i64, f32)> = rows
        .into_iter()
        .map(|r| {
            let vec = decode_vec(&r.vector);
            (r.question_id, cosine_similarity(&qvec, &vec))
        })
        .collect();

    let top = top_k_scores(scores, top_k);

    let mut out = Vec::new();
    for (qid, score) in top {
        if score <= 0.0 {
            continue;
        }
        if let Ok(q) = question::get_by_id(state, qid).await {
            out.push(RagSource {
                question_id: qid,
                title: q.title,
                score,
            });
        }
    }
    Ok(out)
}

/// RAG 问答主流程
pub async fn ask(
    state: &AppState,
    embedder: &dyn Embedder,
    cleaner: &dyn crate::cleaner::Cleaner,
    question: &str,
    top_k: usize,
) -> Result<RagAnswer> {
    let sources = retrieve(state, embedder, question, top_k).await?;
    if sources.is_empty() {
        return Ok(RagAnswer {
            answer: "没有检索到相关题目。请先建立索引，或换个问法。".into(),
            sources,
        });
    }

    let mut ctx = String::new();
    for (i, s) in sources.iter().enumerate() {
        ctx.push_str(&format!("[{}] 题目: {}\n", i + 1, s.title));
    }
    let answer = cleaner.ask(question, &ctx).await?;
    Ok(RagAnswer { answer, sources })
}

#[derive(sqlx::FromRow)]
struct EmbeddingRow {
    question_id: i64,
    vector: Vec<u8>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cleaner::Cleaner;
    use crate::db;
    use crate::models::QuestionInput;
    use async_trait::async_trait;

    /// 确定性 mock 嵌入器：第 i 个文本在维度 i 置 1，其余 0
    struct MockEmbedder {
        dim: usize,
    }
    #[async_trait]
    impl Embedder for MockEmbedder {
        async fn embed(&self, texts: &[String]) -> Result<Vec<Vec<f32>>> {
            Ok(texts
                .iter()
                .enumerate()
                .map(|(i, _)| {
                    let mut v = vec![0.0; self.dim];
                    if i < self.dim {
                        v[i] = 1.0;
                    }
                    v
                })
                .collect())
        }
        fn dim(&self) -> usize {
            self.dim
        }
    }

    struct MockCleaner;
    #[async_trait]
    impl Cleaner for MockCleaner {
        async fn clean(&self, _ocr: &str) -> Result<crate::models::CleanedQuestion> {
            unimplemented!()
        }
        async fn ask(&self, question: &str, context: &str) -> Result<String> {
            Ok(format!("answer for: {} | ctx: {}", question, context))
        }
    }

    async fn setup_state() -> (AppState, i64, i64) {
        let pool = db::init_db(None).await.expect("memory db");
        let state = AppState::new(pool);
        let subj = crate::commands::subject::create_subject(&state, "数学".into())
            .await
            .expect("create subject");
        let q1 = crate::commands::question::create_question(
            &state,
            QuestionInput {
                subject_id: subj.id,
                chapter_id: None,
                qtype: Some("single".into()),
                title: "一元二次方程求解".into(),
                options: None,
                answer: Some("x=2".into()),
                analysis: Some("配方求根".into()),
                difficulty: Some(3),
                status: None,
                notes: None,
                is_favorite: None,
                image_path: None,
                source: None,
                wrong_reason: None,
                tags: None,
            },
        )
        .await
        .expect("create q1");
        let q2 = crate::commands::question::create_question(
            &state,
            QuestionInput {
                subject_id: subj.id,
                chapter_id: None,
                qtype: Some("single".into()),
                title: "勾股定理".into(),
                options: None,
                answer: Some("a^2+b^2=c^2".into()),
                analysis: None,
                difficulty: Some(2),
                status: None,
                notes: None,
                is_favorite: None,
                image_path: None,
                source: None,
                wrong_reason: None,
                tags: None,
            },
        )
        .await
        .expect("create q2");
        (state, q1.id, q2.id)
    }

    #[tokio::test]
    async fn test_index_and_retrieve_top_k() {
        let (state, q1, _q2) = setup_state().await;
        let embedder = MockEmbedder { dim: 8 };
        let n = index_all(&state, &embedder).await.expect("index");
        assert_eq!(n, 2);

        // 查询向量与第 0 个文本（q1？顺序不定）求相似，验证返回非空且都为有效 id
        let hits = retrieve(&state, &embedder, "x^2-5x+6=0", 1).await.expect("retrieve");
        assert!(!hits.is_empty());
        assert!(hits.iter().all(|s| s.question_id == q1 || s.question_id == _q2));
        assert!(hits[0].score > 0.0);
    }

    #[tokio::test]
    async fn test_ask_wraps_answer_and_sources() {
        let (state, _q1, _q2) = setup_state().await;
        let embedder = MockEmbedder { dim: 8 };
        index_all(&state, &embedder).await.expect("index");
        let cleaner = MockCleaner;
        let ans = ask(&state, &embedder, &cleaner, "如何解二次方程", 2)
            .await
            .expect("ask");
        assert!(ans.answer.starts_with("answer for:"));
        assert!(!ans.sources.is_empty());
    }

    #[tokio::test]
    async fn test_ask_returns_friendly_message_when_no_hits() {
        let state = AppState::new(db::init_db(None).await.expect("memory db"));
        let embedder = MockEmbedder { dim: 8 };
        let cleaner = MockCleaner;
        let ans = ask(&state, &embedder, &cleaner, "随便问问", 2)
            .await
            .expect("ask");
        assert!(ans.answer.contains("没有检索到相关题目"));
        assert!(ans.sources.is_empty());
    }

    #[tokio::test]
    async fn test_index_incremental_only_indexes_new_and_missing() {
        let (state, q1, q2) = setup_state().await;
        let embedder = MockEmbedder { dim: 8 };

        // 首次全量索引
        let n = index_all(&state, &embedder).await.expect("index all");
        assert_eq!(n, 2);

        // 新增一道题
        q3(&state).await;

        // 增量：只索引新题，跳过已索引的
        let s1 = index_incremental(&state, &embedder).await.expect("incremental 1");
        assert_eq!(s1.indexed, 1, "应只索引新增的题");
        assert_eq!(s1.skipped, 2, "已有两道应被跳过");

        // 删除 q1 的向量 → 应被重新索引
        sqlx::query("DELETE FROM question_embeddings WHERE question_id = ?")
            .bind(q1)
            .execute(&state.pool)
            .await
            .expect("delete embedding q1");
        let s2 = index_incremental(&state, &embedder).await.expect("incremental 2");
        assert_eq!(s2.indexed, 1);
        assert_eq!(s2.skipped, 2);

        // 模拟 q2 修改导致向量过期（updated_at 晚于向量时间）
        sqlx::query("UPDATE questions SET updated_at = datetime('now','localtime','+1 day') WHERE id = ?")
            .bind(q2)
            .execute(&state.pool)
            .await
            .expect("stale q2");
        let s3 = index_incremental(&state, &embedder).await.expect("incremental 3");
        assert_eq!(s3.indexed, 1, "过期向量应被重新索引");
    }

    async fn q3(state: &AppState) -> i64 {
        crate::commands::question::create_question(
            state,
            QuestionInput {
                subject_id: 1,
                chapter_id: None,
                qtype: Some("single".into()),
                title: "三角函数".into(),
                options: None,
                answer: Some("sin".into()),
                analysis: None,
                difficulty: Some(1),
                status: None,
                notes: None,
                is_favorite: None,
                image_path: None,
                source: None,
                wrong_reason: None,
                tags: None,
            },
        )
        .await
        .expect("create q3")
        .id
    }
}