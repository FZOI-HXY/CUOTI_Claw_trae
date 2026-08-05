//! question 模块测试：list_questions 筛选、keyword 转义、更新/删除/状态操作

use cuoti_core::commands::{chapter, question, subject, AppState};
use cuoti_core::db;
use cuoti_core::error::Error;
use cuoti_core::models::{QuestionFilter, QuestionInput};

/// 通用造题辅助
async fn make_q(
    state: &AppState,
    sid: i64,
    cid: Option<i64>,
    qtype: Option<String>,
    title: &str,
    difficulty: Option<i64>,
    status: Option<String>,
    is_fav: Option<bool>,
    tags: Option<Vec<String>>,
) -> i64 {
    let q = question::create_question(
        state,
        QuestionInput {
            subject_id: sid,
            chapter_id: cid,
            qtype,
            title: title.to_string(),
            options: None,
            answer: Some("42".into()),
            analysis: Some("解析".into()),
            difficulty,
            status,
            notes: None,
            is_favorite: is_fav,
            image_path: None,
            source: None,
            wrong_reason: None,
            tags,
        },
    )
    .await
    .expect("create question");
    q.id
}

/// 便捷：默认 single / difficulty3 / not_mastered / 未收藏
async fn make_question(
    state: &AppState,
    sid: i64,
    cid: Option<i64>,
    title: &str,
    tags: Option<Vec<String>>,
) -> i64 {
    make_q(state, sid, cid, Some("single".into()), title, Some(3), Some("not_mastered".into()), Some(false), tags)
        .await
}

/// 初始化一个带科目/章节/若干题目的状态
async fn seeded_state() -> (AppState, i64, i64) {
    let pool = db::init_db(None).await.expect("init db");
    let state = AppState::new(pool);
    let subj = subject::create_subject(&state, "数学".into())
        .await
        .expect("subject");
    let chap = chapter::create_chapter(&state, subj.id, 0, "第一章".into())
        .await
        .expect("chapter");
    (state, subj.id, chap.id)
}

// ---- list_questions 筛选分支 ----

#[tokio::test]
async fn test_list_default_returns_all() {
    let (state, sid, cid) = seeded_state().await;
    make_question(&state, sid, Some(cid), "题A", None).await;
    make_question(&state, sid, Some(cid), "题B", None).await;

    let list = question::list_questions(&state, &QuestionFilter::default())
        .await
        .expect("list");
    assert_eq!(list.len(), 2);
}

#[tokio::test]
async fn test_list_filter_by_subject_id() {
    let (state, sid, cid) = seeded_state().await;
    let subj2 = subject::create_subject(&state, "英语".into()).await.expect("subject2");
    make_question(&state, sid, Some(cid), "数学题A", None).await;
    make_question(&state, sid, Some(cid), "数学题B", None).await;
    make_question(&state, subj2.id, None, "英语题", None).await;

    let list = question::list_questions(
        &state,
        &QuestionFilter {
            subject_id: Some(sid),
            ..Default::default()
        },
    )
    .await
    .expect("list");
    assert_eq!(list.len(), 2);
    assert!(list.iter().all(|q| q.subject_id == sid));
}

#[tokio::test]
async fn test_list_filter_by_chapter_id() {
    let (state, sid, cid) = seeded_state().await;
    let chap2 = chapter::create_chapter(&state, sid, 0, "第二章".into())
        .await
        .expect("chap2");
    make_question(&state, sid, Some(cid), "第一章题", None).await;
    make_question(&state, sid, Some(chap2.id), "第二章题", None).await;

    let list = question::list_questions(
        &state,
        &QuestionFilter {
            chapter_id: Some(cid),
            ..Default::default()
        },
    )
    .await
    .expect("list");
    assert_eq!(list.len(), 1);
    assert_eq!(list[0].title, "第一章题");
}

#[tokio::test]
async fn test_list_filter_by_qtype() {
    let (state, sid, cid) = seeded_state().await;
    make_q(&state, sid, Some(cid), Some("single".into()), "单选", None, None, None, None).await;
    make_q(&state, sid, Some(cid), Some("judge".into()), "判断", None, None, None, None).await;

    let list = question::list_questions(
        &state,
        &QuestionFilter {
            qtype: Some("judge".into()),
            ..Default::default()
        },
    )
    .await
    .expect("list");
    assert_eq!(list.len(), 1);
    assert_eq!(list[0].title, "判断");
}

