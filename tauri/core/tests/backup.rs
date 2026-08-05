//! 数据导出/导入 集成测试（内存库）

use cuoti_core::commands::{backup, config, question, subject, AppState};
use cuoti_core::db;
use cuoti_core::models::QuestionInput;

async fn seeded_state() -> AppState {
    let pool = db::init_db(None).await.expect("init db");
    let state = AppState::new(pool);
    let subj = subject::create_subject(&state, "数学".into()).await.expect("subject");
    question::create_question(
        &state,
        QuestionInput {
            subject_id: subj.id,
            chapter_id: None,
            qtype: Some("single".into()),
            title: "1+1=?".into(),
            options: Some(vec!["A. 1".into(), "B. 2".into()]),
            answer: Some("B".into()),
            analysis: Some("加法".into()),
            difficulty: Some(1),
            status: Some("mastered".into()),
            notes: None,
            is_favorite: Some(true),
            image_path: None,
            source: None,
            wrong_reason: None,
            tags: Some(vec!["基础".into(), "运算".into()]),
        },
    )
    .await
    .expect("create question");
    state
}

#[tokio::test]
async fn test_export_produces_valid_json_with_subjects_and_questions() {
    let state = seeded_state().await;
    let json = backup::export_all(&state).await.expect("export");
    let v: serde_json::Value = serde_json::from_str(&json).expect("valid json");
    assert_eq!(v["version"], 1);
    assert_eq!(v["subjects"].as_array().map(|a| a.len()), Some(1));
    assert_eq!(v["questions"].as_array().map(|a| a.len()), Some(1));
    assert_eq!(v["questions"][0]["title"], "1+1=?");
    assert_eq!(v["questions"][0]["subject_name"], "数学");
}

#[tokio::test]
async fn test_export_import_roundtrip_restores_questions() {
    let state = seeded_state().await;
    let json = backup::export_all(&state).await.expect("export");

    // 导入到全新数据库
    let fresh = AppState::new(db::init_db(None).await.expect("fresh db"));
    let summary = backup::import_all(&fresh, &json).await.expect("import");
    assert!(summary.subjects >= 1);
    assert!(summary.questions >= 1);

    let list = question::list_questions(&fresh, &Default::default())
        .await
        .expect("list");
    assert_eq!(list.len(), 1, "导入后应有一条错题");
    assert_eq!(list[0].title, "1+1=?");
    assert_eq!(list[0].status, "mastered");
    assert!(list[0].is_favorite);
    assert_eq!(list[0].tags.as_deref().map(|t| t.len()), Some(2));
}

#[tokio::test]
async fn test_import_into_existing_db_does_not_duplicate_subjects() {
    let state = seeded_state().await;
    let json = backup::export_all(&state).await.expect("export");
    // 再次导入到同一数据库
    let summary = backup::import_all(&state, &json).await.expect("import");
    assert_eq!(summary.subjects, 0, "科目不应重复创建");
    assert_eq!(summary.questions, 1, "问题应新增一条");
}

#[tokio::test]
async fn test_import_malformed_json_returns_error() {
    let state = AppState::new(db::init_db(None).await.expect("db"));
    assert!(backup::import_all(&state, "{not json").await.is_err());
    assert!(backup::import_all(&state, "12345").await.is_err());
}

#[tokio::test]
async fn test_export_import_preserves_chapter_hierarchy() {
    use cuoti_core::commands::chapter;

    let state = seeded_state().await;
    // 建: 根知识点「代数」→ 子知识点「方程」
    let root = chapter::create_chapter(&state, 1, 0, "代数".into())
        .await
        .expect("create root");
    chapter::create_chapter(&state, 1, root.id, "方程".into())
        .await
        .expect("create child");

    let json = backup::export_all(&state).await.expect("export");
    let fresh = AppState::new(db::init_db(None).await.expect("fresh db"));
    let summary = backup::import_all(&fresh, &json).await.expect("import");
    assert_eq!(summary.subjects, 1);
    assert_eq!(summary.chapters, 2, "应导入 2 个知识点");

    // 校验层级：子知识点「方程」的 parent_id 应指向「代数」
    let child = chapter::list_by_subject(&fresh, 1)
        .await
        .expect("list chapters");
    let by_name: std::collections::HashMap<_, _> =
        child.iter().map(|c| (c.name.clone(), c.id)).collect();
    let root_id = by_name.get("代数").copied().expect("代数存在");
    let eq = child.iter().find(|c| c.name == "方程").expect("方程存在");
    assert_eq!(eq.parent_id, root_id, "子知识点应保留父级引用");
}

#[tokio::test]
async fn test_export_import_roundtrip_preserves_config() {
    let state = seeded_state().await;
    config::set(&state, "llm_base_url", "https://api.example.com").await.expect("set");
    config::set(&state, "llm_api_key", "secret-key").await.expect("set");
    config::set(&state, "ocr_model", "PaddleOCR-VL-1.6").await.expect("set");

    let json = backup::export_all(&state).await.expect("export");

    // 导入到全新数据库
    let fresh = AppState::new(db::init_db(None).await.expect("fresh db"));
    let summary = backup::import_all(&fresh, &json).await.expect("import");
    assert!(summary.subjects >= 1);

    assert_eq!(
        config::get(&fresh, "llm_base_url").await,
        Some("https://api.example.com".into()),
        "导入后应能取到原配置值"
    );
    assert_eq!(config::get(&fresh, "llm_api_key").await, Some("secret-key".into()));
    assert_eq!(config::get(&fresh, "ocr_model").await, Some("PaddleOCR-VL-1.6".into()));
}

#[tokio::test]
async fn test_import_legacy_backup_without_config_field() {
    // 手写一个不含 config 字段的旧版备份 JSON（version=1）
    let json = r#"{
        "version": 1,
        "subjects": [{"id": 1, "name": "数学", "created_at": "2024-01-01T00:00:00Z"}],
        "chapters": [],
        "tags": [],
        "questions": []
    }"#;

    let fresh = AppState::new(db::init_db(None).await.expect("fresh db"));
    let summary = backup::import_all(&fresh, json).await.expect("legacy import 应成功");
    assert_eq!(summary.subjects, 1, "旧备份科目应导入");
    assert_eq!(summary.questions, 0);

    // 科目应实际落库
    let list = subject::list_subjects(&fresh).await.expect("list subjects");
    assert_eq!(list.len(), 1);
    assert_eq!(list[0].name, "数学");
}