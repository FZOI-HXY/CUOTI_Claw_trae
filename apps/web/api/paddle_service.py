"""
错题管理系统 - PaddleOCR API 服务
基于百度AI Studio PaddleOCR官方API

支持模型:
  - PaddleOCR-VL-1.6 / PaddleOCR-VL-1.5 / PaddleOCR-VL（多模态文档结构化分析，推荐）
  - PP-StructureV3（文档结构化分析）
  - PP-OCRv6 / PP-OCRv5（文字识别）

官方API流程:
  1. POST multipart/form-data 提交本地文件（或 fileUrl）到 /api/v2/ocr/jobs，获取 jobId
  2. GET /api/v2/ocr/jobs/{jobId} 轮询任务状态
  3. state=done 后，从 resultUrl.jsonUrl 下载 JSONL / markdownUrl 下载 Markdown
  4. VL/Structure 模型: result.layoutParsingResults[].markdown.text/images 提取内容
     OCR 模型: result.ocrResults[].ocrImage 提取文字识别结果

参考文档: https://ai.baidu.com/ai-doc/AISTUDIO/fml7mozw5
"""
import asyncio
import json
import time
import io
from typing import Optional, Dict, Any
import httpx
from httpx import Timeout as HttpxTimeout
from apps.web.api.logger import setup_logger
from apps.web.api.services.paddle_parser import extract_ocr_result

logger = setup_logger("PaddleOCRService")

# 轮询配置
POLL_INTERVAL = 5       # 轮询间隔（秒），官方建议 5s
POLL_MAX_RETRIES = 120  # 最大轮询次数（总共 600 秒）

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


