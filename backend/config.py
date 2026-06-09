"""
错题管理系统 - 配置模块
"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """系统配置类"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # PaddleOCR API 配置 (百度AI Studio PaddleOCR 官方API)
    # 文档: https://ai.baidu.com/ai-doc/AISTUDIO/fml7mozw5
    # API_URL 和 TOKEN 从 https://paddleocr.aistudio-app.com 获取
    paddleocr_api_url: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
    paddleocr_api_key: str = ""  # TOKEN，认证格式: Authorization: bearer {TOKEN}
    paddleocr_model: str = "PP-StructureV3"  # 模型: PaddleOCR-VL-1.5 / PaddleOCR-VL / PP-StructureV3 / PP-OCRv5

    # 服务器配置
    host: str = "0.0.0.0"
    port: int = 8500
    debug: bool = True

    # 文件存储配置
    upload_dir: str = "./uploads"
    output_dir: str = "./output"
    log_dir: str = "./logs"
    max_upload_size_mb: int = 50

    # 日志配置
    log_level: str = "INFO"
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    def get_upload_path(self) -> Path:
        path = Path(self.upload_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_output_path(self) -> Path:
        path = Path(self.output_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_log_path(self) -> Path:
        path = Path(self.log_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()

# .env 文件的绝对路径，供写入配置使用
ENV_FILE_PATH = Path(__file__).parent / ".env"
