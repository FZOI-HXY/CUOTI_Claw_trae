"""
DocFlow — AI智能文档识别与管理系统 - FastAPI 后端主服务

支持的 OCR 模型:
  - PaddleOCR-VL-1.6（多模态文档分析，最新推荐）
  - PaddleOCR-VL-1.5 / PaddleOCR-VL（文档结构化分析）
  - PP-StructureV3（文档结构化分析）
  - PP-OCRv6 / PP-OCRv5（纯文字识别）

处理流程: 上传 → PaddleOCR API 异步识别 → 轮询结果 → 保存结构化 Markdown

参考文档: https://ai.baidu.com/ai-doc/AISTUDIO/fml7mozw5
"""
import io
import re
import uuid
import hmac
import socket
import shutil
import zipfile
import asyncio
import ipaddress
from pathlib import Path
from typing import List, Optional
from datetime import datetime
from time import time as _time
from urllib.parse import quote, urlparse
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
import uvicorn
import httpx

from apps.web.api.config import settings, ENV_FILE_PATH, validate_api_token
from apps.web.api.logger import setup_logger, update_log_level
from apps.web.api.models.schemas import (
    ConfigUpdateRequest,
    BatchDeleteRequest,
    BatchDownloadRequest,
    BatchLayoutRequest,
    SubmitTaskRequest,
)

# ---------------------------------------------------------------------------
# 条件导入 PaddleOCRService（方案 3：httpx 优先 + 自动降级）
#   - 开发模式：直接使用 httpx 版
#   - PyInstaller 打包后：先尝试 httpx 版，若导入失败则降级到标准库版
# ---------------------------------------------------------------------------
import sys as _sys

_use_standalone = False

if getattr(_sys, 'frozen', False):
    try:
        from apps.web.api.paddle_service import PaddleOCRService as _HTTPService  # type: ignore[assignment]
        PaddleOCRService = _HTTPService
    except ImportError:
        from apps.desktop.paddle_service_standalone import PaddleOCRService  # type: ignore[no-redef]
        _use_standalone = True
else:
    from apps.web.api.paddle_service import PaddleOCRService  # type: ignore[no-redef]

from apps.web.api.markdown_generator import MarkdownGenerator
from apps.web.api.services.task_service import task_service as ts
from apps.web.api.services.config_service import save_env_file

logger = setup_logger("MainServer")

if getattr(_sys, 'frozen', False):
    logger.info(f"PaddleOCRService 加载模式: {'标准库降级' if _use_standalone else 'httpx'} (frozen)")

# 已知的无效占位符 API URL（启动时自动修正）
_PLACEHOLDER_URLS = {"new-api.example.com", "example.com", ""}
_CORRECT_API_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
_CORRECT_MODEL = "PaddleOCR-VL-1.6"


