# 智能问答 RAG 助手 — 设计文档

日期：2026-08-04
状态：已确认

## 1. 背景与目标

错题本应用为 Tauri 2 + Rust + Vue 3 + SQLite 架构。当前已有 `Cleaner` trait 作为 RAG 扩展点，但系统仅支持关键词搜索，无法进行语义检索与智能问答。

本设计为系统新增**智能问答 RAG 助手**：用户用自然语言提问，系统从错题库中检索相关知识点题目作为上下文，调用 LLM 生成带引用的解答。

## 2. 需求确认

| 维度 | 决策 |
|------|------|
| RAG 用途 | 智能问答优先，语义搜索/相似题推荐为后续 |
| 集成端 | Tauri 桌面端（Rust） |
| 嵌入模型 | 本地 fastembed-rs（CPU）优先，可切换 API（后续扩展） |
| 生成模型 | 复用现有 `Cleaner` trait（OpenAI 兼容云端 LLM，与清洗同源），本地生成留待后续 |
| 推理约束 | 仅 CPU 推理（fastembed-rs 默认 ONNX CPU，满足） |

## 3. 模型源澄清

| 能力 | 模型源 | 现有代码 | 与 RAG 关系 |
|------|--------|----------|-------------|
| OCR 识别 | PaddleOCR（PaddleOcrService） | `ocr.rs` | 独立，不参与 RAG |
| 清洗 / 问答生成 | OpenAI 兼容 LLM（LlmCleaner） | `cleaner.rs` | **复用同一抽象** |
| 向量嵌入 | fastembed 本地（bge-small-zh） | 新增 | 独立 |

问答生成复用 `Cleaner` trait（与清洗同源）；OCR 用独立的 `PaddleOcrService`，两者不相干。

## 4. 架构

```
┌────────────── Vue 3 前端 ──────────────┐
│  新增「AI 问答」页面 + 侧边栏入口        │
└──────────────┬──────────────────────────┘
               │ invoke('rag_ask' / 'rag_index' / 'rag_retrieve')
┌──────────────▼──────────────────────────┐
│        Rust 后端 (cuoti-core)           │
│  ┌─────────────┐   ┌────────────────┐   │
│  │  Embedder    │   │  RagService    │   │
│  │ (trait)      │   │  检索+生成+排序 │   │
│  │  └ LocalEmbed │   └──────┬─────────┘   │
│  └──────┬───────┘          │ 复用 Cleaner │
🏁  └─────────────────────┴──────────────┘
          │ SQLite (BLOB 向量)
    questions + question_embeddings
```

## 5. 组件设计

### 5.1 嵌入层 `Embedder` trait（`core/src/embedder.rs`，新增）

```rust
#[async_trait]
pub trait Embedder: Send + Sync {
    async fn embed(&self, texts: &[String]) -> Result<Vec<Vec<f32>>>;
    fn dim(&self) -> usize;
}
```

- `LocalEmbedder`：`fastembed-rs` 跑 `bge-small-zh-v1.5`（CPU，ONNX），维度 512
- `ApiEmbedder`：调 OpenAI 兼容 `/embeddings` 端点（**后续扩展**，预留接口）
- 单例管理模型加载，避免重复初始化

### 5.2 向量存储（扩展 `core/src/db.rs`）

新增表（追加到现有 `migrate()`，幂等）：

```sql
CREATE TABLE IF NOT EXISTS question_embeddings (
    question_id INTEGER PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
    model       TEXT NOT NULL,
    vector      BLOB NOT NULL,   -- f32 LE 序列化
    updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
```

复用现有 `pool`，不新建连接。

### 5.3 检索与编排 `RagService`（`core/src/rag.rs`，新增）

- `index_all(&AppState)`：为所有题生成嵌入并入库（增量：仅对缺失/更新的题）
- `retrieve(query, top_k)`：查询向量化 → 内存余弦相似度 → 返回 top_k 相似题
- `ask(question)`：RAG 问答主流程

### 5.4 `Cleaner` trait 扩展（`core/src/cleaner.rs`，修改）

新增 `ask` 方法，让问答与清洗共用同一 LLM 抽象：

```rust
#[async_trait]
pub trait Cleaner: Send + Sync {
    async fn clean(&self, ocr_text: &str) -> Result<CleanedQuestion>;
    async fn ask(&self, question: &str, context: &str) -> Result<String>;  // 新增
}
```

`LlmCleaner` 实现 `ask`：复用 `base_url`/`api_key`/`model` 与 reqwest 模式，组装检索上下文 + 问题，返回生成回答。

### 5.5 配置（扩展 `core/src/commands/config.rs`）

- 嵌入配置存进现有 `config` 表：`embed_provider`（`local`/`api`）、`embed_model`
- 复用 `LlmConfig`（问答生成与清洗共用），不新增 LLM 结构

### 5.6 Tauri 命令（扩展 `src-tauri/src/main.rs`）

照抄现有 `#[tauri::command]` + `State<'_, AppState>` 模式，新增：

- `rag_ask(question, top_k)` → `{ answer, sources }`
- `rag_index()` → 触发全量索引
- `rag_retrieve(query, top_k)` → 相似题列表（供语义搜索/调试）

## 6. 数据流

1. 用户点击「更新索引」（或新题写入后触发增量追加）
2. `index_all()`：逐题 `embed(title+options+answer+analysis)` → BLOB 存库
3. `rag_ask`：`embed(query)` → 余弦检索 top_k → 组装 prompt → `Cleaner::ask` → 返回 `{ answer, sources }`

## 7. 错误处理与降级

- 嵌入模型未下载 → 返回下载进度提示，不崩溃
- LLM 未配置 → 问答退化为纯检索（返回 top_k 相似题，无生成），提示配置
- 检索为空 → 友好提示"无相关题目或请先建立索引"
- 索引失败单题失败不阻塞整体，记录跳过

## 8. 与原有功能的耦合约束

**复用（不重复造轮子）：**
- LLM 调用：扩展 `Cleaner` trait，问答与清洗共用，配置统一走 `config::get_llm_config`
- 数据层：复用 `AppState` pool，向量表追加到现有 `migrate()`
- 命令注册：复用现有 `#[tauri::command]` 模式

**新增（全新能力）：**
- `embedder.rs`：嵌入 trait + 本地实现
- `rag.rs`：检索编排
- `question_embeddings` 表

**不侵入：**
- 不修改 `create_question`/`update_question`/`delete_question` 的签名与逻辑
- 索引采用「手动 + 成功后追加」而非侵入 CRUD 流程
- OCR（PaddleOcrService）与 RAG 完全独立

## 9. 测试

- `Embedder` 余弦相似度、top_k 排序单元测试（mock 向量）
- `db.rs` 向量表迁移测试
- `Cleaner::ask` prompt 组装测试
- `RagService` 检索逻辑测试（注入 mock embedder）
- TDD：先写失败测试，再实现

## 10. 关键取舍

- 本地模型首次下载约 100MB（bge-small-zh，CPU 可跑）
- 问答生成依赖云端 LLM（复用现有配置），本地生成留作后续
- 错题数据量小，内存余弦检索足够，无需 ANN 索引