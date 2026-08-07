//! cuoti-core — 错题管理核心逻辑
//!
//! 独立于 Tauri 的库 crate，包含：
//! - SQLite 数据层（db.rs + models.rs）
//! - 错题/科目/知识点/标签 CRUD 与统计（commands/）
//! - 多模态 LLM 识别与清洗（cleaner.rs）
//! - RAG 检索问答（rag.rs）

pub mod commands;
pub mod cleaner;
pub mod db;
pub mod embedder;
pub mod error;
pub mod hybrid;
pub mod meta;
pub mod models;
pub mod rag;

pub use error::{Error, Result};