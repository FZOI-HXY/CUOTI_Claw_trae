# RAG 改进：上下文元信息检索 + Self-RAG 轻量自检 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 通过「上下文元信息检索」提升关键词召回，并引入 Self-RAG 轻量自检（弱相关性短路 + 接地提示），改进 RAG 问答的准确性与诚实性。

**Architecture:** 在 `rag.rs` 新增 `question_keyword_text`（含科目/章节/题型/标签元信息）供 BM25 使用，向量嵌入文本不变；在 `ask` 中加入阈值自检（`WEAK_SCORE`/`GROUNDING_SCORE`），信号通过 `answer` 文本透出。接口、结构、前端均不变。

**Tech Stack:** Rust (cuoti-core)、sqlx(SQLite)、fastembed（既有）；无新增依赖。

**设计依据:** 见 `docs/superpowers/specs/2026-08-06-rag-contextual-selfcheck-design.md`。

**耦合约束（务必遵守）：**
- 不修改 `retrieve` 签名、`RagSource` / `RagAnswer` 结构、前端 `api.ts`/`types.ts`/`RagChat.vue`。
- 不新增字段；自检信号只改 `answer` 文本。
- 不新增第三方 crate。
- 仅改动 `tauri/core/src/rag.rs` 与 `.trae/rules/project_rules.md`。

---

### Task 1: 新增 `question_keyword_text` + `qtype_label`（含元信息）

**Files:**
- Modify: `tauri/core/src/rag.rs`（在 `question_text` 之后新增两个函数 + 测试）

- [ ] **Step 1: 写失败测试**

在 `rag.rs` 的 `#[cfg(test)] mod tests` 内新增测试。先确认 `use super::*` 已引入 `Question` 模型（通过 `setup_state` 已使用）。在 `tests` 模块末尾追加：

```rust
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
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /workspace/tauri && cargo test -p cuoti-core --lib rag::tests::test_question_keyword_text_includes_metadata rag::tests::test_qtype_label_maps_all_types`
Expected: FAIL（`question_keyword_text` / `qtype_label` 未定义；编译错误）

- [ ] **Step 3: 实现两个函数**

在 `rag.rs` 的 `question_text` 函数之后新增：

```rust
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
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd /workspace/tauri && cargo test -p cuoti-core --lib rag::tests::test_question_keyword_text_includes_metadata rag::tests::test_qtype_label_maps_all_types`
Expected: PASS（2 个用例）

- [ ] **Step 5: Commit**

```bash
cd /workspace && git add tauri/core/src/rag.rs && git commit -m "feat: add question_keyword_text and qtype_label for metadata retrieval"
```

---

### Task 2: 在 `retrieve` 中启用元信息关键词检索

**Files:**
- Modify: `tauri/core/src/rag.rs`（`retrieve` 的 BM25 docs 构建）

- [ ] **Step 1: 写失败测试**

在 `tests` 模块末尾追加（复用 `Question` 构造方式，验证「按题型/知识点」可被 BM25 召回）：

```rust
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
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /workspace/tauri && cargo test -p cuoti-core --lib rag::tests::test_bm25_recalls_by_metadata_keyword`
Expected: FAIL — 原因：`retrieve` 目前 BM25 用的是 `question_text`（不含元信息），但本测试直接调 `question_keyword_text`，因此**预期会 PASS**。
> 说明：本测试验证的是 `question_keyword_text` 产出的文本能被 BM25 命中元信息，属于 Task 1 功能的集成验证。若 Task 1 已完成则此处直接 PASS；真正的「接入 retrieve」改动在 Step 3。若需严格 TDD，可在 Step 3 前临时把 `retrieve` 的 docs 仍用 `question_text` 并断言失败，再切换。

- [ ] **Step 3: 修改 `retrieve` 使用元信息文本**

在 `rag.rs` 的 `retrieve` 中，将 BM25 docs 构建行替换（当前为 `question_text`）：

```rust
    let docs: Vec<(i64, String)> = questions
        .iter()
        .map(|q| (q.id, question_keyword_text(q)))
        .collect();
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd /workspace/tauri && cargo test -p cuoti-core --lib rag::tests`
Expected: PASS（原 5 + 新增 3 = 8 个用例）

- [ ] **Step 5: Commit**

```bash
cd /workspace && git add tauri/core/src/rag.rs && git commit -m "feat: enable metadata-rich keyword retrieval in rag retrieve"
```

---

### Task 3: Self-RAG 自检1（弱相关性短路）

