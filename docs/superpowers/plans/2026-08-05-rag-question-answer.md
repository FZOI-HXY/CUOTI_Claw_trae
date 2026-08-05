# 智能问答 RAG 助手 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为错题本应用新增"AI 问答"能力：用户用自然语言提问，系统从错题库中检索相关题目作为上下文，复用现有 LLM（`Cleaner` trait）生成带引用的解答。

**Architecture:** 在 cuoti-core 新增纯逻辑的 `embedder.rs`（嵌入 trait + 余弦检索）与 `rag.rs`（索引/检索/编排）；向量存进新增 `question_embeddings` 表（BLOB，f32 LE）；问答生成复用并扩展 `Cleaner` trait（新增 `ask` 方法）；通过 `#[tauri::command]` 暴露 `rag_ask` / `rag_index` / `rag_retrieve` 给 Vue 前端。本地嵌入用 fastembed-rs（`bge-small-zh-v1.5`，CPU/ONNX），单例懒加载避免重复初始化。

**Tech Stack:** Rust (tokio, sqlx, async-trait)、fastembed-rs、reqwest、Vue 3 + TypeScript、Vitest、Tauri 2

**设计文档:** `docs/superpowers/specs/2026-08-04-rag-question-answer-design.md`

**耦合约束（务必遵守）：**
- 不修改 `create_question`/`update_question`/`delete_question` 的签名与逻辑
- 索引采用「手动 + 成功后追加」，不侵入 CRUD 流程
- OCR（PaddleOcrService）与 RAG 完全独立
- 问答生成复用现有 `LlmConfig`（`config::get_llm_config`），不新增 LLM 结构

---

### Task 1: 新增 `question_embeddings` 表（db.rs 迁移）

**Files:**
- Modify: `tauri/core/src/db.rs`（`migrate()` 中追加表定义）
- Test: `tauri/core/src/db.rs`（文件末尾新增 `#[cfg(test)]`）

- [ ] **Step 1: 写失败测试**

在 `tauri/core/src/db.rs` 末尾追加：

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_question_embeddings_table_exists_after_migrate() {
        let pool = init_db(None).await.expect("init memory db");
        let row: (i64,) =
            sqlx::query_as("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='question_embeddings'")
                .fetch_one(&pool)
                .await
                .expect("query table existence");
        assert_eq!(row.0, 1, "question_embeddings 表应存在");
    }
}
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /workspace/tauri && cargo test -p cuoti-core --lib db::tests::test_question_embeddings_table_exists_after_migrate`
Expected: FAIL，报错 "no such table: question_embeddings"

- [ ] **Step 3: 实现迁移**

在 `migrate()` 的 `CREATE TABLE` 语句块末尾（`config` 表之后、`;` 之前）追加：

```sql
        CREATE TABLE IF NOT EXISTS question_embeddings (
            question_id INTEGER PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
            model       TEXT NOT NULL,
            vector      BLOB NOT NULL,
            updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );
```

- [ ] **Step 4: 运行测试验证通过**

Run: 同 Step 2 命令
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /workspace && git add tauri/core/src/db.rs && git commit -m "feat: add question_embeddings table migration"
```

---

### Task 2: 嵌入层 trait + 纯逻辑（余弦相似度 / top_k / 向量编解码）

**Files:**
- Create: `tauri/core/src/embedder.rs`
- Test: `tauri/core/src/embedder.rs`（`#[cfg(test)]`）

- [ ] **Step 1: 写失败测试**

创建 `tauri/core/src/embedder.rs`，先写测试与函数签名占位，运行确认失败：

```rust
//! 嵌入层：trait 抽象 + 本地 fastembed 实现 + 检索纯逻辑

use async_trait::async_trait;

use crate::error::{Error, Result};

/// 文本嵌入抽象：本地或 API 提供方
#[async_trait]
pub trait Embedder: Send + Sync {
    async fn embed(&self, texts: &[String]) -> Result<Vec<Vec<f32>>>;
    fn dim(&self) -> usize;
}

/// 余弦相似度
pub fn cosine_similarity(a: &[f32], b: &[f32]) -> f32 { unimplemented!() }

/// 取相似度最高的前 k 个（返回 (id, score)，降序）
pub fn top_k_scores(scores: Vec<(i64, f32)>, k: usize) -> Vec<(i64, f32)> { unimplemented!() }

/// f32 向量 → BLOB（little-endian）
pub fn encode_vec(v: &[f32]) -> Vec<u8> { unimplemented!() }

/// BLOB → f32 向量
pub fn decode_vec(bytes: &[u8]) -> Vec<f32> { unimplemented!() }

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
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /workspace/tauri && cargo test -p cuoti-core --lib embedder::tests`
Expected: FAIL（`unimplemented!()` panic）

