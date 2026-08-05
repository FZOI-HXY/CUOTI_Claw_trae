//! 批量操作集成测试

use cuoti_core::commands::{question, subject, AppState};
use cuoti_core::db;
use cuoti_core::models::QuestionFilter;
use cuoti_core::models::QuestionInput;

async fn seeded_state(n: i64) -> (AppState, i64, Vec<i64>) {
    let pool = db::init_db(None).await.expect("init db");
    let state = AppState::new(pool);
    let subj = subject::create_subject(&state, "数学".into())
        .await
        .expect("subject");
    let mut ids = Vec::new();
    for i in 0..n {
        let q = question::create_question(
            &state,
            QuestionInput {
                subject_id: subj.id,
                chapter_id: None,
                qtype: None,
                title: format!("题目{}", i),
                options: None,
                answer: None,
                analysis: None,
                difficulty: None,
                status: None,
                notes: None,
                is_favorite: None,
                image_path: None,
                source: None,
                wrong_reason: None,
                tags: None,
            },
        )
        .await
        .expect("create");
        ids.push(q.id);
    }
    (state, subj.id, ids)
}

#[tokio::test]
async fn test_batch_delete_removes_selected() {
    let (state, _sid, ids) = seeded_state(4).await;
    let removed = question::batch_delete(&state, vec![ids[0], ids[2]])
        .await
        .expect("batch delete");
    assert_eq!(removed, 2);

    let list = question::list_questions(&state, &QuestionFilter::default())
        .await
        .expect("list");
    assert_eq!(list.len(), 2, "应剩 2 道");
}

#[tokio::test]
async fn test_batch_update_status_marks_all() {
    let (state, _sid, ids) = seeded_state(3).await;
    let updated = question::batch_update_status(&state, ids.clone(), "mastered".into())
        .await
        .expect("batch status");
    assert_eq!(updated, 3);

    let list = question::list_questions(
        &state,
        &QuestionFilter {
            status: Some("mastered".into()),
            ..Default::default()
        },
    )
    .await
    .expect("list mastered");
    assert_eq!(list.len(), 3);
}

#[tokio::test]
async fn test_batch_toggle_favorite_flips_all() {
    let (state, _sid, ids) = seeded_state(3).await;
    let updated = question::batch_toggle_favorite(&state, ids).await.expect("toggle");
    assert_eq!(updated, 3);

    let list = question::list_questions(
        &state,
        &QuestionFilter {
            is_favorite: Some(true),
            ..Default::default()
        },
    )
    .await
    .expect("list fav");
    assert_eq!(list.len(), 3);
}

#[tokio::test]
async fn test_batch_delete_empty_returns_zero() {
    let (state, _sid, _ids) = seeded_state(1).await;
    let removed = question::batch_delete(&state, Vec::<i64>::new())
        .await
        .expect("empty batch");
    assert_eq!(removed, 0);
}