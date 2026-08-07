//! 错题图片命令：将用户选择的图片保存到应用数据目录，返回绝对路径供前端展示。

use crate::error::{Error, Result};

use super::AppState;

/// 允许保存的图片扩展名（小写）
const ALLOWED_EXT: [&str; 5] = ["jpg", "jpeg", "png", "webp", "gif"];
/// 单张图片大小上限（10 MB）
const MAX_BYTES: usize = 10 * 1024 * 1024;

/// 将图片 bytes 保存到 {data_dir}/images/ 下，返回可持久化的绝对路径。
/// 文件名用时间戳纳秒 + 安全化后的原始文件名，避免重名覆盖与路径穿越。
pub async fn save_image(state: &AppState, bytes: Vec<u8>, filename: String) -> Result<String> {
    if bytes.is_empty() {
        return Err(Error::Invalid("图片内容为空".into()));
    }
    if bytes.len() > MAX_BYTES {
        return Err(Error::Invalid(format!(
            "图片超过大小上限（{} MB）",
            MAX_BYTES / 1024 / 1024
        )));
    }

    let ext = std::path::Path::new(&filename)
        .extension()
        .and_then(|e| e.to_str())
        .map(|e| e.to_lowercase())
        .ok_or_else(|| Error::Invalid("无法识别图片格式".into()))?;
    if !ALLOWED_EXT.contains(&ext.as_str()) {
        return Err(Error::Invalid(format!(
            "不支持的图片格式: {ext}（仅支持 {:?}）",
            ALLOWED_EXT
        )));
    }

    let dir = state.data_dir.join("images");
    std::fs::create_dir_all(&dir)
        .map_err(|e| Error::Cleaner(format!("创建图片目录失败: {e}")))?;

    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    // 安全化文件名：仅保留字母/数字/下划线/点，避免路径穿越
    let safe_base: String = std::path::Path::new(&filename)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("img")
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() || c == '_' || c == '-' { c } else { '_' })
        .collect::<String>();
    let name = format!("{nanos}_{safe_base}.{ext}");
    let path = dir.join(name);

    std::fs::write(&path, &bytes)
        .map_err(|e| Error::Cleaner(format!("保存图片失败: {e}")))?;

    Ok(path.to_string_lossy().to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::commands::AppState;
    use crate::db;

    /// 用临时目录 + 内存库构造状态
    async fn state() -> (AppState, std::path::PathBuf) {
        let pool = db::init_db(None).await.expect("memory db");
        let dir = std::env::temp_dir().join(format!("cuoti_img_test_{}", std::process::id()));
        std::fs::create_dir_all(&dir).ok();
        (AppState::with_data_dir(pool, dir.clone()), dir)
    }

    #[tokio::test]
    async fn test_save_image_returns_path_and_persists_file() {
        let (st, dir) = state().await;
        let bytes = b"fake-png-bytes".to_vec();
        let path = save_image(&st, bytes.clone(), "题目.png".into())
            .await
            .expect("save");
        // 返回绝对路径，文件真实存在于 images 目录
        assert!(path.starts_with(dir.to_str().unwrap()));
        assert!(std::path::Path::new(&path).exists());
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
        // 清理
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[tokio::test]
    async fn test_save_image_rejects_unsupported_extension() {
        let (st, dir) = state().await;
        let err = save_image(&st, b"x".to_vec(), "note.txt".into())
            .await
            .expect_err("should reject");
        assert!(err.to_string().contains("不支持的图片格式"));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[tokio::test]
    async fn test_save_image_rejects_empty() {
        let (st, dir) = state().await;
        let err = save_image(&st, Vec::new(), "a.png".into())
            .await
            .expect_err("should reject empty");
        assert!(err.to_string().contains("图片内容为空"));
        let _ = std::fs::remove_dir_all(&dir);
    }
}