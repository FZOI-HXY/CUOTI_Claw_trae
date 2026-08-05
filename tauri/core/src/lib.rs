//! cuoti-core — 错题管理核心逻辑
//!
//! 独立于 Tauri 的库 crate，包含：
//! - SQLite 数据层（db.rs + models.rs）
//! - 错题/科目/知识点/标签 CRUD 与统计（commands/）
//! - PaddleOCR 云 API 服务（ocr.rs）
//! - LLM 清洗 / RAG 扩展点（cleaner.rs）

pub mod commands;
pub mod cleaner;
pub mod db;
pub mod embedder;
pub mod error;
pub mod meta;
pub mod models;
pub mod ocr;
pub mod rag;

pub use error::{Error, Result};