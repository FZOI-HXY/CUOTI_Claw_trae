# RAG 改进：上下文元信息检索 + Self-RAG 轻量自检 Design

**Date:** 2026-08-06
**Status:** 已获用户认可（含「弱相关性→直接短路不调 LLM」行为）

## 背景与动机

当前 RAG 实现为「Standard RAG + Hybrid(BM25+RRF)」（见 `tauri/core/src/hybrid.rs`、`rag.rs`）。对照 16 种主流 RAG 架构，本轮选取两个「轻量、可落地、不破坏既有约束」的优点进行改进：

- **上下文元信息检索**（对应 #10 Contextual Retrieval / #12 Domain-Specific）：让关键词检索能命中「科目 / 知识点 / 题型 / 标签」等元信息。
- **Self-RAG 轻量自检**（对应 #14 Self-RAG）：检索后判断上下文是否足够、生成后给出接地(grounding)提示，减少在无关上下文上的无效生成与幻觉。

**约束前提（本轮严格遵守）：**
- `retrieve` 签名不变；`RagSource` / `RagAnswer` 结构不变；前端零改动。
- 自检信号一律通过 `answer` 文本透出，不新增结构字段。
- 不新增第三方依赖。

## A. 上下文元信息检索

### 现状
`rag.rs::question_text(q)` 拼接 title/options/answer/analysis，同时用于向量嵌入与 BM25 docs。账号信息 `subject_name`/`chapter_name`/`tags` 已由 `question::list_questions` 填充，但未参与检索文本。

### 改动
1. 新增 `fn question_keyword_text(q: &Question) -> String`：
   - 保留现有内容（title/options/answer/analysis）。
   - 追加 `subject_name`、`chapter_name`、qtype 中文标签（single→单选 etc.）、`tags`。
2. `retrieve` 第 2 步（BM25 docs 构建）改用 `question_keyword_text`。
3. **向量嵌入文本 `question_text` 保持不变** → 存量向量无需重建，`index_all`/`index_incremental` 不改。

### 收益
查询如「勾股定理 选择题」「代数 函数 填空」能通过关键词命中对应题型/知识点/标签，提升混合检索召回。

### 测试
- 单测：构造含科目/章节/题型/标签的题目，验证 `question_keyword_text` 生成的文本包含这些元信息；验证按「题型/知识点」关键词 `bm25_scores` 可召回对应题。

## B. Self-RAG 轻量自检

### 阈值常量（`rag.rs`）
```rust
/// 余弦相似度：低于该值视为「相关性弱」，检索后可短路
const WEAK_SCORE: f32 = 0.30;
/// 余弦相似度：低于该值但非空，生成后追加接地提示
const GROUNDING_SCORE: f32 = 0.45;
```

### 自检1（检索后相关性门控）— 在 `rag::ask`
- `sources` 为空 → 维持现状「没有检索到相关题目…」。
- `sources` 非空但全部 `score < WEAK_SCORE` → **不调 LLM**，直接返回：
  「检索到 N 道相关题目，但与问题相关性较低，以下题目仅供参考，可能无法给出准确解答。」
  仍附带 `sources`（列表照常返回，供前端展示）。
- 否则 → 正常走 LLM 生成。

### 自检2（生成后接地提示）— 在 `rag::ask`
- 生成出 `answer` 后，若首条来源 `score < GROUNDING_SCORE`（且 ≥ WEAK_SCORE）→ 在答案末尾追加：
  「（提示：检索到的相关题目相关性一般，以上回答仅供参考，建议确认题目原文。）」
- 否则不改动答案文本。

### 行为确认
- 弱相关性时**直接短路不调 LLM**（已获用户认可）。
- 两条自检均只改 `answer` 文本，接口不变。

### 测试
- 单测（`MockEmbedder`/`QueryEmbedder`）：
  - 构造低分命中 → `ask` 返回「相关性较低」分支且不调用 LLM（可用 mock cleaner 计数验证）。
  - 构造中分命中 → `ask` 返回的 `answer` 包含接地提示。
  - 高分命中 → 无提示、正常生成。

## C. 约束解耦决策（本轮不实现，仅记录）

- 更新 `.trae/rules/project_rules.md` 规则5：明确「后续可引入 cross-encoder 重排、Adaptive 查询路由等进阶手段」，本轮仍保持接口稳定、不新增依赖。
- 作为后续方向记录，不在本轮实现。

## 涉及文件
- `tauri/core/src/rag.rs`：新增 `question_keyword_text`、阈值常量、自检1/2 逻辑、新增测试。
- `.trae/rules/project_rules.md`：规则5 更新（解耦决策）。

## 非目标（YAGNI）
- 不引入 cross-encoder 重排、Graph/多模态/联邦 RAG、HyDE、Adaptive 路由。
- 不新增 `RagAnswer` 字段、不改前端。
- 不为元信息检索重建向量索引。