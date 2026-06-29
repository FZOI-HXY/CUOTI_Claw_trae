"""
PaddleOCR API 服务 — 标准库版（零第三方依赖，用于 PyInstaller 打包）

与 apps/web/api/paddle_service.py 功能完全一致，唯一区别：
  - 使用 urllib.request（标准库）替代 httpx
  - 所有 HTTP 调用通过 asyncio.to_thread() 封装为异步
  - 无需安装 httpx / httpcore / h2 / anyio 等依赖

官方API流程:
  1. POST multipart/form-data 提交本地文件（或 fileUrl）到 /api/v2/ocr/jobs，获取 jobId
  2. GET /api/v2/ocr/jobs/{jobId} 轮询任务状态
  3. state=done 后，从 resultUrl.jsonUrl 下载 JSONL / markdownUrl 下载 Markdown

参考文档: https://ai.baidu.com/ai-doc/AISTUDIO/fml7mozw5
"""
import asyncio
import json
import time
import io
import uuid
import urllib.request
import urllib.error
import socket
from typing import Optional, Dict, Any

from apps.web.api.logger import setup_logger
from apps.web.api.config import settings
from apps.web.api.services.paddle_parser import extract_ocr_result

logger = setup_logger("PaddleOCRService")

# 模型分组
VL_MODELS = {"PaddleOCR-VL-1.6", "PaddleOCR-VL-1.5", "PaddleOCR-VL"}
STRUCTURE_MODELS = {"PP-StructureV3"}
OCR_MODELS = {"PP-OCRv6", "PP-OCRv5", "PP-OCRv4"}

# API 错误码映射（参考百度AI Studio异步API文档）
ERROR_CODE_MAP = {
    401: "Token无效，请检查 access_token",
    10001: "空文件，请检查文件内容",
    10002: "文件URL无法识别，请检查URL有效性",
    10003: "文件大小超限（本地文件≤50MB，文件链接≤200MB）",
    10004: "文件格式不支持，请检查文件类型",
    10005: "文件内容无法解析",
    10006: "文件页数超过限制（单次≤1000页）",
    10007: "模型参数错误，请检查模型名称",
    10008: "请求参数错误，请检查 optionalPayload",
    10009: "同一 batchId 任务数超限（≤100条）",
    10010: "任务队列已满，请稍后重试",
    11001: "jobId 不存在，请检查 jobId",
    11002: "job 已过期，请重新提交",
    12001: "每日页数上限，请查看配额说明",
    12002: "请求频率过高，请降低频率",
}

# ---------------------------------------------------------------------------
# 超时配置（秒）
# ---------------------------------------------------------------------------
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 30.0
SUBMIT_READ_TIMEOUT = 60.0     # 文件上传允许更长的服务端处理时间
DOWNLOAD_READ_TIMEOUT = 45.0


