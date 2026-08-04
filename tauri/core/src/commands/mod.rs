//! 业务命令模块（错题/科目/知识点/标签/统计/配置/OCR）

pub mod chapter;
pub mod config;
pub mod ocr;
pub mod question;
pub mod stats;
pub mod subject;
pub mod tag;

/// 应用状态：数据库连接池
#[derive(Clone)]
pub struct AppState {
    pub pool: sqlx::SqlitePool,
}

impl AppState {
    pub fn new(pool: sqlx::SqlitePool) -> Self {
        Self { pool }
    }
}