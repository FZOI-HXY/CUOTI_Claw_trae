"""
测试: apps/desktop/paddle_service_standalone.py - SSRF 防护逻辑

补测 paddle_service_standalone.py 中的 _validate_result_url 和 _is_internal_ip 函数，
以及 _download_result_json / _download_markdown_result 方法中的 SSRF 拦截行为。

测试策略:
  - 对 _validate_result_url 和 _is_internal_ip 用真实函数测试（不 mock）
  - 对下载方法测试 SSRF 拦截行为（验证返回空值，不实际发起网络请求）
"""

import socket as _socket
from unittest.mock import patch

import pytest

# 路径设置
_desktop_path = str(__import__("pathlib").Path(__file__).parent.parent / "apps" / "desktop")
import sys
if _desktop_path in sys.path:
    sys.path.remove(_desktop_path)
sys.path.insert(0, _desktop_path)

_backend_path = str(__import__("pathlib").Path(__file__).parent.parent / "apps" / "web" / "api")
if _backend_path in sys.path:
    sys.path.remove(_backend_path)
sys.path.insert(0, _backend_path)


@pytest.mark.unit
class TestStandaloneValidateResultUrl:
    """测试 paddle_service_standalone._validate_result_url SSRF 防护校验"""

    @pytest.mark.parametrize("url", [
        "https://paddleocr.baidu.com/result.json",
        "http://example.com/file.md",
    ])
    def test_valid_urls_pass(self, url):
        """合法的公网 http(s) URL 应通过校验（不抛异常）"""
        from apps.desktop.paddle_service_standalone import _validate_result_url
        _validate_result_url(url)  # 不抛异常即通过

    def test_empty_url_rejected(self):
        """空 URL 应抛出 ResultUrlValidationError"""
        from apps.desktop.paddle_service_standalone import (
            _validate_result_url, ResultUrlValidationError
        )
        with pytest.raises(ResultUrlValidationError, match="为空"):
            _validate_result_url("")

    @pytest.mark.parametrize("url", [
        "ftp://example.com/file.json",
        "file:///etc/passwd",
        "gopher://localhost/",
    ])
    def test_non_http_rejected(self, url):
        """非 http(s) 协议应被拒绝"""
        from apps.desktop.paddle_service_standalone import (
            _validate_result_url, ResultUrlValidationError
        )
        with pytest.raises(ResultUrlValidationError, match="http"):
            _validate_result_url(url)

    def test_localhost_rejected(self):
        """localhost 主机名应被拒绝"""
        from apps.desktop.paddle_service_standalone import (
            _validate_result_url, ResultUrlValidationError
        )
        with pytest.raises(ResultUrlValidationError, match="内网"):
            _validate_result_url("https://localhost/result.json")

    @pytest.mark.parametrize("ip", [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.1.1",
    ])
    def test_internal_ip_rejected(self, ip):
        """各类内网 IP 应被拒绝"""
        from apps.desktop.paddle_service_standalone import (
            _validate_result_url, ResultUrlValidationError
        )
        with pytest.raises(ResultUrlValidationError, match="内网"):
            _validate_result_url(f"https://{ip}/result.json")

    def test_dns_resolution_to_internal_rejected(self):
        """解析到内网 IP 的域名应被拒绝（防 SSRF 绕过）"""
        from apps.desktop.paddle_service_standalone import (
            _validate_result_url, ResultUrlValidationError
        )
        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.side_effect = [
                [(_socket.AF_INET, _socket.SOCK_STREAM, _socket.IPPROTO_TCP, "", ("10.0.0.5", 0))],
                _socket.gaierror,
            ]
            with pytest.raises(ResultUrlValidationError, match="内网"):
                _validate_result_url("https://evil.example.com/result.json")


@pytest.mark.unit
class TestStandaloneDownloadResultJson:
    """测试 _download_result_json 方法的 SSRF 拦截行为"""

    @pytest.mark.anyio
    async def test_ssrf_blocked_returns_empty(self):
        """SSRF URL 应被拦截，返回 ("", None) 而不发起网络请求"""
        from apps.desktop.paddle_service_standalone import PaddleOCRService

        service = PaddleOCRService(api_url="https://api.example.com", api_key="key")

        # 使用内网 URL，应被 SSRF 校验拦截
        json_text, parsed = await service._download_result_json("https://127.0.0.1/result.json")

        assert json_text == ""
        assert parsed is None


@pytest.mark.unit
class TestStandaloneDownloadMarkdownResult:
    """测试 _download_markdown_result 方法的 SSRF 拦截行为"""

    @pytest.mark.anyio
    async def test_ssrf_blocked_returns_empty(self):
        """SSRF URL 应被拦截，返回空字符串而不发起网络请求"""
        from apps.desktop.paddle_service_standalone import PaddleOCRService

        service = PaddleOCRService(api_url="https://api.example.com", api_key="key")

        # 使用内网 URL，应被 SSRF 校验拦截
        result = await service._download_markdown_result("https://10.0.0.1/result.md")

        assert result == ""
