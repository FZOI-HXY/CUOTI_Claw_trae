//! Tauri 应用入口：注册命令，将 core 功能暴露给前端

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use cuoti_core::commands::{
    backup, chapter, config, image, ocr, question, rag as rag_cmd, stats, subject, tag, AppState,
};
use cuoti_core::db;
use cuoti_core::meta;
use tauri::{Manager, State};

/// API Key 返回前端时的掩码占位符
const API_KEY_MASK: &str = "********";

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            let app_data_dir = app
                .path()
                .app_data_dir()
                .expect("无法获取应用数据目录");
            std::fs::create_dir_all(&app_data_dir).ok();
            let db_path = app_data_dir.join("errors.db");
            let db_path_str = db_path.to_str().unwrap();
            let pool = tauri::async_runtime::block_on(db::init_db(Some(db_path_str)))?;
            app.manage(AppState::with_data_dir(pool, app_data_dir));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            // 错题
            create_question,
            update_question,
            delete_question,
            get_question,
            list_questions,
            review_queue,
            update_status,
            increment_wrong_count,
            toggle_favorite,
            batch_delete_questions,
            batch_update_status,
            batch_toggle_favorite,
            // 科目
            create_subject,
            list_subjects,
            rename_subject,
            delete_subject,
            // 知识点
            create_chapter,
            list_chapters,
            rename_chapter,
            delete_chapter,
            // 标签
            create_tag,
            list_tags,
            delete_tag,
            // 统计
            get_stats,
            // 配置
            get_config,
            set_config,
            get_ocr_config,
            set_ocr_config,
            get_llm_config,
            set_llm_config,
            // OCR
            recognize_image,
            clean_text,
            // 图片
            save_image,
            get_meta,
            // 备份
            export_all,
            import_all,
            // RAG
            rag_ask,
            rag_index,
            rag_index_incremental,
            rag_retrieve,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

// ---- 错题 ----

