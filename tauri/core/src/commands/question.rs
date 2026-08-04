//! 错题 CRUD、筛选、搜索、状态更新

use sqlx::SqlitePool;

use crate::error::{Error, Result};
use crate::models::{MasteryStatus, Question, QuestionFilter, QuestionInput, QuestionType};

use super::AppState;

/// 创建错题
pub async fn create_question(state: &AppState, input: QuestionInput) -> Result<Question> {
    let qtype = input
        .qtype
        .as_deref()
        .filter(|s| QuestionType::from_str(s).is_some())
        .unwrap_or("single");
    let status = input
        .status
        .as_deref()
        .filter(|s| MasteryStatus::from_str(s).is_some())
        .unwrap_or("not_mastered");
    let difficulty = input.difficulty.unwrap_or(3).clamp(1, 5);
    let options = input
        .options
        .map(|o| serde_json::to_string(&o).unwrap_or_else(|_| "[]".to_string()));

    let result = sqlx::query(
        r#"
        INSERT INTO questions
            (subject_id, chapter_id, qtype, title, options, answer, analysis,
             difficulty, status, notes, is_favorite, image_path, source, wrong_reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        "#,
    )
    .bind(input.subject_id)
    .bind(input.chapter_id)
    .bind(qtype)
    .bind(&input.title)
    .bind(options)
    .bind(&input.answer)
    .bind(&input.analysis)
    .bind(difficulty)
    .bind(status)
    .bind(&input.notes)
    .bind(input.is_favorite.unwrap_or(false) as i64)
    .bind(&input.image_path)
    .bind(&input.source)
    .bind(&input.wrong_reason)
    .execute(&state.pool)
    .await?;

    let id = result.last_insert_rowid();
    set_tags(&state.pool, id, input.tags.as_deref().unwrap_or(&[])).await?;
    get_question(&state.pool, id).await
}

/// 更新错题
pub async fn update_question(state: &AppState, id: i64, input: QuestionInput) -> Result<Question> {
    let qtype = input
        .qtype
        .as_deref()
        .filter(|s| QuestionType::from_str(s).is_some())
        .unwrap_or("single");
    let status = input
        .status
        .as_deref()
        .filter(|s| MasteryStatus::from_str(s).is_some())
        .unwrap_or("not_mastered");
    let difficulty = input.difficulty.unwrap_or(3).clamp(1, 5);
    let options = input
        .options
        .map(|o| serde_json::to_string(&o).unwrap_or_else(|_| "[]".to_string()));

    let rows = sqlx::query(
        r#"
        UPDATE questions SET
            subject_id = ?, chapter_id = ?, qtype = ?, title = ?, options = ?,
            answer = ?, analysis = ?, difficulty = ?, status = ?, notes = ?,
            is_favorite = ?, image_path = ?, source = ?, wrong_reason = ?,
            updated_at = datetime('now', 'localtime')
        WHERE id = ?
        "#,
    )
    .bind(input.subject_id)
    .bind(input.chapter_id)
    .bind(qtype)
    .bind(&input.title)
    .bind(options)
    .bind(&input.answer)
    .bind(&input.analysis)
    .bind(difficulty)
    .bind(status)
    .bind(&input.notes)
    .bind(input.is_favorite.unwrap_or(false) as i64)
    .bind(&input.image_path)
    .bind(&input.source)
    .bind(&input.wrong_reason)
    .bind(id)
    .execute(&state.pool)
    .await?;

    if rows.rows_affected() == 0 {
        return Err(Error::NotFound(format!("错题 {} 不存在", id)));
    }

    // 若传了 tags 则更新标签
    if let Some(tags) = &input.tags {
        set_tags(&state.pool, id, tags).await?;
    }

    get_question(&state.pool, id).await
}

/// 删除错题
pub async fn delete_question(state: &AppState, id: i64) -> Result<()> {
    let rows = sqlx::query("DELETE FROM questions WHERE id = ?")
        .bind(id)
        .execute(&state.pool)
        .await?;
    if rows.rows_affected() == 0 {
        return Err(Error::NotFound(format!("错题 {} 不存在", id)));
    }
    Ok(())
}

/// 更新掌握状态（复习用）
pub async fn update_status(state: &AppState, id: i64, status: String) -> Result<Question> {
    if MasteryStatus::from_str(&status).is_none() {
        return Err(Error::Invalid(format!("无效的掌握状态: {}", status)));
    }
    let rows = sqlx::query(
        r#"
        UPDATE questions SET status = ?,
            last_reviewed_at = datetime('now', 'localtime'),
            updated_at = datetime('now', 'localtime')
        WHERE id = ?
        "#,
    )
    .bind(&status)
    .bind(id)
    .execute(&state.pool)
    .await?;
    if rows.rows_affected() == 0 {
        return Err(Error::NotFound(format!("错题 {} 不存在", id)));
    }
    get_question(&state.pool, id).await
}

/// 增加出错次数
pub async fn increment_wrong_count(state: &AppState, id: i64) -> Result<Question> {
    sqlx::query(
        r#"
        UPDATE questions SET wrong_count = wrong_count + 1,
            updated_at = datetime('now', 'localtime')
        WHERE id = ?
        "#,
    )
    .bind(id)
    .execute(&state.pool)
    .await?;
    get_question(&state.pool, id).await
}

/// 切换收藏
pub async fn toggle_favorite(state: &AppState, id: i64) -> Result<Question> {
    sqlx::query(
        r#"
        UPDATE questions SET is_favorite = 1 - is_favorite,
            updated_at = datetime('now', 'localtime')
        WHERE id = ?
        "#,
    )
    .bind(id)
    .execute(&state.pool)
    .await?;
    get_question(&state.pool, id).await
}

/// 按 ID 获取错题
pub async fn get_by_id(state: &AppState, id: i64) -> Result<Question> {
    get_question(&state.pool, id).await
}

/// 列表 + 筛选 + 搜索
pub async fn list_questions(state: &AppState, filter: &QuestionFilter) -> Result<Vec<Question>> {
    let mut sql = String::from(
        r#"
        SELECT q.*, s.name AS subject_name, c.name AS chapter_name,
               (SELECT GROUP_CONCAT(t.name) FROM question_tags qt
                 JOIN tags t ON t.id = qt.tag_id WHERE qt.question_id = q.id) AS tag_names
        FROM questions q
        LEFT JOIN subjects s ON s.id = q.subject_id
        LEFT JOIN chapters c ON c.id = q.chapter_id
        WHERE 1=1
        "#,
    );
    let mut conds: Vec<String> = Vec::new();
    if let Some(sid) = filter.subject_id {
        conds.push(format!("q.subject_id = {}", sid));
    }
    if let Some(cid) = filter.chapter_id {
        conds.push(format!("q.chapter_id = {}", cid));
    }
    if let Some(qt) = &filter.qtype {
        conds.push(format!("q.qtype = '{}'", qt.replace('\'', "''")));
    }
    if let Some(d) = filter.difficulty {
        conds.push(format!("q.difficulty = {}", d));
    }
    if let Some(st) = &filter.status {
        conds.push(format!("q.status = '{}'", st.replace('\'', "''")));
    }
    if let Some(fav) = filter.is_favorite {
        conds.push(format!("q.is_favorite = {}", fav as i64));
    }
    if let Some(tag) = &filter.tag {
        conds.push(format!(
            "q.id IN (SELECT question_id FROM question_tags qt JOIN tags t ON t.id=qt.tag_id WHERE t.name='{}')",
            tag.replace('\'', "''")
        ));
    }
    if let Some(kw) = &filter.keyword {
        if !kw.trim().is_empty() {
            let kw = kw.trim().replace('\'', "''");
            conds.push(format!(
                "(q.title LIKE '%{kw}%' OR q.answer LIKE '%{kw}%' OR q.analysis LIKE '%{kw}%')"
            ));
        }
    }
    if !conds.is_empty() {
        sql.push_str(" AND ");
        sql.push_str(&conds.join(" AND "));
    }
    sql.push_str(" ORDER BY q.updated_at DESC");

    let rows = sqlx::query_as::<_, QuestionRow>(&sql).fetch_all(&state.pool).await?;
    Ok(rows.into_iter().map(map_row).collect())
}

/// 待复习题目（未掌握 + 需复习）
pub async fn review_queue(state: &AppState, limit: i64) -> Result<Vec<Question>> {
    let sql = format!(
        r#"
        SELECT q.*, s.name AS subject_name, c.name AS chapter_name,
               (SELECT GROUP_CONCAT(t.name) FROM question_tags qt
                 JOIN tags t ON t.id = qt.tag_id WHERE qt.question_id = q.id) AS tag_names
        FROM questions q
        LEFT JOIN subjects s ON s.id = q.subject_id
        LEFT JOIN chapters c ON c.id = q.chapter_id
        WHERE q.status IN ('not_mastered', 'need_review')
        ORDER BY q.last_reviewed_at IS NULL DESC, q.last_reviewed_at ASC
        LIMIT {}
        "#,
        limit
    );
    let rows = sqlx::query_as::<_, QuestionRow>(&sql).fetch_all(&state.pool).await?;
    Ok(rows.into_iter().map(map_row).collect())
}

// ---- 内部辅助 ----

async fn get_question(pool: &SqlitePool, id: i64) -> Result<Question> {
    let sql = r#"
        SELECT q.*, s.name AS subject_name, c.name AS chapter_name,
               (SELECT GROUP_CONCAT(t.name) FROM question_tags qt
                 JOIN tags t ON t.id = qt.tag_id WHERE qt.question_id = q.id) AS tag_names
        FROM questions q
        LEFT JOIN subjects s ON s.id = q.subject_id
        LEFT JOIN chapters c ON c.id = q.chapter_id
        WHERE q.id = ?
    "#;
    let row = sqlx::query_as::<_, QuestionRow>(sql)
        .bind(id)
        .fetch_optional(pool)
        .await?;
    row.map(map_row).ok_or_else(|| Error::NotFound(format!("错题 {} 不存在", id)))
}

async fn set_tags(pool: &SqlitePool, question_id: i64, tags: &[String]) -> Result<()> {
    sqlx::query("DELETE FROM question_tags WHERE question_id = ?")
        .bind(question_id)
        .execute(pool)
        .await?;
    for name in tags {
        let name = name.trim();
        if name.is_empty() {
            continue;
        }
        // 获取或创建标签
        let tag_id = sqlx::query_scalar::<_, i64>(
            "SELECT id FROM tags WHERE name = ?",
        )
        .bind(name)
        .fetch_optional(pool)
        .await?;
        let tag_id = match tag_id {
            Some(id) => id,
            None => {
                let res = sqlx::query("INSERT INTO tags (name) VALUES (?)")
                    .bind(name)
                    .execute(pool)
                    .await?;
                res.last_insert_rowid()
            }
        };
        sqlx::query("INSERT OR IGNORE INTO question_tags (question_id, tag_id) VALUES (?, ?)")
            .bind(question_id)
            .bind(tag_id)
            .execute(pool)
            .await?;
    }
    Ok(())
}

#[derive(sqlx::FromRow)]
struct QuestionRow {
    id: i64,
    subject_id: i64,
    chapter_id: Option<i64>,
    qtype: String,
    title: String,
    options: Option<String>,
    answer: Option<String>,
    analysis: Option<String>,
    difficulty: i64,
    status: String,
    wrong_count: i64,
    notes: Option<String>,
    is_favorite: i64,
    image_path: Option<String>,
    source: Option<String>,
    wrong_reason: Option<String>,
    last_reviewed_at: Option<String>,
    created_at: String,
    updated_at: String,
    subject_name: Option<String>,
    chapter_name: Option<String>,
    tag_names: Option<String>,
}

fn map_row(row: QuestionRow) -> Question {
    let tags = row
        .tag_names
        .as_deref()
        .map(|s| s.split(',').map(|x| x.to_string()).collect())
        .unwrap_or_default();
    Question {
        id: row.id,
        subject_id: row.subject_id,
        chapter_id: row.chapter_id,
        qtype: row.qtype,
        title: row.title,
        options: row.options,
        answer: row.answer,
        analysis: row.analysis,
        difficulty: row.difficulty,
        status: row.status,
        wrong_count: row.wrong_count,
        notes: row.notes,
        is_favorite: row.is_favorite != 0,
        image_path: row.image_path,
        source: row.source,
        wrong_reason: row.wrong_reason,
        last_reviewed_at: row.last_reviewed_at,
        created_at: row.created_at,
        updated_at: row.updated_at,
        subject_name: row.subject_name,
        chapter_name: row.chapter_name,
        tags: Some(tags),
    }
}