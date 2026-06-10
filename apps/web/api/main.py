"""
错题管理系统 - FastAPI 后端主服务

支持的 OCR 模型:
  - PaddleOCR-VL-1.5 / PaddleOCR-VL（文档结构化分析，推荐）
  - PP-StructureV3（文档结构化分析）
  - PP-OCRv5（文字识别）

处理流程: 上传 → PaddleOCR API 异步识别 → 轮询结果 → 保存结构化 Markdown

参考文档: https://ai.baidu.com/ai-doc/AISTUDIO/fml7mozw5
"""
import io
import uuid
import shutil
import zipfile
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
import uvicorn

from apps.web.api.config import settings, ENV_FILE_PATH
from apps.web.api.logger import setup_logger
from apps.web.api.paddle_service import PaddleOCRService
from apps.web.api.markdown_generator import MarkdownGenerator
from apps.web.api.services.task_service import task_service as ts
from apps.web.api.services.config_service import save_env_file

logger = setup_logger("MainServer")

# 初始化 FastAPI 应用
app = FastAPI(
    title="错题管理系统",
    description="基于 PaddleOCR PP-StructureV3 的智能错题识别与管理系统",
    version="1.2.0",
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化服务
paddle_service = PaddleOCRService(
    api_url=settings.paddleocr_api_url,
    api_key=settings.paddleocr_api_key,
    model=settings.paddleocr_model,
)
markdown_generator = MarkdownGenerator(output_dir=settings.get_output_path())

SYSTEM_START_TIME = datetime.now()


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
    """全局未知异常处理器"""
    logger.error(f"未处理异常 [{request.method} {request.url.path}]: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": str(exc), "code": "INTERNAL_ERROR"},
    )


# ============ API 路由 ============

@app.get("/")
async def root():
    return {
        "name": "错题管理系统",
        "version": "1.2.0",
        "status": "running",
        "uptime": str(datetime.now() - SYSTEM_START_TIME),
    }


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.get("/api/status")
async def system_status():
    return {
        "status": "running",
        "start_time": SYSTEM_START_TIME.isoformat(),
        "uptime_seconds": (datetime.now() - SYSTEM_START_TIME).total_seconds(),
        "processed_count": ts.get_history_count(),
        "api_configured": bool(settings.paddleocr_api_key),
        "upload_dir": str(settings.get_upload_path()),
        "output_dir": str(settings.get_output_path()),
    }


@app.get("/api/config")
async def get_config():
    return {
        "paddleocr_api_url": settings.paddleocr_api_url,
        "paddleocr_model": settings.paddleocr_model,
        "api_key_configured": bool(settings.paddleocr_api_key),
        "api_key_prefix": settings.paddleocr_api_key[:8] + "***" if settings.paddleocr_api_key else "",
        "host": settings.host,
        "port": settings.port,
        "upload_dir": settings.upload_dir,
        "output_dir": settings.output_dir,
        "max_upload_size_mb": settings.max_upload_size_mb,
        "log_level": settings.log_level,
    }


@app.post("/api/config")
async def update_config(config_data: dict):
    """更新配置并持久化到 .env 文件"""
    try:
        updated = []
        for key, value in config_data.items():
            if hasattr(settings, key):
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

        return {
            "success": True,
            "updated_fields": updated,
            "message": f"已更新 {len(updated)} 项配置",
        }
    except Exception as e:
        logger.error(f"配置更新失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/history")
async def get_history(limit: int = Query(default=50, le=200)):
    items = ts.get_history(limit)
    return {
        "total": ts.get_history_count(),
        "items": items,
    }


