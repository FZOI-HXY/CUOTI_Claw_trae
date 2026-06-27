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

@pytest.mark.unit
class TestHistoryIdFormat:
    """测试 history_id 使用足够长的随机 ID"""

    def test_history_id_length(self, temp_dir):
        """history_id 应为 16 字符 hex（64 位熵）"""
        from apps.web.api.config import settings
        original_upload = settings.upload_dir
        original_output = settings.output_dir
        original_log = settings.log_dir
        settings.upload_dir = str(temp_dir / "uploads")
        settings.output_dir = str(temp_dir / "output")
        settings.log_dir = str(temp_dir / "logs")
        settings.paddleocr_api_key = "test_token"
        for d in [settings.upload_dir, settings.output_dir, settings.log_dir]:
            Path(d).mkdir(parents=True, exist_ok=True)

        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "backend_main_hid",
                Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
            )
            backend = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(backend)
            from apps.web.api.services.task_service import task_service
            task_service._task_store.clear()
            task_service._history.clear()

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
        finally:
            settings.upload_dir = original_upload
            settings.output_dir = original_output
            settings.log_dir = original_log

    def test_history_ids_are_unique(self, temp_dir):
        """多个 history_id 应互不相同"""
        from apps.web.api.config import settings
        original_upload = settings.upload_dir
        original_output = settings.output_dir
        original_log = settings.log_dir
        settings.upload_dir = str(temp_dir / "uploads")
        settings.output_dir = str(temp_dir / "output")
        settings.log_dir = str(temp_dir / "logs")
        settings.paddleocr_api_key = "test_token"
        for d in [settings.upload_dir, settings.output_dir, settings.log_dir]:
            Path(d).mkdir(parents=True, exist_ok=True)

        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "backend_main_hid2",
                Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
            )
            backend = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(backend)
            from apps.web.api.services.task_service import task_service
            task_service._task_store.clear()
            task_service._history.clear()

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
        finally:
            settings.upload_dir = original_upload
            settings.output_dir = original_output
            settings.log_dir = original_log


# ──────────────────────────────────────────────────
# 3. 错误消息环境区分（debug 模式）
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestErrorMessagesEnv:
    """测试错误消息是否根据 debug 模式区分"""

    def test_debug_false_hides_details(self, temp_dir):
        """debug=False 时错误消息应隐藏详情"""
        from apps.web.api.config import settings
        original_debug = settings.debug
        original_upload = settings.upload_dir
        original_output = settings.output_dir
        original_log = settings.log_dir
        settings.debug = False
        settings.upload_dir = str(temp_dir / "uploads")
        settings.output_dir = str(temp_dir / "output")
        settings.log_dir = str(temp_dir / "logs")
        settings.paddleocr_api_key = "test_token"
        for d in [settings.upload_dir, settings.output_dir, settings.log_dir]:
            Path(d).mkdir(parents=True, exist_ok=True)

        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "backend_main_debug",
                Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
            )
            backend = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(backend)
            from apps.web.api.services.task_service import task_service
            task_service._task_store.clear()
            task_service._history.clear()

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
            settings.upload_dir = original_upload
            settings.output_dir = original_output
            settings.log_dir = original_log

    def test_debug_true_shows_details(self, temp_dir):
        """debug=True 时错误消息可包含详情"""
        from apps.web.api.config import settings
        original_debug = settings.debug
        original_upload = settings.upload_dir
        original_output = settings.output_dir
        original_log = settings.log_dir
        settings.debug = True
        settings.upload_dir = str(temp_dir / "uploads")
        settings.output_dir = str(temp_dir / "output")
        settings.log_dir = str(temp_dir / "logs")
        settings.paddleocr_api_key = "test_token"
        for d in [settings.upload_dir, settings.output_dir, settings.log_dir]:
            Path(d).mkdir(parents=True, exist_ok=True)

        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "backend_main_debug2",
                Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
            )
            backend = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(backend)
            from apps.web.api.services.task_service import task_service
            task_service._task_store.clear()
            task_service._history.clear()

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
            settings.upload_dir = original_upload
            settings.output_dir = original_output
            settings.log_dir = original_log