**Files:**
- Modify: `tauri/core/src/rag.rs`（新增阈值常量 + 修改 `ask` + 测试）

- [ ] **Step 1: 写失败测试**

在 `tests` 模块顶部新增 import（放到 `use super::*;` 之后）：

```rust
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;
```

在 `MockCleaner` 之后新增「计数 cleaner」（用于验证短路时不调 LLM）：

```rust
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
```

在 `tests` 模块末尾追加（构造随机正交向量使余弦≈0，触发短路）：

```rust
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
        // 手工写入与查询向量正交的向量 → 余弦=0 < WEAK_SCORE
        sqlx::query(
            "INSERT OR REPLACE INTO question_embeddings (question_id, model, vector, updated_at)
             VALUES (?,?,?,datetime('now','localtime'))",
        )
        .bind(qid)
        .bind(EMBED_MODEL)
        .bind(encode_vec(&vec![0.0f32, 1.0, 0.0]))
        .execute(&state.pool)
        .await
        .expect("insert vec");

        let calls = Arc::new(AtomicUsize::new(0));
        let cleaner = CountingCleaner { calls: Arc::clone(&calls) };
        let embedder = QueryEmbedder { qvec: vec![1.0, 0.0, 0.0] };
        let ans = rag::ask(&state, &embedder, &cleaner, "随便问问", 5).await.expect("ask");
        assert!(ans.answer.contains("相关性较低"), "应命中弱相关性分支: {}", ans.answer);
        assert!(ans.sources.iter().any(|s| s.question_id == qid), "来源列表应返回");
        assert_eq!(calls.load(Ordering::SeqCst), 0, "弱相关性不应调用 LLM");
    }
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /workspace/tauri && cargo test -p cuoti-core --lib rag::tests::test_ask_short_circuits_on_weak_relevance`
Expected: FAIL（当前 `ask` 直接调 cleaner，`calls == 1` 而非 0，且 answer 不以「相关性较低」开头）

- [ ] **Step 3: 实现阈值常量与自检1**

在 `rag.rs` 中 `EMBED_MODEL` 常量之后新增：

```rust
/// 余弦相似度：低于该值视为「相关性弱」，检索后可短路不调 LLM
pub const WEAK_SCORE: f32 = 0.30;
/// 余弦相似度：低于该值但非空，生成后追加接地提示
pub const GROUNDING_SCORE: f32 = 0.45;
```

将 `ask` 函数体替换为：

```rust
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

    let mut ctx = String::new();
    for (i, s) in sources.iter().enumerate() {
        ctx.push_str(&format!("[{}] 题目: {}\n", i + 1, s.title));
    }
    let mut answer = cleaner.ask(question, &ctx).await?;

    // 自检2：首条来源相关性一般 → 追加接地提示
    if sources[0].score < GROUNDING_SCORE {
        answer.push_str("（提示：检索到的相关题目相关性一般，以上回答仅供参考，建议确认题目原文。）");
    }
    Ok(RagAnswer { answer, sources })
}
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd /workspace/tauri && cargo test -p cuoti-core --lib rag::tests::test_ask_short_circuits_on_weak_relevance`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /workspace && git add tauri/core/src/rag.rs && git commit -m "feat: Self-RAG weak-relevance short-circuit in ask"
```

---

### Task 4: Self-RAG 自检2（接地提示）

**Files:**
- Modify: `tauri/core/src/rag.rs`（测试）

- [ ] **Step 1: 写失败测试**

在 `tests` 模块末尾追加（中分命中 → 答案含提示；高分命中 → 无提示）：

```rust
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
        let ans = rag::ask(&state, &embedder, &cleaner, "问题", 5).await.expect("ask");
        assert!(ans.answer.ends_with("建议确认题目原文。）"), "应追加接地提示: {}", ans.answer);
    }

    #[tokio::test]
    async fn test_ask_no_hint_on_strong_relevance() {
        let pool = db::init_db(None).await.expect("memory db");
        let state = AppState::new(pool);
        insert_question_with_vec(&state, "题目B", vec![1.0f32, 0.0]).await;
        let cleaner = MockCleaner;
        let embedder = QueryEmbedder { qvec: vec![1.0, 0.0] };
        let ans = rag::ask(&state, &embedder, &cleaner, "问题", 5).await.expect("ask");
        assert!(!ans.answer.contains("建议确认题目原文"), "强相关不应有提示: {}", ans.answer);
        assert!(ans.answer.starts_with("answer for:"), "应正常生成");
    }
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /workspace/tauri && cargo test -p cuoti-core --lib rag::tests::test_ask_appends_grounding_hint_on_medium_relevance rag::tests::test_ask_no_hint_on_strong_relevance`
Expected: 
- `test_ask_appends_grounding_hint_on_medium_relevance` FAIL（当前 `ask` 未加提示）
- `test_ask_no_hint_on_strong_relevance` PASS

- [ ] **Step 3: 实现（已在 Task 3 完成）**

自检2 逻辑已在 Task 3 的 `ask` 实现中（`if sources[0].score < GROUNDING_SCORE`）。本步无需额外代码改动。

- [ ] **Step 4: 运行测试验证通过**

Run: `cd /workspace/tauri && cargo test -p cuoti-core --lib rag::tests`
Expected: PASS（原 8 + 新增 3 = 11 个用例）

- [ ] **Step 5: Commit**

```bash
cd /workspace && git add tauri/core/src/rag.rs && git commit -m "test: Self-RAG grounding hint on medium relevance"
```

---

### Task 5: 更新约束文件（约束解耦决策）

**Files:**
- Modify: `.trae/rules/project_rules.md`（规则5）

- [ ] **Step 1: 更新规则5**

将规则5内容替换为：

```markdown
## 5. RAG 约束（延续既有设计）

