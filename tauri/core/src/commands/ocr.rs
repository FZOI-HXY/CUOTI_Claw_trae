//! 多模态 AI 识别命令
//! 图片 → 多模态 LLM 直接输出结构化错题 JSON

use crate::cleaner::{Cleaner, LlmCleaner};
use crate::error::Result;
use crate::models::{CleanedQuestion, OcrDraft};

use super::{config, AppState};

/// 识别图片：直接把图片喂给多模态 LLM，输出结构化错题草稿
pub async fn recognize_image(
    state: &AppState,
    image_data: Vec<u8>,
    filename: String,
) -> Result<OcrDraft> {
    let llm_cfg = config::get_llm_config(state).await?;
    if !llm_cfg.enabled {
        return Ok(OcrDraft {
            raw_text: String::new(),
            cleaned: None,
            error: Some("AI 识别未启用，请在设置中开启".into()),
        });
    }

    let cleaner = LlmCleaner::new(&llm_cfg);
    match cleaner.clean_image(&image_data, &filename).await {
        Ok(cleaned) => Ok(OcrDraft {
            raw_text: cleaned.title.clone().unwrap_or_default(),
            cleaned: Some(cleaned),
            error: None,
        }),
        Err(e) => Ok(OcrDraft {
            raw_text: String::new(),
            cleaned: None,
            error: Some(e.to_string()),
        }),
    }
}

/// 仅对文本做 LLM 清洗（不经过 OCR）
pub async fn clean_text(state: &AppState, text: String) -> Result<CleanedQuestion> {
    let llm_cfg = config::get_llm_config(state).await?;
    if !llm_cfg.enabled {
        return Err(crate::error::Error::Cleaner(
            "LLM 清洗未启用，请在设置中开启".into(),
        ));
    }
    let cleaner = LlmCleaner::new(&llm_cfg);
    cleaner.clean(&text).await
}