@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...)):
    """上传图片文件"""
    allowed_types = {"image/jpeg", "image/png", "image/bmp", "image/webp", "image/tiff"}
    if file.content_type and file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {file.content_type}。支持: JPEG, PNG, BMP, WebP, TIFF",
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
        ext = Path(file.filename).suffix if file.filename else ".png"
        saved_name = f"{file_id}{ext}"
        saved_path = upload_path / saved_name

        content = await file.read()
        with open(saved_path, "wb") as f:
            f.write(content)

        logger.info(f"文件上传成功: {file.filename} -> {saved_name} ({file_size / 1024:.1f}KB)")

        return {
            "success": True,
            "file_id": file_id,
            "original_name": file.filename,
            "saved_name": saved_name,
            "size": file_size,
            "path": str(saved_path),
        }
    except Exception as e:
        logger.error(f"文件上传失败: {e}")
        raise HTTPException(status_code=500, detail=f"文件保存失败: {str(e)}")


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
    upload_path = settings.get_upload_path()
    matching_files = list(upload_path.glob(f"{file_id}.*"))
    if not matching_files:
        raise HTTPException(status_code=404, detail=f"文件不存在: {file_id}")

    file_path = matching_files[0]
    logger.info(f"提交异步任务: {file_path.name}")

    try:
        with open(file_path, "rb") as f:
            image_data = f.read()

        submit_result = await paddle_service.submit_task(
            image_data=image_data,
            filename=file_path.name,
            page_ranges=page_ranges,
            batch_id=batch_id,
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
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/submit-url")
async def submit_task_by_url(request_data: dict):
    """通过文件 URL 提交 PaddleOCR 异步识别任务（无需先上传文件）"""
    file_url = request_data.get("fileUrl")
    if not file_url:
        raise HTTPException(status_code=400, detail="fileUrl 参数必填")

    filename = request_data.get("filename", "unknown")
    page_ranges = request_data.get("pageRanges")
    batch_id = request_data.get("batchId")

    logger.info(f"通过URL提交异步任务: {filename} url={file_url}")

    try:
        submit_result = await paddle_service.submit_task(
            filename=filename,
            file_url=file_url,
            page_ranges=page_ranges,
            batch_id=batch_id,
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
        raise HTTPException(status_code=500, detail=str(e))


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
        raise HTTPException(status_code=500, detail=str(e))


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

    # 卡死检测参数
    STUCK_THRESHOLD = 15
    last_extracted = task_info.get("_last_extracted_pages", -1)
    no_progress_count = task_info.get("_no_progress_count", 0)

    try:
        poll_status = await paddle_service.poll_once(task_id, task_info["filename"])
        status = poll_status.get("status")

        if status == "done":
            return await _handle_task_done(task_id, task_info, poll_status)

        elif status == "failed":
            task_info["status"] = "error"
            task_info["error"] = poll_status.get("error", "PaddleOCR 任务失败")
            logger.error(f"PaddleOCR 任务失败: task_id={task_id}, error={task_info['error']}")
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

    except Exception as e:
        exc_name = type(e).__name__
        task_info["status"] = "error"
        task_info["error"] = f"[{exc_name}] {e}"
        logger.error(f"轮询任务异常: task_id={task_id}, [{exc_name}] {e}")
        return {
            "task_id": task_id,
            "file_id": task_info["file_id"],
            "filename": task_info["filename"],
            "status": "error",
            "error": str(e),
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

    report_dir = markdown_generator.save_report(
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
    if layout_items:
        markdown_generator.save_layout_report_standalone(
            report_dir=report_dir,
            original_filename=task_info["filename"],
            layout_items=layout_items,
            layout_image_base64=extracted.get("layout_image"),
            processing_time=processing_time,
        )

    if json_text:
        json_dump_path = Path(report_dir) / "downloaded_result.json"
        with open(json_dump_path, "w", encoding="utf-8") as f:
            f.write(json_text)
        logger.info(f"原始下载JSON已保存: {json_dump_path}")

    result_data = {
        "success": True,
        "markdown_text": extracted["markdown_text"],
        "images": extracted["images"],
        "images_count": len(extracted["images"]),
        "layout_items": extracted.get("layout_items", []),
        "layout_items_count": len(extracted.get("layout_items", [])),
        "layout_image_base64": extracted.get("layout_image"),
        "report_dir": str(report_dir),
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

    ts.add_history({
        "id": uuid.uuid4().hex[:8],
        "file_id": task_info["file_id"],
        "filename": task_info["filename"],
        "timestamp": datetime.now().isoformat(),
        "success": True,
        "processing_time": processing_time,
        "images_count": len(extracted["images"]),
        "markdown_length": len(extracted["markdown_text"]),
        "report_dir": str(report_dir),
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
        logger.warning(f"任务卡死: task_id={task_id}, {msg}")
        return {
            "task_id": task_id,
            "file_id": task_info["file_id"],
            "filename": task_info["filename"],
            "status": "stuck",
            "error": msg,
            "completed": True,
        }

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
    upload_path = settings.get_upload_path()
    matching_files = list(upload_path.glob(f"{file_id}.*"))
    if not matching_files:
        raise HTTPException(status_code=404, detail=f"文件不存在: {file_id}")

    file_path = matching_files[0]
    logger.info(f"开始处理（同步模式）: {file_path.name}")

    try:
        with open(file_path, "rb") as f:
            image_data = f.read()

        result = await paddle_service.submit_and_poll(image_data, file_path.name)

        if not result["success"]:
            raise Exception(result.get("error", "处理失败"))

        report_dir = markdown_generator.save_report(
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
            markdown_generator.save_layout_report_standalone(
                report_dir=report_dir,
                original_filename=file_path.name,
                layout_items=layout_items_sync,
                layout_image_base64=result.get("layout_image_base64"),
                processing_time=result.get("processing_time", 0),
            )

        ts.add_history({
            "id": uuid.uuid4().hex[:8],
            "file_id": file_id,
            "filename": file_path.name,
            "timestamp": datetime.now().isoformat(),
            "success": True,
            "processing_time": result.get("processing_time", 0),
            "images_count": len(result.get("images", {})),
            "markdown_length": len(result.get("markdown_text", "")),
            "report_dir": str(report_dir),
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
            "report_dir": str(report_dir),
        }

    except Exception as e:
        logger.error(f"处理失败 [{file_id}]: {e}")
        ts.add_history({
            "id": uuid.uuid4().hex[:8],
            "file_id": file_id,
            "filename": file_path.name,
            "timestamp": datetime.now().isoformat(),
            "success": False,
            "processing_time": 0,
            "error": str(e),
        })
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")


@app.post("/api/upload/batch")
async def upload_images_batch(files: List[UploadFile] = File(...)):
    """批量上传图片文件"""
    if not files:
        raise HTTPException(status_code=400, detail="未选择任何文件")

    results = []
    allowed_types = {"image/jpeg", "image/png", "image/bmp", "image/webp", "image/tiff"}
    max_size = settings.max_upload_size_mb * 1024 * 1024

    for file in files:
        try:
            if file.content_type and file.content_type not in allowed_types:
                results.append({
                    "original_name": file.filename,
                    "success": False,
                    "error": f"不支持的文件类型: {file.content_type}",
                })
                continue

            content = await file.read()
            if len(content) > max_size:
                results.append({
                    "original_name": file.filename,
                    "success": False,
                    "error": f"文件过大: {len(content) / 1024 / 1024:.1f}MB",
                })
                continue

            upload_path = settings.get_upload_path()
            file_id = uuid.uuid4().hex
            ext = Path(file.filename).suffix if file.filename else ".png"
            saved_name = f"{file_id}{ext}"
            saved_path = upload_path / saved_name

            with open(saved_path, "wb") as f:
                f.write(content)

            results.append({
                "success": True,
                "file_id": file_id,
                "original_name": file.filename,
                "saved_name": saved_name,
                "size": len(content),
            })

        except Exception as e:
            logger.error(f"批量上传中单个文件失败 [{file.filename}]: {e}")
            results.append({
                "original_name": file.filename,
                "success": False,
                "error": str(e),
            })

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
    reports = []

    if output_dir.exists():
        for report_dir in sorted(output_dir.iterdir(), reverse=True):
            if report_dir.is_dir():
                md_file = report_dir / "report.md"
                reports.append({
                    "id": report_dir.name,
                    "path": str(report_dir),
                    "has_markdown": md_file.exists(),
                    "created_time": datetime.fromtimestamp(
                        report_dir.stat().st_ctime
                    ).isoformat(),
                })
                if len(reports) >= limit:
                    break

    return {"total": len(reports), "reports": reports}


@app.get("/api/report/{report_id}")
async def get_report(report_id: str):
    """获取指定报告的 Markdown 内容"""
    report_dir = settings.get_output_path() / report_id
    md_file = report_dir / "report.md"

    if not md_file.exists():
        raise HTTPException(status_code=404, detail="报告不存在")

    with open(md_file, "r", encoding="utf-8") as f:
        content = f.read()

    return {"id": report_id, "content": content, "path": str(report_dir)}


@app.get("/api/report/{report_id}/download")
async def download_report_zip(report_id: str):
    """下载报告的 ZIP 包"""
    report_dir = settings.get_output_path() / report_id
    md_file = report_dir / "report.md"

    if not md_file.exists():
        raise HTTPException(status_code=404, detail="报告不存在")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(md_file, "report.md")
        image_extensions = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
        for file_path in report_dir.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in image_extensions:
                zf.write(file_path, file_path.name)

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="report_{report_id}.zip"'},
    )


@app.post("/api/batch/download")
async def download_batch_zip(request_data: dict):
    """批量下载所有报告的 ZIP 包"""
    report_ids = request_data.get("report_ids", [])
    if not report_ids:
        raise HTTPException(status_code=400, detail="未提供报告ID列表")

    output_root = settings.get_output_path()
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for report_id in report_ids:
            report_dir = output_root / report_id
            if not report_dir.exists():
                logger.warning(f"批量下载: 报告目录不存在 {report_id}")
                continue
            for file_path in report_dir.iterdir():
                if file_path.is_file():
                    zf.write(file_path, f"{report_id}/{file_path.name}")

    zip_buffer.seek(0)
    logger.info(f"批量下载: {len(report_ids)} 个报告已打包")
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="batch_reports.zip"'},
    )


@app.post("/api/batch/download-layout")
async def download_batch_layout_report(request_data: dict):
    """批量版面分析聚合报告"""
    files = request_data.get("files", [])
    if not files:
        raise HTTPException(status_code=400, detail="未提供文件数据")

    now = datetime.now()
    total_items = sum(len(f.get("layout_items", [])) for f in files)

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
        filename = file_data.get("filename", f"文件{file_idx}")
        layout_items = file_data.get("layout_items", [])
        processing_time = file_data.get("processing_time", 0)

        lines.append(f"## {file_idx}. {filename}")
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

    lines.append("*本文档由错题管理系统自动生成 - 批量版面分析报告*")
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
    report_dir = settings.get_output_path() / report_id
    img_path = report_dir / image_name

    if not img_path.exists():
        raise HTTPException(status_code=404, detail="图片不存在")

    content_type_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    suffix = img_path.suffix.lower()
    media_type = content_type_map.get(suffix, "application/octet-stream")

    return FileResponse(img_path, media_type=media_type)


@app.delete("/api/report/{report_id}")
async def delete_report(report_id: str):
    """删除指定报告"""
    report_dir = settings.get_output_path() / report_id
    if not report_dir.exists():
        raise HTTPException(status_code=404, detail="报告不存在")

    try:
        shutil.rmtree(report_dir)
        logger.info(f"报告已删除: {report_id}")
        return {"success": True, "message": f"报告 {report_id} 已删除"}
    except Exception as e:
        logger.error(f"删除报告失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============ 静态文件服务 ============

frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/app", StaticFiles(directory=str(frontend_path), html=True), name="frontend")
    logger.info(f"前端静态文件已挂载: {frontend_path}")


# ============ 启动入口 ============

if __name__ == "__main__":
    logger.info("错题管理系统启动中...")
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
