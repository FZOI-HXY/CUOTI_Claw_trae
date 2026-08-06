//! RAG 检索与编排：建索引、语义检索、问答
//! 不持有 embedder/cleaner，由调用方注入，便于测试。

use crate::commands::question;
use crate::commands::AppState;
use crate::embedder::{cosine_similarity, decode_vec, encode_vec, top_k_scores, Embedder};
use crate::error::Result;
use crate::hybrid;
use crate::models::{QuestionFilter, RagAnswer, RagSource};
use std::collections::HashMap;

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

/// 余弦相似度：低于该值视为「相关性弱」，检索后可短路不调 LLM
pub const WEAK_SCORE: f32 = 0.30;
/// 余弦相似度：低于该值但非空，生成后追加接地提示
pub const GROUNDING_SCORE: f32 = 0.45;

/// 增量索引结果
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
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
    // 1. 向量召回
    let qvec = match embedder.embed(&[query.to_string()]).await {
        Ok(mut v) if !v.is_empty() => v.remove(0),
        _ => return Ok(Vec::new()),
    };
    let rows = sqlx::query_as::<_, EmbeddingRow>("SELECT question_id, vector FROM question_embeddings")
        .fetch_all(&state.pool)
        .await?;
    let vector_scores: Vec<(i64, f32)> = rows
        .into_iter()
        .map(|r| {
            let vec = decode_vec(&r.vector);
            (r.question_id, cosine_similarity(&qvec, &vec))
        })
        .collect();
    let vector_top = top_k_scores(vector_scores.clone(), top_k);

    // 2. 关键词召回（BM25 式，无额外存储，查询时对题目文本实时打分）
    let questions = question::list_questions(state, &QuestionFilter::default()).await?;
    let docs: Vec<(i64, String)> = questions
        .iter()
        .map(|q| (q.id, question_keyword_text(q)))
        .collect();
    let keyword_scores = hybrid::bm25_scores(&docs, query);
    let keyword_top = top_k_scores(
        keyword_scores.into_iter().filter(|(_, s)| *s > 0.0).collect(),
        top_k,
    );

    // 3. RRF 融合排序（关键词命中的题可被排到向量榜单之前）
    let mut fused = hybrid::rrf_fuse(&[vector_top, keyword_top], 60.0);
    let cosine_map: HashMap<i64, f32> = vector_scores.into_iter().collect();
    // RRF 同分时用向量余弦作次级排序键，保证语义更相关的排在前面
    fused.sort_by(|a, b| {
        b.1.partial_cmp(&a.1)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| {
                cosine_map
                    .get(&b.0)
                    .unwrap_or(&0.0)
                    .partial_cmp(cosine_map.get(&a.0).unwrap_or(&0.0))
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
    });

    // 4. 组装结果：顺序按融合排序，score 保留向量余弦（供前端展示）
    // 批量拉取命中的题目，避免逐条查询（N+1）
    let mut out = Vec::new();
    let mut qids: Vec<i64> = fused
        .iter()
        .filter_map(|(qid, _)| {
            let score = *cosine_map.get(qid).unwrap_or(&0.0);
            (score > 0.0).then_some(*qid)
        })
        .collect();
    qids.truncate(top_k);
    let qmap = question::get_by_ids(state, &qids).await?;
    for (qid, _) in fused {
        let score = *cosine_map.get(&qid).unwrap_or(&0.0);
        if score <= 0.0 {
            continue;
        }
        if let Some(q) = qmap.get(&qid) {
            out.push(RagSource {
                question_id: qid,
                title: q.title.clone(),
                score,
            });
        }
    }
    out.truncate(top_k);
    Ok(out)
}

/// 拼接含元信息的题目文本，用于关键词(BM25)检索。
/// 与 question_text（向量嵌入）分离：仅关键词路径使用，避免改变存量向量。
fn question_keyword_text(q: &crate::models::Question) -> String {
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
    if let Some(s) = &q.subject_name {
        parts.push(s.clone());
    }
    if let Some(c) = &q.chapter_name {
        parts.push(c.clone());
    }
    parts.push(qtype_label(&q.qtype).to_string());
    if let Some(tags) = &q.tags {
        for t in tags {
            parts.push(t.clone());
        }
    }
    parts.join("\n")
}

