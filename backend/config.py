"""
错题管理系统 - 配置模块
"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """系统配置类

    支持的环境变量（用于 standalone 内嵌模式）:
      CLAW_ENV_FILE: 覆盖 .env 文件路径
      CLAW_DATA_DIR:  覆盖 upload/output/log 目录的根路径
    """

    model_config = SettingsConfigDict(
        env_file=os.environ.get("CLAW_ENV_FILE", ".env"),
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

    def _resolve_path(self, dir_path: str) -> Path:
        """解析路径，支持 CLAW_DATA_DIR 环境变量作为根目录"""
        data_root = os.environ.get("CLAW_DATA_DIR", "")
        if data_root and not os.path.isabs(dir_path):
            return Path(data_root) / dir_path.lstrip("./")
        return Path(dir_path)

    def get_upload_path(self) -> Path:
        path = self._resolve_path(self.upload_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_output_path(self) -> Path:
        path = self._resolve_path(self.output_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_log_path(self) -> Path:
        path = self._resolve_path(self.log_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()

# .env 文件的绝对路径，供写入配置使用
ENV_FILE_PATH = Path(__file__).parent / ".env"
