//! 应用元信息

use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct Meta {
    pub name: String,
    pub version: String,
    pub description: String,
}

pub fn meta() -> Meta {
    Meta {
        name: "错题本".to_string(),
        version: env!("CARGO_PKG_VERSION").to_string(),
        description: "基于 Tauri + Rust + Vue 的错题管理应用".to_string(),
    }
}