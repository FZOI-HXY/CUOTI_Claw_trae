"""
错题管理系统 - 配置模块
"""
import os
import sys
from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _discover_env_files() -> tuple[str, ...]:
    """发现所有候选 .env 文件（按优先级从低到高排序）

    pydantic-settings 会按顺序读取多个 .env 文件，
    后面的文件中的值会覆盖前面的。

    frozen 模式优先级（从低到高）:
      1. 用户数据目录 .env（%APPDATA%/Claw/.env 或 ~/.claw/.env）— 旧配置，最低优先级
      2. _MEIPASS/.env（打包时包含的默认配置）— 打包时继承的开发环境配置
      3. exe 同级目录 .env — 便携模式，允许用户在 exe 目录自定义
      4. CLAW_ENV_FILE 环境变量 — 显式覆盖，最高优先级

    开发模式优先级（从低到高）:
      1. 源码目录 .env — 开发配置
      2. 用户数据目录 .env — 用户修改的配置
      3. CLAW_ENV_FILE 环境变量 — 显式覆盖
    """
    candidates: list[str] = []
    seen: set[str] = set()

    def _add(path: str):
        if path and os.path.exists(path) and path not in seen:
            candidates.append(path)
            seen.add(path)

    is_frozen = getattr(sys, 'frozen', False)

    if is_frozen:
        # frozen 模式：旧配置最低，打包时的配置优先

        # 1. 用户数据目录 .env（旧配置，最低优先级）
        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
            _add(os.path.join(appdata, "Claw", ".env"))
        else:
            _add(os.path.join(os.path.expanduser("~"), ".claw", ".env"))

        # 2. _MEIPASS/.env（打包时包含的默认配置，优先于旧配置）
        meipass = getattr(sys, '_MEIPASS', '')
        if meipass:
            _add(os.path.join(meipass, ".env"))

        # 3. exe 同级目录 .env（便携模式）
        _add(os.path.join(os.path.dirname(sys.executable), ".env"))

    else:
        # 开发模式：源码目录配置优先
        _add(str(Path(__file__).parent / ".env"))

        # 用户数据目录 .env（用户修改的配置）
        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
            _add(os.path.join(appdata, "Claw", ".env"))
        else:
            _add(os.path.join(os.path.expanduser("~"), ".claw", ".env"))

    # CLAW_ENV_FILE 显式覆盖（最高优先级）
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
    host: str = "127.0.0.1"
    port: int = 8500
    debug: bool = False

    # 文件存储配置
    upload_dir: str = "./uploads"
    output_dir: str = "./output"
    log_dir: str = "./logs"
    max_upload_size_mb: int = 50

    # 轮询配置（PaddleOCR 异步任务）
    poll_interval: int = 5          # 轮询间隔（秒）
    poll_max_retries: int = 120     # 最大轮询次数

    # 速率限制配置
    rate_limit_requests: int = 60   # 每窗口最大请求数
    rate_limit_window: int = 60      # 窗口大小（秒）

    # 日志配置
    log_level: str = "INFO"
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # 本地认证 token（由桌面端 backend_server.py 生成并设置到环境变量）
    # 为空时表示不启用认证（开发模式/测试模式）
    claw_auth_token: str = ""

    @field_validator("max_upload_size_mb")
    @classmethod
    def validate_max_upload_size(cls, v: int) -> int:
        """限制上传大小在 1-500MB 之间"""
        if v < 1 or v > 500:
            raise ValueError("max_upload_size_mb 必须在 1-500 之间")
        return v

    @field_validator("poll_interval")
    @classmethod
    def validate_poll_interval(cls, v: int) -> int:
        """轮询间隔至少 1 秒"""
        if v < 1:
            raise ValueError("poll_interval 至少为 1 秒")
        return v

    @field_validator("poll_max_retries")
    @classmethod
    def validate_poll_max_retries(cls, v: int) -> int:
        """最大轮询次数至少 1 次"""
        if v < 1:
            raise ValueError("poll_max_retries 至少为 1")
        return v

    @field_validator("rate_limit_requests")
    @classmethod
    def validate_rate_limit_requests(cls, v: int) -> int:
        """速率限制请求数至少 1"""
        if v < 1:
            raise ValueError("rate_limit_requests 至少为 1")
        return v

    @field_validator("rate_limit_window")
    @classmethod
    def validate_rate_limit_window(cls, v: int) -> int:
        """速率限制窗口至少 1 秒"""
        if v < 1:
            raise ValueError("rate_limit_window 至少为 1 秒")
        return v

    def _resolve_path(self, dir_path: str) -> Path:
        """解析路径，支持 CLAW_DATA_DIR 环境变量作为根目录

        安全措施：
          - 禁止路径包含 ``..``（防止路径遍历攻击）
          - 使用 ``removeprefix("./")`` 替代 ``lstrip("./")``（lstrip 会误删路径中的合法字符）
        """
        if ".." in dir_path:
            raise ValueError(f"路径不允许包含 '..': {dir_path}")
        # 使用自动发现的数据目录（不依赖 CLAW_DATA_DIR 是否被外部设置）
        if not os.path.isabs(dir_path):
            return Path(_RESOLVED_DATA_DIR) / dir_path.removeprefix("./")
        return Path(dir_path)

    def get_db_path(self) -> Path:
        """动态获取 SQLite 数据库路径（始终基于当前 output_dir 解析）"""
        return self.get_output_path() / "processing_history.db"

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


def validate_api_token() -> bool:
    """启动时校验 API Token 是否已配置。

    Returns:
        True 如果 Token 已配置，False 如果未配置（仅警告，不阻止启动）。
    """
    if not settings.paddleocr_api_key:
        import warnings
        warnings.warn(
            "PaddleOCR API Token 未配置！请在系统设置中配置 API Token 后才能使用 OCR 功能。",
            stacklevel=2,
        )
        return False
    return True
