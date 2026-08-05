//! SQLite 数据层：连接池初始化 + 建表迁移

use sqlx::sqlite::{SqliteConnectOptions, SqlitePool, SqlitePoolOptions};
use std::path::Path;
use std::str::FromStr;

use crate::error::{Error, Result};

/// 初始化数据库连接池，并执行建表迁移。
pub async fn init_db(db_path: Option<&str>) -> Result<SqlitePool> {
    let url = match db_path {
        Some(p) => p.to_string(),
        None => "sqlite::memory:".to_string(),
    };

    let options = SqliteConnectOptions::from_str(&url)?
        .create_if_missing(true)
        .foreign_keys(true)
        .busy_timeout(std::time::Duration::from_secs(5));

    let pool = SqlitePoolOptions::new()
        .max_connections(5)
        .connect_with(options)
        .await?;

    migrate(&pool).await?;
    Ok(pool)
}

/// 建表迁移（幂等）
pub async fn migrate(pool: &SqlitePool) -> Result<()> {
    sqlx::query(
        r#"
        CREATE TABLE IF NOT EXISTS subjects (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS chapters (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL,
            parent_id  INTEGER NOT NULL DEFAULT 0,
            name       TEXT NOT NULL,
            path       TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS tags (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS questions (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id       INTEGER NOT NULL,
            chapter_id       INTEGER,
            qtype            TEXT NOT NULL DEFAULT 'single',
            title            TEXT NOT NULL,
            options          TEXT,
            answer           TEXT,
            analysis         TEXT,
            difficulty       INTEGER NOT NULL DEFAULT 3,
            status           TEXT NOT NULL DEFAULT 'not_mastered',
            wrong_count      INTEGER NOT NULL DEFAULT 0,
            notes            TEXT,
            is_favorite      INTEGER NOT NULL DEFAULT 0,
            image_path       TEXT,
            source           TEXT,
            wrong_reason     TEXT,
            last_reviewed_at TEXT,
            created_at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
            FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS question_tags (
            question_id INTEGER NOT NULL,
            tag_id      INTEGER NOT NULL,
            PRIMARY KEY (question_id, tag_id),
            FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE,
            FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS config (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS question_embeddings (
            question_id INTEGER PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
            model       TEXT NOT NULL,
            vector      BLOB NOT NULL,
            updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );
        "#,
    )
    .execute(pool)
    .await?;

    // 索引
    sqlx::query("CREATE INDEX IF NOT EXISTS idx_questions_subject ON questions(subject_id);")
        .execute(pool)
        .await?;
    sqlx::query("CREATE INDEX IF NOT EXISTS idx_questions_status ON questions(status);")
        .execute(pool)
        .await?;
    sqlx::query("CREATE INDEX IF NOT EXISTS idx_chapters_subject ON chapters(subject_id);")
        .execute(pool)
        .await?;

    Ok(())
}

/// 确保 db 目录存在（用于文件型数据库）
pub fn ensure_dir(path: &str) -> Result<()> {
    if let Some(dir) = Path::new(path).parent() {
        if !dir.as_os_str().is_empty() {
            std::fs::create_dir_all(dir).map_err(|e| Error::Config(e.to_string()))?;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_question_embeddings_table_exists_after_migrate() {
        let pool = init_db(None).await.expect("init memory db");
        let row: (i64,) =
            sqlx::query_as("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='question_embeddings'")
                .fetch_one(&pool)
                .await
                .expect("query table existence");
        assert_eq!(row.0, 1, "question_embeddings 表应存在");
    }
}