# ──────────────────────────────────────────────────
# 4. SQLite WAL 模式
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestSQLiteWAL:
    """测试 SQLite WAL 模式是否正确启用"""

    def test_wal_mode_enabled(self, temp_dir, monkeypatch):
        """数据库应启用 WAL 模式"""
        # 使用 monkeypatch 修改全局 DB_PATH，避免影响真实数据库
        import sys
        ts_module = sys.modules.get("apps.web.api.services.task_service")
        if ts_module is None:
            import importlib
            ts_module = importlib.import_module("apps.web.api.services.task_service")
        db_path = temp_dir / "test_wal.db"
        monkeypatch.setattr(ts_module, "DB_PATH", db_path)

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
        monkeypatch.setattr(ts_module, "DB_PATH", db_path)

        svc = ts_module.TaskService()
        db = svc._ensure_db()

        cursor = db.execute("PRAGMA busy_timeout")
        timeout = cursor.fetchone()[0]
        assert timeout == 5000, f"busy_timeout 应为 5000，实际为 {timeout}"

        svc.close()


# ──────────────────────────────────────────────────
# 5. 速率限制
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestRateLimit:
    """测试 API 速率限制"""

    def test_rate_limit_returns_429(self, temp_dir):
        """超过速率限制应返回 429"""
        from apps.web.api.config import settings
        original_upload = settings.upload_dir
        original_output = settings.output_dir
        original_log = settings.log_dir
        original_requests = settings.rate_limit_requests
        original_window = settings.rate_limit_window
        settings.upload_dir = str(temp_dir / "uploads")
        settings.output_dir = str(temp_dir / "output")
        settings.log_dir = str(temp_dir / "logs")
        settings.paddleocr_api_key = "test_token"
        # 设置很低的速率限制便于测试
        settings.rate_limit_requests = 3
        settings.rate_limit_window = 60
        for d in [settings.upload_dir, settings.output_dir, settings.log_dir]:
            Path(d).mkdir(parents=True, exist_ok=True)

        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "backend_main_rate",
                Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
            )
            backend = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(backend)
            from apps.web.api.services.task_service import task_service
            task_service._task_store.clear()
            task_service._history.clear()

            client = TestClient(backend.app)

            # 发送超过限制的请求（健康检查不限制，用 /api/config）
            statuses = []
            for _ in range(5):
                resp = client.get("/api/config")
                statuses.append(resp.status_code)

            # 应有 429 状态码
            assert 429 in statuses, f"超过速率限制应返回 429，实际状态码: {statuses}"
        finally:
            settings.upload_dir = original_upload
            settings.output_dir = original_output
            settings.log_dir = original_log
            settings.rate_limit_requests = original_requests
            settings.rate_limit_window = original_window

    def test_health_check_exempt_from_rate_limit(self, temp_dir):
        """健康检查应豁免速率限制"""
        from apps.web.api.config import settings
        original_upload = settings.upload_dir
        original_output = settings.output_dir
        original_log = settings.log_dir
        original_requests = settings.rate_limit_requests
        original_window = settings.rate_limit_window
        settings.upload_dir = str(temp_dir / "uploads")
        settings.output_dir = str(temp_dir / "output")
        settings.log_dir = str(temp_dir / "logs")
        settings.paddleocr_api_key = "test_token"
        settings.rate_limit_requests = 2
        settings.rate_limit_window = 60
        for d in [settings.upload_dir, settings.output_dir, settings.log_dir]:
            Path(d).mkdir(parents=True, exist_ok=True)

        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "backend_main_rate2",
                Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
            )
            backend = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(backend)
            from apps.web.api.services.task_service import task_service
            task_service._task_store.clear()
            task_service._history.clear()

            client = TestClient(backend.app)

            # 发送多个健康检查请求
            statuses = []
            for _ in range(10):
                resp = client.get("/api/health")
                statuses.append(resp.status_code)

            # 健康检查不应被限制
            assert all(s == 200 for s in statuses), f"健康检查应豁免速率限制，实际状态码: {statuses}"
        finally:
            settings.upload_dir = original_upload
            settings.output_dir = original_output
            settings.log_dir = original_log
            settings.rate_limit_requests = original_requests
            settings.rate_limit_window = original_window


