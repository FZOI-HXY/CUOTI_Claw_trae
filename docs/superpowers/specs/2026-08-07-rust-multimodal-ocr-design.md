# Rust 端识别切换为多模态 LLM — 设计文档

日期：2026-08-07
状态：已确认

## 背景

当前项目同时存在 Python Web 端和 Rust Tauri 桌面端两套识别实现，均调用百度 PaddleOCR 云 API（提交→轮询→下载→解析），Rust 端再可选地经 LLM 清洗成结构化错题。

用户希望：**分平台处理识别路径**。

- **Python 端**：保持不变，继续使用 PaddleOCR → LLM 清洗。
- **Rust 端（Tauri 桌面端）**：识别彻底切换为直接调用多模态大模型（智谱 `glm-4.5-air`），一次调用直接输出结构化错题 JSON，不再走 PaddleOCR。

## 目标

1. Rust 端 `recognize_image` 由「PaddleOCR → LLM 清洗（两步）」改为「图片直投多模态 LLM（一步）」，直接返回错题 `CleanedQuestion`。
2. 移除 Rust 端 PaddleOCR 相关代码与配置依赖。
3. Python 端不产生任何改动。

## 架构与组件

### 1. `cleaner.rs` — 新增多模态方法

在 `LlmCleaner` 上新增具体方法（**不扩展 `Cleaner` trait**，避免破坏 `rag.rs` 中的 mock 实现）：

```rust
pub async fn clean_image(&self, image_data: &[u8], filename: &str) -> Result<CleanedQuestion>
```

实现要点：
- 图片 base64 编码为 `data:<mime>;base64,...`（按扩展名推断 mime，默认 `image/png`）。
- 构造 OpenAI 兼容 content 数组：`[{type:"text"},{type:"image_url",image_url:{url:data_url}}]`。
- POST `{base_url}/chat/completions`，`model` 取 LLM 配置值（`glm-4.5-air`），`temperature: 0.2`，`response_format: {"type":"json_object"}`。
- 复用现有 `check_config`、HTTP client、`extract_json`、错误响应截断逻辑。
- 图片大小上限：base64 后约膨胀 33%，超过 10MB 原始图报错提示。

### 2. `commands/ocr.rs` — 重写 `recognize_image`

- 删除 `use crate::ocr::PaddleOcrService` 与 OCR 配置读取。
- 直接调用 `LlmCleaner::clean_image(image_data, filename)`。
- 返回 `OcrDraft { raw_text, cleaned, error }`：
  - 成功：`raw_text` 置为识别文本（可为空），`cleaned` 为结构化错题，`error` 为 None。
  - 失败：`error` 携带错误信息，`cleaned` 为 None。
- `clean_text`（纯文本走 LLM）保留不变。

### 3. 删除 Rust 端 PaddleOCR

- 删除 `src/ocr.rs`（`PaddleOcrService` 及全部单元测试）。
- 删除 `models.rs` 中 `OcrConfig`。
- 清理 `commands/config.rs` 中 `get_ocr_config` / `set_ocr_config` / `ensure_configured` 及 `KEY_OCR_*` 常量。
- 清理 `main.rs` 中的 `get_ocr_config` / `set_ocr_config` 命令注册与实现，`recognize_image` 命令实现改为调用新的多模态逻辑。
- 清理 `lib.rs` 中 `pub mod ocr`。

### 4. 前端 `Settings.vue`

- 移除 PaddleOCR 配置区块（API URL / Key / 模型），保留 LLM 配置区块。
- 识别按钮文案由「📷 OCR 识别」改为「✨ AI 识别」。

## 数据流（Rust 端）

```
选图 → readFile → recognize_image → 图片 base64(Data URL) → glm-4.5-air → 错题 JSON → fillFromCleaned 填充表单
```

## 错误处理

- LLM 未配置（`check_config` 失败）→ `OcrDraft.error`。
- 图片过大（>10MB）→ `OcrDraft.error`。
- HTTP / 网络错误 → `OcrDraft.error`（截断响应体）。
- JSON 解析失败或缺少 content → `OcrDraft.error`。
- 以上均不 panic、不中断。

## 测试

- 更新 `tests/config.rs`：移除 `OcrConfig` 相关用例。
- 更新 `tests/integration.rs`：移除 `PaddleOcrService::extract_result` 用例。
- 新增 `tests/llm_e2e.rs` 的 `clean_image` 端到端用例：
  - 需环境变量 `BIGMODEL_API_KEY`，`#[ignore]` 标记，按需运行。
  - 用一张小图（可内存构造）调用 `LlmCleaner::clean_image`，断言返回结构化错题。

## 影响与风险

- Rust 端不再需要 OCR API Key，只需 LLM 配置（base_url / api_key / model / enabled）。
- 删除范围仅限 Rust 端，Python Web 端不受影响。
- `clean_image` 依赖智谱 `glm-4.5-air` 支持图片输入（已验证 OpenAI 兼容格式可用）。