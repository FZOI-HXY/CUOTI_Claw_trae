//! 错误类型定义

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("数据库错误: {0}")]
    Db(#[from] sqlx::Error),

    #[error("配置错误: {0}")]
    Config(String),

    #[error("OCR 错误: {0}")]
    Ocr(String),

    #[error("LLM 清洗错误: {0}")]
    Cleaner(String),

    #[error("网络错误: {0}")]
    Network(String),

    #[error("参数错误: {0}")]
    Invalid(String),

    #[error("未找到: {0}")]
    NotFound(String),
}

impl serde::Serialize for Error {
    fn serialize<S>(&self, serializer: S) -> std::result::Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        serializer.serialize_str(&self.to_string())
    }
}

pub type Result<T> = std::result::Result<T, Error>;