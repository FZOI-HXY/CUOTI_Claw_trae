"""
错题管理系统 - 配置模块
"""
import os
import sys
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


def _discover_env_files() -> tuple[str, ...]:
    """发现所有候选 .env 文件（按优先级从低到高排序）

    pydantic-settings 会按顺序读取多个 .env 文件，
    后面的文件中的值会覆盖前面的。这样即使 exe 同级 .env 的 key 为空，
    也能从 %APPDATA%/Claw/.env 继承 key。

    优先级（从低到高）:
      1. frozen 模式: _MEIPASS/.env（打包时包含的默认配置）— 最低优先级
      2. 源码目录 .env（apps/web/api/.env）
      3. 开发模式数据目录
         - Windows: %APPDATA%/Claw/.env
         - 其他: ~/.claw/.env
      4. frozen 模式: exe 同级目录 .env — 便携模式
      5. CLAW_ENV_FILE 环境变量 — 显式覆盖，最高优先级
    """
    candidates: list[str] = []
    seen: set[str] = set()

    def _add(path: str):
        if path and os.path.exists(path) and path not in seen:
            candidates.append(path)
            seen.add(path)

    # 1. frozen 模式: _MEIPASS/.env（打包时包含的默认配置，最低优先级）
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', '')
        if meipass:
            _add(os.path.join(meipass, ".env"))

    # 2. 源码目录 fallback
    _add(str(Path(__file__).parent / ".env"))

    # 3. 开发模式数据目录
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
        _add(os.path.join(appdata, "Claw", ".env"))
    else:
        _add(os.path.join(os.path.expanduser("~"), ".claw", ".env"))

    # 4. frozen 模式: exe 同级目录（便携模式）
    if getattr(sys, 'frozen', False):
        _add(os.path.join(os.path.dirname(sys.executable), ".env"))

    # 5. CLAW_ENV_FILE 显式覆盖（最高优先级）
    _add(os.environ.get("CLAW_ENV_FILE", ""))

    if not candidates:
        # 没有找到任何 .env，返回默认路径（pydantic 会用默认值）
        return (str(Path(__file__).parent / ".env"),)

    return tuple(candidates)


def _discover_data_dir() -> str:
    """自动发现数据根目录（不依赖 CLAW_DATA_DIR 环境变量的设置时机）

    优先级:
      1. CLAW_DATA_DIR 环境变量
      2. frozen 模式: exe 同级目录
      3. 开发模式: %APPDATA%/Claw (Windows) 或 ~/.claw (其他)
    """
    data_dir = os.environ.get("CLAW_DATA_DIR")
    if data_dir:
        return data_dir

    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)

    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(appdata, "Claw")
    return os.path.join(os.path.expanduser("~"), ".claw")


# 在导入 Settings 之前确定 .env 路径
_RESOLVED_ENV_FILES = _discover_env_files()
_RESOLVED_DATA_DIR = _discover_data_dir()
os.makedirs(_RESOLVED_DATA_DIR, exist_ok=True)


class Settings(BaseSettings):
    """系统配置类

    支持的环境变量（用于 standalone 内嵌模式）:
      CLAW_ENV_FILE: 覆盖 .env 文件路径
      CLAW_DATA_DIR:  覆盖 upload/output/log 目录的根路径
    """

    model_config = SettingsConfigDict(
        env_file=_RESOLVED_ENV_FILES,
        env_file_encoding="utf-8",
    )

    # PaddleOCR API 配置 (百度AI Studio PaddleOCR 官方API)
    # 文档: https://ai.baidu.com/ai-doc/AISTUDIO/fml7mozw5
    # API_URL 和 TOKEN 从 https://paddleocr.aistudio-app.com 获取
    paddleocr_api_url: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
    # API Token：通过环境变量 PADDLEOCR_API_KEY 或 .env 文件配置
    # 从 https://aistudio.baidu.com/paddleocr/task 获取
    paddleocr_api_key: str = ""
    paddleocr_model: str = "PaddleOCR-VL-1.6"  # 模型: PaddleOCR-VL-1.6 / PaddleOCR-VL-1.5 / PP-StructureV3 / PP-OCRv6 / PP-OCRv5

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
        # 使用自动发现的数据目录（不依赖 CLAW_DATA_DIR 是否被外部设置）
        if not os.path.isabs(dir_path):
            return Path(_RESOLVED_DATA_DIR) / dir_path.lstrip("./")
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


def _read_env_key(env_path: str) -> str:
    """读取 .env 文件中的 PADDLEOCR_API_KEY 值（返回非空值或空字符串）"""
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("PADDLEOCR_API_KEY=") or line.startswith("paddleocr_api_key="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if val:
                        return val
    except Exception:
        pass
    return ""


settings = Settings()

# Fallback：如果 API key 为空（可能因为高优先级 .env 有空 key 覆盖了低优先级的非空 key），
# 遍历所有候选 .env 文件，找到第一个有非空 key 的，通过环境变量重新初始化 settings。
# 环境变量优先级高于 .env 文件，能确保 key 被正确加载。
if not settings.paddleocr_api_key:
    for env_file in _RESOLVED_ENV_FILES:
        key = _read_env_key(env_file)
        if key:
            os.environ["PADDLEOCR_API_KEY"] = key
            settings = Settings()  # 重新创建（环境变量优先级最高）
            break

# .env 文件的绝对路径，供写入配置使用
# 指向最高优先级的 .env（pydantic 读取顺序的最后一个）
ENV_FILE_PATH = Path(_RESOLVED_ENV_FILES[-1]) if _RESOLVED_ENV_FILES else Path(__file__).parent / ".env"
