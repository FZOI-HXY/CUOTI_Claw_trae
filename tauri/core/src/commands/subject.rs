//! 科目管理

use crate::error::{Error, Result};
use crate::models::Subject;

use super::AppState;

pub async fn create_subject(state: &AppState, name: String) -> Result<Subject> {
    let name = name.trim().to_string();
    if name.is_empty() {
        return Err(Error::Invalid("科目名称不能为空".into()));
    }
    let res = sqlx::query("INSERT INTO subjects (name) VALUES (?)")
        .bind(&name)
        .execute(&state.pool)
        .await?;
    get_by_id(state, res.last_insert_rowid()).await
}

pub async fn list_subjects(state: &AppState) -> Result<Vec<Subject>> {
    let rows = sqlx::query_as::<_, Subject>("SELECT * FROM subjects ORDER BY name")
        .fetch_all(&state.pool)
        .await?;
    Ok(rows)
}

pub async fn get_by_id(state: &AppState, id: i64) -> Result<Subject> {
    sqlx::query_as::<_, Subject>("SELECT * FROM subjects WHERE id = ?")
        .bind(id)
        .fetch_optional(&state.pool)
        .await?
        .ok_or_else(|| Error::NotFound(format!("科目 {} 不存在", id)))
}

pub async fn rename_subject(state: &AppState, id: i64, name: String) -> Result<Subject> {
    let name = name.trim().to_string();
    if name.is_empty() {
        return Err(Error::Invalid("科目名称不能为空".into()));
    }
    sqlx::query("UPDATE subjects SET name = ? WHERE id = ?")
        .bind(&name)
        .bind(id)
        .execute(&state.pool)
        .await?;
    get_by_id(state, id).await
}

pub async fn delete_subject(state: &AppState, id: i64) -> Result<()> {
    let rows = sqlx::query("DELETE FROM subjects WHERE id = ?")
        .bind(id)
        .execute(&state.pool)
        .await?;
    if rows.rows_affected() == 0 {
        return Err(Error::NotFound(format!("科目 {} 不存在", id)));
    }
    Ok(())
}