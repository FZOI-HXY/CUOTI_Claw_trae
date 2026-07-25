"""
安全相关测试: 覆盖之前修复的安全问题

测试覆盖:
  1. 文件名清理 / 路径遍历防护
  2. 任务 ID / history_id 格式验证（防枚举）
  3. 错误消息环境区分（debug 模式）
  4. SQLite WAL 模式
  5. 速率限制
  6. Markdown → HTML 转义（防 XSS）
"""

import io
import os
import sys
import re
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch
from unittest import mock

import pytest
from fastapi.testclient import TestClient

# 路径设置
_backend_path = str(Path(__file__).parent.parent / "apps" / "web" / "api")
if _backend_path in sys.path:
    sys.path.remove(_backend_path)
sys.path.insert(0, _backend_path)

_desktop_path = str(Path(__file__).parent.parent / "apps" / "desktop")
if _desktop_path in sys.path:
    sys.path.remove(_desktop_path)
sys.path.insert(0, _desktop_path)


# ──────────────────────────────────────────────────
# 1. 文件名清理 / 路径遍历防护
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestSecureFilename:
    """测试 _secure_filename 函数"""

    def test_strips_path_traversal(self):
        """路径遍历攻击应被阻止"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "backend_main_sec",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        # 路径遍历尝试
        result = backend._secure_filename("../../etc/passwd")
        assert ".." not in result
        assert "/" not in result
        assert "\\" not in result
        assert "passwd" in result

    def test_strips_windows_path(self):
        """Windows 路径分隔符应被清理"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "backend_main_sec2",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        result = backend._secure_filename("..\\..\\windows\\system32")
        assert ".." not in result
        assert "\\" not in result

    def test_removes_dangerous_chars(self):
        """危险字符应被替换"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "backend_main_sec3",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        dangerous = '<script>alert("xss")</script>:file?"|*.txt'
        result = backend._secure_filename(dangerous)
        for ch in ['<', '>', ':', '"', '|', '?', '*']:
            assert ch not in result, f"危险字符 {ch!r} 未被清理"

    def test_prevents_hidden_files(self):
        """隐藏文件名攻击应被阻止（防止 . 开头）"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "backend_main_sec4",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        result = backend._secure_filename(".hidden_file")
        assert not result.startswith(".")

    def test_length_limit(self):
        """文件名长度应受限"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "backend_main_sec5",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        long_name = "a" * 500 + ".txt"
        result = backend._secure_filename(long_name)
        assert len(result) <= 255

    def test_empty_filename(self):
        """空文件名应返回空或默认值"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "backend_main_sec6",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        result = backend._secure_filename("")
        assert result == ""


# ──────────────────────────────────────────────────
# 2. history_id 格式验证（防枚举）
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestHistoryIdFormat:
    """测试 history_id 使用足够长的随机 ID"""

    def test_history_id_length(self, temp_dir, load_backend_app):
        """history_id 应为 16 字符 hex（64 位熵）"""
        backend = load_backend_app(temp_dir, "history_id_length")

        with patch.object(backend.paddle_service, "submit_task", new_callable=AsyncMock) as ms, \
             patch.object(backend.paddle_service, "poll_once", new_callable=AsyncMock) as mp, \
             patch.object(backend.paddle_service, "extract_result") as me:
            async def _s(*a, **k):
                return {"success": True, "job_id": "mock_job_001"}
            ms.side_effect = _s
            mp.return_value = {"status": "done", "state": "done", "raw_result": {}}
            me.return_value = {"markdown_text": "# T", "images": {}, "layout_image": None, "layout_items": []}

            client = TestClient(backend.app)
            # 上传并完成一个任务
            from PIL import Image
            img = Image.new("RGB", (50, 50))
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            up = client.post("/api/upload", files={"file": ("t.jpg", io.BytesIO(buf.getvalue()), "image/jpeg")})
            fid = up.json()["file_id"]
            sub = client.post(f"/api/submit/{fid}")
            tid = sub.json()["task_id"]
            client.post(f"/api/poll/{tid}")

        # 检查 history_id
        resp = client.get("/api/history")
        items = resp.json()["items"]
        assert len(items) >= 1
        hid = items[0]["id"]
        # history_id 应为 16 字符 hex
        assert len(hid) == 16, f"history_id 长度应为 16，实际 {len(hid)}: {hid}"
        assert re.match(r'^[0-9a-f]{16}$', hid), f"history_id 不是有效的 16 位 hex: {hid}"

    def test_history_ids_are_unique(self, temp_dir, load_backend_app):
        """多个 history_id 应互不相同"""
        backend = load_backend_app(temp_dir, "history_id_unique")

        with patch.object(backend.paddle_service, "submit_task", new_callable=AsyncMock) as ms, \
             patch.object(backend.paddle_service, "poll_once", new_callable=AsyncMock) as mp, \
             patch.object(backend.paddle_service, "extract_result") as me:
            async def _s(*a, **k):
                return {"success": True, "job_id": "mock_job_002"}
            ms.side_effect = _s
            mp.return_value = {"status": "done", "state": "done", "raw_result": {}}
            me.return_value = {"markdown_text": "# T", "images": {}, "layout_image": None, "layout_items": []}

            client = TestClient(backend.app)
            from PIL import Image
            ids = []
            for i in range(5):
                img = Image.new("RGB", (50, 50))
                buf = io.BytesIO()
                img.save(buf, format="JPEG")
                up = client.post("/api/upload", files={"file": (f"t{i}.jpg", io.BytesIO(buf.getvalue()), "image/jpeg")})
                fid = up.json()["file_id"]
                sub = client.post(f"/api/submit/{fid}")
                tid = sub.json()["task_id"]
                client.post(f"/api/poll/{tid}")

            resp = client.get("/api/history")
            ids = [item["id"] for item in resp.json()["items"]]
            assert len(ids) == len(set(ids)), "history_id 存在重复"


