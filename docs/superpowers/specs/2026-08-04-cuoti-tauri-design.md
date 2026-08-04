# 错题管理 Tauri 应用 — 设计文档

> 日期：2026-08-04
> 目标：将现有 PaddleOCR 文档识别系统重构为 Tauri (Rust + Vue) 桌面应用，新增基于 SQLite 的错题管理。

## 1. 背景与目标

现有仓库（`/workspace`，origin: `github.com/FZOI-HXY/CUOTI_Claw_trae`）为基于 PaddleOCR 的文档识别系统（FastAPI + PyQt6 + PaddleOCR 云 API）。

本次重构目标：
- 采用 **Tauri 2.x** 架构（Rust 后端 + Vue 3 前端，前后端分离）。
- 后端使用 **SQLite** 实现错题管理。
- 保留 **OCR 能力**（Rust 直连 PaddleOCR 云 API），并在识别后**可选**接入 LLM 清洗（RAG 扩展）。
- **保留原 Python 项目**，新代码独立放在 `tauri/` 目录。

## 2. 架构

```
┌─────────────── Vue 3 前端 (Tailwind) ───────────────┐
│  错题列表 / 详情编辑 / 复习 / 统计 / 设置             │
│  invoke(tauri_command)  ←──→  @tauri-apps/api       │
└──────────────────────────┬──────────────────────────┘
                           │ IPC (命令)
┌──────────────────────────▼──────────────────────────┐
│              Rust 后端 (src-tauri)                   │
│  commands/ : question, subject, tag, ocr, stats,    │
│              config                                  │
│  db.rs      : SQLx + SQLite 连接池 + 建表迁移        │
│  ocr.rs     : PaddleOCR 云 API 调用 + 结构化解析      │
│  cleaner.rs : LLM 清洗（OpenAI 兼容，可扩展 RAG）     │
└──────────────────────────┬──────────────────────────┘
                           │ SQLx
                    ┌──────▼──────┐
                    │  SQLite     │  (app-data/errors.db)
                    └─────────────┘
```

## 3. 数据模型（SQLite）

### 表结构
- `subjects`：id, name, created_at
- `chapters`（知识点层级）：id, subject_id, parent_id(0=顶级), name, path, created_at
- `tags`：id, name
- `question_tags`（多对多）：question_id, tag_id
- `questions`：见下表
- `config`：key, value（存放 PaddleOCR 与 LLM API 配置）

### questions 表
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 主键 |
| subject_id | INTEGER | 科目（FK subjects.id） |
| chapter_id | INTEGER | 知识点/章节（FK chapters.id，可空） |
| type | TEXT | 题型：single/multiple/judge/fill/answer |
| title | TEXT | 题干 |
| options | TEXT | 选项（JSON 数组） |
| answer | TEXT | 正确答案 |
| analysis | TEXT | 解析 |
| difficulty | INTEGER | 难度 1-5 |
| status | TEXT | 未掌握/已掌握/需复习 |
| wrong_count | INTEGER | 出错次数 |
| notes | TEXT | 笔记 |
| is_favorite | INTEGER | 收藏/重点 0/1 |
| image_path | TEXT | 题目图片路径 |
| source | TEXT | 来源 |
| wrong_reason | TEXT | 错题原因 |
| last_reviewed_at | TEXT | 最近重做时间 |
| created_at | TEXT | 创建时间 |
| updated_at | TEXT | 更新时间 |

## 4. 处理管线（OCR + RAG）

```
图片上传 → PaddleOCR-VL(直接输出结构化 Markdown/JSON)
        → [可选] LLM 清洗（OpenAI 兼容）→ 规范化 JSON 题型结构
        → 自动填充错题表单
```

