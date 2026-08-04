//! SQLite 数据层集成测试（内存库）

use cuoti_core::commands::{question, stats, subject, AppState};
use cuoti_core::db;
use cuoti_core::models::{QuestionFilter, QuestionInput};

#[tokio::test]
async fn test_crud_and_stats() {
    let pool = db::init_db(None).await.expect("init db");
    let state = AppState::new(pool);

    // 科目
    let subj = subject::create_subject(&state, "数学".into()).await.expect("create subject");
    assert_eq!(subj.name, "数学");

    // 错题
    let q = question::create_question(
        &state,
        QuestionInput {
            subject_id: subj.id,
            chapter_id: None,
            qtype: Some("single".into()),
            title: "1+1=?".into(),
            options: Some(vec!["A. 1".into(), "B. 2".into()]),
            answer: Some("B".into()),
            analysis: Some("基本加法".into()),
            difficulty: Some(1),
            status: Some("need_review".into()),
            notes: None,
            is_favorite: Some(true),
            image_path: None,
            source: Some("测试".into()),
            wrong_reason: None,
            tags: Some(vec!["基础".into()]),
        },
    )
    .await
    .expect("create question");

    assert_eq!(q.title, "1+1=?");

    // 列表筛选
    let filter = QuestionFilter {
        keyword: Some("1+1".into()),
        ..Default::default()
    };
    let list = question::list_questions(&state, &filter).await.expect("list");
    assert_eq!(list.len(), 1);

    // 状态更新（复习）
    let updated = question::update_status(&state, q.id, "mastered".into())
        .await
        .expect("update status");
    assert_eq!(updated.status, "mastered");

    // 复习队列不再包含已掌握
    let queue = question::review_queue(&state, 10).await.expect("review queue");
    assert_eq!(queue.len(), 0);

    // 统计
    let stats = stats::get_stats(&state).await.expect("stats");
    assert_eq!(stats.total, 1);
    assert_eq!(stats.mastered, 1);
    assert_eq!(stats.favorite, 1);
    assert_eq!(stats.by_subject.len(), 1);

    // 删除
    question::delete_question(&state, q.id).await.expect("delete");
    let stats_after = stats::get_stats(&state).await.expect("stats after");
    assert_eq!(stats_after.total, 0);
}

#[tokio::test]
async fn test_ocr_parser() {
    use cuoti_core::ocr::PaddleOcrService;

    // VL 模型 JSONL 结构
    let jsonl = r##"{"result":{"layoutParsingResults":[{"markdown":{"text":"# 题目\n1+1=?"}}]}}"##;
    let result = PaddleOcrService::extract_result(jsonl, None);
    assert!(result.success);
    assert!(result.markdown_text.contains("1+1=?"));
}