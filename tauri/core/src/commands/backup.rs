//! 数据导出/导入（JSON 备份与恢复）
//! 导出科目/知识点/标签/错题，导入时按名称查找或创建，避免重复。

use serde::{Deserialize, Serialize};

use crate::error::{Error, Result};
use crate::models::{Chapter, ConfigItem, Subject, Tag};

use super::AppState;

/// 导入结果统计
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ImportSummary {
    pub subjects: usize,
    pub chapters: usize,
    pub tags: usize,
    pub questions: usize,
}

/// 备份数据根对象
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BackupData {
    pub version: i64,
    pub subjects: Vec<Subject>,
    pub chapters: Vec<Chapter>,
    pub tags: Vec<Tag>,
    #[serde(default)]
    pub config: Vec<ConfigItem>,
    pub questions: Vec<BackupQuestion>,
}

/// 备份中的错题（保留名称引用，便于跨库恢复）
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BackupQuestion {
    pub qtype: String,
    pub title: String,
    pub options: Option<Vec<String>>,
    pub answer: Option<String>,
    pub analysis: Option<String>,
    pub difficulty: i64,
    pub status: String,
    pub notes: Option<String>,
    pub is_favorite: bool,
    pub image_path: Option<String>,
    pub source: Option<String>,
    pub wrong_reason: Option<String>,
    pub subject_name: String,
    pub chapter_name: Option<String>,
    pub tags: Vec<String>,
}

/// 导出全部数据为 JSON 字符串
pub async fn export_all(state: &AppState) -> Result<String> {
    let subjects = sqlx::query_as::<_, Subject>("SELECT * FROM subjects ORDER BY id")
        .fetch_all(&state.pool)
        .await?;
    let chapters = sqlx::query_as::<_, Chapter>("SELECT * FROM chapters ORDER BY id")
        .fetch_all(&state.pool)
        .await?;
    let tags = sqlx::query_as::<_, Tag>("SELECT * FROM tags ORDER BY id")
        .fetch_all(&state.pool)
        .await?;

    let config = crate::commands::config::get_all(state).await?;

    let questions = crate::commands::question::list_questions(state, &Default::default()).await?;
    let questions = questions
        .into_iter()
        .map(|q| BackupQuestion {
            qtype: q.qtype,
            title: q.title,
            options: parse_options(&q.options),
            answer: q.answer,
            analysis: q.analysis,
            difficulty: q.difficulty,
            status: q.status,
            notes: q.notes,
            is_favorite: q.is_favorite,
            image_path: q.image_path,
            source: q.source,
            wrong_reason: q.wrong_reason,
            subject_name: q.subject_name.unwrap_or_default(),
            chapter_name: q.chapter_name,
            tags: q.tags.unwrap_or_default(),
        })
        .collect();

    let data = BackupData {
        version: 1,
        subjects,
        chapters,
        tags,
        config,
        questions,
    };
    serde_json::to_string_pretty(&data).map_err(|e| Error::Cleaner(format!("序列化备份失败: {e}")))
}