class PaddleOCRService:
    """
    PaddleOCR API 服务封装
    使用百度AI Studio 官方API（异步模式）
    提交任务 → 获取 jobId → 轮询结果 → 下载 JSON/Markdown

    模型分组:
      VL_MODELS:     PaddleOCR-VL-1.6, VL-1.5, VL（文档结构化+图表识别）
      STRUCTURE_MODELS: PP-StructureV3（文档结构化）
      OCR_MODELS:    PP-OCRv6, PP-OCRv5, PP-OCRv4（纯文字识别）
    """

    # 默认占位 Token（未配置时使用，应提示用户配置）
    DEFAULT_TOKEN = "your-paddleocr-api-token-here"

    # HTTP 请求超时配置
    # connect=10s: 快速失败，避免 TCP 连接长时间挂起
    # read=30s:   文件上传允许较长的服务端处理时间
    SUBMIT_TIMEOUT = HttpxTimeout(connect=10.0, read=30.0, write=15.0, pool=5.0)
    POLL_TIMEOUT = HttpxTimeout(connect=10.0, read=30.0, write=10.0, pool=5.0)
    DOWNLOAD_TIMEOUT = HttpxTimeout(connect=10.0, read=45.0, write=10.0, pool=5.0)

    def __init__(self, api_url: str = "", api_key: str = "", model: str = "PaddleOCR-VL-1.6"):
        self.job_url = api_url.rstrip("/")
        self.token = api_key
        self.model = model

    @property
    def is_configured(self) -> bool:
        """检查 API Token 是否已配置"""
        return bool(self.token) and self.token != self.DEFAULT_TOKEN

    def _build_headers(self, content_type: Optional[str] = None) -> Dict[str, str]:
        headers = {"Authorization": f"bearer {self.token}"}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _get_optional_payload(self) -> Dict[str, Any]:
        """
        根据模型类型返回对应的 optionalPayload 参数

        - PaddleOCR-VL-1.6 / VL-1.5 / VL / PP-StructureV3（文档结构化）:
            useDocOrientationClassify, useDocUnwarping, useChartRecognition
        - PP-OCRv6 / PP-OCRv5（纯文字识别）:
            useDocOrientationClassify, useDocUnwarping, useTextlineOrientation

        注意: PaddleOCR-VL-1.6 新增字段（如需要）可在此扩展；
              useTextlineOrientation 是 OCR 模型专用，VL/Structure 模型不可使用。
        """
        if self.model in VL_MODELS or self.model in STRUCTURE_MODELS:
            return {
                "useDocOrientationClassify": False,
                "useDocUnwarping": False,
                "useChartRecognition": False,
            }
        else:
            # PP-OCRv6/v5 等纯文字识别模型
            return {
                "useDocOrientationClassify": False,
                "useDocUnwarping": False,
                "useTextlineOrientation": False,
            }

    def _get_result_field_name(self) -> str:
        """
        根据模型返回结果 JSON 中的主字段名
        - PaddleOCR-VL-1.6 / VL-1.5 / VL / PP-StructureV3 → layoutParsingResults
        - PP-OCRv6 / PP-OCRv5 → ocrResults
        """
        if self.model in VL_MODELS or self.model in STRUCTURE_MODELS:
            return "layoutParsingResults"
        else:
            return "ocrResults"

    def _parse_error(self, result: Dict[str, Any]) -> str:
        """解析 API 返回的错误信息"""
        code = result.get("code")
        if code and code in ERROR_CODE_MAP:
            return f"[{code}] {ERROR_CODE_MAP[code]}"
        return result.get("errorMsg") or result.get("message") or f"未知错误 (code={code})"

    async def _api_get(
        self, url: str, timeout: "HttpxTimeout | None" = None
    ) -> Dict[str, Any]:
        """通用 GET 请求"""
        if timeout is None:
            timeout = self.POLL_TIMEOUT
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                response = await client.get(url, headers=self._build_headers())
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"API HTTP错误: {e.response.status_code}")
                try:
                    logger.error(f"错误详情: {e.response.json()}")
                except Exception:
                    logger.error(f"响应内容: {e.response.text}")
                raise
            except Exception as e:
                exc_name = type(e).__name__
                exc_repr = repr(e) if repr(e) != f"{exc_name}()" else ""
                logger.error(f"API调用异常 [{exc_name}] {e}{' | ' + exc_repr if exc_repr else ''}")
                raise

    async def submit_task(
        self,
        image_data: Optional[bytes] = None,
        filename: str = "unknown",
        file_url: Optional[str] = None,
        page_ranges: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        提交异步识别任务

        支持两种提交方式:
        1. multipart/form-data 提交本地文件（image_data + filename）
        2. fileUrl 提交文件链接（file_url）

        可选参数:
        - page_ranges: 页码范围，如 "2,4-6" 或 "2--2"
        - batch_id: 批量ID，用于批量查询

        返回: {"success": True/False, "job_id": "xxx", "error": "..."}
        """
        if not image_data and not file_url:
            return {"success": False, "error": "必须提供 image_data 或 file_url", "filename": filename}

        # 预检：API Token 未配置时快速失败，避免长时间等待
        if not self.is_configured:
            return {
                "success": False,
                "error": "API Token 未配置，请在系统配置中填入 PaddleOCR API Token",
                "filename": filename,
            }

        optional_payload = self._get_optional_payload()

        try:
            logger.info(f"提交异步任务 [{filename}] model={self.model}")

            # 方式1: fileUrl 模式 (application/json)
            if file_url:
                data = {
                    "model": self.model,
                    "optionalPayload": optional_payload,  # 直接传 dict，不用 json.dumps
                    "fileUrl": file_url,
                }
                if page_ranges:
                    data["pageRanges"] = page_ranges
                if batch_id:
                    data["batchId"] = batch_id

                async with httpx.AsyncClient(timeout=self.SUBMIT_TIMEOUT) as client:
                    response = await client.post(
                        self.job_url,
                        headers=self._build_headers("application/json"),
                        json=data,
                    )
                    response.raise_for_status()
                    result = response.json()
            else:
                # 方式2: multipart/form-data 上传本地文件
                # image_data 在此分支必须非空（已在函数入口校验，此处做防御性检查）
                if image_data is None:
                    return {"success": False, "error": "内部错误：image_data 为空", "filename": filename}
                # optionalPayload 在 form-data 中需要是 JSON 字符串
                data = {
                    "model": self.model,
                    "optionalPayload": json.dumps(optional_payload),
                }
                if page_ranges:
                    data["pageRanges"] = page_ranges
                if batch_id:
                    data["batchId"] = batch_id

                files = {"file": (filename, io.BytesIO(image_data))}

                async with httpx.AsyncClient(timeout=self.SUBMIT_TIMEOUT) as client:
                    response = await client.post(
                        self.job_url,
                        headers=self._build_headers(),
                        data=data,
                        files=files,
                    )
                    response.raise_for_status()
                    result = response.json()

            data_field = result.get("data", {})
            job_id = data_field.get("jobId")

            if not job_id:
                error_msg = self._parse_error(result)
                logger.error(f"提交失败 [{filename}]: {error_msg}, 完整响应: {result}")
                raise Exception(f"API 返回异常: {error_msg}")

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

    async def poll_once(
        self, job_id: str, filename: str = "unknown"
    ) -> Dict[str, Any]:
        """
        单次轮询 PaddleOCR 任务状态（不做内循环）。
        供前端驱动的异步轮询模式使用（/api/poll/）。

        返回: {"status": "pending"/"running"/"done"/"failed"/"error",
                "extracted_pages": int, "total_pages": int,
                ...或 result 字段（done 时）}
        """
        query_url = f"{self.job_url}/{job_id}"

        try:
            result = await self._api_get(query_url, timeout=self.POLL_TIMEOUT)

            data_field = result.get("data", {})
            state = data_field.get("state", "")

            if state == "done":
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

                # 下载结果 JSON
                json_text = ""
                raw_json = None
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

                # 下载 Markdown 结果（可选）
                markdown_text = ""
                if markdown_url:
                    try:
                        markdown_text = await self._download_markdown_result(markdown_url)
                        logger.info(f"下载Markdown结果成功 [{filename}]: {len(markdown_text)} 字符")
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

    async def poll_result(
        self, job_id: str, filename: str = "unknown"
    ) -> Dict[str, Any]:
        """
        轮询直到任务完成（内循环模式）。
        供同步处理模式使用（submit_and_poll）。

        内置卡死检测：如果 running 状态下进度持续不变超过 STUCK_THRESHOLD 次，判定为卡死。
        """
        query_url = f"{self.job_url}/{job_id}"
        STUCK_THRESHOLD = 20           # running 进度不变超此次数 → 判定卡死
        TX_ERROR_THRESHOLD = 8          # 连续网络异常超此次数 → 判定不可达

        last_extracted = -1
        stuck_count = 0
        tx_error_count = 0

        for attempt in range(1, POLL_MAX_RETRIES + 1):
            try:
                result = await self._api_get(query_url, timeout=self.POLL_TIMEOUT)
                tx_error_count = 0  # 请求成功，重置连续错误计数

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

                    # 下载结果 JSON
                    json_text = ""
                    raw_json = None
                    if json_url:
                        try:
                            json_text, raw_json = await self._download_result_json(json_url)
                            logger.info(
                                f"下载JSON结果成功 [{filename}]: {len(json_text)} 字符"
                            )
                        except Exception as e:
                            exc_name = type(e).__name__
                            logger.error(f"下载JSON结果失败 [{filename}]: [{exc_name}] {e}")
                            return {
                                "success": False,
                                "error": f"下载结果失败: {e}",
                            }
                    else:
                        logger.warning(f"resultUrl.jsonUrl 为空 [{filename}]")

                    # 尝试下载 Markdown 结果（如果有）
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

                        # ---- 卡死检测 ----
                        if extracted == last_extracted and total != "?":
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
                        # -----------------
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
                    # pending 阶段不检测卡死
                    stuck_count = 0

                else:
                    logger.info(
                        f"轮询中 [{filename}] jobId={job_id}: "
                        f"第{attempt}次, state={state}"
                    )

                await asyncio.sleep(POLL_INTERVAL)

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

                if attempt >= POLL_MAX_RETRIES:
                    return {"success": False, "error": f"轮询超时: {str(e)}"}
                await asyncio.sleep(POLL_INTERVAL)

        return {
            "success": False,
            "error": f"轮询超时 ({POLL_MAX_RETRIES * POLL_INTERVAL}s)",
            "filename": filename,
        }

    async def _download_result_json(self, json_url: str) -> tuple:
        """
        下载结果 JSON 文件

        返回: (json_text, parsed_json)
        """
        headers = {
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
        }
        async with httpx.AsyncClient(timeout=self.DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(json_url, headers=headers)
            response.raise_for_status()
            text = response.text
            if not text:
                logger.warning(f"下载JSON结果为空 (status={response.status_code})")
                return "", None
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                # 可能是 JSONL 格式（每行一个 JSON）
                parsed = None
                logger.info("结果不是标准 JSON，尝试按 JSONL 解析")
            return text, parsed

    async def _download_markdown_result(self, markdown_url: str) -> str:
        """
        下载 Markdown 结果文件

        返回: markdown 文本内容
        """
        headers = {
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
        }
        async with httpx.AsyncClient(timeout=self.DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(markdown_url, headers=headers)
            response.raise_for_status()
            if not response.text:
                logger.warning(f"下载Markdown结果为空 (status={response.status_code})")
            return response.text

    async def batch_get_results(
        self, batch_id: str
    ) -> Dict[str, Any]:
        """
        批量获取同一 batchId 下所有任务的结果

        Endpoint: GET /api/v2/ocr/jobs/batch/{batchId}
        限制: 同一 batchId 最多 100 条任务

        返回: {"success": True/False, "results": [...], "error": "..."}
        """
        batch_url = f"{self.job_url}/batch/{batch_id}"
        try:
            logger.info(f"批量查询结果: batchId={batch_id}")
            result = await self._api_get(batch_url, timeout=self.POLL_TIMEOUT)
            data = result.get("data", [])
            logger.info(f"批量查询完成: batchId={batch_id}, 共 {len(data)} 条")
            return {"success": True, "results": data}
        except Exception as e:
            logger.error(f"批量查询失败 batchId={batch_id}: {e}")
            return {"success": False, "error": str(e)}

    async def submit_and_poll(
        self,
        image_data: Optional[bytes] = None,
        filename: str = "unknown",
        file_url: Optional[str] = None,
        page_ranges: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        提交任务并轮询直到完成（单文件同步等待模式）
        流程: 提交 → 获取 jobId → 轮询直到完成 → 提取结果
        """
        start_time = time.time()

        # 步骤1: 提交任务
        submit_result = await self.submit_task(
            image_data=image_data,
            filename=filename,
            file_url=file_url,
            page_ranges=page_ranges,
        )
        if not submit_result["success"]:
            return self._error_response(filename, submit_result.get("error", "提交失败"), start_time)

        job_id = submit_result["job_id"]

        # 步骤2: 轮询结果
        poll_result_data = await self.poll_result(job_id, filename)
        if not poll_result_data["success"]:
            return self._error_response(filename, poll_result_data.get("error", "轮询失败"), start_time)

        # 步骤3: 提取结构化数据
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