# ──────────────────────────────────────────────────
# 3. 错误消息环境区分（debug 模式）
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestErrorMessagesEnv:
    """测试错误消息是否根据 debug 模式区分"""

    def test_debug_false_hides_details(self, temp_dir, load_backend_app):
        """debug=False 时错误消息应隐藏详情"""
        from apps.web.api.config import settings
        original_debug = settings.debug
        settings.debug = False
        try:
            backend = load_backend_app(temp_dir, "debug_false")

            # Mock submit 抛出异常
            with patch.object(backend.paddle_service, "submit_task", new_callable=AsyncMock) as ms:
                async def _raise(*a, **k):
                    raise RuntimeError("SECRET_INTERNAL_PATH_12345 leaked")
                ms.side_effect = _raise

                client = TestClient(backend.app, raise_server_exceptions=False)
                from PIL import Image
                img = Image.new("RGB", (50, 50))
                buf = io.BytesIO()
                img.save(buf, format="JPEG")
                up = client.post("/api/upload", files={"file": ("t.jpg", io.BytesIO(buf.getvalue()), "image/jpeg")})
                fid = up.json()["file_id"]
                resp = client.post(f"/api/submit/{fid}")

            # 生产模式下不应泄露内部错误详情
            assert resp.status_code == 500
            body = resp.json()
            detail = str(body)
            assert "SECRET_INTERNAL_PATH_12345" not in detail, "生产模式下不应泄露内部错误详情"
        finally:
            settings.debug = original_debug

    def test_debug_true_shows_details(self, temp_dir, load_backend_app):
        """debug=True 时错误消息可包含详情"""
        from apps.web.api.config import settings
        original_debug = settings.debug
        settings.debug = True
        try:
            backend = load_backend_app(temp_dir, "debug_true")

            with patch.object(backend.paddle_service, "submit_task", new_callable=AsyncMock) as ms:
                async def _raise(*a, **k):
                    raise RuntimeError("SECRET_DEBUG_DETAIL_98765")
                ms.side_effect = _raise

                client = TestClient(backend.app, raise_server_exceptions=False)
                from PIL import Image
                img = Image.new("RGB", (50, 50))
                buf = io.BytesIO()
                img.save(buf, format="JPEG")
                up = client.post("/api/upload", files={"file": ("t.jpg", io.BytesIO(buf.getvalue()), "image/jpeg")})
                fid = up.json()["file_id"]
                resp = client.post(f"/api/submit/{fid}")

            # debug 模式下应包含详情
            assert resp.status_code == 500
            body = resp.json()
            detail = str(body)
            assert "SECRET_DEBUG_DETAIL_98765" in detail, "debug 模式下应包含错误详情"
        finally:
            settings.debug = original_debug


# ──────────────────────────────────────────────────
# 4. SQLite WAL 模式
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestSQLiteWAL:
    """测试 SQLite WAL 模式是否正确启用"""

    def test_wal_mode_enabled(self, temp_dir, monkeypatch):
        """数据库应启用 WAL 模式"""
        # L23: 使用 monkeypatch 修改 _get_db_path，避免影响真实数据库
        import sys
        ts_module = sys.modules.get("apps.web.api.services.task_service")
        if ts_module is None:
            import importlib
            ts_module = importlib.import_module("apps.web.api.services.task_service")
        db_path = temp_dir / "test_wal.db"
        monkeypatch.setattr(ts_module, "_get_db_path", lambda: db_path)

        svc = ts_module.TaskService()
        db = svc._ensure_db()

        # 查询 journal_mode
        cursor = db.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        assert mode.lower() == "wal", f"journal_mode 应为 wal，实际为 {mode}"

        # 查询 busy_timeout
        cursor = db.execute("PRAGMA busy_timeout")
        timeout = cursor.fetchone()[0]
        assert timeout > 0, f"busy_timeout 应大于 0，实际为 {timeout}"

        svc.close()

    def test_busy_timeout_value(self, temp_dir, monkeypatch):
        """busy_timeout 应为 5000ms"""
        import sys
        ts_module = sys.modules.get("apps.web.api.services.task_service")
        if ts_module is None:
            import importlib
            ts_module = importlib.import_module("apps.web.api.services.task_service")
        db_path = temp_dir / "test_timeout.db"
        monkeypatch.setattr(ts_module, "_get_db_path", lambda: db_path)

        svc = ts_module.TaskService()
        db = svc._ensure_db()

        cursor = db.execute("PRAGMA busy_timeout")
        timeout = cursor.fetchone()[0]
        assert timeout == 5000, f"busy_timeout 应为 5000，实际为 {timeout}"

        svc.close()


# ──────────────────────────────────────────────────
# 5. 速率限制
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestRateLimit:
    """测试 API 速率限制"""

    def test_rate_limit_returns_429(self, temp_dir, load_backend_app):
        """超过速率限制应返回 429"""
        from apps.web.api.config import settings
        original_requests = settings.rate_limit_requests
        original_window = settings.rate_limit_window
        # 设置很低的速率限制便于测试
        settings.rate_limit_requests = 3
        settings.rate_limit_window = 60
        try:
            backend = load_backend_app(temp_dir, "rate_limit_429")
            client = TestClient(backend.app)

            # 发送超过限制的请求（健康检查不限制，用 /api/config）
            statuses = []
            for _ in range(5):
                resp = client.get("/api/config")
                statuses.append(resp.status_code)

            # 应有 429 状态码
            assert 429 in statuses, f"超过速率限制应返回 429，实际状态码: {statuses}"
        finally:
            settings.rate_limit_requests = original_requests
            settings.rate_limit_window = original_window

    def test_health_check_exempt_from_rate_limit(self, temp_dir, load_backend_app):
        """健康检查应豁免速率限制"""
        from apps.web.api.config import settings
        original_requests = settings.rate_limit_requests
        original_window = settings.rate_limit_window
        settings.rate_limit_requests = 2
        settings.rate_limit_window = 60
        try:
            backend = load_backend_app(temp_dir, "rate_limit_health")
            client = TestClient(backend.app)

            # 发送多个健康检查请求
            statuses = []
            for _ in range(10):
                resp = client.get("/api/health")
                statuses.append(resp.status_code)

            # 健康检查不应被限制
            assert all(s == 200 for s in statuses), f"健康检查应豁免速率限制，实际状态码: {statuses}"
        finally:
            settings.rate_limit_requests = original_requests
            settings.rate_limit_window = original_window


