"""
测试: apps/web/api/paddle_service.py - PaddleOCR API 服务

覆盖:
  - 轮询卡死检测 (poll_result 中的 STUCK_THRESHOLD)
  - 网络异常处理 (TX_ERROR_THRESHOLD)
  - 不同模型类型的可选参数
  - API 错误码映射
  - 提交任务的边界条件
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest

_backend_path = str(Path(__file__).parent.parent / "apps" / "web" / "api")
if _backend_path in sys.path:
    sys.path.remove(_backend_path)
sys.path.insert(0, _backend_path)


@pytest.mark.unit
class TestPaddleOCRServiceInit:
    """测试服务初始化"""

    def test_init_with_valid_config(self):
        """使用有效配置初始化"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService(
            api_url="https://api.example.com",
            api_key="test_key",
            model="PaddleOCR-VL-1.6",
        )
        assert service.job_url == "https://api.example.com"
        assert service.token == "test_key"
        assert service.model == "PaddleOCR-VL-1.6"
        assert service.is_configured is True

    def test_init_not_configured(self):
        """未配置 API key 时 is_configured 返回 False"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService(api_url="https://api.example.com")
        assert service.is_configured is False

        service2 = PaddleOCRService(api_url="", api_key="")
        assert service2.is_configured is False


@pytest.mark.unit
class TestOptionalPayload:
    """测试不同模型的可选参数"""

    def test_vl_model_payload(self):
        """VL 模型应包含图表识别参数"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService(model="PaddleOCR-VL-1.6")
        payload = service._get_optional_payload()

        assert "useDocOrientationClassify" in payload
        assert "useDocUnwarping" in payload
        assert "useChartRecognition" in payload
        assert "useTextlineOrientation" not in payload

    def test_structure_model_payload(self):
        """PP-StructureV3 模型应包含图表识别参数"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService(model="PP-StructureV3")
        payload = service._get_optional_payload()

        assert "useChartRecognition" in payload
        assert "useTextlineOrientation" not in payload

    def test_ocr_model_payload(self):
        """OCR 模型应包含文本行方向参数"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService(model="PP-OCRv5")
        payload = service._get_optional_payload()

        assert "useDocOrientationClassify" in payload
        assert "useDocUnwarping" in payload
        assert "useTextlineOrientation" in payload
        assert "useChartRecognition" not in payload


