"""
配置持久化服务 - 管理 .env 文件的读写

将原本放在 main.py 中的 _save_env_file 独立出来，职责单一。
"""
from pathlib import Path
from backend.logger import setup_logger

logger = setup_logger("ConfigService")

# 字段名映射：Python 小写 → .env 大写
ENV_KEY_MAPPING = {
    "paddleocr_api_url": "PADDLEOCR_API_URL",
    "paddleocr_api_key": "PADDLEOCR_API_KEY",
    "paddleocr_model": "PADDLEOCR_MODEL",
    "host": "HOST",
    "port": "PORT",
    "debug": "DEBUG",
    "upload_dir": "UPLOAD_DIR",
    "output_dir": "OUTPUT_DIR",
    "log_dir": "LOG_DIR",
    "max_upload_size_mb": "MAX_UPLOAD_SIZE_MB",
    "log_level": "LOG_LEVEL",
}


def save_env_file(config_data: dict, env_path: Path) -> bool:
    """将配置更新写入 .env 文件

    Args:
        config_data: {python_key: value} 字典
        env_path: .env 文件路径

    Returns:
        True 表示写入成功
    """
    try:
        # 读取现有 .env 内容
        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()
        else:
            lines = []

        for python_key, value in config_data.items():
            env_key = ENV_KEY_MAPPING.get(python_key)
            if not env_key:
                continue

            # 跳过空的 api_key
            if python_key == "paddleocr_api_key" and not value:
                continue

            # 转换 value 为字符串
            str_value = str(value).lower() if isinstance(value, bool) else str(value)

            # 查找并更新对应行
            found = False
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith(f"{env_key}=") or stripped.startswith(f"# {env_key}="):
                    lines[i] = f"{env_key}={str_value}"
                    found = True
                    break

            # 如果没找到，追加到文件末尾
            if not found:
                lines.append(f"{env_key}={str_value}")

        # 写回文件
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        logger.info(f"配置已持久化到 {env_path}")
        return True

    except Exception as e:
        logger.error(f"保存 .env 失败: {e}")
        return False