# ──────────────────────────────────────────────────
# 6. Markdown → HTML 转义（防 XSS）
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestMarkdownHtmlEscape:
    """测试桌面端 render_markdown_html 的 HTML 转义"""

    @pytest.mark.parametrize("md_content,forbidden_substring,escape_marker", [
        # <script> 标签转义
        ('# Title\n\nSome text <script>alert("xss")</script>',
         "<script>", "&lt;script&gt;"),
        # HTML 事件属性转义
        ('# Title\n\n<img src=x onerror=alert(1)>',
         "<img src=x onerror", "&lt;img"),
        # 表格内容转义
        ('| 列1 | 列2 |\n| --- | --- |\n| <b>bold</b> | normal |',
         "<b>bold</b>", "&lt;b&gt;"),
        # 行内代码中的特殊字符转义
        ('Some `code <script>` here',
         "<script>", None),
        # 引用块中的 HTML 转义
        ('> <img src=x onerror=alert(1)>',
         "<img src=x onerror", "&lt;img"),
        # 图片 alt 文本转义
        ('![<script>alert(1)</script>](http://example.com/img.png)',
         "<script>alert(1)</script>", None),
        # 代码块内容转义
        ('```json\n{"evil": "</script><script>alert(1)</script>"}\n```',
         "<script>alert(1)</script>", None),
    ])
    def test_xss_payloads_escaped(self, md_content, forbidden_substring, escape_marker):
        """各类 XSS 载荷应被转义，不应存在未转义的恶意标签"""
        from utils import render_markdown_html
        html = render_markdown_html(md_content)

        assert forbidden_substring not in html, f"未转义的恶意内容存在: {forbidden_substring}"
        if escape_marker is not None:
            assert escape_marker in html, f"转义标记 {escape_marker} 未找到"

    @pytest.mark.parametrize("md_content,checks", [
        # 空输入应返回有效 HTML
        ("", ["<html>", "</html>"]),
        # 正常 Markdown 标记应保留
        ('# Title\n\n**bold** and *italic*', ["<h1>", "<strong>", "<em>"]),
    ])
    def test_safe_and_empty_input(self, md_content, checks):
        """空输入和正常 Markdown 应正确处理"""
        from utils import render_markdown_html
        html = render_markdown_html(md_content)
        for check in checks:
            assert check in html, f"期望包含 {check!r}，实际未包含"


# ──────────────────────────────────────────────────
# 8. 工具函数测试
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestUtils:
    """测试桌面端工具函数"""

    def test_format_size_bytes(self):
        """字节单位格式化"""
        from utils import format_size
        assert format_size(0) == "0 B"
        assert format_size(512) == "512 B"
        assert format_size(1023) == "1023 B"

    def test_format_size_kb(self):
        """KB 单位格式化"""
        from utils import format_size
        assert format_size(1024) == "1.0 KB"
        assert format_size(2048) == "2.0 KB"
        assert format_size(1536) == "1.5 KB"

    def test_format_size_mb(self):
        """MB 单位格式化"""
        from utils import format_size
        assert format_size(1024 * 1024) == "1.0 MB"
        assert format_size(5 * 1024 * 1024) == "5.0 MB"
        assert format_size(1024 * 1024 + 512 * 1024) == "1.5 MB"

    def test_format_size_large(self):
        """大文件格式化"""
        from utils import format_size
        assert format_size(10 * 1024 * 1024) == "10.0 MB"


# ──────────────────────────────────────────────────
# 9. 安全工具函数测试
# ──────────────────────────────────────────

