//! 知识点层级管理

use crate::error::{Error, Result};
use crate::models::Chapter;

use super::AppState;

pub async fn create_chapter(
    state: &AppState,
    subject_id: i64,
    parent_id: i64,
    name: String,
) -> Result<Chapter> {
    let name = name.trim().to_string();
    if name.is_empty() {
        return Err(Error::Invalid("知识点名称不能为空".into()));
    }
    // 构建路径：subject_id/parent/path + id
    let path = if parent_id == 0 {
        format!("{}/", subject_id)
    } else {
        let parent = get_by_id(state, parent_id).await?;
        format!("{}{}/", parent.path, subject_id)
    };

    let res = sqlx::query(
        "INSERT INTO chapters (subject_id, parent_id, name, path) VALUES (?, ?, ?, ?)",
    )
    .bind(subject_id)
    .bind(parent_id)
    .bind(&name)
    .bind(&path)
    .execute(&state.pool)
    .await?;
    get_by_id(state, res.last_insert_rowid()).await
}

pub async fn list_by_subject(state: &AppState, subject_id: i64) -> Result<Vec<Chapter>> {
    let rows = sqlx::query_as::<_, Chapter>(
        "SELECT * FROM chapters WHERE subject_id = ? ORDER BY parent_id, id",
    )
    .bind(subject_id)
    .fetch_all(&state.pool)
    .await?;
    Ok(rows)
}

pub async fn get_by_id(state: &AppState, id: i64) -> Result<Chapter> {
    sqlx::query_as::<_, Chapter>("SELECT * FROM chapters WHERE id = ?")
        .bind(id)
        .fetch_optional(&state.pool)
        .await?
        .ok_or_else(|| Error::NotFound(format!("知识点 {} 不存在", id)))
}

pub async fn rename_chapter(state: &AppState, id: i64, name: String) -> Result<Chapter> {
    let name = name.trim().to_string();
    if name.is_empty() {
        return Err(Error::Invalid("知识点名称不能为空".into()));
    }
    sqlx::query("UPDATE chapters SET name = ? WHERE id = ?")
        .bind(&name)
        .bind(id)
        .execute(&state.pool)
        .await?;
    get_by_id(state, id).await
}

pub async fn delete_chapter(state: &AppState, id: i64) -> Result<()> {
    let rows = sqlx::query("DELETE FROM chapters WHERE id = ?")
        .bind(id)
        .execute(&state.pool)
        .await?;
    if rows.rows_affected() == 0 {
        return Err(Error::NotFound(format!("知识点 {} 不存在", id)));
    }
    Ok(())
}

pub async fn list_tree(state: &AppState, subject_id: i64) -> Result<Vec<Chapter>> {
    // 按 path 顺序返回树结构
    list_by_subject(state, subject_id).await
}