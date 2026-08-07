//! 配置读写（PaddleOCR API / LLM API）

use crate::error::{Error, Result};
use crate::models::{ConfigItem, LlmConfig, OcrConfig};

use super::AppState;

const KEY_OCR_URL: &str = "ocr_api_url";
const KEY_OCR_KEY: &str = "ocr_api_key";
const KEY_OCR_MODEL: &str = "ocr_model";
const KEY_LLM_URL: &str = "llm_base_url";
const KEY_LLM_KEY: &str = "llm_api_key";
const KEY_LLM_MODEL: &str = "llm_model";
const KEY_LLM_ENABLED: &str = "llm_enabled";
const KEY_EMBED_PROVIDER: &str = "embed_provider";
const KEY_EMBED_MODEL: &str = "embed_model";
const KEY_RERANK_ENABLED: &str = "rerank_enabled";

pub async fn get(state: &AppState, key: &str) -> Option<String> {
    sqlx::query_scalar::<_, String>("SELECT value FROM config WHERE key = ?")
        .bind(key)
        .fetch_optional(&state.pool)
        .await
        .ok()
        .flatten()
}

pub async fn set(state: &AppState, key: &str, value: &str) -> Result<()> {
    sqlx::query(
        "INSERT INTO config (key, value) VALUES (?, ?)
         ON CONFLICT(key) DO UPDATE SET value = excluded.value",
    )
    .bind(key)
    .bind(value)
    .execute(&state.pool)
    .await?;
    Ok(())
}

pub async fn get_all(state: &AppState) -> Result<Vec<ConfigItem>> {
    let rows = sqlx::query_as::<_, ConfigItem>("SELECT key, value FROM config")
        .fetch_all(&state.pool)
        .await?;
    Ok(rows)
}

pub async fn set_all(state: &AppState, items: Vec<ConfigItem>) -> Result<()> {
    let mut tx = state.pool.begin().await?;
    for item in items {
        sqlx::query(
            "INSERT INTO config (key, value) VALUES (?, ?)
             ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        )
        .bind(&item.key)
        .bind(&item.value)
        .execute(&mut *tx)
        .await?;
    }
    tx.commit().await?;
    Ok(())
}

/// 读取 OCR 配置
pub async fn get_ocr_config(state: &AppState) -> Result<OcrConfig> {
    Ok(OcrConfig {
        api_url: get(state, KEY_OCR_URL).await.unwrap_or_else(|| {
            "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs".to_string()
        }),
        api_key: get(state, KEY_OCR_KEY).await.unwrap_or_default(),
        model: get(state, KEY_OCR_MODEL).await.unwrap_or_else(|| "PaddleOCR-VL-1.6".to_string()),
    })
}

pub async fn set_ocr_config(state: &AppState, cfg: OcrConfig) -> Result<()> {
    set(state, KEY_OCR_URL, &cfg.api_url).await?;
    set(state, KEY_OCR_KEY, &cfg.api_key).await?;
    set(state, KEY_OCR_MODEL, &cfg.model).await?;
    Ok(())
}

/// 读取 LLM 配置
pub async fn get_llm_config(state: &AppState) -> Result<LlmConfig> {
    let enabled = get(state, KEY_LLM_ENABLED).await.unwrap_or_else(|| "false".into());
    Ok(LlmConfig {
        base_url: get(state, KEY_LLM_URL).await.unwrap_or_default(),
        api_key: get(state, KEY_LLM_KEY).await.unwrap_or_default(),
        model: get(state, KEY_LLM_MODEL).await.unwrap_or_default(),
        enabled: enabled == "true" || enabled == "1",
    })
}

pub async fn set_llm_config(state: &AppState, cfg: LlmConfig) -> Result<()> {
    set(state, KEY_LLM_URL, &cfg.base_url).await?;
    set(state, KEY_LLM_KEY, &cfg.api_key).await?;
    set(state, KEY_LLM_MODEL, &cfg.model).await?;
    set(state, KEY_LLM_ENABLED, &cfg.enabled.to_string()).await?;
    Ok(())
}

// 供 OCR 命令复用
pub fn ensure_configured(cfg: &OcrConfig) -> Result<()> {
    if cfg.api_key.trim().is_empty() || cfg.api_url.trim().is_empty() {
        return Err(Error::Config(
            "PaddleOCR API 未配置，请在设置中填写 API URL 和 API Key".into(),
        ));
    }
    Ok(())
}

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

/// 重排开关（cross-encoder），默认开启。纯 CPU / 低内存环境可关闭以省内存与延迟。
pub async fn get_rerank_enabled(state: &AppState) -> bool {
    get(state, KEY_RERANK_ENABLED)
        .await
        .map(|v| v == "true" || v == "1")
        .unwrap_or(true)
}

pub async fn set_rerank_enabled(state: &AppState, enabled: bool) -> Result<()> {
    set(state, KEY_RERANK_ENABLED, &enabled.to_string()).await
}