class PaddleOCRService:
    """PaddleOCR API 服务封装 — 标准库版"""

    DEFAULT_TOKEN = ""  # 不再提供默认值；须由用户通过配置或环境变量设置

    def __init__(self, api_url: str = "", api_key: str = "", model: str = "PaddleOCR-VL-1.6"):
        self.job_url = api_url.rstrip("/")
        self.token = api_key
        self.model = model

    @property
    def is_configured(self) -> bool:
        """检查 API Token 是否已配置"""
        return bool(self.token and self.token.strip())

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _build_headers(self, content_type: Optional[str] = None) -> Dict[str, str]:
        headers = {"Authorization": f"bearer {self.token}"}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _get_optional_payload(self) -> Dict[str, Any]:
        if self.model in VL_MODELS or self.model in STRUCTURE_MODELS:
            return {
                "useDocOrientationClassify": False,
                "useDocUnwarping": False,
                "useChartRecognition": False,
            }
        else:
            return {
                "useDocOrientationClassify": False,
                "useDocUnwarping": False,
                "useTextlineOrientation": False,
            }

    def _get_result_field_name(self) -> str:
        if self.model in VL_MODELS or self.model in STRUCTURE_MODELS:
            return "layoutParsingResults"
        else:
            return "ocrResults"

    def _parse_error(self, result: Dict[str, Any]) -> str:
        code = result.get("code")
        if code and code in ERROR_CODE_MAP:
            return f"[{code}] {ERROR_CODE_MAP[code]}"
        return result.get("errorMsg") or result.get("message") or f"未知错误 (code={code})"

    # ------------------------------------------------------------------
    # 标准库 HTTP 封装（同步 → 异步桥接）
    # ------------------------------------------------------------------

    @staticmethod
    def _sync_request(
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        data: Optional[bytes] = None,
        timeout: float = READ_TIMEOUT,
    ) -> Dict[str, Any]:
        """同步 HTTP 请求，返回 (status_code, response_body_str, response_json)

        异常:
          urllib.error.HTTPError  — HTTP 4xx/5xx
          urllib.error.URLError   — 网络/DNS/连接错误
          socket.timeout          — 超时
        """
        req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}

    @staticmethod
    def _sync_request_raw(
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = DOWNLOAD_READ_TIMEOUT,
    ) -> bytes:
        """同步 GET，返回原始字节"""
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()

    async def _api_get(self, url: str, timeout: float = READ_TIMEOUT) -> Dict[str, Any]:
        """异步 GET 请求"""
        headers = self._build_headers()
        try:
            return await asyncio.to_thread(self._sync_request, url, "GET", headers, None, timeout)
        except urllib.error.HTTPError as e:
            logger.error(f"API HTTP错误: {e.code}")
            try:
                err_body = e.read().decode("utf-8", errors="replace")
                logger.error(f"错误详情: {err_body}")
            except Exception:
                logger.error(f"响应内容: {e.reason}")
            raise
        except (urllib.error.URLError, socket.timeout, OSError) as e:
            exc_name = type(e).__name__
            logger.error(f"API调用异常 [{exc_name}] {e}")
            raise RuntimeError(f"[{exc_name}] {e}") from e

    @staticmethod
    def _build_multipart_body(
        fields: Dict[str, str],
        files: Dict[str, tuple],
    ) -> tuple[bytes, str]:
        """构建 multipart/form-data 请求体

        Args:
            fields: 普通表单字段 {name: value}
            files:  文件字段 {name: (filename, file_bytes)}

        Returns:
            (body_bytes, content_type_header_value)
        """
        boundary = "----ClawFormBoundary" + uuid.uuid4().hex
        body_parts: list[bytes] = []

        # 普通字段
        for name, value in fields.items():
            body_parts.append(f"--{boundary}\r\n".encode("utf-8"))
            body_parts.append(
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8")
            )
            body_parts.append(value.encode("utf-8"))
            body_parts.append(b"\r\n")

        # 文件字段
        for field_name, (filename, file_bytes) in files.items():
            body_parts.append(f"--{boundary}\r\n".encode("utf-8"))
            body_parts.append(
                f'Content-Disposition: form-data; name="{field_name}"; '
                f'filename="{filename}"\r\n'.encode("utf-8")
            )
            body_parts.append(b"Content-Type: application/octet-stream\r\n\r\n")
            body_parts.append(file_bytes)
            body_parts.append(b"\r\n")

        # 结束标记
        body_parts.append(f"--{boundary}--\r\n".encode("utf-8"))

        body = b"".join(body_parts)
        content_type = f"multipart/form-data; boundary={boundary}"
        return body, content_type

    # ------------------------------------------------------------------
    # 业务 API
    # ------------------------------------------------------------------

    async def submit_task(
        self,
        image_data: Optional[bytes] = None,
        filename: str = "unknown",
        file_url: Optional[str] = None,
        page_ranges: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """提交异步识别任务"""
        if not image_data and not file_url:
            return {
                "success": False,
                "error": "必须提供 image_data 或 file_url",
                "filename": filename,
            }

        if not self.is_configured:
            return {
                "success": False,
                "error": "API Token 未配置，请在系统配置中填入 PaddleOCR API Token",
                "filename": filename,
            }

        optional_payload = self._get_optional_payload()

        try:
            logger.info(f"提交异步任务 [{filename}] model={self.model}")

            if file_url:
                # 方式1: fileUrl 模式 (application/json)
                json_data = {
                    "model": self.model,
                    "optionalPayload": optional_payload,
                    "fileUrl": file_url,
                }
                if page_ranges:
                    json_data["pageRanges"] = page_ranges
                if batch_id:
                    json_data["batchId"] = batch_id

                request_headers = self._build_headers("application/json")
                body_bytes = json.dumps(json_data).encode("utf-8")
                result = await asyncio.to_thread(
                    self._sync_request,
                    self.job_url, "POST", request_headers, body_bytes,
                    SUBMIT_READ_TIMEOUT,
                )
            else:
                # 方式2: multipart/form-data 上传本地文件
                if image_data is None:
                    return {
                        "success": False,
                        "error": "内部错误：image_data 为空",
                        "filename": filename,
                    }

                fields = {
                    "model": self.model,
                    "optionalPayload": json.dumps(optional_payload),
                }
                if page_ranges:
                    fields["pageRanges"] = page_ranges
                if batch_id:
                    fields["batchId"] = batch_id

                files = {"file": (filename, image_data)}
                body_bytes, content_type = self._build_multipart_body(fields, files)

                request_headers = self._build_headers()
                request_headers["Content-Type"] = content_type

                result = await asyncio.to_thread(
                    self._sync_request,
                    self.job_url, "POST", request_headers, body_bytes,
                    SUBMIT_READ_TIMEOUT,
                )

            data_field = result.get("data", {})
            job_id = data_field.get("jobId")

            if not job_id:
                error_msg = self._parse_error(result)
                # S16: 仅记录状态码和错误消息，不记录完整 result（防止敏感信息泄露）
                logger.error(
                    f"提交失败 [{filename}]: {error_msg}"
                )
                raise RuntimeError(f"API 返回异常: {error_msg}")

            logger.info(f"任务已提交 [{filename}]: jobId={job_id}")
            return {
                "success": True,
                "job_id": job_id,
                "filename": filename,
                "batch_id": batch_id,
            }

        except Exception as e:
            logger.error(f"提交任务失败 [{filename}]: {e}")
            return {"success": False, "error": str(e), "filename": filename}

    # ------------------------------------------------------------------
    # 轮询
    # ------------------------------------------------------------------

    async def poll_once(
        self, job_id: str, filename: str = "unknown"
    ) -> Dict[str, Any]:
        """单次轮询 PaddleOCR 任务状态（供前端驱动的异步轮询模式使用）"""
        query_url = f"{self.job_url}/{job_id}"

        try:
            result = await self._api_get(query_url, timeout=READ_TIMEOUT)
            data_field = result.get("data", {})
            state = data_field.get("state", "")

            if state == "done":
                return await self._handle_done_state(data_field, filename, job_id)

            elif state == "failed":
                error_msg = self._parse_error(data_field)
                logger.error(f"任务失败 [{filename}]: {error_msg}")
                return {"status": "failed", "error": error_msg}

            elif state in ("running", "pending"):
                progress = data_field.get("extractProgress", {})
                extracted = progress.get("extractedPages", 0)
                total = progress.get("totalPages", 0)
                return {
                    "status": state,
                    "extracted_pages": extracted,
                    "total_pages": total if total > 0 else extracted,
                }

            else:
                logger.warning(f"未知状态 [{filename}]: state={state}")
                return {"status": state, "extracted_pages": 0, "total_pages": 0}

        except Exception as e:
            exc_name = type(e).__name__
            exc_repr = repr(e) if repr(e) != f"{exc_name}()" else ""
            logger.error(
                f"单次轮询异常 [{filename}] jobId={job_id}: "
                f"[{exc_name}] {e}{' | ' + exc_repr if exc_repr else ''}"
            )
            return {"status": "error", "error": f"[{exc_name}] {e}"}

    async def _handle_done_state(
        self, data_field: Dict[str, Any], filename: str, job_id: str
    ) -> Dict[str, Any]:
        """处理 done 状态：下载 JSON/Markdown 结果"""
        progress = data_field.get("extractProgress", {})
        extracted_pages = progress.get("extractedPages", 0)
        total_pages = progress.get("totalPages", 0)
        result_url_obj = data_field.get("resultUrl", {})
        json_url = result_url_obj.get("jsonUrl", "")
        markdown_url = result_url_obj.get("markdownUrl", "")

        logger.info(
            f"任务完成 [{filename}]: jobId={job_id}, "
            f"页数={extracted_pages}/{total_pages}"
        )

        json_text, raw_json = "", None
        if json_url:
            try:
                json_text, raw_json = await self._download_result_json(json_url)
                logger.info(f"下载JSON结果成功 [{filename}]: {len(json_text)} 字符")
            except Exception as e:
                exc_name = type(e).__name__
                logger.error(f"下载JSON结果失败 [{filename}]: [{exc_name}] {e}")
                return {"status": "error", "error": f"下载结果失败: {e}"}
        else:
            logger.warning(f"resultUrl.jsonUrl 为空 [{filename}]")

        markdown_text = ""
        if markdown_url:
            try:
                markdown_text = await self._download_markdown_result(markdown_url)
                logger.info(
                    f"下载Markdown结果成功 [{filename}]: {len(markdown_text)} 字符"
                )
            except Exception as e:
                logger.warning(f"下载Markdown结果失败 [{filename}]: {e}")

        return {
            "status": "done",
            "json_text": json_text,
            "raw_json": raw_json,
            "markdown_text": markdown_text,
            "extracted_pages": extracted_pages,
            "total_pages": total_pages,
            "raw_result": data_field,
        }

    async def poll_result(
        self, job_id: str, filename: str = "unknown"
    ) -> Dict[str, Any]:
        """轮询直到任务完成（内循环模式，供同步处理使用）"""
        query_url = f"{self.job_url}/{job_id}"
        STUCK_THRESHOLD = 20
        TX_ERROR_THRESHOLD = 8

        last_extracted = -1
        stuck_count = 0
        tx_error_count = 0

        for attempt in range(1, settings.poll_max_retries + 1):
            try:
                result = await self._api_get(query_url, timeout=READ_TIMEOUT)
                tx_error_count = 0

                data_field = result.get("data", {})
                state = data_field.get("state", "")

                if state == "done":
                    progress = data_field.get("extractProgress", {})
                    extracted_pages = progress.get("extractedPages", 0)
                    total_pages = progress.get("totalPages", 0)
                    result_url_obj = data_field.get("resultUrl", {})
                    json_url = result_url_obj.get("jsonUrl", "")
                    markdown_url = result_url_obj.get("markdownUrl", "")
                    start_time = data_field.get("startTime", "")
                    end_time = data_field.get("endTime", "")

                    logger.info(
                        f"任务完成 [{filename}]: jobId={job_id}, "
                        f"页数={extracted_pages}/{total_pages}, "
                        f"轮询次数={attempt}, "
                        f"耗时={start_time}~{end_time}"
                    )

                    json_text, raw_json = "", None
                    if json_url:
                        try:
                            json_text, raw_json = await self._download_result_json(json_url)
                            logger.info(
                                f"下载JSON结果成功 [{filename}]: {len(json_text)} 字符"
                            )
                        except Exception as e:
                            exc_name = type(e).__name__
                            logger.error(
                                f"下载JSON结果失败 [{filename}]: [{exc_name}] {e}"
                            )
                            return {"success": False, "error": f"下载结果失败: {e}"}
                    else:
                        logger.warning(f"resultUrl.jsonUrl 为空 [{filename}]")

                    markdown_text = ""
                    if markdown_url:
                        try:
                            markdown_text = await self._download_markdown_result(markdown_url)
                            logger.info(
                                f"下载Markdown结果成功 [{filename}]: "
                                f"{len(markdown_text)} 字符"
                            )
                        except Exception as e:
                            logger.warning(f"下载Markdown结果失败 [{filename}]: {e}")

                    return {
                        "success": True,
                        "json_text": json_text,
                        "raw_json": raw_json,
                        "markdown_text": markdown_text,
                        "extracted_pages": extracted_pages,
                        "total_pages": total_pages,
                        "raw_result": data_field,
                    }

                elif state == "failed":
                    error_msg = self._parse_error(data_field)
                    logger.error(f"任务失败 [{filename}]: {error_msg}")
                    return {"success": False, "error": error_msg}

                elif state == "running":
                    try:
                        progress = data_field.get("extractProgress", {})
                        total = progress.get("totalPages", "?")
                        extracted = progress.get("extractedPages", "?")
                        logger.info(
                            f"轮询中 [{filename}] jobId={job_id}: "
                            f"第{attempt}次, running {extracted}/{total} 页"
                        )

                        # M07: 类型安全检查 — extracted/total 可能为字符串 "?"
                        # 仅当两者均为 int 时才进行卡死检测比较
                        if (isinstance(extracted, int)
                                and isinstance(last_extracted, int)
                                and extracted == last_extracted
                                and isinstance(total, int)):
                            stuck_count += 1
                        else:
                            stuck_count = 0
                            last_extracted = extracted

                        if stuck_count >= STUCK_THRESHOLD:
                            msg = (
                                f"任务疑似卡死 [{filename}]: running {extracted}/{total} 页, "
                                f"连续 {stuck_count} 次无变化 (jobId={job_id})"
                            )
                            logger.warning(msg)
                            return {"success": False, "error": f"任务卡死: {msg}"}
                    except Exception:
                        logger.info(
                            f"轮询中 [{filename}] jobId={job_id}: "
                            f"第{attempt}次, running..."
                        )

                elif state == "pending":
                    logger.info(
                        f"轮询中 [{filename}] jobId={job_id}: "
                        f"第{attempt}次, pending..."
                    )
                    stuck_count = 0

                else:
                    logger.info(
                        f"轮询中 [{filename}] jobId={job_id}: "
                        f"第{attempt}次, state={state}"
                    )

                await asyncio.sleep(settings.poll_interval)

            except Exception as e:
                exc_name = type(e).__name__
                exc_repr = repr(e) if repr(e) != f"{exc_name}()" else ""
                logger.warning(
                    f"轮询异常 [{filename}] jobId={job_id} "
                    f"(第{attempt}次): [{exc_name}] {e}"
                    f"{' | ' + exc_repr if exc_repr else ''}"
                )

                tx_error_count += 1
                if tx_error_count >= TX_ERROR_THRESHOLD:
                    msg = (
                        f"连续 {tx_error_count} 次网络异常，判定 API 不可达 "
                        f"[{filename}] jobId={job_id}"
                    )
                    logger.error(msg)
                    return {"success": False, "error": msg}

                if attempt >= settings.poll_max_retries:
                    return {"success": False, "error": f"轮询超时: {str(e)}"}
                await asyncio.sleep(settings.poll_interval)

        return {
            "success": False,
            "error": f"轮询超时 ({settings.poll_max_retries * settings.poll_interval}s)",
            "filename": filename,
        }

    # ------------------------------------------------------------------
    # 结果下载
    # ------------------------------------------------------------------

    async def _download_result_json(self, json_url: str) -> tuple:
        """下载结果 JSON 文件 → (json_text, parsed_json)"""
        headers = {
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
        }
        try:
            raw = await asyncio.to_thread(
                self._sync_request_raw, json_url, headers, DOWNLOAD_READ_TIMEOUT
            )
            text = raw.decode("utf-8")
            if not text:
                logger.warning("下载JSON结果为空")
                return "", None
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
                logger.info("结果不是标准 JSON，尝试按 JSONL 解析")
            return text, parsed
        except urllib.error.HTTPError as e:
            logger.warning(f"下载JSON HTTP错误: status={e.code}")
            return "", None
        except Exception as e:
            logger.warning(f"下载JSON异常: {e}")
            return "", None

    async def _download_markdown_result(self, markdown_url: str) -> str:
        """下载 Markdown 结果文件"""
        headers = {
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
        }
        try:
            raw = await asyncio.to_thread(
                self._sync_request_raw, markdown_url, headers, DOWNLOAD_READ_TIMEOUT
            )
            text = raw.decode("utf-8")
            if not text:
                logger.warning("下载Markdown结果为空")
            return text
        except urllib.error.HTTPError as e:
            logger.warning(f"下载Markdown HTTP错误: status={e.code}")
            return ""
        except Exception as e:
            logger.warning(f"下载Markdown异常: {e}")
            return ""

    # ------------------------------------------------------------------
    # 批量查询
    # ------------------------------------------------------------------

    async def batch_get_results(self, batch_id: str) -> Dict[str, Any]:
        """批量获取同一 batchId 下所有任务的结果"""
        batch_url = f"{self.job_url}/batch/{batch_id}"
        try:
            logger.info(f"批量查询结果: batchId={batch_id}")
            result = await self._api_get(batch_url, timeout=READ_TIMEOUT)
            data = result.get("data", [])
            logger.info(f"批量查询完成: batchId={batch_id}, 共 {len(data)} 条")
            return {"success": True, "results": data}
        except Exception as e:
            logger.error(f"批量查询失败 batchId={batch_id}: {e}")
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------
    # 便捷方法：提交 + 轮询一步完成
    # ------------------------------------------------------------------

    async def submit_and_poll(
        self,
        image_data: Optional[bytes] = None,
        filename: str = "unknown",
        file_url: Optional[str] = None,
        page_ranges: Optional[str] = None,
    ) -> Dict[str, Any]:
        """提交任务并轮询直到完成"""
        start_time = time.time()

        submit_result = await self.submit_task(
            image_data=image_data,
            filename=filename,
            file_url=file_url,
            page_ranges=page_ranges,
        )
        if not submit_result["success"]:
            return self._error_response(
                filename, submit_result.get("error", "提交失败"), start_time
            )

        job_id = submit_result["job_id"]
        poll_result_data = await self.poll_result(job_id, filename)
        if not poll_result_data["success"]:
            return self._error_response(
                filename, poll_result_data.get("error", "轮询失败"), start_time
            )

        extracted = self.extract_result(poll_result_data)
        elapsed = round(time.time() - start_time, 2)
        logger.info(
            f"处理完成 [{filename}]: {len(extracted['markdown_text'])}字符, "
            f"{len(extracted['images'])}张图片, 耗时 {elapsed}s"
        )

        return {
            "filename": filename,
            "success": True,
            "markdown_text": extracted["markdown_text"],
            "images": extracted["images"],
            "layout_image_base64": extracted.get("layout_image"),
            "layout_items": extracted.get("layout_items", []),
            "raw_result": poll_result_data.get("raw_result"),
            "processing_time": elapsed,
        }

    @staticmethod
    def _error_response(filename: str, error: str, start_time: float) -> Dict[str, Any]:
        return {
            "filename": filename,
            "success": False,
            "error": error,
            "markdown_text": "",
            "images": {},
            "layout_image_base64": None,
            "raw_result": None,
            "processing_time": round(time.time() - start_time, 2),
        }

    @staticmethod
    def extract_result(poll_result: Dict[str, Any]) -> Dict[str, Any]:
        """委托到 paddle_parser.extract_ocr_result 进行结果解析"""
        return extract_ocr_result(poll_result)