### 4.1 PaddleOCR 云 API（复刻原项目 [paddle_service.py] 逻辑）
1. `POST /api/v2/ocr/jobs`：multipart `file` + `model` + `optionalPayload`(JSON 字符串)，Header `Authorization: Bearer <token>` → 返回 `data.jobId`。
2. `GET /api/v2/ocr/jobs/{jobId}`：轮询 `data.state`（pending/running/done/failed）。
3. done 后从 `data.resultUrl.jsonUrl` / `markdownUrl` 下载结果。
4. 解析：VL 模型取 `result.layoutParsingResults[].markdown.text`（结构化 Markdown）；OCR 模型取 `result.ocrResults[].ocrImage`。支持 JSONL 每行一个 JSON。
5. 错误码映射：401/10001~10010/11001/11002/12001/12002。

默认模型：`PaddleOCR-VL-1.6`（VL 直出结构化文本）。

### 4.2 LLM 清洗（可选，RAG 扩展点）
- `cleaner.rs` 定义 trait，默认实现调用 OpenAI 兼容 API（`base_url` + `key` + `model` 可配置）。
- 输入 OCR 文本/Markdown，要求 LLM 输出固定 JSON 结构（type/title/options/answer/analysis/difficulty/knowledge），用于规范化填充。
- 预留向量检索接口（Embedding/Rerank），后续扩展不改现有代码。
- 未配置 LLM 时降级为直接使用 OCR 结构化输出，不阻断使用。

## 5. Rust 后端模块

| 文件 | 职责 |
|------|------|
| `main.rs` | Tauri 启动，注册命令 |
| `db.rs` | SQLx 连接池，建表迁移 |
| `models.rs` | 结构体与 DTO |
| `commands/question.rs` | 错题 CRUD、筛选、搜索、状态更新 |
| `commands/subject.rs` | 科目管理 |
| `commands/tag.rs` | 标签管理 |
| `commands/chapter.rs` | 知识点层级管理 |
| `commands/stats.rs` | 统计（科目/知识点数量、掌握率） |
| `commands/config.rs` | 配置读写 |
| `commands/ocr.rs` | OCR + LLM 清洗编排 |
| `ocr.rs` | PaddleOCR 服务封装 |
| `cleaner.rs` | LLM 清洗 trait 与实现 |

### 依赖
`tauri`, `tauri-plugin-*`, `sqlx`(sqlite, runtime-tokio), `tokio`, `reqwest`, `serde`, `serde_json`, `chrono`, `rusqlite`(可选测试), `thiserror`。

## 6. Vue 前端页面

- 错题列表：卡片/表格 + 筛选（科目/难度/状态/题型/知识点）+ 关键词搜索
- 错题详情/编辑：表单 + OCR/RAG 导入按钮
- 复习模式：逐题查看，标记掌握状态
- 统计：科目/知识点数量对比、掌握率（图表）
- 设置：PaddleOCR API / LLM API 配置
- 状态管理：Pinia；路由：Vue Router；样式：Tailwind CSS

## 7. 数据流

Vue 组件 → `invoke('command')` → Rust 命令 → SQLx 查询 SQLite → 返回 `Result<T, String>` → Vue 渲染。
OCR 流程：Vue 选图 → 传文件到 Rust → 调 PaddleOCR API 轮询 → 解析结构化 Markdown → （可选）LLM 清洗 → 返回错题 JSON → 前端填充表单。

## 8. 错误处理

- Rust 命令统一返回 `Result<T, String>`，前端统一错误提示。
- OCR 失败（网络/未配 Key）降级为手动录入。
- LLM 未配置或失败时使用 OCR 原始输出。

## 9. 测试

- Rust 单元测试：SQLx 内存库（`sqlite::memory:`）测 CRUD、筛选、统计计算、OCR 解析。
- 参考原项目测试：`tests/test_paddle_service.py`、`tests/test_paddle_parser.py`。

## 10. 目录结构

```
/workspace/
├── apps/            # 保留原 Python 项目（不动）
├── tauri/           # 新 Tauri 项目
│   ├── src-tauri/
│   │   ├── src/ (main.rs, db.rs, models.rs, ocr.rs, cleaner.rs, commands/*)
│   │   ├── Cargo.toml
│   │   └── tauri.conf.json
│   └── frontend/ (Vue3 + TS + Vite + Tailwind)
└── docs/superpowers/specs/2026-08-04-cuoti-tauri-design.md
```