# ──────────────────────────────────────────────────
# 6. Markdown → HTML 转义（防 XSS）
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestMarkdownHtmlEscape:
    """测试桌面端 render_markdown_html 的 HTML 转义"""

    def test_escapes_script_tag(self):
        """<script> 标签应被转义"""
        from utils import render_markdown_html
        md = '# Title\n\nSome text <script>alert("xss")</script>'
        html = render_markdown_html(md)

        assert "<script>" not in html, "<script> 标签未被转义"
        assert "</script>" not in html, "</script> 标签未被转义"
        # 应以转义形式存在
        assert "&lt;script&gt;" in html or "&lt;script" in html

    def test_escapes_html_attributes(self):
        """HTML 事件属性应被转义"""
        from utils import render_markdown_html
        md = '# Title\n\n<img src=x onerror=alert(1)>'
        html = render_markdown_html(md)

        # 不应存在未转义的 <img 标签（带 onerror 的恶意 img）
        assert "<img src=x onerror" not in html, "未转义的 <img onerror> 标签存在 XSS 风险"
        # < 和 > 应被转义为 &lt; &gt;
        assert "&lt;img" in html, "恶意 HTML 标签未被转义"

    def test_escapes_table_content(self):
        """表格内容应被转义"""
        from utils import render_markdown_html
        md = '| 列1 | 列2 |\n| --- | --- |\n| <b>bold</b> | normal |'
        html = render_markdown_html(md)

        # <b> 标签应被转义，不应作为 HTML 执行
        assert "<b>bold</b>" not in html, "表格中的 HTML 标签未被转义"
        assert "&lt;b&gt;" in html

    def test_preserves_safe_markdown(self):
        """正常的 Markdown 标记应保留"""
        from utils import render_markdown_html
        md = '# Title\n\n**bold** and *italic*'
        html = render_markdown_html(md)

        assert "<h1>" in html
        assert "<strong>" in html
        assert "<em>" in html

    def test_escapes_inline_code(self):
        """行内代码中的特殊字符应被转义"""
        from utils import render_markdown_html
        md = 'Some `code <script>` here'
        html = render_markdown_html(md)

        assert "<script>" not in html, "行内代码中的 <script> 未被转义"
        assert "<code>" in html

    def test_escapes_blockquote(self):
        """引用块中的 HTML 应被转义"""
        from utils import render_markdown_html
        md = '> <img src=x onerror=alert(1)>'
        html = render_markdown_html(md)

        # 不应存在未转义的 <img 标签带 onerror
        assert "<img src=x onerror" not in html, "引用块中存在未转义的恶意 <img> 标签"
        assert "&lt;img" in html, "引用块中的 HTML 标签未被转义"

    def test_image_alt_escaped(self):
        """图片 alt 文本应被转义"""
        from utils import render_markdown_html
        md = '![<script>alert(1)</script>](http://example.com/img.png)'
        html = render_markdown_html(md)

        # <script> 标签不应作为真实 HTML 执行
        assert "<script>alert(1)</script>" not in html, "图片 alt 中的 <script> 未被转义"
        # 图片标签应存在但 alt 中的特殊字符被转义
        assert "<img" in html

    def test_code_block_content_escaped(self):
        """代码块内容应被转义"""
        from utils import render_markdown_html
        md = '```json\n{"evil": "</script><script>alert(1)</script>"}\n```'
        html = render_markdown_html(md)

        assert "<script>alert(1)</script>" not in html, "代码块中的 <script> 未被转义"
        assert "<pre><code>" in html

    def test_empty_input(self):
        """空输入应返回有效 HTML"""
        from utils import render_markdown_html
        html = render_markdown_html("")
        assert "<html>" in html
        assert "</html>" in html