- [ ] **Step 3: 实现纯逻辑**

将 `embedder.rs` 中以下函数体替换为真实实现：

```rust
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
```

- [ ] **Step 4: 运行测试验证通过**

Run: 同 Step 2
Expected: PASS（5 个用例全通过）

- [ ] **Step 5: Commit**

```bash
cd /workspace && git add tauri/core/src/embedder.rs && git commit -m "feat: add embedder trait and retrieval pure logic"
```

---

### Task 3: `LocalEmbedder` 实现 + 单例懒加载

**Files:**
- Modify: `tauri/core/src/embedder.rs`
- Modify: `tauri/core/Cargo.toml`（新增 fastembed 依赖）

- [ ] **Step 1: 添加依赖**

在 `tauri/core/Cargo.toml` 的 `[dependencies]` 追加：

```toml
fastembed = "4"
```

> 注：若编译时 fastembed API/版本不匹配，以 `cargo` 报错为准修正版本（如 `3`）。`embed` 为阻塞调用，包在 `spawn_blocking` 中。

- [ ] **Step 2: 实现 `LocalEmbedder`**

在 `embedder.rs` 顶部 import 追加：

```rust
use fastembed::{EmbeddingModel, InitOptions, TextEmbedding};
use tokio::sync::OnceCell;
```

在 `Embedder` trait 实现之后追加：

```rust
/// 本地 fastembed 嵌入实现（bge-small-zh，CPU/ONNX）
pub struct LocalEmbedder {
    model: TextEmbedding,
    dim: usize,
}

impl LocalEmbedder {
    pub async fn new() -> Result<Self> {
        let model = TextEmbedding::try_new(InitOptions::new(EmbeddingModel::BGESmallZHV15))
            .await
            .map_err(|e| Error::Cleaner(format!("加载嵌入模型失败: {}", e)))?;
        let dim = model.dim();
        Ok(Self { model, dim })
    }
}

#[async_trait]
impl Embedder for LocalEmbedder {
    async fn embed(&self, texts: &[String]) -> Result<Vec<Vec<f32>>> {
        let model = self.model.clone();
        let texts = texts.clone();
        tokio::task::spawn_blocking(move || model.embed(texts, None))
            .await
            .map_err(|e| Error::Cleaner(format!("嵌入线程失败: {}", e)))?
            .map_err(|e| Error::Cleaner(format!("嵌入失败: {}", e)))
    }

    fn dim(&self) -> usize {
        self.dim
    }
}

/// 全局单例：整个应用只加载一次本地模型
static LOCAL_EMBEDDER: OnceCell<LocalEmbedder> = OnceCell::const_new();

/// 获取本地嵌入器单例（懒加载）
pub async fn local_embedder() -> Result<&'static LocalEmbedder> {
    LOCAL_EMBEDDER.get_or_try_init(LocalEmbedder::new).await
}
```

- [ ] **Step 3: 编译检查**

Run: `cd /workspace/tauri && cargo build -p cuoti-core`
Expected: 编译通过（不下载模型，仅编译）。若 fastembed 版本 API 报错，按报错信息修正。

- [ ] **Step 4: Commit**

```bash
cd /workspace && git add tauri/core/src/embedder.rs tauri/core/Cargo.toml && git commit -m "feat: add LocalEmbedder with lazy singleton"
```

---

### Task 4: 扩展 `Cleaner` trait 新增 `ask` + `LlmCleaner` 实现

**Files:**
- Modify: `tauri/core/src/cleaner.rs`

- [ ] **Step 1: 写失败测试**

在 `tauri/core/src/cleaner.rs` 的 `tests` 模块追加：