@pytest.mark.unit
class TestErrorMapping:
    """测试 API 错误码映射"""

    def test_known_error_code(self):
        """已知错误码应返回映射消息"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService()

        result = service._parse_error({"code": 401})
        assert "Token无效" in result

        result = service._parse_error({"code": 10003})
        assert "文件大小超限" in result

        result = service._parse_error({"code": 10007})
        assert "模型参数错误" in result

    def test_unknown_error_code(self):
        """未知错误码应返回通用消息"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService()

        result = service._parse_error({"code": 9999})
        assert "未知错误" in result

    def test_error_msg_fallback(self):
        """当 code 不在映射中时使用 errorMsg 字段"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService()

        result = service._parse_error({
            "code": 9999,
            "errorMsg": "自定义错误消息",
        })
        assert "自定义错误消息" in result


@pytest.mark.unit
class TestSubmitTask:
    """测试任务提交"""

    @pytest.mark.anyio
    async def test_submit_without_config(self):
        """未配置 API key 应快速失败"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService(api_url="https://api.example.com")

        result = await service.submit_task(image_data=b"test", filename="test.jpg")
        assert result["success"] is False
        assert "API Token 未配置" in result["error"]

    @pytest.mark.anyio
    async def test_submit_without_data(self):
        """缺少 image_data 和 file_url 应返回错误"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService(api_url="https://api.example.com", api_key="key")

        result = await service.submit_task(filename="test.jpg")
        assert result["success"] is False
        assert "必须提供 image_data 或 file_url" in result["error"]


@pytest.mark.unit
class TestPollOnce:
    """测试单次轮询"""

    @pytest.mark.anyio
    async def test_poll_once_done_state(self):
        """done 状态应返回完整结果"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService(api_url="https://api.example.com", api_key="key")

        with patch.object(service, "_api_get", new_callable=AsyncMock) as mock_api_get:
            mock_api_get.return_value = {
                "data": {
                    "state": "done",
                    "extractProgress": {"extractedPages": 1, "totalPages": 1},
                    "resultUrl": {"jsonUrl": "https://example.com/result.jsonl"},
                },
            }

            with patch.object(service, "_download_results_concurrent", new_callable=AsyncMock) as mock_download:
                mock_download.return_value = {
                    "json_text": "{\"result\":{}}",
                    "raw_json": {"result": {}},
                    "markdown_text": "",
                    "json_error": None,
                    "markdown_error": None,
                }

                result = await service.poll_once("job123", "test.jpg")
                assert result["status"] == "done"
                assert result["extracted_pages"] == 1
                assert result["total_pages"] == 1

    @pytest.mark.anyio
    async def test_poll_once_failed_state(self):
        """failed 状态应返回错误"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService(api_url="https://api.example.com", api_key="key")

        with patch.object(service, "_api_get", new_callable=AsyncMock) as mock_api_get:
            mock_api_get.return_value = {
                "data": {"state": "failed", "errorMsg": "识别失败"},
            }

            result = await service.poll_once("job123", "test.jpg")
            assert result["status"] == "failed"
            assert "识别失败" in result["error"]

    @pytest.mark.anyio
    async def test_poll_once_running_state(self):
        """running 状态应返回进度"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService(api_url="https://api.example.com", api_key="key")

        with patch.object(service, "_api_get", new_callable=AsyncMock) as mock_api_get:
            mock_api_get.return_value = {
                "data": {
                    "state": "running",
                    "extractProgress": {"extractedPages": 2, "totalPages": 5},
                },
            }

            result = await service.poll_once("job123", "test.jpg")
            assert result["status"] == "running"
            assert result["extracted_pages"] == 2
            assert result["total_pages"] == 5

    @pytest.mark.anyio
    async def test_poll_once_network_error(self):
        """网络异常应返回 error 状态"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService(api_url="https://api.example.com", api_key="key")

        with patch.object(service, "_api_get", new_callable=AsyncMock) as mock_api_get:
            mock_api_get.side_effect = RuntimeError("网络超时")

            result = await service.poll_once("job123", "test.jpg")
            assert result["status"] == "error"
            assert "网络超时" in result["error"]


@pytest.mark.unit
class TestPollResultStuckDetection:
    """测试轮询卡死检测"""

    @pytest.mark.anyio
    async def test_poll_result_stuck_detection(self, monkeypatch):
        """进度长时间不变应触发卡死检测"""
        from apps.web.api.paddle_service import PaddleOCRService
        from apps.web.api.config import settings

        # 置零轮询间隔，避免 22 次轮询各自 sleep 5s 拖慢测试（逻辑不变）
        monkeypatch.setattr(settings, "poll_interval", 0)

        service = PaddleOCRService(api_url="https://api.example.com", api_key="key")

        call_count = [0]

        def _mock_api_get_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 22:
                return {
                    "data": {
                        "state": "running",
                        "extractProgress": {"extractedPages": 1, "totalPages": 5},
                    },
                }
            return {
                "data": {"state": "done"},
            }

        with patch.object(service, "_api_get", new_callable=AsyncMock) as mock_api_get:
            mock_api_get.side_effect = _mock_api_get_side_effect

            result = await service.poll_result("job123", "test.jpg")

            assert result["success"] is False
            assert "任务卡死" in result["error"]

    @pytest.mark.anyio
    async def test_poll_result_resumes_after_progress(self, monkeypatch):
        """进度变化后应重置卡死计数"""
        from apps.web.api.paddle_service import PaddleOCRService
        from apps.web.api.config import settings

        # 置零轮询间隔，避免 10 次轮询各自 sleep 5s 拖慢测试（逻辑不变）
        monkeypatch.setattr(settings, "poll_interval", 0)

        service = PaddleOCRService(api_url="https://api.example.com", api_key="key")

        call_count = [0]

        def _mock_api_get_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 10:
                return {
                    "data": {
                        "state": "running",
                        "extractProgress": {"extractedPages": call_count[0], "totalPages": 20},
                    },
                }
            return {
                "data": {
                    "state": "done",
                    "extractProgress": {"extractedPages": 20, "totalPages": 20},
                    "resultUrl": {"jsonUrl": "https://example.com/result.jsonl"},
                },
            }

        with patch.object(service, "_api_get", new_callable=AsyncMock) as mock_api_get:
            mock_api_get.side_effect = _mock_api_get_side_effect

            with patch.object(service, "_download_results_concurrent", new_callable=AsyncMock) as mock_download:
                mock_download.return_value = {
                    "json_text": "{\"result\":{}}",
                    "raw_json": {"result": {}},
                    "markdown_text": "",
                    "json_error": None,
                    "markdown_error": None,
                }

                result = await service.poll_result("job123", "test.jpg")

                assert result["success"] is True

    @pytest.mark.anyio
    async def test_poll_result_pending_no_stuck_detection(self, monkeypatch):
        """pending 状态不触发卡死检测"""
        from apps.web.api.paddle_service import PaddleOCRService
        from apps.web.api.config import settings

        # 置零轮询间隔，避免 25 次轮询各自 sleep 5s 拖慢测试（逻辑不变）
        monkeypatch.setattr(settings, "poll_interval", 0)

        service = PaddleOCRService(api_url="https://api.example.com", api_key="key")

        call_count = [0]

        def _mock_api_get_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 25:
                return {"data": {"state": "pending"}}
            return {
                "data": {
                    "state": "done",
                    "extractProgress": {"extractedPages": 1, "totalPages": 1},
                    "resultUrl": {"jsonUrl": "https://example.com/result.jsonl"},
                },
            }

        with patch.object(service, "_api_get", new_callable=AsyncMock) as mock_api_get:
            mock_api_get.side_effect = _mock_api_get_side_effect

            with patch.object(service, "_download_results_concurrent", new_callable=AsyncMock) as mock_download:
                mock_download.return_value = {
                    "json_text": "{\"result\":{}}",
                    "raw_json": {"result": {}},
                    "markdown_text": "",
                    "json_error": None,
                    "markdown_error": None,
                }

                result = await service.poll_result("job123", "test.jpg")

                assert result["success"] is True


@pytest.mark.unit
class TestPollResultNetworkErrors:
    """测试网络异常处理"""

    @pytest.mark.anyio
    async def test_poll_result_network_error_threshold(self, monkeypatch):
        """连续网络异常超过阈值应判定不可达"""
        from apps.web.api.paddle_service import PaddleOCRService
        from apps.web.api.config import settings

        # 置零轮询间隔，避免多次轮询各自 sleep 5s 拖慢测试（逻辑不变）
        monkeypatch.setattr(settings, "poll_interval", 0)

        service = PaddleOCRService(api_url="https://api.example.com", api_key="key")

        with patch.object(service, "_api_get", new_callable=AsyncMock) as mock_api_get:
            mock_api_get.side_effect = RuntimeError("网络错误")

            result = await service.poll_result("job123", "test.jpg")

            assert result["success"] is False
            assert "连续" in result["error"]
            assert "网络异常" in result["error"]
            assert "不可达" in result["error"]

    @pytest.mark.anyio
    async def test_poll_result_recovers_after_error(self, monkeypatch):
        """网络异常后恢复应继续轮询"""
        from apps.web.api.paddle_service import PaddleOCRService
        from apps.web.api.config import settings

        # 置零轮询间隔，避免多次轮询各自 sleep 5s 拖慢测试（逻辑不变）
        monkeypatch.setattr(settings, "poll_interval", 0)

        service = PaddleOCRService(api_url="https://api.example.com", api_key="key")

        call_count = [0]

        def _mock_api_get_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 3:
                raise RuntimeError("网络错误")
            return {
                "data": {
                    "state": "done",
                    "extractProgress": {"extractedPages": 1, "totalPages": 1},
                    "resultUrl": {"jsonUrl": "https://example.com/result.jsonl"},
                },
            }

        with patch.object(service, "_api_get", new_callable=AsyncMock) as mock_api_get:
            mock_api_get.side_effect = _mock_api_get_side_effect

            with patch.object(service, "_download_results_concurrent", new_callable=AsyncMock) as mock_download:
                mock_download.return_value = {
                    "json_text": "{\"result\":{}}",
                    "raw_json": {"result": {}},
                    "markdown_text": "",
                    "json_error": None,
                    "markdown_error": None,
                }

                result = await service.poll_result("job123", "test.jpg")

                assert result["success"] is True

    @pytest.mark.anyio
    async def test_poll_result_timeout(self):
        """轮询次数超过限制应返回超时"""
        from apps.web.api.paddle_service import PaddleOCRService
        from apps.web.api.config import settings

        original_retries = settings.poll_max_retries
        original_interval = settings.poll_interval
        try:
            settings.poll_max_retries = 5
            settings.poll_interval = 0  # 置零间隔，避免 5 次轮询各自 sleep 5s

            service = PaddleOCRService(api_url="https://api.example.com", api_key="key")

            with patch.object(service, "_api_get", new_callable=AsyncMock) as mock_api_get:
                mock_api_get.return_value = {
                    "data": {"state": "pending"},
                }

                result = await service.poll_result("job123", "test.jpg")

                assert result["success"] is False
                assert "轮询超时" in result["error"]
        finally:
            settings.poll_max_retries = original_retries
            settings.poll_interval = original_interval


@pytest.mark.unit
class TestBatchGetResults:
    """测试批量查询"""

    @pytest.mark.anyio
    async def test_batch_get_results_success(self):
        """批量查询成功"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService(api_url="https://api.example.com", api_key="key")

        with patch.object(service, "_api_get", new_callable=AsyncMock) as mock_api_get:
            mock_api_get.return_value = {"data": [{"jobId": "job1"}, {"jobId": "job2"}]}

            result = await service.batch_get_results("batch123")

            assert result["success"] is True
            assert len(result["results"]) == 2

    @pytest.mark.anyio
    async def test_batch_get_results_failure(self):
        """批量查询失败"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService(api_url="https://api.example.com", api_key="key")

        with patch.object(service, "_api_get", new_callable=AsyncMock) as mock_api_get:
            mock_api_get.side_effect = RuntimeError("查询失败")

            result = await service.batch_get_results("batch123")

            assert result["success"] is False
            assert "查询失败" in result["error"]


@pytest.mark.unit
class TestExtractResult:
    """测试结果提取"""

    def test_extract_result_delegates_to_parser(self):
        """extract_result 应委托给 paddle_parser"""
        from apps.web.api.paddle_service import PaddleOCRService

        poll_result = {
            "json_text": "{\"result\":{\"layoutParsingResults\":[{\"markdown\":{\"text\":\"test\"}}]}}",
        }

        result = PaddleOCRService.extract_result(poll_result)

        assert result["markdown_text"] == "test"
        assert result["images"] == {}
        assert result["layout_items"] == []


@pytest.mark.unit
class TestPaddleIsInternalIp:
    """测试 paddle_service 模块内独立实现的 _is_internal_ip（与 main.py 保持一致但独立维护）"""

    @pytest.mark.parametrize("host,expected", [
        # IPv4 内网
        ("127.0.0.1", True),
        ("10.0.0.1", True),
        ("192.168.1.1", True),
        ("172.16.0.1", True),
        ("169.254.1.1", True),
        # IPv6 内网
        ("::1", True),
        ("fc00::1", True),
        ("fe80::1", True),
        # localhost 和空
        ("localhost", True),
        ("", True),
        # 公网 IP
        ("8.8.8.8", False),
        ("1.2.3.4", False),
        # 公网域名（无 mock 时走真实 DNS，example.com 解析到公网）
        ("example.com", False),
    ])
    def test_is_internal_ip(self, host, expected):
        """内网地址应返回 True，公网地址应返回 False"""
        from apps.web.api.paddle_service import _is_internal_ip
        assert _is_internal_ip(host) is expected

    @pytest.mark.parametrize("resolved_ip,expected", [
        ("192.168.1.1", True),   # 解析到内网 IP
        ("8.8.8.8", False),       # 解析到公网 IP
    ])
    def test_dns_resolution_to_internal(self, resolved_ip, expected):
        """解析到内网 IP 的域名应返回 True（防 SSRF 绕过）"""
        import socket as _socket
        from unittest.mock import patch
        from apps.web.api.paddle_service import _is_internal_ip

        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.side_effect = [
                [(_socket.AF_INET, _socket.SOCK_STREAM, _socket.IPPROTO_TCP, "", (resolved_ip, 0))],
                _socket.gaierror,
            ]
            assert _is_internal_ip("test-domain.com") is expected


@pytest.mark.unit
class TestValidateResultUrl:
    """测试 _validate_result_url SSRF 防护校验"""

    @pytest.mark.parametrize("url", [
        "https://paddleocr.example.com/result.jsonl",
        "http://paddleocr.example.com/result.jsonl",
    ])
    def test_valid_urls_pass(self, url):
        """合法的公网 http(s) URL 应通过校验（不抛异常）"""
        from apps.web.api.paddle_service import _validate_result_url
        _validate_result_url(url)  # 不抛异常即通过

    @pytest.mark.parametrize("url,match_pattern", [
        # 空 URL
        ("", "为空"),
        # 非 http(s) 协议
        ("file:///etc/passwd", "http"),
        ("ftp://example.com/file", "http"),
        ("gopher://localhost/", "http"),
        # 无主机名
        ("https:///result.json", "主机名"),
    ])
    def test_invalid_format_rejected(self, url, match_pattern):
        """格式非法的 URL 应抛出 ResultUrlValidationError"""
        from apps.web.api.paddle_service import _validate_result_url, ResultUrlValidationError
        with pytest.raises(ResultUrlValidationError, match=match_pattern):
            _validate_result_url(url)

    @pytest.mark.parametrize("url", [
        # localhost
        "https://localhost/result.json",
        # IPv4 环回
        "https://127.0.0.1/result.json",
        # 内网 IP 段
        "https://10.0.0.1/result.json",
        "https://192.168.1.1/result.json",
        "https://172.16.0.1/result.json",
        "https://169.254.1.1/result.json",
        # IPv6 环回
        "https://[::1]/result.json",
    ])
    def test_internal_urls_rejected(self, url):
        """localhost 和内网 IP 应被拒绝"""
        from apps.web.api.paddle_service import _validate_result_url, ResultUrlValidationError
        with pytest.raises(ResultUrlValidationError, match="内网"):
            _validate_result_url(url)

    def test_domain_resolving_to_internal_rejected(self):
        """解析到内网 IP 的域名应被拒绝（防 SSRF 绕过）"""
        import socket as _socket
        from unittest.mock import patch
        from apps.web.api.paddle_service import _validate_result_url, ResultUrlValidationError

        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.side_effect = [
                [(_socket.AF_INET, _socket.SOCK_STREAM, _socket.IPPROTO_TCP, "", ("10.0.0.5", 0))],
                _socket.gaierror,
            ]
            with pytest.raises(ResultUrlValidationError, match="内网"):
                _validate_result_url("https://evil.example.com/result.json")


@pytest.mark.unit
class TestBuildHeadersBearer:
    """测试 _build_headers 的 RFC 6750 合规性（bearer → Bearer）"""

    def test_authorization_uses_capital_bearer(self):
        """Authorization 头应使用大写 Bearer（RFC 6750）"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService(api_key="my_token_123")
        headers = service._build_headers()

        assert headers["Authorization"] == "Bearer my_token_123"
        # 确保不是小写 bearer（回归测试）
        assert not headers["Authorization"].startswith("bearer ")

    def test_headers_with_content_type(self):
        """带 content_type 时应附加 Content-Type 头"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService(api_key="token")
        headers = service._build_headers(content_type="application/json")

        assert headers["Authorization"] == "Bearer token"
        assert headers["Content-Type"] == "application/json"

    def test_headers_without_content_type(self):
        """不带 content_type 时不应包含 Content-Type"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService(api_key="token")
        headers = service._build_headers()

        assert "Content-Type" not in headers


