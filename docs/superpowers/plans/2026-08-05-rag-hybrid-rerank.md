# RAG 混合检索 + RRF 融合重排 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有纯向量 RAG 检索上，增加 BM25 式关键词检索 + RRF(Reciprocal Rank Fusion) 融合排序，让公式、题号、选项、专有名词等「精确匹配」的题目能被正确召回并排到前面，提升检索精度。

**Architecture:** 新增纯逻辑模块 `hybrid.rs`（中文 2-gram 分词 + BM25 式稀疏打分 + RRF 融合），全部为无 IO 的纯函数、可单测；在 `rag::retrieve` 中先做向量召回做关键词召回，二者经 RRF 融合作为最终排序，`score` 仍保留向量余弦供前端展示（接口不变，前端零改动）。不新增依赖、不改表结构、不侵入 CRUD。

**Tech Stack:** Rust (cuoti-core)、sqlx(SQLite)、fastembed（既有）；无新增第三方依赖。

**设计依据:** 开源实践（2026 默认 RAG 栈）表明「纯向量检索」在大约 40% 的检索中失败，其中约 73% 的失败发生在检索环节（而非生成环节）；BM25 精确匹配 + 向量语义 + RRF 融合是业界最普遍、性价比最高的提升手段。本计划据此落地。

**耦合约束（务必遵守）：**
- 不修改 `index_all` / `index_incremental` / `ask` 的签名
- `retrieve` 签名保持不变（`(state, embedder, query, top_k) -> Vec<RagSource>`），`RagSource` 结构不新增字段
- 不新增任何第三方 crate
- 前端 `api.ts` / `RagChat.vue` / `types.ts` 不改动
- 仅改动 `tauri/core/src/` 下文件

---

### Task 1: 新建 `hybrid.rs` 模块 + 中文分词器

**Files:**
- Create: `tauri/core/src/hybrid.rs`
- Modify: `tauri/core/src/lib.rs`（注册 `pub mod hybrid;`）

- [ ] **Step 1: 写失败测试**

创建 `tauri/core/src/hybrid.rs`，先写测试与签名占位：

```rust
//! 混合检索：稀疏(BM25 式)召回 + RRF 融合排序
//! 与向量检索互补：向量管语义相似，关键词管公式/题号/专有名词的精确匹配。

/// 中文表意字符（CJK 统一表意文字）
fn is_cjk(c: char) -> bool {
    let u = c as u32;
    (0x3400..=0x4DBF).contains(&u) || (0x4E00..=0x9FFF).contains(&u)
}

/// 分词：CJK 连续段按 2-gram 切分，ASCII 字母数字按连续串切分（小写）
pub fn tokenize(text: &str) -> Vec<String> {
    unimplemented!()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_tokenize_ascii_and_cjk() {
        let toks = tokenize("勾股定理 a^2+b^2=c^2");
        assert!(toks.contains(&"勾股".to_string()));
        assert!(toks.contains(&"定理".to_string()));
        assert!(toks.contains(&"a".to_string()));
        assert!(toks.contains(&"2".to_string()));
    }

    #[test]
    fn test_tokenize_single_cjk_char_is_kept() {
        let toks = tokenize("求解");
        // 两个 CJK 字符 → 一个 2-gram
        assert_eq!(toks, vec!["求解".to_string()]);
    }
}
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /workspace/tauri && cargo test -p cuoti-core --lib hybrid::tests`
Expected: FAIL（`unimplemented!()` panic）

- [ ] **Step 3: 实现分词器**

将 `tokenize` 函数体替换为：

```rust
/// 分词：CJK 连续段按 2-gram 切分，ASCII 字母数字按连续串切分（小写）
pub fn tokenize(text: &str) -> Vec<String> {
    let chars: Vec<char> = text.chars().collect();
    let mut tokens = Vec::new();
    let mut i = 0;
    while i < chars.len() {
        if chars[i].is_ascii_alphanumeric() {
            let start = i;
            while i < chars.len() && chars[i].is_ascii_alphanumeric() {
                i += 1;
            }
            tokens.push(chars[start..i].iter().collect::<String>().to_lowercase());
        } else if is_cjk(chars[i]) {
            let start = i;
            while i < chars.len() && is_cjk(chars[i]) {
                i += 1;
            }
            let run: Vec<char> = chars[start..i].to_vec();
            if run.len() == 1 {
                tokens.push(run[0].to_string());
            } else {
                for w in run.windows(2) {
                    tokens.push(format!("{}{}", w[0], w[1]));
                }
            }
        } else {
            i += 1;
        }
    }
    tokens
}
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd /workspace/tauri && cargo test -p cuoti-core --lib hybrid::tests`
Expected: PASS（2 个用例）