```rust
    #[test]
    fn test_build_ask_prompt_contains_context_and_question() {
        let prompt = LlmCleaner::build_ask_prompt("一元二次方程怎么解？", "[1] 题目: 解方程 x^2-5x+6=0");
        assert!(prompt.contains("x^2-5x+6=0"));
        assert!(prompt.contains("一元二次方程怎么解？"));
    }
```

Run pacth 前先确认失败：`cd /workspace/tauri && cargo test -p cuoti-core --lib cleaner::tests::test_build_ask_prompt_contains_context_and_question`
Expected: FAIL（`build_ask_prompt` 不存在）

- [ ] **Step 2: 扩展 trait 并实现 `ask`**

将 trait 定义改为：

```rust
#[async_trait]
pub trait Cleaner: Send + Sync {
    /// 将 OCR 文本规范化为错题草稿
    async fn clean(&self, ocr_text: &str) -> Result<CleanedQuestion>;
    /// 基于检索上下文回答用户问题（RAG 问答）
    async fn ask(&self, question: &str, context: &str) -> Result<String>;
}
```

在 `impl LlmCleaner` 内新增 prompt 组装：

```rust
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
```

在 `#[async_trait] impl Cleaner for LlmCleaner` 中新增 `ask` 实现：

```rust
    async fn ask(&self, question: &str, context: &str) -> Result<String> {
        if self.api_key.is_empty() || self.base_url.is_empty() {
            return Err(Error::Cleaner("LLM 未配置".into()));
        }

        let client = reqwest::Client::new();
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
            return Err(Error::Cleaner(format!("LLM HTTP {}: {}", status, msg)));
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
```

- [ ] **Step 3: 运行测试验证通过**

Run: `cd /workspace/tauri && cargo test -p cuoti-core --lib cleaner::tests`
Expected: PASS（3 个用例：原 2 个 + 新增 1 个）

- [ ] **Step 4: Commit**

```bash
cd /workspace && git add tauri/core/src/cleaner.rs && git commit -m "feat: extend Cleaner trait with ask for RAG answering"
```

---

### Task 5: 新增 RAG 数据模型

**Files:**
- Modify: `tauri/core/src/models.rs`

- [ ] **Step 1: 追加模型**

在 `models.rs` 末尾追加：

```rust
/// RAG 检索到的来源题目
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RagSource {
    pub question_id: i64,
    pub title: String,
    pub score: f32,
}

/// RAG 问答结果
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RagAnswer {
    pub answer: String,
    pub sources: Vec<RagSource>,
}
```

- [ ] **Step 2: 编译检查**

Run: `cd /workspace/tauri && cargo build -p cuoti-core`
Expected: 编译通过

- [ ] **Step 3: Commit**

```bash
cd /workspace && git add tauri/core/src/models.rs && git commit -m "feat: add RagSource and RagAnswer models"
```

---

### Task 6: `RagService` 逻辑（index_all / retrieve / ask）

**Files:**
- Create: `tauri/core/src/rag.rs`

- [ ] **Step 1: 写失败测试**

创建 `tauri/core/src/rag.rs`，先写测试（用 mock embedder + 内存库）：

```rust
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

/// 为所有题目生成嵌入并入库，返回成功索引数量
pub async fn index_all(state: &AppState, embedder: &dyn Embedder) -> Result<usize> { unimplemented!() }

/// 语义检索：查询向量化 → 余弦相似度 → top_k
pub async fn retrieve(
    state: &AppState,
    embedder: &dyn Embedder,
    query: &str,
    top_k: usize,
) -> Result<Vec<RagSource>> { unimplemented!() }

/// RAG 问答主流程
pub async fn ask(
    state: &AppState,
    embedder: &dyn Embedder,
    cleaner: &dyn crate::cleaner::Cleaner,
    question: &str,
    top_k: usize,
) -> Result<RagAnswer> { unimplemented!() }

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
}
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /workspace/tauri && cargo test -p cuoti-core --lib rag::tests`
Expected: FAIL（`unimplemented!()` panic）

- [ ] **Step 3: 实现**

将 `rag.rs` 中三个函数替换为真实实现：