@pytest.mark.unit
class TestParseErrorCodeZero:
    """测试 _parse_error 对 code=0 的处理（修复 falsy 短路 bug）"""

    def test_code_zero_with_error_msg_returns_error_msg(self):
        """code=0 且有 errorMsg 时应返回 errorMsg（不应被 falsy 短路）"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService()
        result = service._parse_error({"code": 0, "errorMsg": "实际错误信息"})

        assert "实际错误信息" in result

    def test_code_zero_without_error_msg_returns_unknown(self):
        """code=0 且无 errorMsg 时应返回未知错误"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService()
        result = service._parse_error({"code": 0})

        assert "未知错误" in result
        assert "0" in result

    def test_code_zero_in_map_is_looked_up(self):
        """code=0 在映射表中时应被正确查找（证明 is not None 修复有效）

        旧代码 `if code and code in MAP` 会因 code=0 falsy 而跳过映射查找。
        新代码 `if code is not None and code in MAP` 能正确命中。
        """
        from apps.web.api.paddle_service import PaddleOCRService
        from apps.web.api import paddle_service as ps_module

        original_map = ps_module.ERROR_CODE_MAP
        try:
            ps_module.ERROR_CODE_MAP = {**original_map, 0: "成功但需处理"}
            service = PaddleOCRService()
            result = service._parse_error({"code": 0})

            assert "成功但需处理" in result
        finally:
            ps_module.ERROR_CODE_MAP = original_map

    def test_none_code_falls_back_to_error_msg(self):
        """code 为 None 时应回退到 errorMsg"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService()
        result = service._parse_error({"errorMsg": "无 code 的错误"})

        assert "无 code 的错误" in result


@pytest.mark.unit
class TestDownloadResultsConcurrent:
    """测试 _download_results_concurrent 并发下载逻辑"""

    @pytest.mark.anyio
    async def test_both_urls_download_successfully(self):
        """JSON 和 Markdown URL 均有效时应并发下载成功"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService(api_url="https://api.example.com", api_key="key")

        mock_response_json = MagicMock()
        mock_response_json.text = '{"result": {}}'
        mock_response_json.status_code = 200
        mock_response_json.raise_for_status = MagicMock()

        mock_response_md = MagicMock()
        mock_response_md.text = '# Markdown Result'
        mock_response_md.status_code = 200
        mock_response_md.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[mock_response_json, mock_response_md])

        with patch("apps.web.api.paddle_service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await service._download_results_concurrent(
                "https://example.com/result.jsonl",
                "https://example.com/result.md",
            )

        assert result["json_text"] == '{"result": {}}'
        assert result["raw_json"] == {"result": {}}
        assert result["markdown_text"] == "# Markdown Result"
        assert result["json_error"] is None
        assert result["markdown_error"] is None

    @pytest.mark.anyio
    async def test_json_failure_does_not_affect_markdown(self):
        """JSON 下载失败不应影响 Markdown 下载（return_exceptions 隔离）"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService(api_url="https://api.example.com", api_key="key")

        mock_response_md = MagicMock()
        mock_response_md.text = '# Markdown OK'
        mock_response_md.status_code = 200
        mock_response_md.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[
            httpx.HTTPStatusError("server error", request=MagicMock(), response=MagicMock()),
            mock_response_md,
        ])

        with patch("apps.web.api.paddle_service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await service._download_results_concurrent(
                "https://example.com/result.jsonl",
                "https://example.com/result.md",
            )

        assert result["json_text"] == ""
        assert result["raw_json"] is None
        assert result["json_error"] is not None
        # Markdown 仍应成功
        assert result["markdown_text"] == "# Markdown OK"
        assert result["markdown_error"] is None

    @pytest.mark.anyio
    async def test_markdown_failure_does_not_affect_json(self):
        """Markdown 下载失败不应影响 JSON 下载"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService(api_url="https://api.example.com", api_key="key")

        mock_response_json = MagicMock()
        mock_response_json.text = '{"data": 1}'
        mock_response_json.status_code = 200
        mock_response_json.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[
            mock_response_json,
            RuntimeError("markdown download failed"),
        ])

        with patch("apps.web.api.paddle_service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await service._download_results_concurrent(
                "https://example.com/result.jsonl",
                "https://example.com/result.md",
            )

        assert result["json_text"] == '{"data": 1}'
        assert result["raw_json"] == {"data": 1}
        assert result["json_error"] is None
        assert result["markdown_text"] == ""
        assert result["markdown_error"] is not None

    @pytest.mark.anyio
    async def test_empty_urls_return_defaults(self):
        """两个 URL 均为空时应返回默认值"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService(api_url="https://api.example.com", api_key="key")

        with patch("apps.web.api.paddle_service.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await service._download_results_concurrent("", "")

        assert result["json_text"] == ""
        assert result["raw_json"] is None
        assert result["markdown_text"] == ""
        assert result["json_error"] is None
        assert result["markdown_error"] is None

    @pytest.mark.anyio
    async def test_internal_url_rejected_by_ssrf_validation(self):
        """内网 URL 应被 SSRF 校验拒绝，记为 json_error"""
        from apps.web.api.paddle_service import PaddleOCRService
        from apps.web.api.paddle_service import ResultUrlValidationError

        service = PaddleOCRService(api_url="https://api.example.com", api_key="key")

        with patch("apps.web.api.paddle_service.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await service._download_results_concurrent(
                "https://127.0.0.1/result.jsonl",
                "",
            )

        assert result["json_text"] == ""
        assert result["json_error"] is not None
        assert isinstance(result["json_error"], ResultUrlValidationError)

    @pytest.mark.anyio
    async def test_non_json_text_sets_raw_json_none(self):
        """下载内容不是有效 JSON 时 raw_json 应为 None"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService(api_url="https://api.example.com", api_key="key")

        mock_response = MagicMock()
        mock_response.text = "this is not json {{{"
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("apps.web.api.paddle_service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await service._download_results_concurrent(
                "https://example.com/result.jsonl",
                "",
            )

        assert result["json_text"] == "this is not json {{{"
        assert result["raw_json"] is None
        assert result["json_error"] is None