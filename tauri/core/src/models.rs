//! 数据模型

use serde::{Deserialize, Serialize};

/// 题型分类
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum QuestionType {
    Single,   // 单选
    Multiple, // 多选
    Judge,    // 判断
    Fill,     // 填空
    Answer,   // 解答
}

impl QuestionType {
    pub fn as_str(&self) -> &'static str {
        match self {
            QuestionType::Single => "single",
            QuestionType::Multiple => "multiple",
            QuestionType::Judge => "judge",
            QuestionType::Fill => "fill",
            QuestionType::Answer => "answer",
        }
    }

    pub fn from_str(s: &str) -> Option<Self> {
        match s {
            "single" => Some(QuestionType::Single),
            "multiple" => Some(QuestionType::Multiple),
            "judge" => Some(QuestionType::Judge),
            "fill" => Some(QuestionType::Fill),
            "answer" => Some(QuestionType::Answer),
            _ => None,
        }
    }
}

/// 掌握状态
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum MasteryStatus {
    NotMastered, // 未掌握
    Mastered,    // 已掌握
    NeedReview,  // 需复习
}

impl MasteryStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            MasteryStatus::NotMastered => "not_mastered",
            MasteryStatus::Mastered => "mastered",
            MasteryStatus::NeedReview => "need_review",
        }
    }

    pub fn from_str(s: &str) -> Option<Self> {
        match s {
            "not_mastered" => Some(MasteryStatus::NotMastered),
            "mastered" => Some(MasteryStatus::Mastered),
            "need_review" => Some(MasteryStatus::NeedReview),
            _ => None,
        }
    }
}

/// 科目
#[derive(Debug, Clone, Serialize, Deserialize, sqlx::FromRow)]
pub struct Subject {
    pub id: i64,
    pub name: String,
    pub created_at: String,
}

/// 知识点/章节（支持层级）
#[derive(Debug, Clone, Serialize, Deserialize, sqlx::FromRow)]
pub struct Chapter {
    pub id: i64,
    pub subject_id: i64,
    pub parent_id: i64,
    pub name: String,
    pub path: String,
    pub created_at: String,
}

/// 标签
#[derive(Debug, Clone, Serialize, Deserialize, sqlx::FromRow)]
pub struct Tag {
    pub id: i64,
    pub name: String,
}

/// 错题
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Question {
    pub id: i64,
    pub subject_id: i64,
    pub chapter_id: Option<i64>,
    pub qtype: String,
    pub title: String,
    /// JSON 数组字符串
    pub options: Option<String>,
    pub answer: Option<String>,
    pub analysis: Option<String>,
    pub difficulty: i64,
    pub status: String,
    pub wrong_count: i64,
    pub notes: Option<String>,
    pub is_favorite: bool,
    pub image_path: Option<String>,
    pub source: Option<String>,
    pub wrong_reason: Option<String>,
    pub last_reviewed_at: Option<String>,
    pub created_at: String,
    pub updated_at: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub subject_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub chapter_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tags: Option<Vec<String>>,
}

/// 错题创建/更新入参
#[derive(Debug, Clone, Deserialize)]
pub struct QuestionInput {
    pub subject_id: i64,
    pub chapter_id: Option<i64>,
    pub qtype: Option<String>,
    pub title: String,
    pub options: Option<Vec<String>>,
    pub answer: Option<String>,
    pub analysis: Option<String>,
    pub difficulty: Option<i64>,
    pub status: Option<String>,
    pub notes: Option<String>,
    pub is_favorite: Option<bool>,
    pub image_path: Option<String>,
    pub source: Option<String>,
    pub wrong_reason: Option<String>,
    pub tags: Option<Vec<String>>,
}

/// 错题筛选条件
#[derive(Debug, Clone, Default, Deserialize)]
pub struct QuestionFilter {
    pub subject_id: Option<i64>,
    pub chapter_id: Option<i64>,
    pub qtype: Option<String>,
    pub difficulty: Option<i64>,
    pub status: Option<String>,
    pub keyword: Option<String>,
    pub is_favorite: Option<bool>,
    pub tag: Option<String>,
}

/// 统计：按科目
#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct SubjectStat {
    pub subject_id: i64,
    pub subject_name: String,
    pub total: i64,
    pub mastered: i64,
    pub need_review: i64,
    pub not_mastered: i64,
}

/// 统计：按知识点
#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct ChapterStat {
    pub chapter_id: i64,
    pub chapter_name: String,
    pub path: String,
    pub total: i64,
    pub mastered: i64,
}

/// 统计：按题型
#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct TypeStat {
    pub qtype: String,
    pub total: i64,
}

/// 总体统计
#[derive(Debug, Clone, Serialize)]
pub struct Stats {
    pub total: i64,
    pub mastered: i64,
    pub need_review: i64,
    pub not_mastered: i64,
    pub favorite: i64,
    pub by_subject: Vec<SubjectStat>,
    pub by_chapter: Vec<ChapterStat>,
    pub by_type: Vec<TypeStat>,
}

/// 配置键值
#[derive(Debug, Clone, Serialize, Deserialize, sqlx::FromRow)]
pub struct ConfigItem {
    pub key: String,
    pub value: String,
}

/// PaddleOCR 配置
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OcrConfig {
    pub api_url: String,
    pub api_key: String,
    pub model: String,
}

/// LLM 清洗配置
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LlmConfig {
    pub base_url: String,
    pub api_key: String,
    pub model: String,
    pub enabled: bool,
}

/// OCR + LLM 清洗结果 → 可填充的错题草稿
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OcrDraft {
    pub raw_text: String,
    pub cleaned: Option<CleanedQuestion>,
    pub error: Option<String>,
}

/// LLM 清洗出的结构化错题草稿
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CleanedQuestion {
    pub qtype: Option<String>,
    pub title: Option<String>,
    pub options: Option<Vec<String>>,
    pub answer: Option<String>,
    pub analysis: Option<String>,
    pub difficulty: Option<i64>,
    pub subject: Option<String>,
    pub chapter: Option<String>,
    pub tags: Option<Vec<String>>,
}