```rust
/// 为所有题目生成嵌入并入库，返回成功索引数量
pub async fn index_all(state: &AppState, embedder: &dyn Embedder) -> Result<usize> {
    let questions =
        question::list_questions(state, &QuestionFilter::default()).await?;
    let mut indexed = 0usize;
    for q in questions {
        let text = question_text(&q);
        let vec = match embedder.embed(&[text]).await {
            Ok(mut v) if !v.is_empty() => v.remove(0),
            _ => continue,
        };
        sqlx::query(
            "INSERT INTO question_embeddings (question_id, model, vector, updated_at)
             VALUES (?, ?, ?, datetime('now','localtime'))
             ON CONFLICT(question_id) DO UPDATE SET
               model = excluded.model, vector = excluded.vector, updated_at = datetime('now','localtime')",
        )
        .bind(q.id)
        .bind("local:bge-small-zh-v1.5")
        .bind(encode_vec(&vec))
        .execute(&state.pool)
        .await?;
        indexed += 1;
    }
    Ok(indexed)
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

    let mut scores: Vec<(i64, f32)> = rows
        .into_iter()
        .map(|r| {
            let vec = decode_vec(&r.vector);
            (r.question_id, cosine_similarity(&qvec, &vec))
        })
        .collect();

    let top = top_k_scores(scores.drain(..).collect(), top_k);

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
```

> 注：Step 1 测试中 `let mut scores` 与 `scores.drain(..)` 写法冗余，实现时直接对 `scores` 调用 `top_k_scores(scores, top_k)` 即可（去掉 `mut` 与 `drain`）。此处以可编译为准。

- [ ] **Step 4: 运行测试验证通过**

Run: `cd /workspace/tauri && cargo test -p cuoti-core --lib rag::tests`
Expected: PASS（3 个用例）

- [ ] **Step 5: Commit**

```bash
cd /workspace && git add tauri/core/src/rag.rs && git commit -m "feat: add RagService index/retrieve/ask"
```

---

### Task 7: 嵌入配置（config.rs）

**Files:**
- Modify: `tauri/core/src/commands/config.rs`

- [ ] **Step 1: 实现配置读写**

在 `config.rs` 中常量区追加：

```rust
const KEY_EMBED_PROVIDER: &str = "embed_provider";
const KEY_EMBED_MODEL: &str = "embed_model";
```

在文件末尾（`ensure_configured` 之后）追加：

```rust
/// 读取嵌入配置（provider: local/api，model: 嵌入模型名）
pub async fn get_embed_config(state: &AppState) -> Result<(String, String)> {
    let provider = get(state, KEY_EMBED_PROVIDER).await.unwrap_or_else(|| "local".into());
    let model = get(state, KEY_EMBED_MODEL).await.unwrap_or_else(|| "bge-small-zh-v1.5".into());
    Ok((provider, model))
}

pub async fn set_embed_config(state: &AppState, provider: &str, model: &str) -> Result<()> {
    set(state, KEY_EMBED_PROVIDER, provider).await?;
    set(state, KEY_EMBED_MODEL, model).await?;
    Ok(())
}
```

- [ ] **Step 2: 编译检查**

Run: `cd /workspace/tauri && cargo build -p cuoti-core`
Expected: 编译通过

- [ ] **Step 3: Commit**

```bash
cd /workspace && git add tauri/core/src/commands/config.rs && git commit -m "feat: add embed provider/model config"
```

---

### Task 8: 命令编排层（commands/rag.rs）

**Files:**
- Create: `tauri/core/src/commands/rag.rs`
- Modify: `tauri/core/src/commands/mod.rs`

- [ ] **Step 1: 创建编排命令**

创建 `tauri/core/src/commands/rag.rs`：

```rust
//! RAG 命令编排：组装 embedder / cleaner，调用 rag 服务

use crate::cleaner::LlmCleaner;
use crate::embedder;
use crate::error::Result;
use crate::models::{RagAnswer, RagSource};
use crate::rag;

use super::{config, AppState};

/// 问答：检索 + LLM 生成
pub async fn ask(state: &AppState, question: String, top_k: Option<usize>) -> Result<RagAnswer> {
    let top_k = top_k.unwrap_or(5).clamp(1, 20);
    let llm_cfg = config::get_llm_config(state).await?;
    let cleaner = LlmCleaner::new(&llm_cfg);
    rag::ask(state, embedder::local_embedder().await?, &cleaner, &question, top_k).await
}

/// 为所有错题建立向量索引，返回索引数量
pub async fn index(state: &AppState) -> Result<usize> {
    rag::index_all(state, embedder::local_embedder().await?).await
}

/// 纯语义检索（供调试/后续语义搜索）
pub async fn retrieve(state: &AppState, query: String, top_k: Option<usize>) -> Result<Vec<RagSource>> {
    let top_k = top_k.unwrap_or(5).clamp(1, 20);
    rag::retrieve(state, embedder::local_embedder().await?, &query, top_k).await
}
```