@pytest.mark.unit
class TestSecurityUtils:
    """测试 main.py 中的安全工具函数"""

    def test_extract_safe_extension(self):
        """_extract_safe_extension 应安全提取扩展名"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "backend_main_sec_ext",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        assert backend._extract_safe_extension("test.jpg") == ".jpg"
        assert backend._extract_safe_extension("test.png") == ".png"
        assert backend._extract_safe_extension("../../etc/passwd.exe") == ".exe"
        assert backend._extract_safe_extension("no_extension") == ".png"
        assert backend._extract_safe_extension("") == ".png"
        assert backend._extract_safe_extension("file.with.multiple.dots.txt") == ".txt"

    def test_validate_file_id_valid(self):
        """_validate_file_id 应接受有效格式"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "backend_main_fid",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        valid_id = "a" * 32
        backend._validate_file_id(valid_id)

    def test_validate_file_id_invalid(self):
        """_validate_file_id 应拒绝无效格式"""
        import importlib.util
        from fastapi import HTTPException
        spec = importlib.util.spec_from_file_location(
            "backend_main_fid2",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        for bad_id in ["", "short", "a" * 31, "a" * 33, "invalid_chars!@#", "../../etc/passwd"]:
            with pytest.raises(HTTPException) as exc_info:
                backend._validate_file_id(bad_id)
            assert exc_info.value.status_code == 400

    def test_is_internal_ip(self):
        """_is_internal_ip 应正确识别内网地址"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "backend_main_internal",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        assert backend._is_internal_ip("localhost") is True
        assert backend._is_internal_ip("127.0.0.1") is True
        assert backend._is_internal_ip("10.0.0.1") is True
        assert backend._is_internal_ip("192.168.1.1") is True
        assert backend._is_internal_ip("172.16.0.1") is True
        assert backend._is_internal_ip("0.0.0.0") is True
        assert backend._is_internal_ip("169.254.1.1") is True
        assert backend._is_internal_ip("::1") is True

        assert backend._is_internal_ip("8.8.8.8") is False
        assert backend._is_internal_ip("example.com") is False
        assert backend._is_internal_ip("1.2.3.4") is False

    def test_is_internal_ip_dns_resolution(self):
        """_is_internal_ip 应检测解析到内网 IP 的域名（防 SSRF 绕过）"""
        import importlib.util
        import socket
        spec = importlib.util.spec_from_file_location(
            "backend_main_internal_dns",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.side_effect = [
                [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.168.1.1", 0))],
                socket.gaierror,
            ]
            assert backend._is_internal_ip("evil-domain.com") is True

        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.side_effect = [
                [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 0))],
                socket.gaierror,
            ]
            assert backend._is_internal_ip("good-domain.com") is False

    def test_resolve_and_validate_ip_returns_public_ip(self):
        """_resolve_and_validate_ip 应返回首个公网 IP（防 DNS 重绑定）"""
        import importlib.util
        import socket
        spec = importlib.util.spec_from_file_location(
            "backend_main_resolve",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.side_effect = [
                [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 0))],
                socket.gaierror,
            ]
            result = backend._resolve_and_validate_ip("example.com")
            assert result == "93.184.216.34"

    def test_resolve_and_validate_ip_rejects_localhost(self):
        """_resolve_and_validate_ip 应拒绝 localhost"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "backend_main_resolve_localhost",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        result = backend._resolve_and_validate_ip("localhost")
        assert result is None

    def test_resolve_and_validate_ip_rejects_internal_ip(self):
        """_resolve_and_validate_ip 应拒绝内网 IP"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "backend_main_resolve_internal",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        assert backend._resolve_and_validate_ip("127.0.0.1") is None
        assert backend._resolve_and_validate_ip("192.168.1.1") is None
        assert backend._resolve_and_validate_ip("10.0.0.1") is None
        assert backend._resolve_and_validate_ip("172.16.0.1") is None
        assert backend._resolve_and_validate_ip("::1") is None

    def test_resolve_and_validate_ip_rejects_domain_resolving_to_internal(self):
        """_resolve_and_validate_ip 应拒绝解析到内网 IP 的域名（防 DNS 重绑定）"""
        import importlib.util
        import socket
        spec = importlib.util.spec_from_file_location(
            "backend_main_resolve_dns",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.side_effect = [
                [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.168.1.100", 0))],
                socket.gaierror,
            ]
            result = backend._resolve_and_validate_ip("evil-ssrf.example.com")
            assert result is None

    def test_resolve_and_validate_ip_returns_first_public_ip_from_multiple(self):
        """_resolve_and_validate_ip 应从多个 IP 中返回首个公网 IP"""
        import importlib.util
        import socket
        spec = importlib.util.spec_from_file_location(
            "backend_main_resolve_multi",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.side_effect = [
                [
                    (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.168.1.1", 0)),
                    (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 0)),
                    (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.0.0.1", 0)),
                ],
                socket.gaierror,
            ]
            result = backend._resolve_and_validate_ip("mixed-ips.example.com")
            assert result == "93.184.216.34"

    def test_resolve_and_validate_ip_returns_ipv6_public(self):
        """_resolve_and_validate_ip 应正确处理 IPv6 公网地址"""
        import importlib.util
        import socket
        spec = importlib.util.spec_from_file_location(
            "backend_main_resolve_ipv6",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.side_effect = [
                socket.gaierror,
                [(socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("2606:2800:220:1:248:1893:25c8:1946", 0, 0, 0))],
            ]
            result = backend._resolve_and_validate_ip("ipv6.example.com")
            assert result == "2606:2800:220:1:248:1893:25c8:1946"

    def test_resolve_and_validate_ip_rejects_ipv6_local(self):
        """_resolve_and_validate_ip 应拒绝 IPv6 本地地址"""
        import importlib.util
        import socket
        spec = importlib.util.spec_from_file_location(
            "backend_main_resolve_ipv6_local",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.side_effect = [
                socket.gaierror,
                [(socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("fc00::1", 0, 0, 0))],
            ]
            result = backend._resolve_and_validate_ip("local-ipv6.example.com")
            assert result is None

    def test_resolve_and_validate_ip_dns_failure_returns_none(self):
        """DNS 解析失败时应返回 None"""
        import importlib.util
        import socket
        spec = importlib.util.spec_from_file_location(
            "backend_main_resolve_fail",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.side_effect = socket.gaierror
            result = backend._resolve_and_validate_ip("non-existent-domain-xyz123.com")
            assert result is None

    def test_validate_file_url_valid(self):
        """_validate_file_url 应接受有效 URL"""
        import importlib.util
        from unittest.mock import patch
        import socket as _socket
        spec = importlib.util.spec_from_file_location(
            "backend_main_url",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        # B6: _validate_file_url 现在做真实 DNS 解析，需 mock 公网 IP 避免测试环境依赖
        with patch.object(backend, '_resolve_and_validate_ip', return_value='93.184.216.34'):
            backend._validate_file_url("https://example.com/image.jpg")
            backend._validate_file_url("https://cdn.example.com/path/to/file.png")

    def test_validate_file_url_invalid(self):
        """_validate_file_url 应拒绝无效 URL"""
        import importlib.util
        from fastapi import HTTPException
        spec = importlib.util.spec_from_file_location(
            "backend_main_url2",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        with pytest.raises(HTTPException) as exc_info:
            backend._validate_file_url("http://example.com/image.jpg")
        assert exc_info.value.status_code == 400

        with pytest.raises(HTTPException) as exc_info:
            backend._validate_file_url("https://localhost/image.jpg")
        assert exc_info.value.status_code == 400

        with pytest.raises(HTTPException) as exc_info:
            backend._validate_file_url("https://127.0.0.1/image.jpg")
        assert exc_info.value.status_code == 400

        with pytest.raises(HTTPException) as exc_info:
            backend._validate_file_url("")
        assert exc_info.value.status_code == 400

    def test_check_magic_bytes_valid(self):
        """_check_magic_bytes 应接受有效图片格式"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "backend_main_magic",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        backend._check_magic_bytes(b"\xff\xd8\xff\x00")
        backend._check_magic_bytes(b"\x89PNG\r\n")
        backend._check_magic_bytes(b"%PDF-")
        backend._check_magic_bytes(b"BM\x00\x00")
        # WebP: RIFF....WEBP（bytes 0-3=RIFF, bytes 8-11=WEBP）
        backend._check_magic_bytes(b"RIFF\x00\x00\x00\x00WEBP")

    def test_check_magic_bytes_invalid(self):
        """_check_magic_bytes 应拒绝无效格式"""
        import importlib.util
        from fastapi import HTTPException
        spec = importlib.util.spec_from_file_location(
            "backend_main_magic2",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        with pytest.raises(HTTPException) as exc_info:
            backend._check_magic_bytes(b"invalid content")
        assert exc_info.value.status_code == 400

        with pytest.raises(HTTPException) as exc_info:
            backend._check_magic_bytes(b"")
        assert exc_info.value.status_code == 400

        with pytest.raises(HTTPException) as exc_info:
            backend._check_magic_bytes(b"\x00\x00\x00")
        assert exc_info.value.status_code == 400

        # AVI 文件也以 RIFF 开头，但 bytes 8-11 不是 WEBP，应被拒绝
        with pytest.raises(HTTPException) as exc_info:
            backend._check_magic_bytes(b"RIFF\x00\x00\x00\x00AVI ")
        assert exc_info.value.status_code == 400

    def test_safe_report_image_path(self):
        """_safe_report_image_path 应防止路径穿越"""
        import importlib.util
        from fastapi import HTTPException
        spec = importlib.util.spec_from_file_location(
            "backend_main_img",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        with tempfile.TemporaryDirectory() as tmp_dir:
            report_dir = Path(tmp_dir) / "report"
            report_dir.mkdir()

            result = backend._safe_report_image_path(report_dir, "valid_image.png")
            assert result == report_dir / "valid_image.png"

            with pytest.raises(HTTPException) as exc_info:
                backend._safe_report_image_path(report_dir, "../malicious.png")
            assert exc_info.value.status_code == 400

            with pytest.raises(HTTPException) as exc_info:
                backend._safe_report_image_path(report_dir, "/etc/passwd")
            assert exc_info.value.status_code == 400


# ──────────────────────────────────────────────────
# 9.5 _safe_report_dir 安全路径校验测试
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestSafeReportDir:
    """测试 _safe_report_dir 函数的路径安全校验"""

    def test_safe_report_dir_valid_id(self, temp_dir):
        """有效 report_id 应返回正确的目录路径"""
        import importlib.util
        from fastapi import HTTPException
        spec = importlib.util.spec_from_file_location(
            "backend_main_safe_dir",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        from apps.web.api.config import settings
        original_output = settings.output_dir
        settings.output_dir = str(temp_dir / "output")
        Path(settings.output_dir).mkdir(parents=True, exist_ok=True)

        try:
            valid_id = "20260613_235614_a1b2c3d4"
            result = backend._safe_report_dir(valid_id)
            expected = Path(settings.output_dir) / valid_id
            assert result.resolve() == expected.resolve()
        finally:
            settings.output_dir = original_output

    def test_safe_report_dir_empty_id(self):
        """空 report_id 应返回 400"""
        import importlib.util
        from fastapi import HTTPException
        spec = importlib.util.spec_from_file_location(
            "backend_main_safe_dir_empty",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        with pytest.raises(HTTPException) as exc_info:
            backend._safe_report_dir("")
        assert exc_info.value.status_code == 400

    def test_safe_report_dir_path_traversal(self, temp_dir):
        """路径穿越攻击应被阻止"""
        import importlib.util
        from fastapi import HTTPException
        spec = importlib.util.spec_from_file_location(
            "backend_main_safe_dir_traverse",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        from apps.web.api.config import settings
        original_output = settings.output_dir
        settings.output_dir = str(temp_dir / "output")
        Path(settings.output_dir).mkdir(parents=True, exist_ok=True)

        try:
            malicious_ids = [
                "../../etc/passwd",
                "../secret",
                "..\\windows\\system32",
                "output/../../etc/passwd",
            ]
            for mid in malicious_ids:
                with pytest.raises(HTTPException) as exc_info:
                    backend._safe_report_dir(mid)
                assert exc_info.value.status_code == 400, f"应拒绝路径穿越: {mid}"
        finally:
            settings.output_dir = original_output

    def test_safe_report_dir_rejects_file_as_dir(self, temp_dir):
        """同名普通文件应被拒绝（防止误删文件）"""
        import importlib.util
        from fastapi import HTTPException
        spec = importlib.util.spec_from_file_location(
            "backend_main_safe_dir_file",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        from apps.web.api.config import settings
        original_output = settings.output_dir
        settings.output_dir = str(temp_dir / "output")
        Path(settings.output_dir).mkdir(parents=True, exist_ok=True)

        try:
            file_path = Path(settings.output_dir) / "fake_report"
            file_path.write_text("not a directory")

            with pytest.raises(HTTPException) as exc_info:
                backend._safe_report_dir("fake_report")
            assert exc_info.value.status_code == 400
        finally:
            settings.output_dir = original_output
            if file_path.exists():
                file_path.unlink()

    def test_safe_report_dir_non_existent_valid_id(self, temp_dir):
        """不存在但格式有效的 report_id 应返回路径（不报错，供后续创建）"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "backend_main_safe_dir_nonexist",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        from apps.web.api.config import settings
        original_output = settings.output_dir
        settings.output_dir = str(temp_dir / "output")
        Path(settings.output_dir).mkdir(parents=True, exist_ok=True)

        try:
            valid_id = "non_existent_report"
            result = backend._safe_report_dir(valid_id)
            expected = Path(settings.output_dir) / valid_id
            assert result.resolve() == expected.resolve()
        finally:
            settings.output_dir = original_output


# ──────────────────────────────────────────────────
# 9.6 report_id 格式校验测试
# ──────────────────────────────────────────────────


@pytest.mark.unit
class TestIsValidReportIdFormat:
    """测试 _is_valid_report_id_format 函数的格式校验

    该函数用于批量下载端点过滤格式非法的 report_id，防止路径穿越和 Shell 注入。
    """

    @pytest.mark.parametrize("report_id,expected", [
        # 合法格式
        ("20260613_235614_a1b2c3d4", True),   # 标准格式 YYYYMMDD_HHMMSS_<8hex>
        ("20260613_235614", True),             # 旧格式（无 hex 后缀）
        ("20260613_235614_A1B2C3D4", True),    # 大写 hex 兼容
        ("report-1", True),                    # 含连字符
        ("a" * 64, True),                      # 刚好 64 字符（边界值）
        # 非法格式
        ("", False),                           # 空字符串
        ("a" * 65, False),                     # 超长字符串（>64 字符）
    ])
    def test_valid_and_invalid_formats(self, report_id, expected):
        """合法与非法格式的边界值测试"""
        from apps.web.api.main import _is_valid_report_id_format
        assert _is_valid_report_id_format(report_id) is expected

    @pytest.mark.parametrize("malicious", [
        # 路径穿越
        "../../etc/passwd",
        "../secret",
        "..\\windows\\system32",
        # Shell 元字符
        "report|test",
        "report;rm -rf",
        "report`echo`",
        "report$x",
        "report>out",
        "report&bg",
        # 路径分隔符
        "report/test",
        "report\\test",
    ])
    def test_malicious_ids_rejected(self, malicious):
        """恶意 ID（路径穿越、Shell 注入、路径分隔符）应被拒绝"""
        from apps.web.api.main import _is_valid_report_id_format
        assert _is_valid_report_id_format(malicious) is False, f"应拒绝: {malicious}"

    @pytest.mark.parametrize("report_id,expected", [
        ("report.test", False),   # 含点号（不在白名单字符集内）
        ("report test", False),   # 含空格
    ])
    def test_special_chars_rejected(self, report_id, expected):
        """点号和空格应被拒绝"""
        from apps.web.api.main import _is_valid_report_id_format
        assert _is_valid_report_id_format(report_id) is expected


# ──────────────────────────────────────────────────
# 10. 认证中间件测试
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestAuthMiddleware:
    """测试认证中间件的安全防护"""

    def test_auth_middleware_rejects_invalid_token(self, temp_dir, load_backend_app):
        """无效 token 应被拒绝（401 Unauthorized）"""
        from apps.web.api.config import settings
        original_token = settings.claw_auth_token
        backend = load_backend_app(temp_dir, "auth_reject")
        settings.claw_auth_token = "valid_test_token_123"
        try:
            client = TestClient(backend.app)

            # POST 请求需要认证
            resp = client.post("/api/config", json={"log_level": "DEBUG"})
            assert resp.status_code == 401, "无效 token 应返回 401"
            assert resp.json()["code"] == "UNAUTHORIZED"

            # 错误的 token
            resp = client.post("/api/config", json={"log_level": "DEBUG"}, headers={"X-Claw-Token": "wrong_token"})
            assert resp.status_code == 401
        finally:
            settings.claw_auth_token = original_token

    def test_auth_middleware_accepts_valid_token(self, temp_dir, load_backend_app):
        """有效 token 应被接受"""
        from apps.web.api.config import settings
        original_token = settings.claw_auth_token
        backend = load_backend_app(temp_dir, "auth_accept")
        settings.claw_auth_token = "valid_test_token_456"
        try:
            client = TestClient(backend.app)

            # 正确的 token
            resp = client.post(
                "/api/config",
                json={"log_level": "DEBUG"},
                headers={"X-Claw-Token": "valid_test_token_456"}
            )
            assert resp.status_code == 200, "有效 token 应被接受"
        finally:
            settings.claw_auth_token = original_token

    def test_auth_middleware_protects_get_business_endpoints(self, temp_dir, load_backend_app):
        """F-001 修复：GET 请求访问业务端点需要认证（不再全局豁免）"""
        from apps.web.api.config import settings
        original_token = settings.claw_auth_token
        # 先加载 backend（会清除 token），再设置 token
        backend = load_backend_app(temp_dir, "auth_get_protect")
        settings.claw_auth_token = "test_token_for_auth"
        try:
            client = TestClient(backend.app)

            # GET 业务端点无 token 应返回 401
            resp = client.get("/api/config")
            assert resp.status_code == 401, "GET /api/config 无 token 应返回 401"

            resp = client.get("/api/history")
            assert resp.status_code == 401, "GET /api/history 无 token 应返回 401"

            resp = client.get("/api/reports")
            assert resp.status_code == 401, "GET /api/reports 无 token 应返回 401"

            # 带正确 token 的 GET 请求应通过
            resp = client.get("/api/config", headers={"X-Claw-Token": "test_token_for_auth"})
            assert resp.status_code == 200, "GET /api/config 带正确 token 应返回 200"

            # ?token= 查询参数也应通过（图片端点回退）
            resp = client.get("/api/config?token=test_token_for_auth")
            assert resp.status_code == 200, "GET /api/config?token= 查询参数应返回 200"

            # 错误 token 应返回 401
            resp = client.get("/api/config?token=wrong_token")
            assert resp.status_code == 401, "GET /api/config?token=wrong 应返回 401"
        finally:
            settings.claw_auth_token = original_token

    def test_auth_middleware_exempt_for_health_check(self, temp_dir, load_backend_app):
        """健康检查端点不需要认证"""
        from apps.web.api.config import settings
        original_token = settings.claw_auth_token
        backend = load_backend_app(temp_dir, "auth_health_exempt")
        settings.claw_auth_token = "test_token_health"
        try:
            client = TestClient(backend.app)

            # 健康检查不需要认证（POST 请求）
            resp = client.get("/api/health")
            assert resp.status_code == 200
        finally:
            settings.claw_auth_token = original_token


# ──────────────────────────────────────────────────
# 11. 安全响应头中间件测试
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestSecurityHeadersMiddleware:
    """测试安全响应头中间件"""

    def test_security_headers_present(self, temp_dir, load_backend_app):
        """所有响应应包含安全响应头"""
        backend = load_backend_app(temp_dir, "sec_headers")
        client = TestClient(backend.app)

        resp = client.get("/api/health")
        assert resp.status_code == 200

        # 检查安全响应头
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("X-XSS-Protection") == "1; mode=block"
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert "Content-Security-Policy" in resp.headers

    def test_csp_header_restricts_script_sources(self, temp_dir, load_backend_app):
        """CSP 头应限制脚本来源"""
        backend = load_backend_app(temp_dir, "csp")
        client = TestClient(backend.app)

        resp = client.get("/api/health")
        csp = resp.headers.get("Content-Security-Policy", "")

        # CSP 应限制 script-src
        assert "script-src" in csp
        # 验证 script-src 指令不含外域 URL（保留原覆盖点，仅放宽字符串切片脆性）
        # 用 directive 迭代替代 split("script-src")[1].split(";")[0]，避免 CSP 格式变化时切片越界
        script_src_part = ""
        for directive in csp.split(";"):
            if "script-src" in directive:
                script_src_part = directive
                break
        assert "https://" not in script_src_part
        assert "http://" not in script_src_part


# ──────────────────────────────────────────────────
# 12. Markdown 渲染长度限制测试
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestMarkdownLengthLimit:
    """测试 Markdown 渲染的长度限制防护"""

    def test_markdown_length_limit_rejects_oversized(self):
        """超大 Markdown 文本应被拒绝渲染"""
        from utils import render_markdown_html

        # 创建超大文本（超过 5MB）
        oversized_md = "a" * (6 * 1024 * 1024)
        html = render_markdown_html(oversized_md)

        # 应返回错误消息而不是渲染
        assert "<html>" in html
        assert "Markdown 文本过长" in html or "性能问题" in html
        # 不应包含原始内容的渲染
        assert "<h1>" not in html
        assert "<body>" in html

    def test_markdown_length_limit_accepts_normal(self):
        """正常大小的 Markdown 应被正确渲染"""
        from utils import render_markdown_html

        # 正常大小文本
        normal_md = "# Test Title\n\n**bold text** and *italic*\n\n```\ncode block\n```"
        html = render_markdown_html(normal_md)

        # 应正常渲染
        assert "<html>" in html
        assert "<h1>" in html
        assert "<strong>" in html
        assert "<em>" in html
        # 代码块内容应被转义后显示
        assert "code block" in html

    def test_markdown_length_limit_boundary(self):
        """边界值测试（接近限制）"""
        from utils import render_markdown_html

        # 接近但不超过限制（4.9MB）
        boundary_md = "# Test\n\n" + "content " * (4 * 1024 * 1024 // 8)
        html = render_markdown_html(boundary_md)

        # 应正常渲染
        assert "<html>" in html
        assert "<h1>" in html
        # 不应出现长度限制警告
        assert "过长" not in html


# ──────────────────────────────────────────────────
# 13. 速率限制存储清理测试
# ──────────────────────────────────────────────────


@pytest.mark.unit
class TestCleanupRateLimitStore:
    """测试 _cleanup_rate_limit_store 函数的内存泄漏防护"""

    def test_cleanup_rate_limit_store_removes_expired_entries(self):
        """应移除过期的速率限制条目"""
        import importlib.util
        import time
        spec = importlib.util.spec_from_file_location(
            "backend_main_cleanup",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        window = backend.settings.rate_limit_window
        now = time.time()

        backend._rate_limit_store = {
            "client1": [now - window - 10],
            "client2": [now - 10],
            "client3": [now],
        }

        backend._cleanup_rate_limit_store()

        assert "client1" not in backend._rate_limit_store
        assert "client2" in backend._rate_limit_store
        assert "client3" in backend._rate_limit_store

    def test_cleanup_rate_limit_store_removes_entries_exceeding_max_age(self):
        """应移除超过最大存活时间的条目"""
        import importlib.util
        import time
        spec = importlib.util.spec_from_file_location(
            "backend_main_cleanup_max",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        window = backend.settings.rate_limit_window
        now = time.time()

        backend._rate_limit_store = {}
        for i in range(100):
            backend._rate_limit_store[f"client{i}"] = [now - (window + 10 - i)]

        backend._cleanup_rate_limit_store()

        for key in backend._rate_limit_store:
            for ts in backend._rate_limit_store[key]:
                assert now - ts < window

    def test_cleanup_rate_limit_store_handles_empty_store(self):
        """空存储应被正确处理"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "backend_main_cleanup_empty",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        backend._rate_limit_store = {}
        backend._cleanup_rate_limit_store()
        assert backend._rate_limit_store == {}

    def test_cleanup_rate_limit_store_preserves_fresh_entries(self):
        """应保留新鲜的条目"""
        import importlib.util
        import time
        spec = importlib.util.spec_from_file_location(
            "backend_main_cleanup_fresh",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        window = backend.settings.rate_limit_window
        now = time.time()

        backend._rate_limit_store = {
            "client1": [now - window + 10, now - window + 5],
            "client2": [now - 1],
        }

        backend._cleanup_rate_limit_store()

        assert "client1" in backend._rate_limit_store
        assert len(backend._rate_limit_store["client1"]) == 2
        assert "client2" in backend._rate_limit_store
        assert len(backend._rate_limit_store["client2"]) == 1


# ──────────────────────────────────────────────────
# 14. 批量下载ZIP路径穿越处理测试（F-001修复补测）
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestBatchDownloadZipPathTraversal:
    """测试批量下载ZIP打包中的路径穿越防护（_build_batch_zip try/except）"""

    def test_batch_download_skips_invalid_report_id(self, temp_dir, load_backend_app):
        """批量下载应跳过路径穿越格式的report_id，继续处理其他合法ID"""
        import io
        import zipfile
        backend = load_backend_app(temp_dir, "batch_zip_invalid")

        # 创建一个合法的报告目录
        output_dir = backend.settings.get_output_path()
        valid_report_dir = output_dir / "valid_report_123"
        valid_report_dir.mkdir(parents=True, exist_ok=True)
        (valid_report_dir / "report.md").write_text("# Valid Report")

        client = TestClient(backend.app)

        # 包含路径穿越ID和合法ID的混合请求
        resp = client.post(
            "/api/batch/download",
            json={"report_ids": ["../../etc/passwd", "valid_report_123"]},
        )

        # 应返回200（跳过非法ID，继续处理合法ID）
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"

        # 验证ZIP内容包含合法报告
        zip_data = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_data, "r") as zf:
            names = zf.namelist()
            # 合法报告应在ZIP中
            assert any("valid_report_123" in n for n in names)

    def test_batch_download_handles_nonexistent_report_gracefully(self, temp_dir, load_backend_app):
        """批量下载应跳过不存在的报告ID，不报错"""
        import io
        import zipfile
        backend = load_backend_app(temp_dir, "batch_zip_nonexist")

        # 创建一个报告
        output_dir = backend.settings.get_output_path()
        report_dir = output_dir / "existing_report"
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.md").write_text("# Test")

        client = TestClient(backend.app)

        resp = client.post(
            "/api/batch/download",
            json={"report_ids": ["nonexistent_report", "existing_report"]},
        )

        assert resp.status_code == 200
        zip_data = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_data, "r") as zf:
            names = zf.namelist()
            assert any("existing_report" in n for n in names)

    def test_batch_download_all_invalid_returns_400(self, temp_dir, load_backend_app):
        """所有report_id格式均非法时应返回400"""
        backend = load_backend_app(temp_dir, "batch_zip_all_invalid")

        client = TestClient(backend.app)

        resp = client.post(
            "/api/batch/download",
            json={"report_ids": ["../../etc/passwd", "../secret", "..\\windows"]},
        )

        assert resp.status_code == 400
        assert "格式均非法" in resp.json()["error"] or "invalid" in resp.json()["error"].lower()


# ──────────────────────────────────────────────────
# 15. 图片端点token查询参数回退测试（F-001修复补测）
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestImageEndpointTokenFallback:
    """测试图片端点通过?token=查询参数传递认证（<img src>无法附加自定义头）"""

    def test_image_endpoint_accepts_token_query_param(self, temp_dir, load_backend_app):
        """图片端点应接受?token=查询参数作为认证回退"""
        from apps.web.api.config import settings
        original_token = settings.claw_auth_token
        backend = load_backend_app(temp_dir, "image_token_fallback")
        settings.claw_auth_token = "test_image_token_xyz"
        try:

            # 创建报告和图片
            output_dir = settings.get_output_path()
            report_dir = output_dir / "test_report_img"
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / "report.md").write_text("# Test")
            (report_dir / "imgs").mkdir(exist_ok=True)
            img_path = report_dir / "imgs" / "test.png"
            img_path.write_bytes(b'\x89PNG\r\n\x1a\n' + b'X' * 100)

            client = TestClient(backend.app)

            # 无token应返回401
            resp = client.get(f"/api/report/test_report_img/image/imgs/test.png")
            assert resp.status_code == 401

            # 错误token应返回401
            resp = client.get(f"/api/report/test_report_img/image/imgs/test.png?token=wrong")
            assert resp.status_code == 401

            # 正确token应返回200
            resp = client.get(f"/api/report/test_report_img/image/imgs/test.png?token=test_image_token_xyz")
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "image/png"
        finally:
            settings.claw_auth_token = original_token

    def test_image_endpoint_rejects_without_auth(self, temp_dir, load_backend_app):
        """图片端点无认证应返回401"""
        from apps.web.api.config import settings
        original_token = settings.claw_auth_token
        backend = load_backend_app(temp_dir, "image_no_auth")
        settings.claw_auth_token = "img_auth_required"
        try:

            output_dir = settings.get_output_path()
            report_dir = output_dir / "report_auth_test"
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / "report.md").write_text("# Test")
            (report_dir / "imgs").mkdir(exist_ok=True)
            img_path = report_dir / "imgs" / "img.jpg"
            img_path.write_bytes(b'\xff\xd8\xff' + b'Y' * 50)

            client = TestClient(backend.app)

            # 无token查询参数
            resp = client.get("/api/report/report_auth_test/image/imgs/img.jpg")
            assert resp.status_code == 401
        finally:
            settings.claw_auth_token = original_token


# ──────────────────────────────────────────────────
# 16. 并发轮询互斥API层集成测试（F-001修复补测）
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestPollMutexApiIntegration:
    """测试并发轮询互斥机制的API层集成（防止TOCTOU竞态）"""

    def test_concurrent_poll_requests_return_mutex_message(self, temp_dir, load_backend_app):
        """并发轮询同一task_id时，后续请求应返回'另一个轮询请求正在处理中'消息"""
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import AsyncMock, patch

        backend = load_backend_app(temp_dir, "poll_mutex_api")

        # Mock poll_once使其延迟返回，模拟长时间处理
        original_poll_once = backend.paddle_service.poll_once

        async def slow_poll_once(task_id, filename):
            await asyncio.sleep(0.5)  # 模拟500ms处理时间
            return {"status": "done", "state": "done", "raw_result": {}}

        with patch.object(backend.paddle_service, "poll_once", new_callable=AsyncMock) as mock_poll:
            mock_poll.side_effect = slow_poll_once

            # Mock extract_result
            with patch.object(backend.paddle_service, "extract_result") as mock_extract:
                mock_extract.return_value = {
                    "markdown_text": "# T",
                    "images": {},
                    "layout_image": None,
                    "layout_items": []
                }

                # 预先设置任务状态
                backend.ts.set_task("test_mutex_task", {
                    "status": "processing",
                    "filename": "test.jpg",
                    "file_id": "abc123",
                    "job_id": "test_mutex_task",
                    "submit_time": "2026-01-01T00:00:00"
                })

                client = TestClient(backend.app)
                results = []

                def poll_request():
                    resp = client.post("/api/poll/test_mutex_task")
                    results.append(resp.json())

                # 并发发送2个轮询请求
                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = [executor.submit(poll_request) for _ in range(2)]
                    for f in futures:
                        f.result()

                # 至少有一个请求应收到"另一个轮询请求正在处理中"消息
                mutex_messages = [r for r in results if r.get("progress", {}).get("message") == "另一个轮询请求正在处理中"]
                assert len(mutex_messages) >= 1, f"应至少有1个请求收到互斥消息，实际: {results}"


# ──────────────────────────────────────────────────
# 17. 批量下载layout报告XSS转义测试（F-001修复补测）
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestBatchLayoutReportXssEscape:
    """测试批量下载layout报告中item_type和content_preview的XSS转义"""

    def test_batch_layout_escapes_item_type_xss(self, temp_dir, load_backend_app):
        """item_type中的XSS载荷应被转义"""
        backend = load_backend_app(temp_dir, "layout_xss_type")

        client = TestClient(backend.app)

        # 包含XSS载荷的layout_items
        malicious_items = [
            {
                "type": "<script>alert('xss')</script>",
                "region": {"bbox": [0, 0, 100, 100]},
                "content_preview": "normal content"
            }
        ]

        resp = client.post(
            "/api/batch/download-layout",
            json={
                "files": [
                    {
                        "filename": "test_file.pdf",
                        "layout_items": malicious_items,
                        "processing_time": 1.5
                    }
                ]
            }
        )

        assert resp.status_code == 200
        content = resp.text

        # <script>标签应被转义为 &lt;script&gt;
        assert "<script>" not in content, "item_type中的<script>标签未被转义"
        assert "&lt;script&gt;" in content, "item_type应包含转义后的&lt;script&gt;"

    def test_batch_layout_escapes_content_preview_xss(self, temp_dir, load_backend_app):
        """content_preview中的XSS载荷应被转义"""
        backend = load_backend_app(temp_dir, "layout_xss_preview")

        client = TestClient(backend.app)

        malicious_items = [
            {
                "type": "text",
                "region": {"x": 0, "y": 0, "width": 100, "height": 50},
                "content_preview": "<img src=x onerror=alert(1)>evil content"
            }
        ]

        resp = client.post(
            "/api/batch/download-layout",
            json={
                "files": [
                    {
                        "filename": "normal_file.jpg",
                        "layout_items": malicious_items,
                        "processing_time": 2.0
                    }
                ]
            }
        )

        assert resp.status_code == 200
        content = resp.text

        # <img>标签应被转义
        assert "<img src=x onerror" not in content, "content_preview中的<img>标签未被转义"
        assert "&lt;img" in content, "content_preview应包含转义后的&lt;img"

    def test_batch_layout_escapes_filename_special_chars(self, temp_dir, load_backend_app):
        """filename中的Markdown特殊字符应被转义"""
        backend = load_backend_app(temp_dir, "layout_xss_filename")

        client = TestClient(backend.app)

        resp = client.post(
            "/api/batch/download-layout",
            json={
                "files": [
                    {
                        "filename": "test|file`name<script>.pdf",
                        "layout_items": [
                            {"type": "text", "region": {}, "content_preview": "normal"}
                        ],
                        "processing_time": 1.0
                    }
                ]
            }
        )

        assert resp.status_code == 200
        content = resp.text

        # filename中的特殊字符应被转义
        assert "<script>" not in content, "filename中的<script>未被转义"
        assert "&lt;script&gt;" in content, "filename应包含转义后的&lt;script&gt;"