#[tauri::command]
async fn create_question(
    state: State<'_, AppState>,
    input: cuoti_core::models::QuestionInput,
) -> Result<cuoti_core::models::Question, String> {
    question::create_question(&state, input).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn update_question(
    state: State<'_, AppState>,
    id: i64,
    input: cuoti_core::models::QuestionInput,
) -> Result<cuoti_core::models::Question, String> {
    question::update_question(&state, id, input).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn delete_question(state: State<'_, AppState>, id: i64) -> Result<(), String> {
    question::delete_question(&state, id).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn get_question(
    state: State<'_, AppState>,
    id: i64,
) -> Result<cuoti_core::models::Question, String> {
    question::get_by_id(&state, id).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn list_questions(
    state: State<'_, AppState>,
    filter: cuoti_core::models::QuestionFilter,
) -> Result<Vec<cuoti_core::models::Question>, String> {
    question::list_questions(&state, &filter).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn review_queue(
    state: State<'_, AppState>,
    limit: Option<i64>,
) -> Result<Vec<cuoti_core::models::Question>, String> {
    question::review_queue(&state, limit.unwrap_or(50)).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn update_status(
    state: State<'_, AppState>,
    id: i64,
    status: String,
) -> Result<cuoti_core::models::Question, String> {
    question::update_status(&state, id, status).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn increment_wrong_count(
    state: State<'_, AppState>,
    id: i64,
) -> Result<cuoti_core::models::Question, String> {
    question::increment_wrong_count(&state, id).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn toggle_favorite(
    state: State<'_, AppState>,
    id: i64,
) -> Result<cuoti_core::models::Question, String> {
    question::toggle_favorite(&state, id).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn batch_delete_questions(state: State<'_, AppState>, ids: Vec<i64>) -> Result<usize, String> {
    question::batch_delete(&state, ids).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn batch_update_status(
    state: State<'_, AppState>,
    ids: Vec<i64>,
    status: String,
) -> Result<usize, String> {
    question::batch_update_status(&state, ids, status).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn batch_toggle_favorite(state: State<'_, AppState>, ids: Vec<i64>) -> Result<usize, String> {
    question::batch_toggle_favorite(&state, ids).await.map_err(|e| e.to_string())
}

// ---- 科目 ----

#[tauri::command]
async fn create_subject(
    state: State<'_, AppState>,
    name: String,
) -> Result<cuoti_core::models::Subject, String> {
    subject::create_subject(&state, name).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn list_subjects(
    state: State<'_, AppState>,
) -> Result<Vec<cuoti_core::models::Subject>, String> {
    subject::list_subjects(&state).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn rename_subject(
    state: State<'_, AppState>,
    id: i64,
    name: String,
) -> Result<cuoti_core::models::Subject, String> {
    subject::rename_subject(&state, id, name).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn delete_subject(state: State<'_, AppState>, id: i64) -> Result<(), String> {
    subject::delete_subject(&state, id).await.map_err(|e| e.to_string())
}

// ---- 知识点 ----

#[tauri::command]
async fn create_chapter(
    state: State<'_, AppState>,
    subject_id: i64,
    parent_id: i64,
    name: String,
) -> Result<cuoti_core::models::Chapter, String> {
    chapter::create_chapter(&state, subject_id, parent_id, name).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn list_chapters(
    state: State<'_, AppState>,
    subject_id: i64,
) -> Result<Vec<cuoti_core::models::Chapter>, String> {
    chapter::list_by_subject(&state, subject_id).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn rename_chapter(
    state: State<'_, AppState>,
    id: i64,
    name: String,
) -> Result<cuoti_core::models::Chapter, String> {
    chapter::rename_chapter(&state, id, name).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn delete_chapter(state: State<'_, AppState>, id: i64) -> Result<(), String> {
    chapter::delete_chapter(&state, id).await.map_err(|e| e.to_string())
}

// ---- 标签 ----

#[tauri::command]
async fn create_tag(
    state: State<'_, AppState>,
    name: String,
) -> Result<cuoti_core::models::Tag, String> {
    tag::create_tag(&state, name).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn list_tags(state: State<'_, AppState>) -> Result<Vec<cuoti_core::models::Tag>, String> {
    tag::list_tags(&state).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn delete_tag(state: State<'_, AppState>, id: i64) -> Result<(), String> {
    tag::delete_tag(&state, id).await.map_err(|e| e.to_string())
}

// ---- 统计 ----

#[tauri::command]
async fn get_stats(state: State<'_, AppState>) -> Result<cuoti_core::models::Stats, String> {
    stats::get_stats(&state).await.map_err(|e| e.to_string())
}

// ---- 配置 ----

#[tauri::command]
async fn get_config(state: State<'_, AppState>) -> Result<Vec<cuoti_core::models::ConfigItem>, String> {
    let mut items = config::get_all(&state).await.map_err(|e| e.to_string())?;
    // 对前端掩码 API Key，避免明文回传
    for it in items.iter_mut() {
        if matches!(it.key.as_str(), "ocr_api_key" | "llm_api_key") && !it.value.is_empty() {
            it.value = API_KEY_MASK.to_string();
        }
    }
    Ok(items)
}

#[tauri::command]
async fn set_config(
    state: State<'_, AppState>,
    mut items: Vec<cuoti_core::models::ConfigItem>,
) -> Result<(), String> {
    // 掩码或空值视为不变更，保留原 key
    for it in items.iter_mut() {
        if matches!(it.key.as_str(), "ocr_api_key" | "llm_api_key")
            && (it.value.is_empty() || it.value == API_KEY_MASK)
        {
            if let Some(cur) = config::get(&state, &it.key).await {
                it.value = cur;
            }
        }
    }
    config::set_all(&state, items).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn get_ocr_config(state: State<'_, AppState>) -> Result<cuoti_core::models::OcrConfig, String> {
    let mut cfg = config::get_ocr_config(&state).await.map_err(|e| e.to_string())?;
    if !cfg.api_key.is_empty() {
        cfg.api_key = API_KEY_MASK.to_string();
    }
    Ok(cfg)
}

#[tauri::command]
async fn set_ocr_config(
    state: State<'_, AppState>,
    mut cfg: cuoti_core::models::OcrConfig,
) -> Result<(), String> {
    // 掩码或空值视为不变更，保留原 key
    if cfg.api_key.is_empty() || cfg.api_key == API_KEY_MASK {
        if let Ok(cur) = config::get_ocr_config(&state).await {
            cfg.api_key = cur.api_key;
        }
    }
    config::set_ocr_config(&state, cfg).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn get_llm_config(state: State<'_, AppState>) -> Result<cuoti_core::models::LlmConfig, String> {
    let mut cfg = config::get_llm_config(&state).await.map_err(|e| e.to_string())?;
    if !cfg.api_key.is_empty() {
        cfg.api_key = API_KEY_MASK.to_string();
    }
    Ok(cfg)
}

#[tauri::command]
async fn set_llm_config(
    state: State<'_, AppState>,
    mut cfg: cuoti_core::models::LlmConfig,
) -> Result<(), String> {
    // 掩码或空值视为不变更，保留原 key
    if cfg.api_key.is_empty() || cfg.api_key == API_KEY_MASK {
        if let Ok(cur) = config::get_llm_config(&state).await {
            cfg.api_key = cur.api_key;
        }
    }
    config::set_llm_config(&state, cfg).await.map_err(|e| e.to_string())
}

// ---- OCR ----

#[tauri::command]
async fn recognize_image(
    state: State<'_, AppState>,
    image_data: Vec<u8>,
    filename: String,
) -> Result<cuoti_core::models::OcrDraft, String> {
    ocr::recognize_image(&state, image_data, filename).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn clean_text(
    state: State<'_, AppState>,
    text: String,
) -> Result<cuoti_core::models::CleanedQuestion, String> {
    ocr::clean_text(&state, text).await.map_err(|e| e.to_string())
}

// ---- 图片 ----

#[tauri::command]
async fn save_image(
    state: State<'_, AppState>,
    image_data: Vec<u8>,
    filename: String,
) -> Result<String, String> {
    image::save_image(&state, image_data, filename)
        .await
        .map_err(|e| e.to_string())
}

// ---- 元信息 ----

#[tauri::command]
async fn get_meta() -> Result<cuoti_core::meta::Meta, String> {
    Ok(meta::meta())
}

// ---- 备份 ----

#[tauri::command]
async fn export_all(state: State<'_, AppState>) -> Result<String, String> {
    backup::export_all(&state).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn import_all(
    state: State<'_, AppState>,
    json: String,
) -> Result<cuoti_core::commands::backup::ImportSummary, String> {
    backup::import_all(&state, &json).await.map_err(|e| e.to_string())
}

// ---- RAG ----

#[tauri::command]
async fn rag_ask(
    state: State<'_, AppState>,
    question: String,
    top_k: Option<usize>,
) -> Result<cuoti_core::models::RagAnswer, String> {
    rag_cmd::ask(&state, question, top_k).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn rag_index(state: State<'_, AppState>) -> Result<usize, String> {
    rag_cmd::index(&state).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn rag_index_incremental(
    state: State<'_, AppState>,
) -> Result<cuoti_core::rag::IndexSummary, String> {
    rag_cmd::index_incremental(&state).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn rag_retrieve(
    state: State<'_, AppState>,
    query: String,
    top_k: Option<usize>,
) -> Result<Vec<cuoti_core::models::RagSource>, String> {
    rag_cmd::retrieve(&state, query, top_k).await.map_err(|e| e.to_string())
}