- [ ] **Step 2: 注册模块**

在 `tauri/core/src/commands/mod.rs` 的 `pub mod` 列表追加：

```rust
pub mod rag;
```

- [ ] **Step 3: 编译检查**

Run: `cd /workspace/tauri && cargo build -p cuoti-core`
Expected: 编译通过

- [ ] **Step 4: Commit**

```bash
cd /workspace && git add tauri/core/src/commands/rag.rs tauri/core/src/commands/mod.rs && git commit -m "feat: add rag command orchestration"
```

---

### Task 9: 注册模块 + Tauri 命令

**Files:**
- Modify: `tauri/core/src/lib.rs`
- Modify: `tauri/src-tauri/src/main.rs`

- [ ] **Step 1: 注册 core 模块**

在 `tauri/core/src/lib.rs` 的 `pub mod` 列表追加：

```rust
pub mod embedder;
pub mod rag;
```

- [ ] **Step 2: 新增 Tauri 命令**

在 `tauri/src-tauri/src/main.rs` 顶部 import 改为：

```rust
use cuoti_core::commands::{config, question, stats, subject, tag, chapter, ocr, rag as rag_cmd, AppState};
```

在 `generate_handler![]` 中 `get_meta,` 之后追加：

```rust
            // RAG
            rag_ask,
            rag_index,
            rag_retrieve,
```

在文件末尾（`get_meta` 命令之后）追加：

```rust
// ---- RAG ----

#[tauri::command]
async fn rag_ask(
    state: State<'_, AppState>,
    question: String,
    top_k: Option<usize>,
) -> Result<cuoti_core::models::RagAnswer, String> {
    rag_cmd::ask(&state, question, top_k).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn rag_index(state: State<'_, AppState>) -> Result<usize, String> {
    rag_cmd::index(&state).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn rag_retrieve(
    state: State<'_, AppState>,
    query: String,
    top_k: Option<usize>,
) -> Result<Vec<cuoti_core::models::RagSource>, String> {
    rag_cmd::retrieve(&state, query, top_k).await.map_err(|e| e.to_string())
}
```

- [ ] **Step 3: 编译检查**

Run: `cd /workspace/tauri && cargo build`
Expected: 编译通过（fastembed 首次拉取依赖较慢属正常）

> 若沙箱缺少 onnxruntime 系统依赖导致链接失败，属环境限制，非代码问题；记录并继续前端部分即可。

- [ ] **Step 4: Commit**

```bash
cd /workspace && git add tauri/core/src/lib.rs tauri/src-tauri/src/main.rs && git commit -m "feat: register rag modules and tauri commands"
```

---

### Task 10: 前端类型 + API + 单元测试

**Files:**
- Modify: `tauri/frontend/src/lib/types.ts`
- Modify: `tauri/frontend/src/lib/api.ts`
- Modify: `tauri/frontend/src/lib/api.test.ts`

- [ ] **Step 1: 写失败测试**

编辑 `tauri/frontend/src/lib/types.ts` 末尾追加类型：

```ts
export interface RagSource {
  question_id: number;
  title: string;
  score: number;
}

export interface RagAnswer {
  answer: string;
  sources: RagSource[];
}
```

在 `tauri/frontend/src/lib/api.ts` 末尾追加：

```ts
// ---- RAG ----
export const ragAsk = (question: string, top_k?: number) =>
  invoke<RagAnswer>("rag_ask", { question, top_k });
export const ragIndex = () => invoke<number>("rag_index");
export const ragRetrieve = (query: string, top_k?: number) =>
  invoke<RagSource[]>("rag_retrieve", { query, top_k });
```

更新 `api.ts` 顶部 import（加入 `RagAnswer`、`RagSource`）：