/// 题型中文标签（用于关键词检索）
fn qtype_label(qtype: &str) -> &'static str {
    match qtype {
        "single" => "单选",
        "multiple" => "多选",
        "judge" => "判断",
        "fill" => "填空",
        "answer" => "解答",
        _ => "题目",
    }
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

    // 自检1：全部来源相关性弱 → 短路，不浪费 LLM 调用
    let max_score = sources.iter().map(|s| s.score).fold(0.0f32, f32::max);
    if max_score < WEAK_SCORE {
        return Ok(RagAnswer {
            answer: format!(
                "检索到 {} 道相关题目，但与问题相关性较低，以下题目仅供参考，可能无法给出准确解答。",
                sources.len()
            ),
            sources,
        });
    }

    // 批量取来源题目的完整信息（一次查询，避免 N+1），供上下文增强
    let ids: Vec<i64> = sources.iter().map(|s| s.question_id).collect();
    let qmap = question::get_by_ids(state, &ids).await?;

    let mut ctx = String::new();
    for (i, s) in sources.iter().enumerate() {
        ctx.push_str(&format!("[{}] 题目: {}\n", i + 1, s.title));
        if let Some(q) = qmap.get(&s.question_id) {
            if let Some(opt) = &q.options {
                ctx.push_str(&format!("   选项: {}\n", opt));
            }
            if let Some(ans) = &q.answer {
                ctx.push_str(&format!("   参考答案: {}\n", ans));
            }
            if let Some(an) = &q.analysis {
                ctx.push_str(&format!("   解析: {}\n", an));
            }
        }
    }
    let mut answer = cleaner.ask(question, &ctx).await?;

    // 自检2：首条来源相关性一般 → 追加接地提示
    if sources[0].score < GROUNDING_SCORE {
        answer.push_str("（提示：检索到的相关题目相关性一般，以上回答仅供参考，建议确认题目原文。）");
    }
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
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;

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

    /// 记录 ask 调用次数的 cleaner，用于验证弱相关性短路逻辑
    struct CountingCleaner {
        calls: Arc<AtomicUsize>,
    }
    #[async_trait]
    impl Cleaner for CountingCleaner {
        async fn clean(&self, _ocr: &str) -> Result<crate::models::CleanedQuestion> {
            unimplemented!()
        }
        async fn ask(&self, question: &str, context: &str) -> Result<String> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            Ok(format!("answer for: {} | ctx: {}", question, context))
        }
    }

    /// 固定查询向量嵌入器：任何输入都返回同一查询向量
    struct QueryEmbedder {
        qvec: Vec<f32>,
    }
    #[async_trait]
    impl Embedder for QueryEmbedder {
        async fn embed(&self, _texts: &[String]) -> Result<Vec<Vec<f32>>> {
            Ok(vec![self.qvec.clone()])
        }
        fn dim(&self) -> usize {
            self.qvec.len()
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

    #[tokio::test]
    async fn test_hybrid_retrieval_surfaces_keyword_exact_match() {
        // 构造：q1、q2 向量相似度高，q3 向量分低（0.05），但 q3 是关键词精确匹配项。
        // 纯向量 top2 应只返回 [q1, q2]；混合检索应靠 BM25 把 q3 召回。
        let pool = db::init_db(None).await.expect("memory db");
        let state = AppState::new(pool);
        let subj = crate::commands::subject::create_subject(&state, "数学".into())
            .await
            .expect("subj");
        let q1 = crate::commands::question::create_question(
            &state,
            QuestionInput {
                subject_id: subj.id,
                chapter_id: None,
                qtype: Some("single".into()),
                title: "三角函数 弧度".into(),
                options: None,
                answer: Some("sin".into()),
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
        .expect("create q1")
        .id;
        let q2 = crate::commands::question::create_question(
            &state,
            QuestionInput {
                subject_id: subj.id,
                chapter_id: None,
                qtype: Some("single".into()),
                title: "指数函数 对数".into(),
                options: None,
                answer: Some("e".into()),
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
        .expect("create q2")
        .id;
        let q3 = crate::commands::question::create_question(
            &state,
            QuestionInput {
                subject_id: subj.id,
                chapter_id: None,
                qtype: Some("single".into()),
                title: "勾股定理 直角边".into(),
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
        .expect("create q3")
        .id;

        // 手工写入向量以精确控制相似度（绕过 index_all）
        let vecs: [(i64, Vec<f32>); 3] = [
            (q1, vec![1.0f32, 0.0, 0.0]),
            (q2, vec![0.9f32, 0.0, 0.0]),
            (q3, vec![0.05f32, 0.0, 0.0]),
        ];
        for (id, vec) in vecs {
            sqlx::query(
                "INSERT OR REPLACE INTO question_embeddings (question_id, model, vector, updated_at)
                 VALUES (?,?,?,datetime('now','localtime'))",
            )
            .bind(id)
            .bind(EMBED_MODEL)
            .bind(encode_vec(&vec))
            .execute(&state.pool)
            .await
            .expect("insert vec");
        }

        let embedder = QueryEmbedder {
            qvec: vec![1.0, 0.0, 0.0],
        };
        let hits = retrieve(&state, &embedder, "勾股定理", 2)
            .await
            .expect("retrieve");
        // 纯向量 top2 为 [q1, q2]（q3 相似度 0.05 被挤出）；混合检索靠关键词召回 q3
        assert!(
            hits.iter().any(|s| s.question_id == q3),
            "关键词精确匹配题应被混合检索召回"
        );
    }

    #[test]
    fn test_question_keyword_text_includes_metadata() {
        let q = crate::models::Question {
            id: 1,
            subject_id: 1,
            chapter_id: Some(2),
            qtype: "single".into(),
            title: "勾股定理".into(),
            options: None,
            answer: Some("a^2+b^2=c^2".into()),
            analysis: Some("直角三角形".into()),
            difficulty: 2,
            status: "not_mastered".into(),
            wrong_count: 0,
            notes: None,
            is_favorite: false,
            image_path: None,
            source: None,
            wrong_reason: None,
            last_reviewed_at: None,
            created_at: "".into(),
            updated_at: "".into(),
            subject_name: Some("数学".into()),
            chapter_name: Some("几何 · 三角形".into()),
            tags: Some(vec!["重点".into(), "常考".into()]),
        };
        let text = question_keyword_text(&q);
        assert!(text.contains("数学"), "应包含科目名");
        assert!(text.contains("几何 · 三角形"), "应包含章节名");
        assert!(text.contains("单选"), "应包含题型中文标签");
        assert!(text.contains("重点"), "应包含标签");
        assert!(text.contains("勾股定理"), "应包含题干");
    }

    #[test]
    fn test_qtype_label_maps_all_types() {
        assert_eq!(qtype_label("single"), "单选");
        assert_eq!(qtype_label("multiple"), "多选");
        assert_eq!(qtype_label("judge"), "判断");
        assert_eq!(qtype_label("fill"), "填空");
        assert_eq!(qtype_label("answer"), "解答");
        assert_eq!(qtype_label("unknown"), "题目");
    }

    #[test]
    fn test_bm25_recalls_by_metadata_keyword() {
        let mk = |subject: Option<String>, chapter: Option<String>, qtype: &str, tags: Option<Vec<String>>| crate::models::Question {
            id: 0,
            subject_id: 1,
            chapter_id: Some(2),
            qtype: qtype.into(),
            title: "求解 x".into(),
            options: None,
            answer: Some("x=2".into()),
            analysis: None,
            difficulty: 2,
            status: "not_mastered".into(),
            wrong_count: 0,
            notes: None,
            is_favorite: false,
            image_path: None,
            source: None,
            wrong_reason: None,
            last_reviewed_at: None,
            created_at: "".into(),
            updated_at: "".into(),
            subject_name: subject,
            chapter_name: chapter,
            tags,
        };
        let docs: Vec<(i64, String)> = vec![
            (1, question_keyword_text(&mk(Some("数学".into()), Some("函数".into()), "single", None))),
            (2, question_keyword_text(&mk(Some("物理".into()), Some("力学".into()), "fill", Some(vec!["重点".into()])))),
        ];
        // 查询只含「填空」—— 仅 doc2 的 qtype 元信息命中
        let scores = hybrid::bm25_scores(&docs, "填空");
        let (top_id, _) = scores.iter().max_by(|a, b| a.1.partial_cmp(&b.1).unwrap()).expect("non-empty");
        assert_eq!(*top_id, 2, "应按题型元信息召回 doc2");
    }

    #[tokio::test]
    async fn test_ask_short_circuits_on_weak_relevance() {
        let pool = db::init_db(None).await.expect("memory db");
        let state = AppState::new(pool);
        let subj = crate::commands::subject::create_subject(&state, "数学".into())
            .await
            .expect("subj");
        let qid = crate::commands::question::create_question(
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
        .expect("create")
        .id;
        // 手工写入与查询向量近乎正交的向量 → 余弦≈0.05，介于 (0, WEAK_SCORE) 之间，
        // 既能通过 retrieve 的 score>0 过滤，又低于 WEAK_SCORE 触发短路
        sqlx::query(
            "INSERT OR REPLACE INTO question_embeddings (question_id, model, vector, updated_at)
             VALUES (?,?,?,datetime('now','localtime'))",
        )
        .bind(qid)
        .bind(EMBED_MODEL)
        .bind(encode_vec(&vec![0.05f32, 1.0, 0.0]))
        .execute(&state.pool)
        .await
        .expect("insert vec");

        let calls = Arc::new(AtomicUsize::new(0));
        let cleaner = CountingCleaner { calls: Arc::clone(&calls) };
        let embedder = QueryEmbedder { qvec: vec![1.0, 0.0, 0.0] };
        let ans = ask(&state, &embedder, &cleaner, "随便问问", 5).await.expect("ask");
        assert!(ans.answer.contains("相关性较低"), "应命中弱相关性分支: {}", ans.answer);
        assert!(ans.sources.iter().any(|s| s.question_id == qid), "来源列表应返回");
        assert_eq!(calls.load(Ordering::SeqCst), 0, "弱相关性不应调用 LLM");
    }

    /// 构造一道题并写入给定向量，返回其 id
    async fn insert_question_with_vec(
        state: &AppState,
        title: &str,
        vec: Vec<f32>,
    ) -> i64 {
        let subj = crate::commands::subject::create_subject(state, "数学".into())
            .await
            .expect("subj");
        let qid = crate::commands::question::create_question(
            state,
            QuestionInput {
                subject_id: subj.id,
                chapter_id: None,
                qtype: Some("single".into()),
                title: title.into(),
                options: None,
                answer: Some("ans".into()),
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
        .expect("create")
        .id;
        sqlx::query(
            "INSERT OR REPLACE INTO question_embeddings (question_id, model, vector, updated_at)
             VALUES (?,?,?,datetime('now','localtime'))",
        )
        .bind(qid)
        .bind(EMBED_MODEL)
        .bind(encode_vec(&vec))
        .execute(&state.pool)
        .await
        .expect("insert vec");
        qid
    }

    #[tokio::test]
    async fn test_ask_appends_grounding_hint_on_medium_relevance() {
        let pool = db::init_db(None).await.expect("memory db");
        let state = AppState::new(pool);
        // 余弦 = dot(a,b)/(|a||b|)，a=[1,0], b=[0.35,1] → 0.35/√(1+0.1225)≈0.33，介于 WEAK 与 GROUNDING 之间
        insert_question_with_vec(&state, "题目A", vec![0.35f32, 1.0]).await;
        let cleaner = MockCleaner;
        let embedder = QueryEmbedder { qvec: vec![1.0, 0.0] };
        let ans = ask(&state, &embedder, &cleaner, "问题", 5).await.expect("ask");
        assert!(ans.answer.ends_with("建议确认题目原文。）"), "应追加接地提示: {}", ans.answer);
    }

    #[tokio::test]
    async fn test_ask_no_hint_on_strong_relevance() {
        let pool = db::init_db(None).await.expect("memory db");
        let state = AppState::new(pool);
        insert_question_with_vec(&state, "题目B", vec![1.0f32, 0.0]).await;
        let cleaner = MockCleaner;
        let embedder = QueryEmbedder { qvec: vec![1.0, 0.0] };
        let ans = ask(&state, &embedder, &cleaner, "问题", 5).await.expect("ask");
        assert!(!ans.answer.contains("建议确认题目原文"), "强相关不应有提示: {}", ans.answer);
        assert!(ans.answer.starts_with("answer for:"), "应正常生成");
    }

    #[tokio::test]
    async fn test_ask_context_includes_answer_and_analysis() {
        let pool = db::init_db(None).await.expect("memory db");
        let state = AppState::new(pool);
        let subj = crate::commands::subject::create_subject(&state, "数学".into())
            .await
            .expect("subj");
        let qid = crate::commands::question::create_question(
            &state,
            QuestionInput {
                subject_id: subj.id,
                chapter_id: None,
                qtype: Some("single".into()),
                title: "勾股定理".into(),
                options: None,
                answer: Some("标准答案XYZ".into()),
                analysis: Some("解析要点ABC".into()),
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
        .expect("create")
        .id;
        sqlx::query(
            "INSERT OR REPLACE INTO question_embeddings (question_id, model, vector, updated_at)
             VALUES (?,?,?,datetime('now','localtime'))",
        )
        .bind(qid)
        .bind(EMBED_MODEL)
        .bind(encode_vec(&vec![1.0f32, 0.0]))
        .execute(&state.pool)
        .await
        .expect("insert vec");
        let cleaner = MockCleaner;
        let embedder = QueryEmbedder { qvec: vec![1.0, 0.0] };
        let ans = ask(&state, &embedder, &cleaner, "问题", 5).await.expect("ask");
        assert!(ans.answer.contains("标准答案XYZ"), "上下文应包含答案: {}", ans.answer);
        assert!(ans.answer.contains("解析要点ABC"), "上下文应包含解析: {}", ans.answer);
    }
}