//! 统计计算：按科目/知识点/题型统计错题和掌握率

use crate::error::Result;
use crate::models::{ChapterStat, Stats, SubjectStat, TypeStat};

use super::AppState;

pub async fn get_stats(state: &AppState) -> Result<Stats> {
    let by_subject = get_by_subject(state).await?;
    let by_chapter = get_by_chapter(state).await?;
    let by_type = get_by_type(state).await?;

    let total = by_subject.iter().map(|s| s.total).sum();
    let mastered = by_subject.iter().map(|s| s.mastered).sum();
    let need_review = by_subject.iter().map(|s| s.need_review).sum();
    let not_mastered = by_subject.iter().map(|s| s.not_mastered).sum();
    let favorite = get_favorite_count(state).await?;

    Ok(Stats {
        total,
        mastered,
        need_review,
        not_mastered,
        favorite,
        by_subject,
        by_chapter,
        by_type,
    })
}

async fn get_by_subject(state: &AppState) -> Result<Vec<SubjectStat>> {
    let sql = r#"
        SELECT
            s.id AS subject_id,
            s.name AS subject_name,
            COUNT(q.id) AS total,
            COALESCE(SUM(CASE WHEN q.status = 'mastered' THEN 1 ELSE 0 END), 0) AS mastered,
            COALESCE(SUM(CASE WHEN q.status = 'need_review' THEN 1 ELSE 0 END), 0) AS need_review,
            COALESCE(SUM(CASE WHEN q.status = 'not_mastered' THEN 1 ELSE 0 END), 0) AS not_mastered
        FROM subjects s
        LEFT JOIN questions q ON q.subject_id = s.id
        GROUP BY s.id, s.name
        ORDER BY total DESC
    "#;
    let rows = sqlx::query_as::<_, SubjectStat>(sql)
        .fetch_all(&state.pool)
        .await?;
    Ok(rows)
}

async fn get_by_chapter(state: &AppState) -> Result<Vec<ChapterStat>> {
    let sql = r#"
        SELECT
            c.id AS chapter_id,
            c.name AS chapter_name,
            c.path AS path,
            COUNT(q.id) AS total,
            COALESCE(SUM(CASE WHEN q.status = 'mastered' THEN 1 ELSE 0 END), 0) AS mastered
        FROM chapters c
        LEFT JOIN questions q ON q.chapter_id = c.id
        WHERE c.subject_id IS NOT NULL
        GROUP BY c.id, c.name, c.path
        HAVING COUNT(q.id) > 0
        ORDER BY total DESC
    "#;
    let rows = sqlx::query_as::<_, ChapterStat>(sql)
        .fetch_all(&state.pool)
        .await?;
    Ok(rows)
}

async fn get_by_type(state: &AppState) -> Result<Vec<TypeStat>> {
    let sql = r#"
        SELECT qtype, COUNT(id) AS total
        FROM questions
        GROUP BY qtype
        ORDER BY total DESC
    "#;
    let rows = sqlx::query_as::<_, TypeStat>(sql)
        .fetch_all(&state.pool)
        .await?;
    Ok(rows)
}

async fn get_favorite_count(state: &AppState) -> Result<i64> {
    let cnt = sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM questions WHERE is_favorite = 1")
        .fetch_one(&state.pool)
        .await?;
    Ok(cnt)
}