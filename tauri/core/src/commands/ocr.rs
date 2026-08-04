//! OCR + LLM 清洗编排命令
//! 图片 → PaddleOCR-VL(结构化 Markdown) → [可选] LLM 清洗 → 错题草稿

use crate::cleaner::{Cleaner, LlmCleaner};
use crate::error::Result;
use crate::models::{CleanedQuestion, OcrDraft};
use crate::ocr::PaddleOcrService;

use super::{config, AppState};

/// 识别图片并返回错题草稿（含可选 LLM 清洗）
pub async fn recognize_image(
    state: &AppState,
    image_data: Vec<u8>,
    filename: String,
) -> Result<OcrDraft> {
    let ocr_cfg = config::get_ocr_config(state).await?;
    config::ensure_configured(&ocr_cfg)?;

    let service = PaddleOcrService::new(ocr_cfg.api_url, ocr_cfg.api_key, Some(ocr_cfg.model));
    let ocr_result = service.submit_and_poll(image_data, &filename).await?;

    if !ocr_result.success {
        return Ok(OcrDraft {
            raw_text: ocr_result.markdown_text,
            cleaned: None,
            error: ocr_result.error,
        });
    }

    let raw_text = ocr_result.markdown_text;

    // 可选 LLM 清洗
    let llm_cfg = config::get_llm_config(state).await?;
    let (cleaned, llm_error) = if llm_cfg.enabled {
        let cleaner = LlmCleaner::new(&llm_cfg);
        match cleaner.clean(&raw_text).await {
            Ok(c) => (Some(c), None),
            Err(e) => {
                // 清洗失败降级为原始 OCR 输出
                (None, Some(format!("LLM 清洗失败，已使用原始 OCR 结果: {}", e)))
            }
        }
    } else {
        (None, None)
    };

    Ok(OcrDraft {
        raw_text,
        cleaned,
        error: llm_error,
    })
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