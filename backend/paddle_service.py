"""
错题管理系统 - PaddleOCR API 服务
基于百度AI Studio PaddleOCR官方API

支持模型:
  - PaddleOCR-VL-1.5 / PaddleOCR-VL（文档结构化分析，推荐）
  - PP-StructureV3（文档结构化分析）
  - PP-OCRv5（文字识别）

官方API流程:
  1. POST multipart/form-data 提交本地文件（或 fileUrl）到 /api/v2/ocr/jobs，获取 jobId
  2. GET /api/v2/ocr/jobs/{jobId} 轮询任务状态
  3. state=done 后，从 resultUrl.jsonUrl 下载 JSONL 结果
  4. JSONL 每行一个 JSON，result.layoutParsingResults[].markdown.text/images 提取内容

参考文档: https://ai.baidu.com/ai-doc/AISTUDIO/fml7mozw5
"""
import asyncio
import json
import time
import io
from typing import Optional, Dict, Any
import httpx
from logger import setup_logger

logger = setup_logger("PaddleOCRService")

# 轮询配置
POLL_INTERVAL = 5       # 轮询间隔（秒），官方建议 5s
POLL_MAX_RETRIES = 120  # 最大轮询次数（总共 600 秒）

# 模型分组
VL_MODELS = {"PaddleOCR-VL-1.5", "PaddleOCR-VL"}
STRUCTURE_MODELS = {"PP-StructureV3"}
OCR_MODELS = {"PP-OCRv5", "PP-OCRv4"}

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
    提交任务 → 获取 jobId → 轮询结果 → 下载 JSON
    """

    def __init__(self, api_url: str = "", api_key: str = "", model: str = "PP-StructureV3"):
        self.job_url = api_url.rstrip("/")
        self.token = api_key
        self.model = model

    def _build_headers(self, content_type: Optional[str] = None) -> Dict[str, str]:
        headers = {"Authorization": f"bearer {self.token}"}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _get_optional_payload(self) -> Dict[str, Any]:
        """
        根据模型类型返回对应的 optionalPayload 参数

        参考百度官方文档 (2026-02-04):
        - VL 系列 / PP-StructureV3: useDocOrientationClassify, useDocUnwarping, useChartRecognition
        - PP-OCRv5: useDocOrientationClassify, useDocUnwarping, useTextlineOrientation

        注意: useTextlineOrientation 是 PP-OCRv5 专用参数，PP-StructureV3 使用 useChartRecognition
        """
        if self.model in VL_MODELS or self.model in STRUCTURE_MODELS:
            return {
                "useDocOrientationClassify": False,
                "useDocUnwarping": False,
                "useChartRecognition": False,
            }
        else:
            # PP-OCRv5 等纯文字识别模型
            return {
                "useDocOrientationClassify": False,
                "useDocUnwarping": False,
                "useTextlineOrientation": False,
            }

    def _get_result_field_name(self) -> str:
        """
        根据模型返回结果 JSON 中的主字段名
        - VL 系列 / PP-StructureV3 返回 layoutParsingResults
        - PP-OCRv5 返回 ocrResults
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
        self, url: str, timeout: float = 30.0
    ) -> Dict[str, Any]:
        """通用 GET 请求"""
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

                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        self.job_url,
                        headers=self._build_headers("application/json"),
                        json=data,
                    )
                    response.raise_for_status()
                    result = response.json()
            else:
                # 方式2: multipart/form-data 上传本地文件
                # image_data 在此分支必然非空（已在函数入口校验）
                assert image_data is not None
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

                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(
                        self.job_url,
                        headers={"Authorization": f"bearer {self.token}"},
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
            result = await self._api_get(query_url, timeout=30.0)

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
                result = await self._api_get(query_url, timeout=30.0)
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
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
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
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
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
            result = await self._api_get(batch_url, timeout=30.0)
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
        """
        从 JSON/JSONL 结果中提取结构化数据

        支持的结果字段:
        - layoutParsingResults[].markdown.text / markdown.images (PP-StructureV3 / VL系列)
        - layoutParsingResults[].outputImages (PP-StructureV3 输出图片)
        - ocrResults[].ocrImage (PP-OCRv5)
        - layoutParsingResults[].layoutType / region (版面分析)

        JSONL 每行格式 (官方API):
        {
            "result": {
                "layoutParsingResults": [
                    {
                        "markdown": {
                            "text": "Markdown文本",
                            "images": {"img_0": "https://..."}
                        },
                        "outputImages": {"0": "https://..."},
                        "layoutType": "text/table/figure/...",
                        "region": {"x": ..., "y": ..., "width": ..., "height": ...}
                    }
                ]
            }
        }

        返回: {"markdown_text": "...", "images": {...}, "layout_image": "...",
               "layout_items": [{"type": "...", "region": {...}}, ...]}
        """
        extracted = {
            "markdown_text": "",
            "images": {},
            "layout_image": None,
            "layout_items": [],  # PP-StructureV3 版面分析结果
        }

        try:
            json_text = poll_result.get("json_text", "")
            raw_json = poll_result.get("raw_json")

            # 如果 API 直接返回了 markdown_text，优先使用
            direct_md = poll_result.get("markdown_text", "")
            if direct_md:
                extracted["markdown_text"] = direct_md
                logger.info(f"使用API直接返回的Markdown: {len(direct_md)}字符")

            # 优先使用已解析的 raw_json
            if raw_json is not None:
                parsed_list = PaddleOCRService._extract_ocr_items(raw_json)
            elif json_text:
                parsed_list = PaddleOCRService._parse_result_json(json_text)
            else:
                if not direct_md:
                    logger.warning("JSON 结果为空，无可用数据")
                return extracted

            if not parsed_list:
                if not direct_md:
                    logger.warning("解析结果中未找到有效的 OCR 数据")
                return extracted

            md_parts = []
            all_images = {}

            for item_index, ocr_result_item in enumerate(parsed_list):
                # 兼容两种数据结构:
                # 新版 API: result["markdown"]["text"] / result["markdown"]["images"]
                # 旧版 (如有): result["prunedResult"]["markdown"]...
                markdown_data = ocr_result_item.get("markdown", {})
                if not markdown_data:
                    pruned = ocr_result_item.get("prunedResult", {})
                    markdown_data = pruned.get("markdown", {})

                # 提取 Markdown 文本
                md_text = markdown_data.get("text", "")
                if md_text:
                    md_parts.append(str(md_text))

                # 提取内嵌图片（URL，非 base64）
                images_map = markdown_data.get("images", {})
                if isinstance(images_map, dict):
                    for img_key, img_value in images_map.items():
                        if isinstance(img_value, str) and img_value:
                            unique_key = (
                                f"img_{item_index}_{img_key}"
                                if item_index > 0
                                else img_key
                            )
                            all_images[unique_key] = img_value

                # 提取 outputImages（PP-StructureV3 输出图片）
                output_images = ocr_result_item.get("outputImages", {})
                if isinstance(output_images, dict):
                    for img_key, img_value in output_images.items():
                        if isinstance(img_value, str) and img_value:
                            unique_key = f"out_{item_index}_{img_key}" if item_index > 0 else img_key
                            all_images[unique_key] = img_value

                # 提取 OCR 结果图片 URL（版面图）
                ocr_image = ocr_result_item.get("ocrImage", "")
                if ocr_image and not extracted["layout_image"]:
                    extracted["layout_image"] = str(ocr_image)

                # 提取 PP-StructureV3 特有字段: layoutType / region (兼容旧版)
                layout_type = ocr_result_item.get("layoutType", "")
                region = ocr_result_item.get("region", {})
                if layout_type or region:
                    # 从当前 item 的 markdown 文本中提取内容预览
                    item_content = str(md_text).strip() if md_text else ""
                    extracted["layout_items"].append({
                        "type": layout_type,
                        "region": region,
                        "content_preview": item_content[:120],
                    })

                # 从 prunedResult.parsing_res_list 提取版面区域 (新版 API)
                pruned = ocr_result_item.get("prunedResult", {})
                parsing_list = pruned.get("parsing_res_list", [])
                for block in parsing_list:
                    block_label = block.get("block_label", "")
                    block_bbox = block.get("block_bbox", {})
                    if block_label:
                        extracted["layout_items"].append({
                            "type": block_label,
                            "region": {"bbox": block_bbox},
                            "content_preview": str(block.get("block_content", ""))[:120],
                        })

            # 合并从 prunedResult 提取的 markdown 和 API 直接返回的 markdown
            parsed_md = "\n\n".join(md_parts)
            if parsed_md:
                if extracted["markdown_text"]:
                    # 如果两者都有，API 直接返回的优先
                    if len(extracted["markdown_text"]) < len(parsed_md):
                        extracted["markdown_text"] = parsed_md
                else:
                    extracted["markdown_text"] = parsed_md

            extracted["images"] = all_images

            logger.info(
                f"提取结果: {len(extracted['markdown_text'])}字符Markdown, "
                f"{len(all_images)}张内嵌图片, "
                f"{len(extracted['layout_items'])}个版面区域"
            )

        except Exception as e:
            logger.error(f"解析JSON结果失败: {e}", exc_info=True)

        return extracted

    @staticmethod
    def _extract_ocr_items(json_obj) -> list:
        """
        从已解析的 JSON 对象中提取 OCR 结果列表

        支持多种嵌套结构:
        - result.layoutParsingResults[] (VL系列 / PP-StructureV3，含 markdown，优先)
        - result.ocrResults[] (PP-OCRv5)
        - 直接的列表

        注意: PP-StructureV3 返回的 JSON 中可能同时包含 layoutParsingResults
        和 ocrResults，必须优先取 layoutParsingResults 才能拿到结构化 Markdown。
        """
        if isinstance(json_obj, list):
            return json_obj

        # 尝试从 result 字段获取
        result = json_obj.get("result", json_obj)

        # VL系列 / PP-StructureV3: 优先取 layoutParsingResults（含结构化 Markdown）
        layout_results = result.get("layoutParsingResults", [])
        if layout_results:
            return layout_results

        # PP-OCRv5: 只有 ocrResults
        ocr_results = result.get("ocrResults", [])
        if ocr_results:
            return ocr_results

        return []

    @staticmethod
    def _parse_result_json(json_text: str) -> list:
        """
        解析结果 JSON 文本，支持三种格式：
        1. JSONL: 每行一个 JSON 对象
        2. 标准 JSON: 整个文本就是一个 JSON 对象
        3. 带 BOM 或其他前缀的 JSON

        返回 OCR 结果项列表
        """
        text = json_text.strip()
        if not text:
            return []

        # 尝试按标准 JSON 解析
        try:
            obj = json.loads(text)
            return PaddleOCRService._extract_ocr_items(obj)
        except (json.JSONDecodeError, ValueError):
            pass

        # 尝试 JSONL 格式（每行一个 JSON）
        lines = text.split("\n")
        ocr_items = []
        for line_num, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                items = PaddleOCRService._extract_ocr_items(obj)
                ocr_items.extend(items)
            except (json.JSONDecodeError, ValueError):
                logger.warning(f"JSONL 第{line_num + 1}行解析失败，跳过")
                continue

        return ocr_items
