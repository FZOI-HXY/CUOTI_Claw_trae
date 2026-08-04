# 错题本 (CuoTi) — Tauri 桌面应用

基于 **Tauri 2 + Rust + Vue 3 + SQLite** 的错题管理桌面应用。

## 功能

- **错题管理**：新增/编辑/删除错题，支持题型（单选/多选/判断/填空/解答）、选项、答案、解析、难度、知识点、标签、收藏、笔记、错题原因、出错次数
- **筛选与搜索**：按科目/知识点/题型/难度/状态筛选，关键词全文搜索
- **复习模式**：逐题查看答案，标记掌握状态（未掌握/已掌握/需复习）
- **统计图表**：按科目/知识点/题型统计错题数量与掌握率
- **OCR 识别**：拍照/上传题目图片 → PaddleOCR 云 API 自动识别结构化题干
- **LLM 清洗（RAG 扩展点）**：可选，将 OCR 结果通过 LLM 规范化成结构化错题，自动填充表单

## 架构

```
┌────────────── Vue 3 前端 (Tailwind) ──────────────┐
│  错题列表 / 详情/编辑 / 复习 / 统计 / 设置          │
│  invoke('command')  ←──→  @tauri-apps/api         │
└──────────────────────────┬────────────────────────┘
                           │ IPC
┌──────────────────────────▼────────────────────────┐
│         Rust 后端 (src-tauri)                     │
│  commands/ + db.rs + ocr.rs + cleaner.rs          │
└──────────────────────────┬────────────────────────┘
                           │ SQLx
                    ┌──────▼──────┐
                    │  SQLite     │  errors.db
                    └─────────────┘
```

- `core/` 独立库 crate：数据层 + OCR + 清洗逻辑，不依赖 Tauri，可独立编译测试
- `src-tauri/` Tauri 二进制 crate，将 core 功能注册为前端命令
- `frontend/` Vue 3 + TypeScript + Vite + Tailwind

## 环境要求

- Rust 1.77+
- Node.js 18+
- Tauri 系统依赖（Linux 需 `webkit2gtk-4.1`、`glib`、`gtk-3` 等）

## 开发

```bash
# 安装前端依赖
cd frontend && npm install

# 启动 Tauri 开发（需系统依赖）
cargo tauri dev
```

## 测试（core 库，无需系统依赖）

```bash
cargo test -p cuoti-core
```

## 配置

在「设置」页配置：

- **PaddleOCR API**：URL（默认 `https://paddleocr.aistudio-app.com/api/v2/ocr/jobs`）、API Key（从百度 AI Studio 获取）、模型（默认 `PaddleOCR-VL-1.6`，直接输出结构化文本）
- **LLM 清洗**：可选。Base URL / API Key / Model（OpenAI 兼容，如 DeepSeek、Kimi）

## 处理管线

```
图片上传 → PaddleOCR-VL(结构化 Markdown/JSON) → [可选] LLM 清洗 → 自动填充错题表单
```

- PaddleOCR-VL 直接输出结构化文本，默认直接使用
- LLM 清洗为可选开关，接口抽象（`cleaner.rs` trait），后续可扩展完整 RAG 向量检索