#[tokio::test]
async fn test_list_filter_by_difficulty() {
    let (state, sid, cid) = seeded_state().await;
    make_q(&state, sid, Some(cid), None, "难题", Some(5), None, None, None).await;
    make_q(&state, sid, Some(cid), None, "易题", Some(1), None, None, None).await;

    let list = question::list_questions(
        &state,
        &QuestionFilter {
            difficulty: Some(5),
            ..Default::default()
        },
    )
    .await
    .expect("list");
    assert_eq!(list.len(), 1);
    assert_eq!(list[0].title, "难题");
}

#[tokio::test]
async fn test_list_filter_by_status() {
    let (state, sid, cid) = seeded_state().await;
    make_q(&state, sid, Some(cid), None, "未掌握", None, Some("not_mastered".into()), None, None).await;
    make_q(&state, sid, Some(cid), None, "已掌握", None, Some("mastered".into()), None, None).await;

    let list = question::list_questions(
        &state,
        &QuestionFilter {
            status: Some("mastered".into()),
            ..Default::default()
        },
    )
    .await
    .expect("list");
    assert_eq!(list.len(), 1);
    assert_eq!(list[0].title, "已掌握");
}

#[tokio::test]
async fn test_list_filter_by_is_favorite() {
    let (state, sid, cid) = seeded_state().await;
    let fav_id = make_q(&state, sid, Some(cid), None, "收藏题", None, None, Some(true), None).await;
    make_q(&state, sid, Some(cid), None, "普通题", None, None, Some(false), None).await;

    let list = question::list_questions(
        &state,
        &QuestionFilter {
            is_favorite: Some(true),
            ..Default::default()
        },
    )
    .await
    .expect("list");
    assert_eq!(list.len(), 1);
    assert_eq!(list[0].id, fav_id);
}

#[tokio::test]
async fn test_list_keyword_trims_whitespace() {
    let (state, sid, cid) = seeded_state().await;
    make_question(&state, sid, Some(cid), "三角函数", None).await;
    make_question(&state, sid, Some(cid), "几何图形", None).await;

    let list = question::list_questions(
        &state,
        &QuestionFilter {
            keyword: Some("  三角函数  ".into()),
            ..Default::default()
        },
    )
    .await
    .expect("list");
    assert_eq!(list.len(), 1);
    assert_eq!(list[0].title, "三角函数");
}

#[tokio::test]
async fn test_list_keyword_empty_or_whitespace_returns_all() {
    let (state, sid, cid) = seeded_state().await;
    make_question(&state, sid, Some(cid), "题A", None).await;
    make_question(&state, sid, Some(cid), "题B", None).await;

    let list = question::list_questions(
        &state,
        &QuestionFilter {
            keyword: Some("   ".into()),
            ..Default::default()
        },
    )
    .await
    .expect("list");
    assert_eq!(list.len(), 2, "纯空白 keyword 应被跳过，返回全部");
}

#[tokio::test]
async fn test_list_filter_by_tag() {
    let (state, sid, cid) = seeded_state().await;
    make_q(&state, sid, Some(cid), None, "带标签题", None, None, None, Some(vec!["重点".into()])).await;
    make_q(&state, sid, Some(cid), None, "无标签题", None, None, None, None).await;

    let list = question::list_questions(
        &state,
        &QuestionFilter {
            tag: Some("重点".into()),
            ..Default::default()
        },
    )
    .await
    .expect("list");
    assert_eq!(list.len(), 1);
    assert_eq!(list[0].title, "带标签题");
}

#[tokio::test]
async fn test_list_combined_filters() {
    let (state, sid, cid) = seeded_state().await;
    make_q(
        &state, sid, Some(cid), Some("single".into()), "匹配题", Some(4),
        Some("need_review".into()), Some(true), None,
    )
    .await;
    make_q(
        &state, sid, Some(cid), Some("single".into()), "难度不符", Some(2),
        Some("need_review".into()), Some(true), None,
    )
    .await;
    make_q(
        &state, sid, Some(cid), Some("judge".into()), "题型不符", Some(4),
        Some("need_review".into()), Some(true), None,
    )
    .await;

    let list = question::list_questions(
        &state,
        &QuestionFilter {
            subject_id: Some(sid),
            qtype: Some("single".into()),
            difficulty: Some(4),
            status: Some("need_review".into()),
            is_favorite: Some(true),
            ..Default::default()
        },
    )
    .await
    .expect("list");
    assert_eq!(list.len(), 1);
    assert_eq!(list[0].title, "匹配题");
}

// ---- keyword 单引号转义边界 ----

