//! LLM 端到端调用验证（智谱 BigModel glm-4.5-air）
//!
//! 需要环境变量:
//!   BIGMODEL_API_KEY=<智谱 API Key>
//!
//! 运行:
//!   BIGMODEL_API_KEY=xxx cargo test --test llm_e2e -- --ignored --nocapture

use cuoti_core::cleaner::{Cleaner, LlmCleaner};
use cuoti_core::models::LlmConfig;

fn llm_config() -> LlmConfig {
    let api_key = std::env::var("BIGMODEL_API_KEY")
        .expect("请设置环境变量 BIGMODEL_API_KEY");
    LlmConfig {
        base_url: "https://open.bigmodel.cn/api/paas/v4".into(),
        api_key,
        model: "glm-4.5-air".into(),
        enabled: true,
    }
}

#[tokio::test]
#[ignore]
async fn clean_ocr_text_to_question() {
    let cleaner = LlmCleaner::new(&llm_config());
    let ocr = "选择题：1+1等于多少？A.1 B.2 C.3 D.4";
    match cleaner.clean(ocr).await {
        Ok(q) => println!(
            "OK qtype={:?} title={:?} options={:?} answer={:?} difficulty={:?}",
            q.qtype, q.title, q.options, q.answer, q.difficulty
        ),
        Err(e) => panic!("clean 失败: {e}"),
    }
}

#[tokio::test]
#[ignore]
async fn ask_rag_question() {
    let cleaner = LlmCleaner::new(&llm_config());
    match cleaner
        .ask("为什么1+1等于2？", "[1] 题目: 1+1=? 答案: 2")
        .await
    {
        Ok(s) => println!("OK answer: {s}"),
        Err(e) => panic!("ask 失败: {e}"),
    }
}