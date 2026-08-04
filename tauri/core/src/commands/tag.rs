//! 标签管理

use crate::error::{Error, Result};
use crate::models::Tag;

use super::AppState;

pub async fn create_tag(state: &AppState, name: String) -> Result<Tag> {
    let name = name.trim().to_string();
    if name.is_empty() {
        return Err(Error::Invalid("标签名称不能为空".into()));
    }
    let res = sqlx::query("INSERT OR IGNORE INTO tags (name) VALUES (?)")
        .bind(&name)
        .execute(&state.pool)
        .await?;
    let id = if res.rows_affected() == 0 {
        sqlx::query_scalar::<_, i64>("SELECT id FROM tags WHERE name = ?")
            .bind(&name)
            .fetch_one(&state.pool)
            .await?
    } else {
        res.last_insert_rowid()
    };
    get_by_id(state, id).await
}

pub async fn list_tags(state: &AppState) -> Result<Vec<Tag>> {
    let rows = sqlx::query_as::<_, Tag>("SELECT * FROM tags ORDER BY name")
        .fetch_all(&state.pool)
        .await?;
    Ok(rows)
}

pub async fn get_by_id(state: &AppState, id: i64) -> Result<Tag> {
    sqlx::query_as::<_, Tag>("SELECT * FROM tags WHERE id = ?")
        .bind(id)
        .fetch_optional(&state.pool)
        .await?
        .ok_or_else(|| Error::NotFound(format!("标签 {} 不存在", id)))
}

pub async fn delete_tag(state: &AppState, id: i64) -> Result<()> {
    let rows = sqlx::query("DELETE FROM tags WHERE id = ?")
        .bind(id)
        .execute(&state.pool)
        .await?;
    if rows.rows_affected() == 0 {
        return Err(Error::NotFound(format!("标签 {} 不存在", id)));
    }
    Ok(())
}