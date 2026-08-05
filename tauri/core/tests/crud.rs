//! subject / chapter / tag 的 CRUD 与校验集成测试（内存库）

use cuoti_core::commands::{chapter, subject, tag, AppState};
use cuoti_core::db;

async fn state() -> AppState {
    AppState::new(db::init_db(None).await.expect("memory db"))
}

// ---------- subject ----------

#[tokio::test]
async fn test_subject_create_empty_name_returns_err() {
    let s = state().await;
    assert!(subject::create_subject(&s, "   ".into()).await.is_err());
    assert!(subject::create_subject(&s, "".into()).await.is_err());
}

#[tokio::test]
async fn test_subject_list_sorted_by_name() {
    let s = state().await;
    let math = subject::create_subject(&s, "math".into()).await.expect("math");
    let eng = subject::create_subject(&s, "english".into()).await.expect("english");
    assert_ne!(math.id, eng.id);

    let list = subject::list_subjects(&s).await.expect("list");
    let names: Vec<&str> = list.iter().map(|x| x.name.as_str()).collect();
    // 按名称排序（english < math）
    assert_eq!(names, vec!["english", "math"]);
}

#[tokio::test]
async fn test_subject_rename_works() {
    let s = state().await;
    let created = subject::create_subject(&s, "old".into()).await.expect("create");
    let renamed = subject::rename_subject(&s, created.id, "new".into())
        .await
        .expect("rename");
    assert_eq!(renamed.name, "new");
    assert_eq!(subject::get_by_id(&s, created.id).await.expect("get").name, "new");
}

#[tokio::test]
async fn test_subject_delete_then_get_returns_not_found() {
    let s = state().await;
    let created = subject::create_subject(&s, "gone".into()).await.expect("create");
    subject::delete_subject(&s, created.id).await.expect("delete");
    assert!(subject::get_by_id(&s, created.id).await.is_err());
}

// ---------- chapter ----------

#[tokio::test]
async fn test_chapter_root_and_nested_path() {
    let s = state().await;
    let subj = subject::create_subject(&s, "ch-math".into()).await.expect("subject");

    // 根节点 parent_id = 0，path 形如 "1/"
    let root = chapter::create_chapter(&s, subj.id, 0, "根".into())
        .await
        .expect("root");
    assert_eq!(root.path, format!("{}/", subj.id));

    // 嵌套子节点：path = 父.path + subject_id + "/"
    let child = chapter::create_chapter(&s, subj.id, root.id, "子".into())
        .await
        .expect("child");
    assert_eq!(child.path, format!("{}{}/", root.path, subj.id));
}

#[tokio::test]
async fn test_chapter_rename_works() {
    let s = state().await;
    let subj = subject::create_subject(&s, "ch-rename".into()).await.expect("subject");
    let created = chapter::create_chapter(&s, subj.id, 0, "old".into())
        .await
        .expect("create");
    let renamed = chapter::rename_chapter(&s, created.id, "new".into())
        .await
        .expect("rename");
    assert_eq!(renamed.name, "new");
}

#[tokio::test]
async fn test_chapter_delete_nonexistent_returns_err() {
    let s = state().await;
    assert!(chapter::delete_chapter(&s, 999_999).await.is_err());
}

#[tokio::test]
async fn test_chapter_list_by_subject_returns_all() {
    let s = state().await;
    let subj = subject::create_subject(&s, "ch-list".into()).await.expect("subject");
    let other = subject::create_subject(&s, "ch-other".into()).await.expect("other");

    let root = chapter::create_chapter(&s, subj.id, 0, "根".into()).await.expect("root");
    chapter::create_chapter(&s, subj.id, root.id, "子".into())
        .await
        .expect("child");
    // 其它科目下的章节不应出现在本科目的列表中
    chapter::create_chapter(&s, other.id, 0, "其它根".into())
        .await
        .expect("other root");

    let list = chapter::list_by_subject(&s, subj.id).await.expect("list");
    assert_eq!(list.len(), 2, "应返回该科目下所有章节");
}

// ---------- tag ----------

#[tokio::test]
async fn test_tag_create_empty_name_returns_err() {
    let s = state().await;
    assert!(tag::create_tag(&s, "   ".into()).await.is_err());
    assert!(tag::create_tag(&s, "".into()).await.is_err());
}

#[tokio::test]
async fn test_tag_duplicate_create_returns_same_id() {
    let s = state().await;
    let a = tag::create_tag(&s, "dup".into()).await.expect("first");
    let b = tag::create_tag(&s, "dup".into()).await.expect("second");
    assert_eq!(a.id, b.id, "INSERT OR IGNORE 去重应返回同一 id");
}

#[tokio::test]
async fn test_tag_delete_then_get_returns_not_found() {
    let s = state().await;
    let created = tag::create_tag(&s, "gone".into()).await.expect("create");
    tag::delete_tag(&s, created.id).await.expect("delete");
    assert!(tag::get_by_id(&s, created.id).await.is_err());
}