- 现状接口保持稳定：`retrieve` 签名、`RagSource`/`RagAnswer` 结构、前端均不变；自检信号通过 `answer` 文本透出。
- 不新增第三方依赖（当前）。
- **后续方向（本轮不实现，仅记录）**：可基于成本/收益评估引入 cross-encoder 重排、Adaptive 查询路由、HyDE 等进阶手段；一旦引入需重新评估依赖与接口约束。
- 混合检索（hybrid.rs：BM25 + RRF）与元信息关键词文本（question_keyword_text）为核心，后续优化需保持接口稳定。
```

- [ ] **Step 2: 确认无回归（纯文档）**

Run: `cd /workspace && git diff --stat`
Expected: 仅 `.trae/rules/project_rules.md`、`tauri/core/src/rag.rs` 有改动

- [ ] **Step 3: Commit**

```bash
cd /workspace && git add .trae/rules/project_rules.md && git commit -m "docs: record RAG constraint decoupling decision"
```

---

### Task 6: 全量回归 + 提交

- [ ] **Step 1: cuoti-core 全量测试**

Run: `cd /workspace/tauri && cargo test -p cuoti-core`
Expected: 全部通过（含既有与新增用例）

- [ ] **Step 2: 确认无侵入**

Run: `cd /workspace && git diff --stat HEAD~6`
Expected: 仅改动 `tauri/core/src/rag.rs`、`.trae/rules/project_rules.md`、`docs/superpowers/specs/2026-08-06-rag-contextual-selfcheck-design.md`；`commands/rag.rs`、`models.rs`、`hybrid.rs`、前端、`ocr.rs` 均未改动

- [ ] **Step 3: Commit**

```bash
cd /workspace && git add -A && git commit -m "chore: RAG contextual metadata + Self-RAG regression pass"
```

---

## Self-Review

**Spec 覆盖：**
- 上下文元信息检索（A）→ Task 1、2 ✓
- 保持向量文本不变、无需重建索引 → Task 2 ✓
- Self-RAG 自检1 弱相关性短路（B）→ Task 3 ✓
- Self-RAG 自检2 接地提示（B）→ Task 4 ✓
- 自检信号只改 answer 文本、接口不变 → Task 3、4 ✓
- 约束解耦决策记录（C）→ Task 5 ✓
- 全量回归 → Task 6 ✓

**类型一致性：**
- `question_keyword_text(&Question) -> String`、`qtype_label(&str) -> &'static str`，Task 1 定义、Task 2 使用一致。
- `WEAK_SCORE`/`GROUNDING_SCORE: f32` 常量，Task 3 定义、Task 3/4 使用一致。
- `insert_question_with_vec(state, title, vec) -> i64` 在 Task 4 定义并使用。
- `CountingCleaner` 在 Task 3 定义、Task 3 测试使用。

**说明：**
- Task 2 Step 2 因测试直接调用 `question_keyword_text`（Task 1 已实现）会直接 PASS，属集成验证；真正的接入改动在 Step 3。
- Task 4 Step 3 无代码改动，因自检2 已在 Task 3 实现，仅补测试验证。