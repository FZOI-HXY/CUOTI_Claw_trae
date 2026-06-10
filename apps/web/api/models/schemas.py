"""
错题管理系统 - Pydantic 请求/响应数据模型

定义所有 API 端点的输入输出结构，供 FastAPI 自动文档和验证使用。
"""
from pydantic import BaseModel, Field
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
    paddleocr_model: str = ""
    api_key_configured: bool = False
    api_key_prefix: str = ""
    host: str = ""
    port: int = 8500
    upload_dir: str = ""
    output_dir: str = ""
    max_upload_size_mb: int = 50
    log_level: str = "INFO"


class ConfigUpdateRequest(BaseModel):
    paddleocr_api_url: Optional[str] = None
    paddleocr_api_key: Optional[str] = None
    paddleocr_model: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    debug: Optional[bool] = None
    upload_dir: Optional[str] = None
    output_dir: Optional[str] = None
    log_dir: Optional[str] = None
    max_upload_size_mb: Optional[int] = None
    log_level: Optional[str] = None


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


# ============ 批量下载 ============

class BatchDownloadRequest(BaseModel):
    report_ids: List[str] = Field(default_factory=list)


class BatchDownloadLayoutFile(BaseModel):
    filename: str = ""
    layout_items: List[Dict[str, Any]] = Field(default_factory=list)
    processing_time: float = 0


class BatchLayoutRequest(BaseModel):
    files: List[BatchDownloadLayoutFile] = Field(default_factory=list)