```ts
import type {
  Chapter,
  CleanedQuestion,
  LlmConfig,
  OcrConfig,
  OcrDraft,
  Question,
  QuestionFilter,
  QuestionInput,
  RagAnswer,
  RagSource,
  Stats,
  Subject,
  Tag,
} from "./types";
```

在 `tauri/frontend/src/lib/api.test.ts` 的 API 测试中追加 describe：

```ts
describe("RAG", () => {
  it("ragAsk 调用 rag_ask 并传入 question/top_k", async () => {
    invoke.mockResolvedValue({ answer: "ok", sources: [] });
    await api.ragAsk("怎样解二次方程", 5);
    expect(invoke).toHaveBeenCalledWith("rag_ask", { question: "怎样解二次方程", top_k: 5 });
  });

  it("ragIndex 调用 rag_index", async () => {
    invoke.mockResolvedValue(3);
    await api.ragIndex();
    expect(invoke).toHaveBeenCalledWith("rag_index");
  });

  it("ragRetrieve 调用 rag_retrieve 并传入 query", async () => {
    invoke.mockResolvedValue([]);
    await api.ragRetrieve("勾股定理", 3);
    expect(invoke).toHaveBeenCalledWith("rag_retrieve", { query: "勾股定理", top_k: 3 });
  });
});
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /workspace/tauri/frontend && npm test`
Expected: FAIL（`api.ragAsk` 等未定义）

- [ ] **Step 3: 运行测试验证通过**

仅改完测试后类型/API 已加，直接运行：

Run: `cd /workspace/tauri/frontend && npm test`
Expected: PASS（含新增 3 个用例）

- [ ] **Step 4: Commit**

```bash
cd /workspace && git add tauri/frontend/src/lib/types.ts tauri/frontend/src/lib/api.ts tauri/frontend/src/lib/api.test.ts && git commit -m "feat: add RAG api layer and tests"
```

---

### Task 11: 「AI 问答」页面 + 路由 + 侧边栏入口

**Files:**
- Create: `tauri/frontend/src/views/RagChat.vue`
- Modify: `tauri/frontend/src/router.ts`
- Modify: `tauri/frontend/src/App.vue`

- [ ] **Step 1: 新增路由**

编辑 `tauri/frontend/src/router.ts`：

```ts
const RagChat = defineAsyncComponent(() => import("./views/RagChat.vue"));
```

在路由数组（`/settings` 之后）追加：

```ts
    { path: "/assistant", component: RagChat },
```

- [ ] **Step 2: 新增侧边栏入口**

编辑 `tauri/frontend/src/App.vue`，在"设置"RouterLink 之前插入：

```html
        <RouterLink
          to="/assistant"
          class="block px-3 py-2 rounded-md text-sm hover:bg-gray-100"
          active-class="bg-brand-50 text-brand-600 font-medium"
        >
          AI 问答
        </RouterLink>
```

- [ ] **Step 3: 创建页面组件**

创建 `tauri/frontend/src/views/RagChat.vue`：

