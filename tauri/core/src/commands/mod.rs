//! 业务命令模块（错题/科目/知识点/标签/统计/配置/OCR）

pub mod backup;
pub mod chapter;
pub mod config;
pub mod image;
pub mod ocr;
pub mod question;
pub mod rag;
pub mod stats;
pub mod subject;
pub mod tag;

/// 应用状态：数据库连接池 + 应用数据目录（图片等资源落盘用）
#[derive(Clone)]
pub struct AppState {
    pub pool: sqlx::SqlitePool,
    pub data_dir: std::path::PathBuf,
}

impl AppState {
    /// 默认仅持数据库连接池（测试/内存库场景），图片资源目录用系统临时目录
    pub fn new(pool: sqlx::SqlitePool) -> Self {
        Self::with_data_dir(pool, std::env::temp_dir())
    }

    /// 指定应用数据目录（由 Tauri setup 注入 app_data_dir）
    pub fn with_data_dir(pool: sqlx::SqlitePool, data_dir: std::path::PathBuf) -> Self {
        Self { pool, data_dir }
    }
}