def _migrate_stale_config():
    """启动时检查并修正已知的无效配置值。

    防止 .env 被外部进程覆盖后，服务带着占位符 URL 启动导致 DNS 解析失败。
    """
    migrated = []
    if settings.paddleocr_api_url in _PLACEHOLDER_URLS or "example.com" in settings.paddleocr_api_url:
        logger.warning(f"检测到无效 API URL: {settings.paddleocr_api_url}，自动修正为官方地址")
        settings.paddleocr_api_url = _CORRECT_API_URL
        migrated.append("paddleocr_api_url")

    if settings.paddleocr_model in ("PP-StructureV3", "PP-OCRv5", "PP-OCRv4"):
        logger.warning(f"检测到旧版模型: {settings.paddleocr_model}，自动升级为 {_CORRECT_MODEL}")
        settings.paddleocr_model = _CORRECT_MODEL
        migrated.append("paddleocr_model")

    if settings.log_level and settings.log_level.startswith("LogLevel."):
        fixed = settings.log_level.replace("LogLevel.", "")
        logger.warning(f"检测到错误的 LOG_LEVEL 格式: {settings.log_level}，修正为 {fixed}")
        settings.log_level = fixed
        migrated.append("log_level")

    if migrated:
        save_env_file({k: getattr(settings, k) for k in migrated}, ENV_FILE_PATH)
        logger.info(f"配置自动迁移完成: {', '.join(migrated)}")
    return migrated


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时执行安全检查和配置迁移。"""
    migrated = _migrate_stale_config()
    # 配置迁移后同步更新 paddle_service 实例（模块级初始化时用的是旧值）
    if migrated:
        paddle_service.job_url = settings.paddleocr_api_url.rstrip("/")
        paddle_service.model = settings.paddleocr_model
        logger.info("paddle_service 实例已同步迁移后的配置")
    if not validate_api_token():
        logger.warning("PaddleOCR API Token 未配置，OCR 功能将不可用。请在系统设置中配置。")
    logger.info(f"速率限制: {settings.rate_limit_requests} 请求/{settings.rate_limit_window}秒")
    yield

# 初始化 FastAPI 应用
# I07: 生产环境禁用 docs（仅在 debug 模式下提供文档）
_is_debug = settings.debug
app = FastAPI(
    title="DocFlow",
    description="AI智能文档识别与管理系统 — 基于 PaddleOCR 多模态识别",
    version="1.2.0",
    lifespan=lifespan,
    docs_url="/docs" if _is_debug else None,
    redoc_url="/redoc" if _is_debug else None,
    openapi_url="/openapi.json" if _is_debug else None,
)

# I06: TrustedHost 中间件（Cloudflare Tunnel 部署需允许任意 Host 头）
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["127.0.0.1", "localhost", "0.0.0.0", "*"],
)

# CORS 配置（仅允许本机访问，桌面应用内嵌后端不暴露到外网）
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8500",
        "http://localhost:8500",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# I05: 安全响应头中间件
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """为所有响应添加安全相关 HTTP 头"""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data: blob:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline';"
    )
    return response


# S06: 本地认证中间件
# 对所有请求校验 X-Claw-Token 头，仅显式白名单端点免认证。
# 当 settings.claw_auth_token 为空时（开发/测试模式），不启用认证。
# 安全说明（F-001 修复）：GET 请求不再全局豁免——公网部署下 GET 端点
# （/api/reports、/api/history 等）返回敏感业务数据，必须校验 token 防止未授权读取。
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """本地认证中间件：保护所有业务端点

    公开端点（免认证）：/、/api/health、/api/init、/api/info、/api/status、/app/*
    业务端点（需认证）：/api/reports、/api/report/*、/api/history、/api/batch/*、/api/config 等
    """
    # 显式白名单：公开端点不需要认证
    if request.url.path in ("/", "/api/health", "/api/init", "/api/info", "/api/status"):
        return await call_next(request)

    # 静态文件不需要认证
    if request.url.path.startswith("/app"):
        return await call_next(request)

    # 如果未配置 token，则不启用认证（开发/测试模式）
    auth_token = settings.claw_auth_token
    if not auth_token:
        return await call_next(request)

    # 校验 X-Claw-Token 头（所有方法含 GET 均需校验）
    # 图片端点通过 <img src> 加载，无法附加自定义头，允许 ?token= 查询参数作为回退
    provided_token = request.headers.get("X-Claw-Token", "") or request.query_params.get("token", "")
    if not hmac.compare_digest(str(provided_token), str(auth_token)):
        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "error": "未授权：缺少或无效的认证 token",
                "code": "UNAUTHORIZED",
            },
        )

    return await call_next(request)

# 初始化服务
paddle_service = PaddleOCRService(
    api_url=settings.paddleocr_api_url,
    api_key=settings.paddleocr_api_key,
    model=settings.paddleocr_model,
)
markdown_generator = MarkdownGenerator(output_dir=settings.get_output_path())

SYSTEM_START_TIME = datetime.now()


# ============ 安全工具函数 ============

def _secure_filename(filename: str) -> str:
    """安全化文件名，防止路径穿越攻击。

    1. 提取纯文件名（剥离所有路径分隔符）
    2. 移除危险字符（<>:"/\\|?*\\x00-\\x1f）
    3. 限制文件名长度（255字符）

    Returns:
        安全的文件名字符串（仅文件名部分，不含路径）。
    """
    if not filename:
        return ""
    # 取纯文件名，剥离任何路径前缀
    safe = Path(filename).name
    # 移除危险字符
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', safe)
    # 移除开头的点和空格（防止隐藏文件名攻击）
    safe = safe.lstrip('. ')
    # 限制长度
    if len(safe) > 255:
        p = Path(safe)
        ext = p.suffix
        max_name_len = 255 - len(ext)
        safe = p.stem[:max_name_len] + ext
    return safe or "upload"


def _extract_safe_extension(filename: str) -> str:
    """从文件名中安全提取扩展名，防止路径穿越。

    使用 _secure_filename 先清洗文件名，再提取后缀。
    """
    safe_name = _secure_filename(filename)
    ext = Path(safe_name).suffix or ".png"
    # 确保扩展名只包含字母数字
    ext = re.sub(r'[^a-zA-Z0-9.]', '', ext)
    return ext if ext.startswith('.') else '.png'


def _validate_file_id(file_id: str) -> None:
    """S01: 校验 file_id 格式，防止路径遍历攻击。

    file_id 必须是 32 位十六进制字符串（UUID4 hex 格式）。
    不匹配则抛出 HTTPException(400)。
    """
    if not file_id or not re.match(r'^[0-9a-f]{32}$', file_id):
        raise HTTPException(
            status_code=400,
            detail="无效的 file_id 格式：必须是 32 位十六进制字符串",
        )


def _is_internal_ip(host: str) -> bool:
    """S05: 判断主机名是否为内网地址或 localhost

    同时检查主机名本身是否为内网 IP，以及域名解析后的 IP 是否为内网地址，
    防止攻击者使用解析到内网 IP 的域名绕过 SSRF 防护。
    """
    if host in ("localhost",):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        pass

    try:
        ips = socket.getaddrinfo(host, None, socket.AF_INET)
        for _, _, _, _, (ip_addr, _) in ips:
            ip = ipaddress.ip_address(ip_addr)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return True
    except (socket.gaierror, ValueError):
        pass

    try:
        ips = socket.getaddrinfo(host, None, socket.AF_INET6)
        for _, _, _, _, (ip_addr, _, _, _) in ips:
            ip = ipaddress.ip_address(ip_addr)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return True
    except (socket.gaierror, ValueError):
        pass

    return False


def _resolve_and_validate_ip(host: str) -> Optional[str]:
    """B6: 解析主机名并校验 IP 安全性，返回首个公网 IP

    一次性完成 DNS 解析和内网 IP 校验，避免二次解析导致 DNS 重绑定。
    如果 host 是 localhost、内网 IP 或解析到内网 IP，返回 None。
    """
    if host in ("localhost",):
        return None

    # 如果 host 本身就是 IP 地址，直接校验
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return None
        return host  # 公网 IP，直接返回
    except ValueError:
        pass

    # DNS 解析域名，返回首个公网 IP
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            infos = socket.getaddrinfo(host, None, family)
            for _, _, _, _, sockaddr in infos:
                ip_addr = sockaddr[0]
                try:
                    ip = ipaddress.ip_address(ip_addr)
                    if not (ip.is_private or ip.is_loopback or ip.is_link_local):
                        return ip_addr
                except ValueError:
                    continue
        except (socket.gaierror, ValueError):
            pass

    return None


def _validate_file_url(file_url: str) -> str:
    """S05: 校验 file_url，防止 SSRF 攻击

    - 必须以 https:// 开头
    - 拒绝 localhost 和内网 IP (10.x, 172.16-31.x, 192.168.x, 127.x, 169.254.x)
    - B6: 返回校验通过的 IP 地址，调用方使用该 IP 发起请求以防止 DNS 重绑定
    """
    if not file_url:
        raise HTTPException(status_code=400, detail="fileUrl 参数必填")

    if not file_url.startswith("https://"):
        raise HTTPException(
            status_code=400,
            detail="fileUrl 必须使用 HTTPS 协议",
        )

    try:
        parsed = urlparse(file_url)
        host = parsed.hostname or ""
        if not host:
            raise HTTPException(status_code=400, detail="fileUrl 主机名无效")

        # B6: 一次性解析并校验 IP，返回首个公网 IP 防止 DNS 重绑定
        validated_ip = _resolve_and_validate_ip(host)
        if validated_ip is None:
            raise HTTPException(
                status_code=400,
                detail="fileUrl 不允许指向内网地址或 localhost",
            )
        return validated_ip
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"fileUrl 格式无效: {e}")


def _check_magic_bytes(content: bytes) -> None:
    """I03: 校验文件头 Magic Bytes，防止伪装文件类型"""
    if not content or len(content) < 4:
        raise HTTPException(status_code=400, detail="文件内容为空或过小")

    # 常见图片/PDF 文件头
    magic_signatures = {
        b'\xff\xd8\xff': "JPEG",
        b'\x89PNG': "PNG",
        b'BM': "BMP",
        b'GIF8': "GIF",
        b'%PDF': "PDF",
        b'II*\x00': "TIFF (LE)",
        b'MM\x00*': "TIFF (BE)",
    }

    for sig, fmt in magic_signatures.items():
        if content[:len(sig)] == sig:
            return  # 有效格式

    # WebP: RIFF....WEBP（bytes 0-3 = RIFF, bytes 8-11 = WEBP）
    # 不能仅检查 RIFF，因为 AVI 文件也以 RIFF 开头
    if len(content) >= 12 and content[:4] == b'RIFF' and content[8:12] == b'WEBP':
        return  # 有效 WebP 格式

    raise HTTPException(
        status_code=400,
        detail="文件内容与声明的类型不匹配（Magic Bytes 校验失败）",
    )


# ============ 速率限制中间件 ============

_rate_limit_store: dict = defaultdict(list)
# S09: 每隔一定请求数后执行一次清理，防止内存泄漏
_RATE_LIMIT_CLEANUP_INTERVAL = 100
_rate_limit_request_count = 0


def _cleanup_rate_limit_store():
    """S09: 清理空的或过期的 IP 条目，防止内存泄漏"""
    now = _time()
    window = settings.rate_limit_window
    expired_keys = []
    for ip, timestamps in _rate_limit_store.items():
        # 清除过期时间戳
        fresh = [t for t in timestamps if now - t < window]
        if fresh:
            _rate_limit_store[ip] = fresh
        else:
            expired_keys.append(ip)
    for ip in expired_keys:
        del _rate_limit_store[ip]


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """简单的内存速率限制中间件，防止暴力请求。"""
    global _rate_limit_request_count
    # 健康检查端点不限速
    if request.url.path == "/api/health":
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    now = _time()
    window = settings.rate_limit_window
    max_requests = settings.rate_limit_requests

    # S09: 定期清理过期/空条目
    _rate_limit_request_count += 1
    if _rate_limit_request_count >= _RATE_LIMIT_CLEANUP_INTERVAL:
        _rate_limit_request_count = 0
        _cleanup_rate_limit_store()

    # 清理当前 IP 的过期记录
    _rate_limit_store[client_ip] = [
        t for t in _rate_limit_store[client_ip] if now - t < window
    ]

    if len(_rate_limit_store[client_ip]) >= max_requests:
        return JSONResponse(
            status_code=429,
            content={
                "success": False,
                "error": "请求过于频繁，请稍后再试",
                "code": "RATE_LIMITED",
            },
        )

    _rate_limit_store[client_ip].append(now)
    return await call_next(request)


# ============ 路径安全校验 ============

def _safe_report_dir(report_id: str) -> Path:
    """安全获取报告目录路径，防止路径穿越攻击

    将用户传入的 report_id 解析为 output_dir 下的绝对路径，
    并验证解析后的路径严格位于 output_dir 子树内且为目录类型。
    """
    if not report_id:
        raise HTTPException(status_code=400, detail="无效的报告 ID")
    output_dir = settings.get_output_path().resolve()
    report_dir = (output_dir / report_id).resolve()
    # 确保解析后路径仍在 output_dir 内
    try:
        report_dir.relative_to(output_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"无效的报告 ID: {report_id}")
    # 确保是目录类型，防止删除普通文件
    if report_dir.exists() and not report_dir.is_dir():
        raise HTTPException(status_code=400, detail=f"无效的报告 ID: {report_id}")
    return report_dir


def _is_valid_report_id_format(report_id: str) -> bool:
    """校验 report_id 格式是否合法（不抛异常，供批量端点过滤使用）

    report_id 由 save_report 生成，格式为 ``YYYYMMDD_HHMMSS_<8hex>``，
    也兼容旧格式 ``YYYYMMDD_HHMMSS``。仅允许字母、数字、下划线、连字符，
    长度上限 64 字符。拒绝：
      - 路径分隔符 (/, \\)
      - 路径穿越 (..)
      - Shell 元字符 (| ; ` $ > < & 等)
    """
    if not report_id:
        return False
    # 仅允许字母、数字、下划线、连字符，长度 1-64
    if not re.match(r'^[A-Za-z0-9_\-]{1,64}$', report_id):
        return False
    return True


def _safe_report_image_path(report_dir: Path, image_name: str) -> Path:
    """安全获取报告图片路径，防止路径穿越"""
    img_path = (report_dir / image_name).resolve()
    try:
        img_path.relative_to(report_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"无效的图片路径: {image_name}")
    return img_path


# ============ 全局异常处理器 ============

@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException):
    """捕获 HTTPException，返回统一格式"""
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": exc.detail, "code": str(exc.status_code)},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局未知异常处理器，生产环境不泄露内部细节。"""
    logger.error(f"未处理异常 [{request.method} {request.url.path}]: {exc}", exc_info=True)
    # 生产环境返回通用错误消息，开发环境返回详细信息便于调试
    error_detail = str(exc) if settings.debug else "服务器内部错误"
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": error_detail, "code": "INTERNAL_ERROR"},
    )


# ============ API 路由 ============

@app.get("/")
async def root():
    """根路径: 优先重定向到前端界面,前端不存在时返回 API 信息"""
    frontend_path = Path(__file__).parent.parent / "frontend"
    if frontend_path.exists():
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/app/", status_code=302)
    return {
        "name": "DocFlow",
        "version": "1.2.0",
        "status": "running",
        "uptime": str(datetime.now() - SYSTEM_START_TIME),
    }


@app.get("/api/info")
async def api_info():
    """API 信息端点(原根路径功能)"""
    return {
        "name": "DocFlow",
        "version": "1.2.0",
        "status": "running",
        "uptime": str(datetime.now() - SYSTEM_START_TIME),
    }


@app.get("/api/health")
async def health_check():
    """I01: 健康检查，包含数据库连接检查"""
    db_ok = True
    try:
        ts.get_history_count()
    except Exception:
        db_ok = False
    status = "healthy" if db_ok else "degraded"
    return {
        "status": status,
        "timestamp": datetime.now().isoformat(),
        "database": "ok" if db_ok else "error",
    }


@app.get("/api/init")
async def init_token(request: Request):
    """S06: 返回认证 token

    当 CLAW_AUTH_TOKEN 为空时（公网部署/比赛演示），不启用认证，直接返回。
    当 CLAW_AUTH_TOKEN 非空时（本地桌面端），仅限 localhost 访问。
    """
    auth_token = settings.claw_auth_token
    # 未配置 token 时，不启用认证，任何来源都可以访问
    if not auth_token:
        return {"token": "", "auth_required": False}

    # 配置了 token 时，仅允许本机访问
    client_ip = request.client.host if request.client else "unknown"
    if client_ip not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="禁止访问")
    return {
        "token": auth_token,
        "auth_required": True,
    }


@app.get("/api/status")
async def system_status():
    # M02: 不返回内部文件系统绝对路径
    return {
        "status": "running",
        "start_time": SYSTEM_START_TIME.isoformat(),
        "uptime_seconds": (datetime.now() - SYSTEM_START_TIME).total_seconds(),
        "processed_count": ts.get_history_count(),
        "api_configured": bool(settings.paddleocr_api_key),
        "upload_dir": Path(settings.upload_dir).name,
        "output_dir": Path(settings.output_dir).name,
    }


@app.get("/api/config")
async def get_config():
    has_key = bool(settings.paddleocr_api_key)
    # S15: 不返回 API Key 前缀，仅返回是否已配置
    # M02: 不返回内部文件系统绝对路径，仅返回配置值
    return {
        "paddleocr_api_url": settings.paddleocr_api_url,
        "paddleocr_api_key": "********" if has_key else "",
        "paddleocr_model": settings.paddleocr_model,
        "api_key_configured": has_key,
        "host": settings.host,
        "port": settings.port,
        "upload_dir": Path(settings.upload_dir).name,
        "output_dir": Path(settings.output_dir).name,
        "max_upload_size_mb": settings.max_upload_size_mb,
        "log_level": settings.log_level,
        "poll_interval": settings.poll_interval,
        "poll_max_retries": settings.poll_max_retries,
        "rate_limit_requests": settings.rate_limit_requests,
        "rate_limit_window": settings.rate_limit_window,
    }


@app.post("/api/config")
async def update_config(config: ConfigUpdateRequest):
    """更新配置并持久化到 .env 文件
    使用 Pydantic 模型校验输入，仅允许白名单属性通过 setattr 写入。
    """
    # 安全白名单：仅允许这些字段通过 setattr 写入 Settings 对象
    ALLOWED_SETATTR_KEYS = frozenset({
        "paddleocr_api_url", "paddleocr_api_key", "paddleocr_model",
        "host", "port", "debug",
        "upload_dir", "output_dir", "log_dir",
        "max_upload_size_mb", "log_level",
        "poll_interval", "poll_max_retries",
        "rate_limit_requests", "rate_limit_window",
    })

    try:
        config_data = config.model_dump(exclude_unset=True)
        updated = []
        for key, value in config_data.items():
            if key not in ALLOWED_SETATTR_KEYS:
                logger.warning(f"拒绝写入非白名单属性: {key}")
                continue
            if not hasattr(settings, key):
                continue
            if key == "paddleocr_api_key" and not value:
                continue
            setattr(settings, key, value)
            updated.append(key)
            logger.info(f"配置更新: {key} = {'***' if 'key' in key else value}")

        # 将更新持久化写入 .env 文件
        save_env_file(config_data, ENV_FILE_PATH)

        # 如果 API 配置有变化，重新初始化 paddle_service
        if any(k in updated for k in ("paddleocr_api_url", "paddleocr_api_key", "paddleocr_model")):
            global paddle_service
            paddle_service = PaddleOCRService(
                api_url=settings.paddleocr_api_url,
                api_key=settings.paddleocr_api_key,
                model=settings.paddleocr_model,
            )
            logger.info("PaddleOCR 服务已重新初始化")

        # L24: 如果 log_level 有变化，立即更新所有 logger 级别
        if "log_level" in updated:
            update_log_level(settings.log_level)
            logger.info(f"日志级别已更新: {settings.log_level}")

        return {
            "success": True,
            "updated_fields": updated,
            "message": f"已更新 {len(updated)} 项配置",
        }
    except Exception as e:
        logger.error(f"配置更新失败: {e}")
        raise HTTPException(status_code=400, detail=str(e) if settings.debug else "配置更新失败")


@app.get("/api/test-paddleocr")
async def test_paddleocr_connection():
    """测试 PaddleOCR API 连接是否正常

    会向配置的 PaddleOCR API URL 发送一个轻量请求,验证:
    1. API URL 是否可达
    2. API Token 是否有效
    """
    if not settings.paddleocr_api_key:
        return {
            "success": False,
            "error": "API Token 未配置",
            "detail": "请在系统配置中设置 PaddleOCR API Key",
        }

    if not settings.paddleocr_api_url:
        return {
            "success": False,
            "error": "API URL 未配置",
            "detail": "请在系统配置中设置 PaddleOCR API URL",
        }

    import httpx
    try:
        headers = {"Authorization": f"Bearer {settings.paddleocr_api_key}"}
        # 发送一个空的 GET 请求测试连通性和认证
        # PaddleOCR API 对未认证请求返回 401,对认证请求返回 200 或 400(参数缺失)
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                response = await client.get(
                    settings.paddleocr_api_url.rstrip("/"),
                    headers=headers,
                )
                # 401/403 = Token 无效
                if response.status_code in (401, 403):
                    return {
                        "success": False,
                        "error": "API Token 无效或已过期",
                        "detail": f"服务器返回 {response.status_code}，请检查 Token 是否正确",
                    }
                # 5xx = 服务器内部错误，连接异常
                if response.status_code >= 500:
                    return {
                        "success": False,
                        "error": "API 服务器内部错误",
                        "detail": f"服务器返回 {response.status_code}，请稍后重试或检查 API 地址是否正确",
                    }
                # 200/400/404 = 服务器可达,Token 有效(400=参数缺失属正常)
                return {
                    "success": True,
                    "status_code": response.status_code,
                    "detail": "API 连接正常，Token 有效",
                }
            except httpx.ConnectError:
                return {
                    "success": False,
                    "error": "无法连接到 API 服务器",
                    "detail": f"请检查 API URL 是否正确: {settings.paddleocr_api_url}",
                }
            except httpx.TimeoutException:
                return {
                    "success": False,
                    "error": "API 请求超时",
                    "detail": "服务器响应超过 10 秒,请检查网络或更换 API 地址",
                }
    except Exception as e:
        logger.error(f"PaddleOCR API 测试失败: {e}")
        return {
            "success": False,
            "error": "测试失败",
            "detail": str(e) if settings.debug else "内部错误",
        }


@app.get("/api/history")
async def get_history(
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
):
    # I02: 支持 offset 分页参数
    # 性能优化：一次加锁同时获取数据和总数，避免两次锁竞争
    items, total = ts.get_history_with_count(limit, offset)
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": items,
    }


@app.delete("/api/history/{history_id}")
async def delete_history(history_id: str):
    if ts.delete_history(history_id):
        return {"success": True, "message": f"历史记录 {history_id} 已删除"}
    raise HTTPException(status_code=404, detail=f"历史记录 {history_id} 不存在")


@app.post("/api/history/batch-delete")
async def batch_delete_history(request: BatchDeleteRequest):
    # M01: 使用 Pydantic 模型替代 dict 参数
    history_ids = request.ids
    if not history_ids:
        raise HTTPException(status_code=400, detail="未提供要删除的记录 ID")
    deleted = ts.batch_delete_history(history_ids)
    return {"success": True, "deleted": deleted, "message": f"已删除 {deleted} 条记录"}


@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...)):
    """上传图片或 PDF 文件"""
    allowed_types = {"image/jpeg", "image/png", "image/bmp", "image/webp", "image/tiff", "application/pdf"}
    allowed_extensions = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".tif", ".pdf"}
    if file.content_type and file.content_type not in allowed_types:
        # 扩展名回退：某些客户端（如桌面端 httpx）可能发送 application/octet-stream，
        # 此时根据文件扩展名判断是否允许上传
        ext = _extract_safe_extension(file.filename).lower()
        if ext not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件类型: {file.content_type}。支持: JPEG, PNG, BMP, WebP, TIFF, PDF",
            )

    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)
    max_size = settings.max_upload_size_mb * 1024 * 1024
    if file_size > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"文件过大: {file_size / 1024 / 1024:.1f}MB。最大允许: {settings.max_upload_size_mb}MB",
        )

    try:
        upload_path = settings.get_upload_path()
        file_id = uuid.uuid4().hex
        # 安全提取扩展名：使用 _extract_safe_extension 防止路径穿越
        ext = _extract_safe_extension(file.filename)
        saved_name = f"{file_id}{ext}"
        saved_path = upload_path / saved_name

        content = await file.read()
        # I03: 校验文件头 Magic Bytes，防止伪装文件类型
        _check_magic_bytes(content)

        # B8: 同步文件写入 → asyncio.to_thread 避免阻塞事件循环
        def _write_file(path, data):
            with open(path, "wb") as f:
                f.write(data)
        await asyncio.to_thread(_write_file, saved_path, content)

        logger.info(f"文件上传成功: {file.filename} -> {saved_name} ({file_size / 1024:.1f}KB)")

        # M02: 不返回内部文件系统路径，仅返回 file_id
        return {
            "success": True,
            "file_id": file_id,
            "original_name": file.filename,
            "saved_name": saved_name,
            "size": file_size,
        }
    except Exception as e:
        logger.error(f"文件上传失败: {e}")
        error_detail = f"文件保存失败: {e}" if settings.debug else "文件保存失败"
        raise HTTPException(status_code=500, detail=error_detail)


# ============ 异步任务 API ============

@app.post("/api/submit/{file_id}")
async def submit_task(
    file_id: str,
    page_ranges: Optional[str] = Query(default=None, description="页码范围，如 2,4-6"),
    batch_id: Optional[str] = Query(default=None, description="批量ID，用于批量查询"),
):
    """
    提交 PaddleOCR 异步识别任务
    """
    # S01: 校验 file_id 格式，防止路径遍历攻击
    _validate_file_id(file_id)

    upload_path = settings.get_upload_path()
    matching_files = list(upload_path.glob(f"{file_id}.*"))
    if not matching_files:
        raise HTTPException(status_code=404, detail=f"文件不存在: {file_id}")

    file_path = matching_files[0]
    logger.info(f"提交异步任务: {file_path.name}")

    try:
        # 性能优化: 使用 asyncio.to_thread 避免同步文件读取阻塞事件循环
        def _read_file(path):
            with open(path, "rb") as f:
                return f.read()
        image_data = await asyncio.to_thread(_read_file, file_path)

        submit_result = await asyncio.wait_for(
            paddle_service.submit_task(
                image_data=image_data,
                filename=file_path.name,
                page_ranges=page_ranges,
                batch_id=batch_id,
            ),
            timeout=40.0,  # 硬超时：40 秒内必须返回
        )

        if not submit_result["success"]:
            raise HTTPException(status_code=500, detail=submit_result.get("error", "提交失败"))

        job_id = submit_result["job_id"]

        ts.set_task(job_id, {
            "file_id": file_id,
            "filename": file_path.name,
            "job_id": job_id,
            "status": "processing",
            "submit_time": datetime.now().isoformat(),
            "image_data": image_data,
            "batch_id": batch_id,
        })

        logger.info(f"任务已提交: file_id={file_id}, job_id={job_id}")
        return {
            "success": True,
            "task_id": job_id,
            "file_id": file_id,
            "filename": file_path.name,
            "status": "processing",
            "batch_id": batch_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"提交任务失败 [{file_id}]: {e}")
        error_detail = str(e) if settings.debug else "提交任务失败"
        raise HTTPException(status_code=500, detail=error_detail)


@app.post("/api/submit-url")
async def submit_task_by_url(request_data: SubmitTaskRequest):
    """通过文件 URL 提交 PaddleOCR 异步识别任务（无需先上传文件）"""
    file_url = request_data.fileUrl
    # S05: 校验 file_url，防止 SSRF 攻击
    _validate_file_url(file_url)

    filename = request_data.filename or "unknown"
    page_ranges = request_data.pageRanges
    batch_id = request_data.batchId

    # M30: 仅记录 URL 的域名和路径部分，不记录完整 URL（可能含敏感参数）
    try:
        _parsed = urlparse(file_url)
        _safe_url_log = f"{_parsed.scheme}://{_parsed.netloc}{_parsed.path}"
    except Exception:
        _safe_url_log = "[invalid_url]"
    logger.info(f"通过URL提交异步任务: {filename} url={_safe_url_log}")

    try:
        submit_result = await asyncio.wait_for(
            paddle_service.submit_task(
                filename=filename,
                file_url=file_url,
                page_ranges=page_ranges,
                batch_id=batch_id,
            ),
            timeout=40.0,
        )

        if not submit_result["success"]:
            raise HTTPException(status_code=500, detail=submit_result.get("error", "提交失败"))

        job_id = submit_result["job_id"]

        ts.set_task(job_id, {
            "file_id": None,
            "filename": filename,
            "job_id": job_id,
            "status": "processing",
            "submit_time": datetime.now().isoformat(),
            "image_data": None,
            "batch_id": batch_id,
        })

        logger.info(f"URL任务已提交: {filename}, job_id={job_id}")
        return {
            "success": True,
            "task_id": job_id,
            "filename": filename,
            "status": "processing",
            "batch_id": batch_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"URL提交失败 [{filename}]: {e}")
        error_detail = str(e) if settings.debug else "提交任务失败"
        raise HTTPException(status_code=500, detail=error_detail)


@app.get("/api/batch/{batch_id}")
async def get_batch_results(batch_id: str):
    """批量获取同一 batchId 下所有任务的结果"""
    try:
        batch_result = await paddle_service.batch_get_results(batch_id)
        if not batch_result["success"]:
            raise HTTPException(status_code=500, detail=batch_result.get("error", "批量查询失败"))

        return {
            "success": True,
            "batch_id": batch_id,
            "count": len(batch_result["results"]),
            "results": batch_result["results"],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量查询失败 batchId={batch_id}: {e}")
        error_detail = str(e) if settings.debug else "批量查询失败"
        raise HTTPException(status_code=500, detail=error_detail)


@app.post("/api/poll/{task_id}")
async def poll_task_result(task_id: str):
    """
    轮询 PaddleOCR 异步任务结果（单次查询，由前端循环驱动）。
    """
    task_info = ts.get_task(task_id)
    if task_info is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    # 如果已经完成/卡死/出错，直接返回缓存结果
    if task_info["status"] in ("done", "error", "stuck"):
        return {
            "task_id": task_id,
            "file_id": task_info["file_id"],
            "filename": task_info["filename"],
            "status": task_info["status"],
            "result": task_info.get("result"),
            "error": task_info.get("error"),
            "completed": True,
        }

    # 并发轮询互斥：防止同一 task_id 被多个请求同时处理
    # （避免 TOCTOU 竞态导致重复 add_history / 重复 save_report / 终态覆盖）
    if not ts.try_acquire_poll(task_id):
        return {
            "task_id": task_id,
            "file_id": task_info["file_id"],
            "filename": task_info["filename"],
            "status": "processing",
            "result": None,
            "completed": False,
            "progress": {"state": "polling", "message": "另一个轮询请求正在处理中"},
        }

    try:
        return await _poll_task_result_inner(task_id, task_info)
    finally:
        ts.release_poll(task_id)


async def _poll_task_result_inner(task_id: str, task_info: dict):
    """poll_task_result 的核心逻辑（已获取轮询互斥权）"""
    # 卡死检测参数
    STUCK_THRESHOLD = 15
    last_extracted = task_info.get("_last_extracted_pages", -1)
    no_progress_count = task_info.get("_no_progress_count", 0)

    try:
        # 总超时保护：poll_once 内部最坏情况（查询25s+下载JSON 55s+下载MD 55s=135s），
        # 设置 90 秒硬上限，防止前端 30s 超时后后端仍长时间占用 worker
        poll_status = await asyncio.wait_for(
            paddle_service.poll_once(task_id, task_info["filename"]),
            timeout=90.0,
        )
        status = poll_status.get("status")

        if status == "done":
            return await _handle_task_done(task_id, task_info, poll_status)

        elif status == "failed":
            task_info["status"] = "error"
            task_info["error"] = poll_status.get("error", "PaddleOCR 任务失败")
            logger.error(f"PaddleOCR 任务失败: task_id={task_id}, error={task_info['error']}")
            # S11: 写回修改后的副本
            ts.set_task(task_id, task_info)
            # S10: 任务失败后延迟清理 image_data
            ts.schedule_image_data_cleanup(task_id)
            return {
                "task_id": task_id,
                "file_id": task_info["file_id"],
                "filename": task_info["filename"],
                "status": "error",
                "error": task_info["error"],
                "completed": True,
            }

        elif status == "error":
            logger.warning(f"单次轮询异常: task_id={task_id}, error={poll_status.get('error')}")
            return {
                "task_id": task_id,
                "file_id": task_info["file_id"],
                "filename": task_info["filename"],
                "status": "processing",
                "result": None,
                "completed": False,
                "progress": {"state": "error", "message": poll_status.get("error")},
            }

        elif status in ("running", "pending"):
            return _handle_task_running(task_id, task_info, poll_status, status,
                                       last_extracted, no_progress_count, STUCK_THRESHOLD)

        else:
            logger.warning(f"未知轮询状态: task_id={task_id}, status={status}")
            return {
                "task_id": task_id,
                "file_id": task_info["file_id"],
                "filename": task_info["filename"],
                "status": "processing",
                "result": None,
                "completed": False,
                "progress": {"state": status or "unknown"},
            }

    except asyncio.TimeoutError:
        logger.warning(f"轮询总超时(90s): task_id={task_id}, 返回 processing 状态")
        return {
            "task_id": task_id,
            "file_id": task_info["file_id"],
            "filename": task_info["filename"],
            "status": "processing",
            "result": None,
            "completed": False,
            "progress": {"state": "timeout", "message": "轮询超时，将在下次重试"},
        }
    except Exception as e:
        exc_name = type(e).__name__
        task_info["status"] = "error"
        task_info["error"] = f"[{exc_name}] {e}"
        # 清理大字段防止内存泄漏（done 路径也会清理，此处为异常路径兜底）
        task_info.pop("image_data", None)
        task_info.pop("_last_extracted_pages", None)
        task_info.pop("_no_progress_count", None)
        # S11: 写回修改后的副本
        ts.set_task(task_id, task_info)
        logger.error(f"轮询任务异常: task_id={task_id}, [{exc_name}] {e}")
        return {
            "task_id": task_id,
            "file_id": task_info["file_id"],
            "filename": task_info["filename"],
            "status": "error",
            "error": str(e) if settings.debug else "轮询任务时发生错误",
            "completed": True,
        }


async def _handle_task_done(task_id: str, task_info: dict, poll_status: dict):
    """处理任务完成逻辑（从 poll_task_result 提取，降低复杂度）"""
    submit_time = datetime.fromisoformat(task_info["submit_time"])
    processing_time = round((datetime.now() - submit_time).total_seconds(), 2)

    extracted = paddle_service.extract_result(poll_status)

    json_text = poll_status.get("json_text", "")
    raw_json = poll_status.get("raw_json")
    structure_result = {
        "poll_data": poll_status.get("raw_result"),
        "raw_json": raw_json,
        "json_text_preview": json_text[:2000] if json_text else "",
    }

    report_dir = await markdown_generator.save_report(
        original_filename=task_info["filename"],
        markdown_text=extracted["markdown_text"],
        images=extracted["images"],
        layout_image_base64=extracted.get("layout_image"),
        layout_items=extracted.get("layout_items", []),
        original_image_data=task_info.get("image_data"),
        structure_result=structure_result,
        processing_time=processing_time,
    )

    layout_items = extracted.get("layout_items", [])
    # 性能优化: layout 报告和 JSON dump 互不依赖，并发写入减少延迟
    post_write_tasks = []

    if layout_items:
        post_write_tasks.append(
            asyncio.to_thread(
                markdown_generator.save_layout_report_standalone,
                report_dir=report_dir,
                original_filename=task_info["filename"],
                layout_items=layout_items,
                layout_image_base64=extracted.get("layout_image"),
                processing_time=processing_time,
            )
        )

    if json_text:
        json_dump_path = Path(report_dir) / "downloaded_result.json"
        def _write_json_dump(path: Path, text: str):
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        post_write_tasks.append(asyncio.to_thread(_write_json_dump, json_dump_path, json_text))

    if post_write_tasks:
        await asyncio.gather(*post_write_tasks)
        if json_text:
            logger.info(f"原始下载JSON已保存: {Path(report_dir) / 'downloaded_result.json'}")

    result_data = {
        "success": True,
        "markdown_text": extracted["markdown_text"],
        "images": extracted["images"],
        "images_count": len(extracted["images"]),
        "layout_items": extracted.get("layout_items", []),
        "layout_items_count": len(extracted.get("layout_items", [])),
        "layout_image_base64": extracted.get("layout_image"),
        "report_id": report_dir.name,
        "processing_time": processing_time,
        "total_pages": poll_status.get("total_pages", 0),
        "extracted_pages": poll_status.get("extracted_pages", 0),
    }

    task_info["status"] = "done"
    task_info["result"] = result_data
    task_info["complete_time"] = datetime.now().isoformat()
    task_info.pop("_last_extracted_pages", None)
    task_info.pop("_no_progress_count", None)
    task_info.pop("image_data", None)
    # S11: 写回修改后的副本
    ts.set_task(task_id, task_info)
    # S10: 任务完成后延迟清理 image_data（兜底，此处已手动清理）
    ts.schedule_image_data_cleanup(task_id)

    ts.add_history({
        "id": uuid.uuid4().hex[:16],
        "file_id": task_info["file_id"],
        "filename": task_info["filename"],
        "timestamp": datetime.now().isoformat(),
        "success": True,
        "processing_time": processing_time,
        "images_count": len(extracted["images"]),
        "markdown_length": len(extracted["markdown_text"]),
        "report_id": report_dir.name,
        "model": settings.paddleocr_model,
        "total_pages": poll_status.get("total_pages", 0),
    })

    logger.info(f"任务完成: task_id={task_id}, file={task_info['filename']}")
    return {
        "task_id": task_id,
        "file_id": task_info["file_id"],
        "filename": task_info["filename"],
        "status": "done",
        "result": result_data,
        "completed": True,
    }


def _handle_task_running(task_id: str, task_info: dict, poll_status: dict,
                         status: str, last_extracted: int,
                         no_progress_count: int, stuck_threshold: int):
    """处理运行中/待处理状态（含卡死检测）"""
    extracted = poll_status.get("extracted_pages", 0)
    total = poll_status.get("total_pages", 0)

    if status == "running" and extracted == last_extracted and total > 0:
        no_progress_count += 1
    else:
        no_progress_count = 0
        last_extracted = extracted

    task_info["_last_extracted_pages"] = last_extracted
    task_info["_no_progress_count"] = no_progress_count

    if no_progress_count >= stuck_threshold:
        msg = (
            f"任务疑似卡死: running {extracted}/{total} 页, "
            f"连续 {no_progress_count} 次无变化"
        )
        task_info["status"] = "stuck"
        task_info["error"] = msg
        task_info.pop("image_data", None)
        # S11: 写回修改后的副本
        ts.set_task(task_id, task_info)
        # S10: 任务卡死后延迟清理 image_data
        ts.schedule_image_data_cleanup(task_id)
        logger.warning(f"任务卡死: task_id={task_id}, {msg}")
        return {
            "task_id": task_id,
            "file_id": task_info["file_id"],
            "filename": task_info["filename"],
            "status": "stuck",
            "error": msg,
            "completed": True,
        }

    # S11: 写回运行状态更新（非终态也需要持久化进度）
    ts.set_task(task_id, task_info)
    return {
        "task_id": task_id,
        "file_id": task_info["file_id"],
        "filename": task_info["filename"],
        "status": "processing",
        "result": None,
        "completed": False,
        "progress": {
            "state": status,
            "extracted_pages": extracted,
            "total_pages": total,
            "attempt": task_info.get("_no_progress_count", 0),
        },
    }


@app.post("/api/process/{file_id}")
async def process_image(file_id: str):
    """处理图片（同步等待模式，兼容旧版）"""
    # S01: 校验 file_id 格式，防止路径遍历攻击
    _validate_file_id(file_id)

    upload_path = settings.get_upload_path()
    matching_files = list(upload_path.glob(f"{file_id}.*"))
    if not matching_files:
        raise HTTPException(status_code=404, detail=f"文件不存在: {file_id}")

    file_path = matching_files[0]
    logger.info(f"开始处理（同步模式）: {file_path.name}")

    try:
        # 性能优化: 使用 asyncio.to_thread 避免同步文件读取阻塞事件循环
        def _read_file_sync(path):
            with open(path, "rb") as f:
                return f.read()
        image_data = await asyncio.to_thread(_read_file_sync, file_path)

        # 总超时保护：submit_and_poll 内循环最多 600s，加 60s 余量
        result = await asyncio.wait_for(
            paddle_service.submit_and_poll(image_data, file_path.name),
            timeout=660.0,
        )

        if not result["success"]:
            raise Exception(result.get("error", "处理失败"))

        report_dir = await markdown_generator.save_report(
            original_filename=file_path.name,
            markdown_text=result["markdown_text"],
            images=result["images"],
            layout_image_base64=result.get("layout_image_base64"),
            layout_items=result.get("layout_items", []),
            original_image_data=image_data,
            structure_result=result.get("raw_result"),
            processing_time=result.get("processing_time", 0),
        )

        layout_items_sync = result.get("layout_items", [])
        if layout_items_sync:
            await asyncio.to_thread(
                markdown_generator.save_layout_report_standalone,
                report_dir=report_dir,
                original_filename=file_path.name,
                layout_items=layout_items_sync,
                layout_image_base64=result.get("layout_image_base64"),
                processing_time=result.get("processing_time", 0),
            )

        ts.add_history({
            "id": uuid.uuid4().hex[:16],
            "file_id": file_id,
            "filename": file_path.name,
            "timestamp": datetime.now().isoformat(),
            "success": True,
            "processing_time": result.get("processing_time", 0),
            "images_count": len(result.get("images", {})),
            "markdown_length": len(result.get("markdown_text", "")),
            "report_id": report_dir.name,
        })

        return {
            "success": True,
            "file_id": file_id,
            "processing_time": result.get("processing_time"),
            "markdown_text": result.get("markdown_text", ""),
            "images": result.get("images", {}),
            "images_count": len(result.get("images", {})),
            "layout_items": result.get("layout_items", []),
            "layout_items_count": len(result.get("layout_items", [])),
            "layout_image_base64": result.get("layout_image_base64"),
            "report_id": report_dir.name,
        }

    except Exception as e:
        logger.error(f"处理失败 [{file_id}]: {e}")
        ts.add_history({
            "id": uuid.uuid4().hex[:16],
            "file_id": file_id,
            "filename": file_path.name,
            "timestamp": datetime.now().isoformat(),
            "success": False,
            "processing_time": 0,
            "error": str(e),
        })
        error_detail = f"处理失败: {e}" if settings.debug else "处理失败"
        raise HTTPException(status_code=500, detail=error_detail)


@app.post("/api/upload/batch")
async def upload_images_batch(files: List[UploadFile] = File(...)):
    """批量上传图片文件"""
    if not files:
        raise HTTPException(status_code=400, detail="未选择任何文件")

    # 限制单次批量请求的文件数量，防止 DoS
    MAX_BATCH_FILES = 20
    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"批量上传文件数量不能超过 {MAX_BATCH_FILES} 个",
        )

    allowed_types = {"image/jpeg", "image/png", "image/bmp", "image/webp", "image/tiff", "application/pdf"}
    allowed_extensions = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".tif", ".pdf"}
    max_size = settings.max_upload_size_mb * 1024 * 1024
    upload_path = settings.get_upload_path()

    # 性能优化：并发处理文件上传，Semaphore 限制并发数避免内存压力
    _batch_semaphore = asyncio.Semaphore(4)

    async def _process_one_file(file: UploadFile) -> dict:
        async with _batch_semaphore:
            original_name = file.filename or "unknown"
            try:
                if file.content_type and file.content_type not in allowed_types:
                    # 扩展名回退：某些客户端（如桌面端 httpx）可能发送 application/octet-stream
                    ext = _extract_safe_extension(original_name).lower()
                    if ext not in allowed_extensions:
                        return {
                            "original_name": original_name,
                            "success": False,
                            "error": f"不支持的文件类型: {file.content_type}",
                        }

                # 安全修复：先用 seek/tell 取文件大小，避免把超大文件整读进内存
                # 与单文件端点 upload_image 保持一致
                file.file.seek(0, 2)
                file_size = file.file.tell()
                file.file.seek(0)
                if file_size > max_size:
                    return {
                        "original_name": original_name,
                        "success": False,
                        "error": f"文件过大: {file_size / 1024 / 1024:.1f}MB",
                    }

                content = await file.read()

                # I03: 校验文件头 Magic Bytes
                try:
                    _check_magic_bytes(content)
                except HTTPException as mb_err:
                    return {
                        "original_name": original_name,
                        "success": False,
                        "error": mb_err.detail,
                    }

                file_id = uuid.uuid4().hex
                # 安全提取扩展名：使用 _extract_safe_extension 防止路径穿越
                ext = _extract_safe_extension(original_name)
                saved_name = f"{file_id}{ext}"
                saved_path = upload_path / saved_name

                # B8: 同步文件写入 → asyncio.to_thread 避免阻塞事件循环
                def _write_batch_file(path, data):
                    with open(path, "wb") as f:
                        f.write(data)
                await asyncio.to_thread(_write_batch_file, saved_path, content)

                return {
                    "success": True,
                    "file_id": file_id,
                    "original_name": original_name,
                    "saved_name": saved_name,
                    "size": file_size,
                }

            except Exception as e:
                logger.error(f"批量上传中单个文件失败 [{original_name}]: {e}")
                # 安全修复：生产模式隐藏内部异常细节，与单文件端点保持一致
                error_detail = f"处理失败: {e}" if settings.debug else "处理失败"
                return {
                    "original_name": original_name,
                    "success": False,
                    "error": error_detail,
                }

    # 并发处理所有文件，gather 保证结果顺序与输入一致
    results = await asyncio.gather(*[_process_one_file(f) for f in files])

    succeeded = sum(1 for r in results if r["success"])
    logger.info(f"批量上传完成: {succeeded}/{len(files)} 成功")

    return {
        "total": len(files),
        "succeeded": succeeded,
        "failed": len(files) - succeeded,
        "results": results,
    }


@app.post("/api/upload-and-process")
async def upload_and_process(file: UploadFile = File(...)):
    """上传并立即处理（一步完成）"""
    upload_result = await upload_image(file)
    if not upload_result.get("success"):
        raise HTTPException(status_code=500, detail="上传失败")
    return await process_image(upload_result["file_id"])


@app.get("/api/reports")
async def list_reports(limit: int = Query(default=50, le=200)):
    """列出所有报告"""
    output_dir = settings.get_output_path()

    # B8: 同步目录遍历 → asyncio.to_thread 避免阻塞事件循环
    def _scan_reports(out_dir, max_count):
        result = []
        if out_dir.exists():
            for report_dir in sorted(out_dir.iterdir(), reverse=True):
                if report_dir.is_dir():
                    md_file = report_dir / "report.md"
                    result.append({
                        "id": report_dir.name,
                        "has_markdown": md_file.exists(),
                        "created_time": datetime.fromtimestamp(
                            report_dir.stat().st_ctime
                        ).isoformat(),
                    })
                    if len(result) >= max_count:
                        break
        return result

    reports = await asyncio.to_thread(_scan_reports, output_dir, limit)

    return {"total": len(reports), "reports": reports}


@app.get("/api/report/{report_id}")
async def get_report(report_id: str):
    """获取指定报告的 Markdown 内容"""
    report_dir = _safe_report_dir(report_id)
    md_file = report_dir / "report.md"

    if not md_file.exists():
        raise HTTPException(status_code=404, detail="报告不存在")

    # B8: 同步文件读取 → asyncio.to_thread 避免阻塞事件循环
    def _read_file(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    content = await asyncio.to_thread(_read_file, md_file)

    # M02: 不返回内部文件系统路径，仅返回 report_id
    return {"id": report_id, "content": content}


@app.get("/api/report/{report_id}/download")
async def download_report_zip(report_id: str):
    """下载报告的 ZIP 包"""
    report_dir = _safe_report_dir(report_id)
    md_file = report_dir / "report.md"

    if not md_file.exists():
        raise HTTPException(status_code=404, detail="报告不存在")

    # 性能优化: 将同步 ZIP 打包移到线程中，避免阻塞事件循环
    def _build_zip(r_dir, m_file):
        buf = io.BytesIO()
        included_files = []
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(m_file, "report.md")
            included_files.append("report.md")
            # 同级目录文件（layout_analysis.png, original.png, layout_report.md, api_response.json 等）
            for file_path in r_dir.iterdir():
                if file_path.is_file() and file_path.name != "report.md":
                    zf.write(file_path, file_path.name)
                    included_files.append(file_path.name)
            # imgs/ 子目录图片
            imgs_dir = r_dir / "imgs"
            if imgs_dir.exists():
                for file_path in imgs_dir.iterdir():
                    if file_path.is_file():
                        zf.write(file_path, f"imgs/{file_path.name}")
                        included_files.append(f"imgs/{file_path.name}")
            else:
                logger.warning(f"报告 {report_id} 的 imgs/ 目录不存在，ZIP 将不包含图片")
        buf.seek(0)
        logger.info(f"报告 {report_id} ZIP 打包完成，包含 {len(included_files)} 个文件: {included_files}")
        return buf

    zip_buffer = await asyncio.to_thread(_build_zip, report_dir, md_file)
    # L22: 使用 urllib.parse.quote 编码 ZIP 文件名，支持非 ASCII 字符
    encoded_filename = quote(f"report_{report_id}.zip")
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"report_{report_id}.zip\"; "
                f"filename*=UTF-8''{encoded_filename}"
            )
        },
    )


@app.post("/api/batch/download")
async def download_batch_zip(request_data: BatchDownloadRequest):
    """批量下载所有报告的 ZIP 包"""
    # M01: 使用 Pydantic 模型替代 dict 参数
    report_ids = request_data.report_ids
    if not report_ids:
        raise HTTPException(status_code=400, detail="未提供报告ID列表")

    # M10: 限制最大报告数量为 20，超过则返回 400
    MAX_BATCH_DOWNLOAD = 20
    if len(report_ids) > MAX_BATCH_DOWNLOAD:
        raise HTTPException(
            status_code=400,
            detail=f"批量下载数量不能超过 {MAX_BATCH_DOWNLOAD} 个报告",
        )

    # 过滤掉格式非法的 report_id（路径穿越、Shell 元字符等）
    # 若全部 ID 均非法，返回 400；若部分非法，仅打包合法的
    valid_ids = [rid for rid in report_ids if _is_valid_report_id_format(rid)]
    if not valid_ids:
        raise HTTPException(
            status_code=400,
            detail="所有报告 ID 格式均非法",
        )
    if len(valid_ids) < len(report_ids):
        skipped = len(report_ids) - len(valid_ids)
        logger.warning(f"批量下载: 已跳过 {skipped} 个格式非法的报告 ID")

    # 性能优化: 将同步 ZIP 打包移到线程中，避免阻塞事件循环
    def _build_batch_zip(r_ids):
        buf = io.BytesIO()
        image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for rid in r_ids:
                # 安全修复：_safe_report_dir 可能因"同名普通文件"等场景抛 HTTPException，
                # 用 try/except 包裹并跳过该条目，与 batch_delete_reports 行为一致
                try:
                    r_dir = _safe_report_dir(rid)
                except HTTPException as e:
                    logger.warning(f"批量下载: 跳过无效报告 ID {rid}: {e.detail}")
                    continue
                if not r_dir.exists():
                    logger.warning(f"批量下载: 报告目录不存在 {rid}")
                    continue
                for file_path in r_dir.iterdir():
                    if file_path.is_file() and file_path.suffix.lower() in image_exts:
                        zf.write(file_path, f"{rid}/{file_path.name}")
                    elif file_path.is_file() and file_path.name != "report.md":
                        zf.write(file_path, f"{rid}/{file_path.name}")
                md_file = r_dir / "report.md"
                if md_file.exists():
                    zf.write(md_file, f"{rid}/report.md")
                imgs_dir = r_dir / "imgs"
                if imgs_dir.exists():
                    for file_path in imgs_dir.iterdir():
                        if file_path.is_file() and file_path.suffix.lower() in image_exts:
                            zf.write(file_path, f"{rid}/imgs/{file_path.name}")
        buf.seek(0)
        return buf

    zip_buffer = await asyncio.to_thread(_build_batch_zip, valid_ids)
    logger.info(f"批量下载: {len(valid_ids)} 个报告已打包")
    # L22: 使用 urllib.parse.quote 编码 ZIP 文件名
    encoded_batch_filename = quote("batch_reports.zip")
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="batch_reports.zip"; '
                f"filename*=UTF-8''{encoded_batch_filename}"
            )
        },
    )


@app.post("/api/batch/download-layout")
async def download_batch_layout_report(request_data: BatchLayoutRequest):
    """批量版面分析聚合报告"""
    # M01: 使用 Pydantic 模型替代 dict 参数
    files = request_data.files
    if not files:
        raise HTTPException(status_code=400, detail="未提供文件数据")

    now = datetime.now()
    # QA修复: Pydantic v2 BaseModel 没有 .get() 方法，使用属性访问
    total_items = sum(len(f.layout_items) for f in files)

    lines = []
    lines.append("# 批量版面分析报告")
    lines.append("")
    lines.append("| 属性 | 值 |")
    lines.append("|------|-----|")
    lines.append(f"| **生成时间** | {now.strftime('%Y-%m-%d %H:%M:%S')} |")
    lines.append(f"| **文件总数** | {len(files)} |")
    lines.append(f"| **版面区域总数** | {total_items} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    for file_idx, file_data in enumerate(files, 1):
        filename = file_data.filename or f"文件{file_idx}"
        layout_items = file_data.layout_items
        processing_time = file_data.processing_time

        # M31: 转义文件名中的 Markdown 特殊字符
        safe_filename = filename
        if safe_filename:
            safe_filename = safe_filename.replace("|", "\\|")
            safe_filename = safe_filename.replace("`", "\\`")
            safe_filename = safe_filename.replace("<", "&lt;")
            safe_filename = safe_filename.replace(">", "&gt;")

        lines.append(f"## {file_idx}. {safe_filename}")
        lines.append("")
        lines.append("| 属性 | 值 |")
        lines.append("|------|-----|")
        lines.append(f"| **版面区域** | {len(layout_items)} 个 |")
        lines.append(f"| **处理耗时** | {processing_time}s |")
        lines.append("")

        if layout_items:
            lines.append("| 序号 | 类型 | 区域坐标 | 内容预览 |")
            lines.append("|------|------|----------|----------|")
            for idx, item in enumerate(layout_items, 1):
                item_type = item.get("type", "unknown")
                # B4: 转义 item_type 中的 Markdown/XSS 特殊字符（与 filename 转义一致）
                item_type = str(item_type).replace("|", "\\|").replace("`", "\\`").replace("<", "&lt;").replace(">", "&gt;")
                region = item.get("region", {})
                region_str = ""
                if region:
                    bbox = region.get("bbox", [])
                    if isinstance(bbox, list) and len(bbox) >= 4:
                        region_str = f"({bbox[0]}, {bbox[1]}, {bbox[2]}, {bbox[3]})"
                    else:
                        x = region.get("x", "")
                        y = region.get("y", "")
                        w = region.get("width", "")
                        h = region.get("height", "")
                        if x != "" and y != "":
                            region_str = f"({x}, {y}, {w}, {h})"
                preview = item.get("content_preview", "")
                if preview:
                    preview = str(preview).replace("|", "\\|").replace("\n", " ")
                    # B4: 转义 content_preview 中的 XSS 特殊字符（与 filename 转义一致）
                    preview = preview.replace("`", "\\`").replace("<", "&lt;").replace(">", "&gt;")
                    if len(preview) > 80:
                        preview = preview[:80] + "..."
                else:
                    preview = "(无文字内容)"
                lines.append(f"| {idx} | **{item_type}** | {region_str} | {preview} |")
            lines.append("")
        else:
            lines.append("*（该文件未检测到版面区域）*")
            lines.append("")

        lines.append("---")
        lines.append("")

    lines.append("*本文档由 DocFlow 自动生成 - 批量版面分析报告*")
    report_content = "\n".join(lines)
    logger.info(f"批量版面分析报告: {len(files)} 个文件, {total_items} 个版面区域")

    return Response(
        content=report_content.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="batch_layout_report.md"'},
    )


@app.get("/api/report/{report_id}/image/{image_name:path}")
async def get_report_image(report_id: str, image_name: str):
    """获取报告中的图片文件"""
    report_dir = _safe_report_dir(report_id)
    img_path = _safe_report_image_path(report_dir, image_name)

    if not img_path.exists():
        raise HTTPException(status_code=404, detail="图片不存在")

    content_type_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
    }
    suffix = img_path.suffix.lower()
    media_type = content_type_map.get(suffix, "application/octet-stream")

    return FileResponse(img_path, media_type=media_type)


@app.delete("/api/report/{report_id}")
async def delete_report(report_id: str):
    """删除指定报告"""
    report_dir = _safe_report_dir(report_id)
    # S02: 额外校验 report_dir 必须在 settings.get_output_path() 内
    output_dir = settings.get_output_path().resolve()
    try:
        report_dir.resolve().relative_to(output_dir)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"无效的报告 ID: {report_id}（不在输出目录内）",
        )

    try:
        # 性能优化: 使用 asyncio.to_thread 避免同步 rmtree 阻塞事件循环
        await asyncio.to_thread(shutil.rmtree, report_dir)
        logger.info(f"报告已删除: {report_id}")
        return {"success": True, "message": f"报告 {report_id} 已删除"}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="报告不存在")
    except Exception as e:
        logger.error(f"删除报告失败: {e}")
        error_detail = str(e) if settings.debug else "删除报告失败"
        raise HTTPException(status_code=500, detail=error_detail)


@app.post("/api/reports/batch-delete")
async def batch_delete_reports(request: BatchDeleteRequest):
    """批量删除报告（并行执行）"""
    # M01: 使用 Pydantic 模型替代 dict 参数
    report_ids = request.ids
    if not report_ids:
        raise HTTPException(status_code=400, detail="未提供要删除的报告 ID")

    # 安全校验：过滤掉路径遍历的 ID，同时缓存已校验的目录路径避免重复校验
    safe_entries = []  # [(rid, report_dir), ...]
    for rid in report_ids:
        try:
            report_dir = _safe_report_dir(rid)
            safe_entries.append((rid, report_dir))
        except Exception:
            continue

    if not safe_entries:
        raise HTTPException(status_code=400, detail="没有有效的报告 ID")

    async def _delete_one(rid: str, report_dir: Path) -> dict:
        try:
            # M32: 使用 asyncio.to_thread 替代弃用的 get_event_loop().run_in_executor
            await asyncio.to_thread(
                lambda d=report_dir: shutil.rmtree(d)
            )
            logger.info(f"报告已删除: {rid}")
            return {"id": rid, "success": True}
        except FileNotFoundError:
            return {"id": rid, "success": False, "error": "报告不存在"}
        except Exception as e:
            logger.error(f"删除报告失败 [{rid}]: {e}")
            error_msg = str(e) if settings.debug else "删除失败"
            return {"id": rid, "success": False, "error": error_msg}

    # 并行执行删除
    results = await asyncio.gather(*[_delete_one(rid, rdir) for rid, rdir in safe_entries])
    deleted_count = sum(1 for r in results if r["success"])
    failed_count = len(results) - deleted_count

    return {
        "success": True,
        "total": len(safe_entries),
        "deleted": deleted_count,
        "failed": failed_count,
        "results": results,
        "message": f"已删除 {deleted_count} 个报告，失败 {failed_count} 个"
    }


# ============ 静态文件服务 ============

frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/app", StaticFiles(directory=str(frontend_path), html=True), name="frontend")
    logger.info(f"前端静态文件已挂载: {frontend_path}")


# ============ 启动入口 ============

if __name__ == "__main__":
    logger.info("DocFlow 启动中...")
    logger.info(f"  - Host: {settings.host}:{settings.port}")
    logger.info(f"  - Upload Dir: {settings.get_upload_path()}")
    logger.info(f"  - Output Dir: {settings.get_output_path()}")
    logger.info(f"  - API Key: {'已配置' if settings.paddleocr_api_key else '未配置'}")

    uvicorn.run(
        "apps.web.api.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
