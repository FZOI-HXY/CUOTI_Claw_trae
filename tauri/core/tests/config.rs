//! 配置读写集成测试（内存库）

use cuoti_core::commands::{config, AppState};
use cuoti_core::db;
use cuoti_core::models::{ConfigItem, LlmConfig, OcrConfig};

async fn state() -> AppState {
    AppState::new(db::init_db(None).await.expect("memory db"))
}

#[tokio::test]
async fn test_set_then_get_roundtrip() {
    let s = state().await;
    config::set(&s, "my_key", "my_value").await.expect("set");
    let v = config::get(&s, "my_key").await;
    assert_eq!(v.as_deref(), Some("my_value"));
}

#[tokio::test]
async fn test_set_overwrites_existing_value() {
    let s = state().await;
    config::set(&s, "k", "v1").await.expect("set1");
    config::set(&s, "k", "v2").await.expect("set2");
    let v = config::get(&s, "k").await;
    assert_eq!(v.as_deref(), Some("v2"));
}

#[tokio::test]
async fn test_get_missing_returns_none() {
    let s = state().await;
    assert_eq!(config::get(&s, "no_such_key").await, None);
}

#[tokio::test]
async fn test_get_ocr_config_returns_defaults_when_empty() {
    let s = state().await;
    let cfg = config::get_ocr_config(&s).await.expect("ocr config");
    assert!(cfg.api_url.contains("paddleocr"));
    assert!(cfg.api_key.is_empty());
    assert_eq!(cfg.model, "PaddleOCR-VL-1.6");
}

#[tokio::test]
async fn test_set_get_ocr_config_roundtrip() {
    let s = state().await;
    let cfg = OcrConfig {
        api_url: "https://example.com/api".into(),
        api_key: "secret".into(),
        model: "PaddleOCRv6".into(),
    };
    config::set_ocr_config(&s, cfg.clone()).await.expect("set ocr");
    let got = config::get_ocr_config(&s).await.expect("get ocr");
    assert_eq!(got.api_url, cfg.api_url);
    assert_eq!(got.api_key, cfg.api_key);
    assert_eq!(got.model, cfg.model);
}

#[tokio::test]
async fn test_get_llm_config_enabled_parsing_true_forms() {
    let s = state().await;
    config::set(&s, "llm_enabled", "true").await.expect("set true");
    let cfg = config::get_llm_config(&s).await.expect("llm config");
    assert!(cfg.enabled);

    config::set(&s, "llm_enabled", "1").await.expect("set 1");
    let cfg = config::get_llm_config(&s).await.expect("llm config");
    assert!(cfg.enabled);
}

#[tokio::test]
async fn test_get_llm_config_enabled_parsing_false() {
    let s = state().await;
    config::set(&s, "llm_enabled", "false").await.expect("set false");
    let cfg = config::get_llm_config(&s).await.expect("llm config");
    assert!(!cfg.enabled);

    // 未设置时应默认关闭
    let fresh = state().await;
    let cfg = config::get_llm_config(&fresh).await.expect("llm config");
    assert!(!cfg.enabled);
}

#[tokio::test]
async fn test_set_get_llm_config_roundtrip() {
    let s = state().await;
    let cfg = LlmConfig {
        base_url: "https://api.example.com".into(),
        api_key: "llm-key".into(),
        model: "gpt-4o".into(),
        enabled: true,
    };
    config::set_llm_config(&s, cfg.clone()).await.expect("set llm");
    let got = config::get_llm_config(&s).await.expect("get llm");
    assert_eq!(got.base_url, cfg.base_url);
    assert_eq!(got.api_key, cfg.api_key);
    assert_eq!(got.model, cfg.model);
    assert!(got.enabled);
}

#[tokio::test]
async fn test_ensure_configured_rejects_empty() {
    let bad = OcrConfig {
        api_url: "".into(),
        api_key: "".into(),
        model: "PaddleOCR-VL-1.6".into(),
    };
    assert!(config::ensure_configured(&bad).is_err());

    let missing_key = OcrConfig {
        api_url: "https://x.com".into(),
        api_key: "".into(),
        model: "PaddleOCR-VL-1.6".into(),
    };
    assert!(config::ensure_configured(&missing_key).is_err());
}

#[tokio::test]
async fn test_ensure_configured_accepts_full() {
    let ok = OcrConfig {
        api_url: "https://x.com".into(),
        api_key: "k".into(),
        model: "PaddleOCR-VL-1.6".into(),
    };
    assert!(config::ensure_configured(&ok).is_ok());
}

#[tokio::test]
async fn test_get_all_and_set_all_roundtrip() {
    let s = state().await;
    let items = vec![
        ConfigItem { key: "a".into(), value: "1".into() },
        ConfigItem { key: "b".into(), value: "2".into() },
    ];
    config::set_all(&s, items).await.expect("set all");

    let all = config::get_all(&s).await.expect("get all");
    let map: std::collections::HashMap<_, _> =
        all.into_iter().map(|c| (c.key, c.value)).collect();
    assert_eq!(map.get("a").map(String::as_str), Some("1"));
    assert_eq!(map.get("b").map(String::as_str), Some("2"));
}