- [ ] **Step 5: 注册模块 + Commit**

在 `tauri/core/src/lib.rs` 的 `pub mod` 列表追加：

```rust
pub mod hybrid;
```

```bash
cd /workspace && git add tauri/core/src/hybrid.rs tauri/core/src/lib.rs && git commit -m "feat: add hybrid module with CJK tokenizer"
```

---

### Task 2: BM25 式稀疏打分

**Files:**
- Modify: `tauri/core/src/hybrid.rs`

- [ ] **Step 1: 写失败测试**

在 `tauri/core/src/hybrid.rs` 的 `tests` 模块末尾追加：

```rust
    #[test]
    fn test_bm25_prefers_exact_match_doc() {
        let docs = vec![
            (1, "一元二次方程求解 x^2-5x+6=0".to_string()),
            (2, "勾股定理 三角形 直角".to_string()),
        ];
        let scores = bm25_scores(&docs, "一元二次方程");
        let (top_id, _) = scores
            .iter()
            .max_by(|a, b| a.1.partial_cmp(&b.1).unwrap())
            .expect("non-empty");
        assert_eq!(*top_id, 1);
        let (_id2, s2) = scores.iter().find(|(id, _)| *id == 2).expect("doc2");
        assert!(scores.iter().find(|(id, _)| *id == 1).unwrap().1 > *s2);
    }

    #[test]
    fn test_bm25_empty_query_returns_zero() {
        let docs = vec![(1, "勾股定理".to_string())];
        let scores = bm25_scores(&docs, "");
        assert_eq!(scores, vec![(1, 0.0)]);
    }
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /workspace/tauri && cargo test -p cuoti-core --lib hybrid::tests::test_bm25`
Expected: FAIL（`bm25_scores` 不存在；编译错误）

- [ ] **Step 3: 实现 BM25**

在 `tokenize` 之后新增函数（顶部 import 加入 `use std::collections::{HashMap, HashSet};`）：

```rust
/// BM25 式稀疏打分（k1=1.5, b=0.75）。docs: (doc_id, 文本)
pub fn bm25_scores(docs: &[(i64, String)], query: &str) -> Vec<(i64, f32)> {
    const K1: f32 = 1.5;
    const B: f32 = 0.75;

    let mut doc_tokens: Vec<Vec<String>> = Vec::with_capacity(docs.len());
    let mut doc_lens: Vec<usize> = Vec::with_capacity(docs.len());
    let mut df: HashMap<String, u32> = HashMap::new();

    for (_, text) in docs {
        let toks = tokenize(text);
        doc_tokens.push(toks.clone());
        doc_lens.push(toks.len());
        let mut seen = HashSet::new();
        for t in &toks {
            if seen.insert(t.clone()) {
                *df.entry(t.clone()).or_insert(0) += 1;
            }
        }
    }
    let n = docs.len().max(1) as f32;
    let avgdl: f32 = if doc_lens.is_empty() {
        1.0
    } else {
        doc_lens.iter().sum::<usize>() as f32 / doc_lens.len() as f32
    };

    let q_tokens = tokenize(query);
    let mut scores = vec![0.0f32; docs.len()];
    for term in &q_tokens {
        let df_t = *df.get(term).unwrap_or(&0);
        let idf = ((n - df_t as f32 + 0.5) / (df_t as f32 + 0.5) + 1.0).ln();
        for (i, doc) in doc_tokens.iter().enumerate() {
            let tf = doc.iter().filter(|t| *t == term).count() as f32;
            if tf == 0.0 {
                continue;
            }
            let dl = doc_lens[i] as f32;
            let denom = tf + K1 * (1.0 - B + B * dl / avgdl);
            scores[i] += idf * (tf * (K1 + 1.0)) / denom;
        }
    }

    docs.iter()
        .enumerate()
        .map(|(i, (id, _))| (*id, scores[i]))
        .collect()
}
```

> 注：若 `tests` 中 `test_bm25_empty_query_returns_zero` 因 `bm25_scores(docs, "")` 返回的 `scores` 全为 0.0，断言 `== vec![(1, 0.0)]` 成立（f32 精确 0.0）。

- [ ] **Step 4: 运行测试验证通过**

Run: `cd /workspace/tauri && cargo test -p cuoti-core --lib hybrid::tests`
Expected: PASS（4 个用例）

- [ ] **Step 5: Commit**

```bash
cd /workspace && git add tauri/core/src/hybrid.rs && git commit -m "feat: add BM25-style sparse scoring"
```

---

### Task 3: RRF 融合排序