#[tokio::test]
async fn test_list_keyword_with_single_quote() {
    let (state, sid, cid) = seeded_state().await;
    make_question(&state, sid, Some(cid), "what's up", None).await;
    make_question(&state, sid, Some(cid), "普通题目", None).await;

    // 含单引号的标题仍可按 keyword 命中，且不报错
    let list = question::list_questions(
        &state,
        &QuestionFilter {
            keyword: Some("what's up".into()),
            ..Default::default()
        },
    )
    .await
    .expect("list keyword with quote");
    assert_eq!(list.len(), 1);
    assert_eq!(list[0].title, "what's up");
}

#[tokio::test]
async fn test_list_keyword_single_quote_no_error() {
    let (state, sid, cid) = seeded_state().await;
    make_question(&state, sid, Some(cid), "标题含'单引号", None).await;

    // 标题本身含单引号时，不带 keyword 列出不应报错
    let list = question::list_questions(&state, &QuestionFilter::default())
        .await
        .expect("list");
    assert_eq!(list.len(), 1);
}

// ---- update_question ----

#[tokio::test]
async fn test_update_question_updates_fields_and_tags() {
    let (state, sid, cid) = seeded_state().await;
    let id = make_question(&state, sid, Some(cid), "旧标题", Some(vec!["tag1".into()])).await;

    let updated = question::update_question(
        &state,
        id,
        QuestionInput {
            subject_id: sid,
            chapter_id: Some(cid),
            qtype: Some("judge".into()),
            title: "新标题".into(),
            options: None,
            answer: None,
            analysis: None,
            difficulty: Some(5),
            status: Some("mastered".into()),
            notes: None,
            is_favorite: Some(true),
            image_path: None,
            source: None,
            wrong_reason: None,
            tags: Some(vec!["tag2".into()]),
        },
    )
    .await
    .expect("update");
    assert_eq!(updated.title, "新标题");
    assert_eq!(updated.difficulty, 5);
    assert_eq!(updated.status, "mastered");
    assert_eq!(updated.is_favorite, true);
    assert_eq!(updated.tags, Some(vec!["tag2".to_string()]));
}

#[tokio::test]
async fn test_update_question_empty_tags_clears() {
    let (state, sid, cid) = seeded_state().await;
    let id = make_question(&state, sid, Some(cid), "带标签", Some(vec!["tag1".into()])).await;

    let updated = question::update_question(
        &state,
        id,
        QuestionInput {
            subject_id: sid,
            chapter_id: Some(cid),
            qtype: None,
            title: "带标签".into(),
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
            tags: Some(vec![]),
        },
    )
    .await
    .expect("update with empty tags");
    assert_eq!(updated.tags, Some(Vec::<String>::new()), "传空 tags 应清空标签");
}

// ---- toggle_favorite / increment_wrong_count ----

#[tokio::test]
async fn test_toggle_favorite_twice_returns_original() {
    let (state, sid, cid) = seeded_state().await;
    let id = make_question(&state, sid, Some(cid), "收藏题", None).await;

    let q1 = question::toggle_favorite(&state, id).await.expect("toggle1");
    assert!(q1.is_favorite, "第一次切换后应为收藏");

    let q2 = question::toggle_favorite(&state, id).await.expect("toggle2");
    assert!(!q2.is_favorite, "第二次切换应回到未收藏");
}

#[tokio::test]
async fn test_increment_wrong_count() {
    let (state, sid, cid) = seeded_state().await;
    let id = make_question(&state, sid, Some(cid), "错题", None).await;

    let q = question::increment_wrong_count(&state, id).await.expect("incr");
    assert_eq!(q.wrong_count, 1);

    let q2 = question::increment_wrong_count(&state, id).await.expect("incr2");
    assert_eq!(q2.wrong_count, 2);
}

// ---- 删除 / 状态校验 ----

#[tokio::test]
async fn test_delete_question_missing_returns_err() {
    let (state, _sid, _cid) = seeded_state().await;
    let err = question::delete_question(&state, 99999).await.unwrap_err();
    assert!(matches!(err, Error::NotFound(_)), "{}", err);
}

#[tokio::test]
async fn test_update_status_invalid_rejected() {
    let (state, sid, cid) = seeded_state().await;
    let id = make_question(&state, sid, Some(cid), "题目", None).await;
    let err = question::update_status(&state, id, "bogus".into()).await.unwrap_err();
    assert!(matches!(err, Error::Invalid(_)), "{}", err);
}

#[tokio::test]
async fn test_batch_update_status_invalid_rejected() {
    let (state, sid, cid) = seeded_state().await;
    let id = make_question(&state, sid, Some(cid), "题目", None).await;
    let err = question::batch_update_status(&state, vec![id], "bogus".into())
        .await
        .unwrap_err();
    assert!(matches!(err, Error::Invalid(_)), "{}", err);
}