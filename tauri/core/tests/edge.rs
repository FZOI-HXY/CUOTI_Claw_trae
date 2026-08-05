//! 边界测试：cleaner.extract_json、clean 未配置、error 序列化、backup 非法版本

use cuoti_core::commands::{backup, AppState};
use cuoti_core::cleaner::{extract_json, Cleaner, LlmCleaner};
use cuoti_core::db;
use cuoti_core::error::Error;
use cuoti_core::models::LlmConfig;

// ---- cleaner.extract_json 边界 ----

#[test]
fn test_extract_json_plain_no_braces_returns_input() {
    assert_eq!(extract_json("  简单文本  ").trim(), "简单文本");
}

#[test]
fn test_extract_json_code_block_without_braces_returns_trimmed() {
    let s = "```python\nprint('hi')\n```";
    assert_eq!(extract_json(s), s.trim());
}

#[test]
fn test_extract_json_extracts_braces_from_noisy_text() {
    let s = "前面乱码中文 {\"a\":1} 后面乱码";
    assert_eq!(extract_json(s), "{\"a\":1}");
}

#[test]
fn test_extract_json_empty_string() {
    assert_eq!(extract_json(""), "");
}

// ---- cleaner.clean 未配置错误分支 ----

#[tokio::test]
async fn test_clean_errors_when_not_configured() {
    let cfg = LlmConfig {
        base_url: String::new(),
        api_key: String::new(),
        model: "m".into(),
        enabled: true,
    };
    let cleaner = LlmCleaner::new(&cfg);
    let err = cleaner.clean("题目文本").await.unwrap_err();
    assert!(err.to_string().contains("未配置"), "{}", err);
}

#[tokio::test]
async fn test_ask_errors_when_not_configured() {
    let cfg = LlmConfig {
        base_url: String::new(),
        api_key: String::new(),
        model: "m".into(),
        enabled: true,
    };
    let cleaner = LlmCleaner::new(&cfg);
    let err = cleaner.ask("问题", "上下文").await.unwrap_err();
    assert!(err.to_string().contains("未配置"), "{}", err);
}

// ---- error 序列化 ----

#[test]
fn test_error_serializes_to_message_string() {
    let err = Error::Invalid("参数错误".into());
    let json = serde_json::to_string(&err).expect("serialize");
    assert_eq!(json, "\"参数错误: 参数错误\"");
}

#[test]
fn test_error_variants_serialize() {
    assert_eq!(
        serde_json::to_string(&Error::NotFound("x".into())).unwrap(),
        "\"未找到: x\""
    );
    assert_eq!(
        serde_json::to_string(&Error::Ocr("o".into())).unwrap(),
        "\"OCR 错误: o\""
    );
}

// ---- backup 非法版本 / 空内容 ----

#[tokio::test]
async fn test_import_rejects_unsupported_version() {
    let s = AppState::new(db::init_db(None).await.expect("db"));
    let json = r##"{"version":99,"subjects":[],"chapters":[],"tags":[],"questions":[]}"##;
    let err = backup::import_all(&s, json).await.unwrap_err();
    assert!(err.to_string().contains("版本"), "{}", err);
}

#[tokio::test]
async fn test_import_rejects_empty_content() {
    let s = AppState::new(db::init_db(None).await.expect("db"));
    assert!(backup::import_all(&s, "").await.is_err());
}