**Files:**
- Modify: `tauri/core/src/hybrid.rs`

- [ ] **Step 1: 写失败测试**

在 `tauri/core/src/hybrid.rs` 的 `tests` 模块末尾追加：

```rust
    #[test]
    fn test_rrf_fuses_and_ranks() {
        let vector = vec![(1, 0.9), (2, 0.8), (3, 0.7)];
        let keyword = vec![(2, 3.0), (1, 2.0)];
        let fused = rrf_fuse(&[vector, keyword], 60.0);
        // id2 在两个榜单都靠前 → 应排第一
        assert_eq!(fused[0].0, 2);
        assert!(fused.iter().any(|(id, _)| *id == 1));
        assert!(fused.iter().any(|(id, _)| *id == 3));
    }

    #[test]
    fn test_rrf_single_list_preserves_order() {
        let vector = vec![(5, 0.9), (6, 0.8)];
        let fused = rrf_fuse(&[vector], 60.0);
        assert_eq!(fused, vec![(5, 1.0 / 61.0), (6, 1.0 / 62.0)]);
    }
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /workspace/tauri && cargo test -p cuoti-core --lib hybrid::tests::test_rrf`
Expected: FAIL（`rrf_fuse` 不存在）

- [ ] **Step 3: 实现 RRF**

在 `bm25_scores` 之后新增：

```rust
/// RRF 融合：输入若干按分数降序的榜单，按名次加权累加（k 常取 60）
pub fn rrf_fuse(lists: &[Vec<(i64, f32)>], k: f32) -> Vec<(i64, f32)> {
    let mut acc: HashMap<i64, f32> = HashMap::new();
    for list in lists {
        for (rank, (id, _)) in list.iter().enumerate() {
            *acc.entry(*id).or_insert(0.0) += 1.0 / (k + rank as f32 + 1.0);
        }
    }
    let mut v: Vec<(i64, f32)> = acc.into_iter().collect();
    v.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    v
}
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd /workspace/tauri && cargo test -p cuoti-core --lib hybrid::tests`
Expected: PASS（6 个用例）

- [ ] **Step 5: Commit**

```bash
cd /workspace && git add tauri/core/src/hybrid.rs && git commit -m "feat: add RRF fusion for hybrid retrieval"
```

---

### Task 4: 集成到 `rag::retrieve`（向量 + 关键词 → RRF → 排序）

**Files:**
- Modify: `tauri/core/src/rag.rs`（`retrieve` 函数与 import）

- [ ] **Step 1: 更新 import 与 `retrieve` 实现**

将 `rag.rs` 顶部的 import 追加：

```rust
use std::collections::HashMap;
// ...原有 import 保留...
use crate::hybrid;
```

将 `rag.rs` 中 `retrieve` 函数体整体替换为：

```rust
/// 混合检索：向量召回 + 关键词(BM25)召回 → RRF 融合排序
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
        .map(|q| (q.id, question_text(q)))
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
    let mut out = Vec::new();
    for (qid, _) in fused {
        let score = *cosine_map.get(&qid).unwrap_or(&0.0);
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
    out.truncate(top_k);
    Ok(out)
}
```

- [ ] **Step 2: 运行既有 RAG 测试确认不回归**

Run: `cd /workspace/tauri && cargo test -p cuoti-core --lib rag::tests`
Expected: PASS（既有 4 个用例：index_and_retrieve_top_k / ask_wraps / ask_no_hits / index_incremental）

- [ ] **Step 3: Commit**

```bash
cd /workspace && git add tauri/core/src/rag.rs && git commit -m "feat: integrate hybrid BM25 + RRF into rag retrieve"
```

---

### Task 5: 混合检索评价测试（关键词精确匹配能被召回）

**Files:**
- Modify: `tauri/core/src/rag.rs`（`#[cfg(test)] mod tests`）

- [ ] **Step 1: 写失败测试**

在 `rag.rs` 测试模块中，`MockEmbedder` 定义之后新增一个「固定查询向量」嵌入器：

```rust
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
```

在 `tests` 模块末尾追加：