```vue
<script setup lang="ts">
import { onMounted, ref } from "vue";
import * as api from "../lib/api";
import type { RagSource } from "../lib/types";

const question = ref("");
const answer = ref("");
const sources = ref<RagSource[]>([]);
const loading = ref(false);
const indexing = ref(false);
const indexMsg = ref("");
const error = ref("");

async function ask() {
  const text = question.value.trim();
  if (!text || loading.value) return;
  loading.value = true;
  error.value = "";
  answer.value = "";
  sources.value = [];
  try {
    const res = await api.ragAsk(text, 5);
    answer.value = res.answer;
    sources.value = res.sources;
  } catch (e) {
    error.value = `问答失败: ${e}`;
  } finally {
    loading.value = false;
  }
}

async function indexNow() {
  if (indexing.value) return;
  indexing.value = true;
  indexMsg.value = "";
  try {
    const n = await api.ragIndex();
    indexMsg.value = `索引完成，共 ${n} 题`;
  } catch (e) {
    indexMsg.value = `索引失败: ${e}`;
  } finally {
    indexing.value = false;
  }
}

onMounted(() => {});
</script>

<template>
  <div class="max-w-3xl mx-auto p-6">
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-2xl font-bold">AI 问答</h1>
      <button
        class="px-4 py-2 border border-gray-300 rounded-lg text-sm hover:bg-gray-50 disabled:opacity-50"
        :disabled="indexing"
        @click="indexNow"
      >
        {{ indexing ? "索引中…" : "更新索引" }}
      </button>
    </div>

    <p v-if="indexMsg" class="text-sm text-gray-500 mb-4">{{ indexMsg }}</p>

    <div class="flex gap-2 mb-4">
      <input
        v-model="question"
        class="flex-1 border border-gray-200 rounded-lg px-3 py-2"
        placeholder="用自然语言提问，例如：怎么解一元二次方程？"
        @keyup.enter="ask"
      />
      <button
        class="px-6 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50"
        :disabled="loading || !question.trim()"
        @click="ask"
      >
        {{ loading ? "思考中…" : "提问" }}
      </button>
    </div>

    <p v-if="error" class="text-red-500 text-sm mb-4">{{ error }}</p>

    <div
      v-if="answer"
      class="bg-white rounded-xl shadow-sm p-6 mb-6 whitespace-pre-wrap leading-relaxed"
    >
      {{ answer }}
    </div>

    <div v-if="sources.length" class="bg-white rounded-xl shadow-sm p-6">
      <h2 class="font-semibold mb-3">参考题目</h2>
      <ul class="space-y-2">
        <li v-for="s in sources" :key="s.question_id" class="text-sm">
          <RouterLink
            :to="`/questions/${s.question_id}/edit`"
            class="text-brand-600 hover:underline"
          >
            {{ s.title }}
          </RouterLink>
          <span class="text-gray-400 ml-2 tabular-nums">相关度 {{ (s.score * 100).toFixed(1) }}%</span>
        </li>
      </ul>
    </div>
  </div>
</template>
```

- [ ] **Step 4: 前端构建与测试**

Run: `cd /workspace/tauri/frontend && npm run build && npm test`
Expected: 构建成功，测试全通过

- [ ] **Step 5: Commit**

```bash
cd /workspace && git add tauri/frontend/src/views/RagChat.vue tauri/frontend/src/router.ts tauri/frontend/src/App.vue && git commit -m "feat: add AI Q&A page with index and ask"
```

---

### Task 12: 全量回归 + 提交

- [ ] **Step 1: Rust 全量测试**

Run: `cd /workspace/tauri && cargo test`
Expected: 全部通过（含既有与新增用例）

- [ ] **Step 2: 前端全量测试**

Run: `cd /workspace/tauri/frontend && npm test`
Expected: 全部通过

- [ ] **Step 3: 确认无侵入**

Run: `cd /workspace && git diff --stat HEAD~9`
Expected: 无非预期修改（`create_question`/`update_question`/`delete_question` 未改动，`ocr.rs` 未改动）

- [ ] **Step 4: Commit**

```bash
cd /workspace && git add -A && git commit -m "chore: final ragging regression pass"
```

---

## Self-Review

**Spec 覆盖：**
- Embedder trait + LocalEmbedder（本地 fastembed bge-small-zh）→ Task 2、3 ✓
- `question_embeddings` 表 → Task 1 ✓
- RagService index_all/retrieve/ask → Task 6 ✓
- Cleaner trait 扩展 `ask` + LlmCleaner 实现 → Task 4 ✓
- 嵌入配置（复用 LlmConfig，不新增 LLM 结构）→ Task 7 ✓
- Tauri 命令 rag_ask/rag_index/rag_retrieve → Task 9 ✓
- 复用 AppState pool、不侵入 CRUD/OCR → Task 6、9、12 ✓
- Vue「AI 问答」页面 + 侧边栏入口 → Task 11 ✓
- 错误与降级（无命中提示、LLM 未配置报错）→ Task 6、4 ✓
- 测试（cosine/top_k/codec/迁移/prompt/检索/前端）→ 各任务 ✓

**类型一致性：** `Embedder::{embed, dim}`、`Cleaner::ask(question, context)`、`RagAnswer{answer, sources}`、`RagSource{question_id,title,score}`、`top_k_scores(Vec<(i64,f32)>, usize)` 在各任务中保持一致。

**注意点：** fastembed `embed` 阻塞调用已包 `spawn_blocking`；fastembed 版本以 `cargo` 报错为准；沙箱若缺 onnxruntime 系统库则构建失败属环境限制，前端部分不受影响，可继续完成并记录。