/// 导入 JSON 备份，返回各类导入数量
pub async fn import_all(state: &AppState, json: &str) -> Result<ImportSummary> {
    let data: BackupData = serde_json::from_str(json).map_err(|e| {
        if json.trim().is_empty() {
            Error::Invalid("备份内容为空".into())
        } else {
            Error::Invalid(format!("备份 JSON 解析失败: {e}"))
        }
    })?;
    if data.version != 1 {
        return Err(Error::Invalid(format!("不支持的备份版本: {}", data.version)));
    }

    let mut tx = state.pool.begin().await?;

    let mut summary = ImportSummary {
        subjects: 0,
        chapters: 0,
        tags: 0,
        questions: 0,
    };

    // 1. 科目：按名称查找或创建
    let mut subject_ids = std::collections::HashMap::new();
    for s in &data.subjects {
        let name = s.name.trim().to_string();
        if name.is_empty() {
            continue;
        }
        let existing = sqlx::query_scalar::<_, i64>("SELECT id FROM subjects WHERE name = ?")
            .bind(&name)
            .fetch_optional(&mut *tx)
            .await?;
        let id = match existing {
            Some(id) => id,
            None => {
                let res = sqlx::query("INSERT INTO subjects (name) VALUES (?)")
                    .bind(&name)
                    .execute(&mut *tx)
                    .await?;
                summary.subjects += 1;
                res.last_insert_rowid()
            }
        };
        subject_ids.insert(s.id, id);
    }

    // 2. 标签：按名称查找或创建（错题标签由 create_question 关联）
    for t in &data.tags {
        let name = t.name.trim().to_string();
        if name.is_empty() {
            continue;
        }
        let existing = sqlx::query_scalar::<_, i64>("SELECT id FROM tags WHERE name = ?")
            .bind(&name)
            .fetch_optional(&mut *tx)
            .await?;
        if existing.is_none() {
            let res = sqlx::query("INSERT INTO tags (name) VALUES (?)")
                .bind(&name)
                .execute(&mut *tx)
                .await?;
            let _ = res.last_insert_rowid();
            summary.tags += 1;
        }
    }

    // 3. 知识点：按 parent 关系重建层级（先建父后建子），避免丢失父子结构
    //    按 path 深度升序处理，保证父节点先于子节点创建。
    let mut chapters_sorted = data.chapters.clone();
    chapters_sorted.sort_by_key(|c| c.path.matches('/').count());
    let mut chapter_ids = std::collections::HashMap::new();
    let mut chapter_paths = std::collections::HashMap::new();
    for c in &chapters_sorted {
        let sname = data
            .subjects
            .iter()
            .find(|s| s.id == c.subject_id)
            .map(|s| s.name.trim().to_string())
            .unwrap_or_default();
        let new_subject_id = subject_ids.get(&c.subject_id).copied().unwrap_or_default();
        let name = c.name.trim().to_string();
        if sname.is_empty() || name.is_empty() || new_subject_id == 0 {
            continue;
        }
        // 解析父节点：优先用备份中的 parent_id 映射，其次按名称匹配
        let new_parent_id = if c.parent_id == 0 {
            0
        } else if let Some(&pid) = chapter_ids.get(&c.parent_id) {
            pid
        } else {
            // 父节点不在备份中：尝试按 (科目, 名称) 匹配库中已有父节点
            match data
                .chapters
                .iter()
                .find(|p| p.id == c.parent_id)
                .map(|p| p.name.trim().to_string())
            {
                Some(pname) if !pname.is_empty() => {
                    sqlx::query_scalar::<_, i64>(
                        "SELECT c.id FROM chapters c JOIN subjects s ON s.id = c.subject_id
                         WHERE s.name = ? AND c.name = ?",
                    )
                    .bind(&sname)
                    .bind(&pname)
                    .fetch_optional(&mut *tx)
                    .await?
                    .unwrap_or(0)
                }
                _ => 0,
            }
        };
        let path = if new_parent_id == 0 {
            format!("{}/", new_subject_id)
        } else {
            let parent_path = chapter_paths
                .get(&c.parent_id)
                .cloned()
                .unwrap_or_default();
            format!("{}{}/", parent_path, new_subject_id)
        };
        let existing = sqlx::query_scalar::<_, i64>(
            "SELECT c.id FROM chapters c JOIN subjects s ON s.id = c.subject_id
             WHERE s.name = ? AND c.name = ?",
        )
        .bind(&sname)
        .bind(&name)
        .fetch_optional(&mut *tx)
        .await?;
        let id = match existing {
            Some(id) => id,
            None => {
                let res = sqlx::query(
                    "INSERT INTO chapters (subject_id, parent_id, name, path) VALUES (?, ?, ?, ?)",
                )
                .bind(new_subject_id)
                .bind(new_parent_id)
                .bind(&name)
                .bind(&path)
                .execute(&mut *tx)
                .await?;
                summary.chapters += 1;
                res.last_insert_rowid()
            }
        };
        chapter_ids.insert(c.id, id);
        chapter_paths.insert(c.id, path);
    }

    // 配置：upsert 写回（不含该字段的旧备份会默认空列表）
    for item in &data.config {
        sqlx::query(
            "INSERT INTO config (key, value) VALUES (?, ?)
             ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        )
        .bind(&item.key)
        .bind(&item.value)
        .execute(&mut *tx)
        .await?;
    }

    // 提交结构数据（科目/章节/标签/配置）事务，释放写锁。
    // create_question 内部走 state.pool（另一条连接）；若此处仍持有未提交的
    // 写事务，SQLite 写锁会让 create_question 阻塞（in-memory 共享库会死锁）。
    tx.commit().await?;

    // 4. 错题：通过 create_question 写库（处理标签）
    for q in &data.questions {
        let subject_id = data
            .subjects
            .iter()
            .find(|s| s.name.trim() == q.subject_name.trim())
            .and_then(|s| subject_ids.get(&s.id))
            .copied()
            .unwrap_or_default();
        if subject_id == 0 {
            continue; // 找不到科目则跳过
        }
        let chapter_id = q.chapter_name.as_ref().and_then(|cn| {
            data.chapters
                .iter()
                .find(|c| c.name.trim() == cn.trim())
                .and_then(|c| chapter_ids.get(&c.id))
                .copied()
        });
        let _ = crate::commands::question::create_question(
            state,
            crate::models::QuestionInput {
                subject_id,
                chapter_id,
                qtype: Some(q.qtype.clone()),
                title: q.title.clone(),
                options: q.options.clone(),
                answer: q.answer.clone(),
                analysis: q.analysis.clone(),
                difficulty: Some(q.difficulty),
                status: Some(q.status.clone()),
                notes: q.notes.clone(),
                is_favorite: Some(q.is_favorite),
                image_path: q.image_path.clone(),
                source: q.source.clone(),
                wrong_reason: q.wrong_reason.clone(),
                tags: if q.tags.is_empty() {
                    None
                } else {
                    Some(q.tags.clone())
                },
            },
        )
        .await?;
        summary.questions += 1;
    }

    Ok(summary)
}

/// 解析 options 的 JSON 数组字符串 → Vec<String>
fn parse_options(s: &Option<String>) -> Option<Vec<String>> {
    s.as_deref()
        .and_then(|raw| serde_json::from_str::<Vec<String>>(raw).ok())
}