```rust
    #[tokio::test]
    async fn test_hybrid_retrieval_surfaces_keyword_exact_match() {
        // 构造：q1、q2 向量相似度高，q3 向量分低（0.05），但 q3 是关键词精确匹配项。
        // 纯向量 top2 应只返回 [q1, q2]；混合检索应靠 BM25 把 q3 召回。
        let pool = db::init_db(None).await.expect("memory db");
        let state = AppState::new(pool);
        let subj = crate::commands::subject::create_subject(&state, "数学".into())
            .await
            .expect("subj");
        let mk = |state: &AppState, title: &str, answer: &str| {
            crate::commands::question::create_question(
                state,
                QuestionInput {
                    subject_id: subj.id,
                    chapter_id: None,
                    qtype: Some("single".into()),
                    title: title.into(),
                    options: None,
                    answer: Some(answer.into()),
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
            .expect("create")
            .id
        };
        let q1 = mk(&state, "三角函数 弧度", "sin");
        let q2 = mk(&state, "指数函数 对数", "e");
        let q3 = mk(&state, "勾股定理 直角边", "a^2+b^2=c^2");

        // 手工写入向量以精确控制相似度（绕过 index_all）
        for (id, vec) in [
            (q1, vec![1.0f32, 0.0, 0.0]),
            (q2, vec![0.9, 0.0, 0.0]),
            (q3, vec![0.05, 0.0, 0.0]),
        ] {
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

        let embedder = QueryEmbedder { qvec: vec![1.0, 0.0, 0.0] };
        let hits = retrieve(&state, &embedder, "勾股定理", 2).await.expect("retrieve");
        // 纯向量 top2 为 [q1, q2]（q3 相似度 0.05 被挤出）；混合检索靠关键词召回 q3
        assert!(
            hits.iter().any(|s| s.question_id == q3),
            "关键词精确匹配题应被混合检索召回"
        );
    }
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd /workspace/tauri && cargo test -p cuoti-core --lib rag::tests::test_hybrid_retrieval_surfaces_keyword_exact_match`
Expected: FAIL（在 Task 4 之前，旧 `retrieve` 直接用向量 top_k，q3 相似度 0.05 不在 top2 内，断言 `hits.contains(q3)` 失败）

> 说明：若先完成 Task 4 再写此测试会直接 PASS。为保证 TDD 顺序，请在 Task 4 之前创建本测试确认失败，或临时 `git stash` Task 4 的改动后验证失败。

- [ ] **Step 3: 实现使其通过**

本测试依赖 Task 4 的混合检索实现。若当前 `retrieve` 已是混合版，直接进入 Step 4。

- [ ] **Step 4: 运行测试验证通过**

Run: `cd /workspace/tauri && cargo test -p cuoti-core --lib rag::tests`
Expected: PASS（原 4 个 + 新增 1 个，共 5 个）

- [ ] **Step 5: Commit**

```bash
cd /workspace && git add tauri/core/src/rag.rs && git commit -m "test: hybrid retrieval surfaces keyword exact match"
```

---

### Task 6: 全量回归 + 提交

- [ ] **Step 1: Rust 全量测试**

Run: `cd /workspace/tauri && cargo test`
Expected: 全部通过（含既有与新增用例）

- [ ] **Step 2: 确认无侵入**

Run: `cd /workspace && git diff --stat HEAD~5`
Expected: 仅改动 `tauri/core/src/hybrid.rs`、`tauri/core/src/lib.rs`、`tauri/core/src/rag.rs`；`commands/rag.rs`、`models.rs`、前端、`ocr.rs`、CRUD 均未改动

- [ ] **Step 3: Commit**

```bash
cd /workspace && git add -A && git commit -m "chore: hybrid retrieval regression pass"
```

---

## Self-Review

**Spec 覆盖：**
- BM25 式关键词检索 → Task 2 ✓
- RRF 融合排序 → Task 3 ✓
- 集成到 `rag::retrieve` → Task 4 ✓
- 保持接口不变（`retrieve` 签名、`RagSource`、前端零改动）→ Task 4、6 ✓
- 中文分词（2-gram，适配题目/公式混合文本）→ Task 1 ✓
- 评价/回归测试 → Task 5、6 ✓
- 不新增依赖、不改表结构、不侵入 CRUD → Task 4、6 ✓

**类型一致性：** `hybrid::{tokenize(&str)->Vec<String>, bm25_scores(&[(i64,String)],&str)->Vec<(i64,f32)>, rrf_fuse(&[Vec<(i64,f32)>],f32)->Vec<(i64,f32)>}`；`top_k_scores(Vec<(i64,f32)>, usize)`；`retrieve` 返回 `Vec<RagSource>`。各任务引用一致。

**设计权衡（记录）：**
- 关键词打分在查询时对全部题目文本实时计算（无反向索引）。题目库规模小（万级内），可接受；若未来题目量激增，可另建 FTS/倒排表，本计划不涉及以免过度设计。
- 采用 RRF 而非线性加权融合，避免 `BM25(无上界)` 与 `cosine(0..1)` 的量纲不一致问题。
- 保留 `score = 向量余弦`（0..1）供前端 `相关度 x%` 展示；RRF 仅用于决定排序，语义不变。