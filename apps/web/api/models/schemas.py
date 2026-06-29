"""
错题管理系统 - Pydantic 请求/响应数据模型

定义所有 API 端点的输入输出结构，供 FastAPI 自动文档和验证使用。
"""
import re
from enum import Enum
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any


# ============ 通用 ============

class ErrorResponse(BaseModel):
    """统一错误响应"""
    success: bool = False
    error: str = ""
    code: str = ""


# ============ 健康检查 ============

class HealthResponse(BaseModel):
    status: str = "healthy"
    timestamp: str = ""


class SystemStatusResponse(BaseModel):
    status: str = "running"
    start_time: str = ""
    uptime_seconds: float = 0
    processed_count: int = 0
    api_configured: bool = False
    upload_dir: str = ""
    output_dir: str = ""


# ============ 配置 ============

class ConfigResponse(BaseModel):
    paddleocr_api_url: str = ""
    paddleocr_api_key: str = ""
    paddleocr_model: str = ""
    api_key_configured: bool = False
    host: str = ""
    port: int = 8500
    upload_dir: str = ""
    output_dir: str = ""
    max_upload_size_mb: int = 50
    log_level: str = "INFO"


class LogLevel(str, Enum):
    """允许的日志级别"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


def _validate_no_traversal(value: Optional[str]) -> Optional[str]:
    """校验路径字段不含路径遍历符 ``..``"""
    if value is not None and ".." in value:
        raise ValueError("路径不允许包含 '..'")
    return value


class ConfigUpdateRequest(BaseModel):
    paddleocr_api_url: Optional[str] = None
    paddleocr_api_key: Optional[str] = None
    paddleocr_model: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    debug: Optional[bool] = None
    upload_dir: Optional[str] = None
    output_dir: Optional[str] = None
    log_dir: Optional[str] = None
    max_upload_size_mb: Optional[int] = None
    log_level: Optional[LogLevel] = None
    poll_interval: Optional[int] = None
    poll_max_retries: Optional[int] = None
    rate_limit_requests: Optional[int] = None
    rate_limit_window: Optional[int] = None

    @field_validator("upload_dir", "output_dir", "log_dir")
    @classmethod
    def validate_paths_no_traversal(cls, v: Optional[str]) -> Optional[str]:
        """路径字段禁止包含 ``..``（防止路径遍历攻击）"""
        return _validate_no_traversal(v)

    @field_validator("host")
    @classmethod
    def validate_host_format(cls, v: Optional[str]) -> Optional[str]:
        """host 必须是 IP 地址或 localhost"""
        if v is None:
            return v
        # 允许 IPv4 / IPv6 / localhost
        if v == "localhost":
            return v
        ipv4_re = re.compile(
            r'^(\d{1,3}\.){3}\d{1,3}$'
        )
        if ipv4_re.match(v):
            parts = v.split(".")
            if all(0 <= int(p) <= 255 for p in parts):
                return v
            raise ValueError("无效的 IPv4 地址")
        # IPv6 简单校验（含冒号）
        if ":" in v and all(c in "0123456789abcdefABCDEF:." for c in v):
            return v
        raise ValueError("host 必须是有效的 IP 地址或 localhost")


# ============ 上传 ============

class UploadResponse(BaseModel):
    success: bool = True
    file_id: str = ""
    original_name: str = ""
    saved_name: str = ""
    size: int = 0
    path: str = ""


# ============ 任务提交与轮询 ============

class SubmitTaskRequest(BaseModel):
    fileUrl: Optional[str] = None
    filename: Optional[str] = None
    pageRanges: Optional[str] = None
    batchId: Optional[str] = None


class SubmitTaskResponse(BaseModel):
    success: bool = True
    task_id: str = ""
    file_id: Optional[str] = None
    filename: str = ""
    status: str = "processing"
    batch_id: Optional[str] = None


class TaskProgress(BaseModel):
    state: Optional[str] = None
    extracted_pages: int = 0
    total_pages: int = 0
    attempt: int = 0


class PollTaskResponse(BaseModel):
    task_id: str = ""
    file_id: Optional[str] = None
    filename: str = ""
    status: str = "processing"
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    completed: bool = False
    progress: Optional[TaskProgress] = None


class ProcessResponse(BaseModel):
    success: bool = True
    file_id: str = ""
    processing_time: Optional[float] = None
    markdown_text: str = ""
    images: Dict[str, str] = Field(default_factory=dict)
    images_count: int = 0
    layout_items: List[Dict[str, Any]] = Field(default_factory=list)
    layout_items_count: int = 0
    layout_image_base64: Optional[str] = None
    report_dir: str = ""


# ============ 历史记录 ============

class HistoryItem(BaseModel):
    id: str = ""
    file_id: Optional[str] = None
    filename: str = ""
    timestamp: str = ""
    success: bool = True
    processing_time: float = 0
    images_count: int = 0
    markdown_length: int = 0
    report_dir: Optional[str] = None
    model: Optional[str] = None
    total_pages: int = 0


class HistoryResponse(BaseModel):
    total: int = 0
    items: List[HistoryItem] = Field(default_factory=list)


# ============ 报告 ============

class ReportItem(BaseModel):
    id: str = ""
    path: str = ""
    has_markdown: bool = False
    created_time: str = ""


class ReportListResponse(BaseModel):
    total: int = 0
    reports: List[ReportItem] = Field(default_factory=list)


# ============ 批量操作 ============

class BatchDeleteRequest(BaseModel):
    """批量删除请求（历史记录/报告通用）"""
    ids: List[str] = Field(default_factory=list)


class BatchDownloadRequest(BaseModel):
    report_ids: List[str] = Field(default_factory=list)


class BatchDownloadLayoutFile(BaseModel):
    filename: str = ""
    layout_items: List[Dict[str, Any]] = Field(default_factory=list)
    processing_time: float = 0


class BatchLayoutRequest(BaseModel):
    files: List[BatchDownloadLayoutFile] = Field(default_factory=list)
