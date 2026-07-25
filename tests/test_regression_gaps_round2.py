"""
测试缺口补充 (Round 2): 覆盖近期代码变更中仍未被测试的实质风险点

重点关注:
  1. main.py 异常处理路径（文件保存失败、同步处理失败、批量下载容错）
  2. 全局异常处理器的安全信息隔离（生产模式不泄露内部错误）
  3. 竞争条件和边界场景（删除时目录消失、报告 ID 同名文件冲突）
  4. 缺少前端静态文件时的根端点回退行为
"""

import sys
import io
import json
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest
from fastapi.testclient import TestClient

_backend_path = str(Path(__file__).parent.parent / "apps" / "web" / "api")
if _backend_path in sys.path:
    sys.path.remove(_backend_path)
sys.path.insert(0, _backend_path)


# ──────────────────────────────────────────────────
# 1. upload_image 异常处理路径
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestUploadImageExceptionPath:
    """测试 upload_image 端点的异常处理（文件保存失败场景）"""

    def test_upload_image_disk_full_returns_500_without_leaking_path(self, temp_dir, load_backend_app):
        """磁盘满时 upload_image 应返回 500 且不泄露内部文件系统路径（生产模式）"""
        from apps.web.api.config import settings
        original_debug = settings.debug
        settings.debug = False

        backend = load_backend_app(temp_dir, "upload_disk_full")
        client = TestClient(backend.app)

        try:
            with patch("builtins.open", side_effect=OSError("No space left on device")):
                resp = client.post("/api/upload", files={
                    "file": ("test.jpg", io.BytesIO(b"\xff\xd8\xff" + b"X" * 100), "image/jpeg")
                })
                assert resp.status_code == 500
                data = resp.json()
                assert "文件保存失败" in data.get("error", "")
                # 生产模式下不应泄露内部异常详情或路径
                assert "No space left" not in str(data)
                assert ":\\" not in str(data)  # Windows 路径隔离
        finally:
            settings.debug = original_debug

    def test_upload_image_debug_mode_includes_details(self, temp_dir, load_backend_app):
        """debug 模式下 upload_image 异常应包含错误详情便于排查"""
        from apps.web.api.config import settings
        original_debug = settings.debug
        settings.debug = True

        backend = load_backend_app(temp_dir, "upload_debug")
        client = TestClient(backend.app)

        try:
            with patch("builtins.open", side_effect=PermissionError("Permission denied")):
                resp = client.post("/api/upload", files={
                    "file": ("test.jpg", io.BytesIO(b"\xff\xd8\xff" + b"X" * 100), "image/jpeg")
                })
                assert resp.status_code == 500
                data = resp.json()
                assert "Permission denied" in data.get("error", "")
        finally:
            settings.debug = original_debug


# ──────────────────────────────────────────────────
# 2. process_image 同步处理异常路径
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestProcessImageExceptionPath:
    """测试 process_image (/api/process/{file_id}) 同步处理异常路径"""

    def test_process_image_ocr_failure_returns_500(self, temp_dir, load_backend_app):
        """OCR 同步处理失败时应返回 500 且不泄露内部错误"""
        from apps.web.api.config import settings
        original_debug = settings.debug
        settings.debug = False

        backend = load_backend_app(temp_dir, "process_ocr_fail")
        client = TestClient(backend.app)

        # 先上传文件
        upload_resp = client.post("/api/upload", files={
            "file": ("test.jpg", io.BytesIO(b"\xff\xd8\xff" + b"X" * 100), "image/jpeg")
        })
        assert upload_resp.status_code == 200
        file_id = upload_resp.json()["file_id"]

        try:
            with patch.object(backend.paddle_service, "submit_and_poll", new_callable=AsyncMock) as mock:
                mock.side_effect = RuntimeError("INTERNAL_OCR_SECRET_ERROR")
                resp = client.post(f"/api/process/{file_id}")
                assert resp.status_code == 500
                data = resp.json()
                assert "处理失败" in data.get("error", "")
                assert "INTERNAL_OCR_SECRET_ERROR" not in str(data)
        finally:
            settings.debug = original_debug

    def test_process_image_save_report_failure_returns_500(self, temp_dir, load_backend_app):
        """save_report 失败时应返回 500"""
        from apps.web.api.config import settings
        original_debug = settings.debug
        settings.debug = False

        backend = load_backend_app(temp_dir, "process_save_fail")
        client = TestClient(backend.app)

        upload_resp = client.post("/api/upload", files={
            "file": ("test.jpg", io.BytesIO(b"\xff\xd8\xff" + b"X" * 100), "image/jpeg")
        })
        file_id = upload_resp.json()["file_id"]

        try:
            with patch.object(backend.paddle_service, "submit_and_poll", new_callable=AsyncMock) as mock_poll, \
                 patch.object(backend.markdown_generator, "save_report", new_callable=AsyncMock) as mock_save:
                mock_poll.return_value = {
                    "success": True,
                    "markdown_text": "# Test",
                    "images": {},
                    "processing_time": 1.0,
                }
                mock_save.side_effect = OSError("Disk full during save_report")
                resp = client.post(f"/api/process/{file_id}")
                assert resp.status_code == 500
        finally:
            settings.debug = original_debug


# ──────────────────────────────────────────────────
# 3. delete_report 竞争条件与异常路径
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestDeleteReportRaceCondition:
    """测试 delete_report 的竞争条件和异常处理"""

    def test_delete_report_file_not_found_during_rmtree(self, temp_dir, load_backend_app):
        """_safe_report_dir 返回有效路径但删除前目录被移除（竞争条件）应返回 404"""
        backend = load_backend_app(temp_dir, "delete_race")
        client = TestClient(backend.app)

        output_dir = Path(backend.settings.output_dir)
        report_dir = output_dir / "race_report"
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.md").write_text("# test")

        # 模拟 shutil.rmtree 抛出 FileNotFoundError（目录已被其他进程删除）
        with patch("apps.web.api.main.shutil.rmtree", side_effect=FileNotFoundError):
            resp = client.delete("/api/report/race_report")
            assert resp.status_code == 404
            assert "不存在" in resp.json().get("error", "")

    def test_delete_report_permission_error_returns_500(self, temp_dir, load_backend_app):
        """删除时权限错误应返回 500 且不泄露内部路径"""
        from apps.web.api.config import settings
        original_debug = settings.debug
        settings.debug = False

        backend = load_backend_app(temp_dir, "delete_perm")
        client = TestClient(backend.app)

        output_dir = Path(backend.settings.output_dir)
        report_dir = output_dir / "perm_report"
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.md").write_text("# test")

        try:
            with patch("apps.web.api.main.shutil.rmtree", side_effect=PermissionError("Access denied")):
                resp = client.delete("/api/report/perm_report")
                assert resp.status_code == 500
                data = resp.json()
                assert "删除报告失败" in data.get("error", "")
                assert "Access denied" not in str(data)
        finally:
            settings.debug = original_debug


# ──────────────────────────────────────────────────
# 4. download_batch_zip 单条目容错路径
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestBatchDownloadZipErrorIsolation:
    """测试批量下载 ZIP 时单个条目错误不应中断整个批次"""

    def test_batch_download_skips_safe_report_dir_exception(self, temp_dir, load_backend_app):
        """某个 report_id 导致 _safe_report_dir 异常时，应跳过该条目继续打包其他报告"""
        backend = load_backend_app(temp_dir, "batch_dl_skip_safe_exc")
        client = TestClient(backend.app)

        output_dir = Path(backend.settings.output_dir)

        # 创建有效报告
        valid_dir = output_dir / "valid_report_dl"
        valid_dir.mkdir()
        (valid_dir / "report.md").write_text("# valid")

        # 创建一个同名普通文件，使 _safe_report_dir 对该 ID 抛 HTTPException(400)
        (output_dir / "file_report_dl").write_text("not a directory")

        resp = client.post("/api/batch/download", json={
            "report_ids": ["valid_report_dl", "file_report_dl"]
        })
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"

    def test_batch_download_skips_nonexistent_report_gracefully(self, temp_dir, load_backend_app):
        """报告目录不存在时应跳过该条目"""
        backend = load_backend_app(temp_dir, "batch_dl_skip_missing")
        client = TestClient(backend.app)

        output_dir = Path(backend.settings.output_dir)

        # 仅创建 1 个有效报告
        valid_dir = output_dir / "exists_report_dl"
        valid_dir.mkdir()
        (valid_dir / "report.md").write_text("# exists")

        resp = client.post("/api/batch/download", json={
            "report_ids": ["exists_report_dl", "nonexistent_report_dl"]
        })
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"


# ──────────────────────────────────────────────────
# 5. 全局异常处理器安全隔离
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestGlobalExceptionHandlerSecurity:
    """测试全局异常处理器在生产模式与 debug 模式下的信息隔离"""

    def test_global_exception_handler_hides_details_in_production(self):
        """生产模式下未捕获异常不应泄露内部错误详情"""
        from apps.web.api.config import settings
        from apps.web.api.main import global_exception_handler
        import asyncio

        original_debug = settings.debug
        settings.debug = False

        class FakeRequest:
            method = "GET"
            url = type("obj", (object,), {"path": "/api/test"})()

        exc = RuntimeError("SECRET_INTERNAL_PATH")

        try:
            result = asyncio.run(global_exception_handler(FakeRequest(), exc))
            assert result.status_code == 500
            data = json.loads(result.body)
            assert "SECRET_INTERNAL_PATH" not in str(data)
            assert "服务器内部错误" in data.get("error", "")
            assert data.get("code") == "INTERNAL_ERROR"
        finally:
            settings.debug = original_debug

    def test_global_exception_handler_shows_details_in_debug(self):
        """debug 模式下未捕获异常应包含详情便于排查"""
        from apps.web.api.config import settings
        from apps.web.api.main import global_exception_handler
        import asyncio

        original_debug = settings.debug
        settings.debug = True

        class FakeRequest:
            method = "GET"
            url = type("obj", (object,), {"path": "/api/test"})()

        exc = RuntimeError("DEBUG_VISIBLE_ERROR")

        try:
            result = asyncio.run(global_exception_handler(FakeRequest(), exc))
            assert result.status_code == 500
            data = json.loads(result.body)
            assert "DEBUG_VISIBLE_ERROR" in data.get("error", "")
        finally:
            settings.debug = original_debug


# ──────────────────────────────────────────────────
# 6. get_batch_results 异常路径
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestGetBatchResultsExceptionPath:
    """测试 /api/batch/{batch_id} 的异常处理"""

    def test_get_batch_results_exception_returns_500(self, temp_dir, load_backend_app):
        """batch_get_results 抛出非 HTTPException 时应返回 500 且不泄露详情"""
        from apps.web.api.config import settings
        original_debug = settings.debug
        settings.debug = False

        backend = load_backend_app(temp_dir, "batch_results_exc")
        client = TestClient(backend.app)

        try:
            with patch.object(backend.paddle_service, "batch_get_results", new_callable=AsyncMock) as mock:
                mock.side_effect = RuntimeError("BATCH_SECRET_ERROR")
                resp = client.get("/api/batch/test_batch_id")
                assert resp.status_code == 500
                data = resp.json()
                assert "BATCH_SECRET_ERROR" not in str(data)
                assert "批量查询失败" in data.get("error", "")
        finally:
            settings.debug = original_debug


# ──────────────────────────────────────────────────
# 7. submit_task 异常路径
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestSubmitTaskExceptionPath:
    """测试 /api/submit/{file_id} 的异常处理"""

    def test_submit_task_exception_returns_500(self, temp_dir, load_backend_app):
        """submit_task 抛出非 HTTPException 时应返回 500 且不泄露详情"""
        from apps.web.api.config import settings
        original_debug = settings.debug
        settings.debug = False

        backend = load_backend_app(temp_dir, "submit_exc")
        client = TestClient(backend.app)

        # 先上传文件
        upload_resp = client.post("/api/upload", files={
            "file": ("test.jpg", io.BytesIO(b"\xff\xd8\xff" + b"X" * 100), "image/jpeg")
        })
        file_id = upload_resp.json()["file_id"]

        try:
            with patch.object(backend.paddle_service, "submit_task", new_callable=AsyncMock) as mock:
                mock.side_effect = RuntimeError("SUBMIT_SECRET_ERROR")
                resp = client.post(f"/api/submit/{file_id}")
                assert resp.status_code == 500
                data = resp.json()
                assert "SUBMIT_SECRET_ERROR" not in str(data)
                assert "提交任务失败" in data.get("error", "")
        finally:
            settings.debug = original_debug


# ──────────────────────────────────────────────────
# 8. submit_task_by_url 异常路径
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestSubmitUrlExceptionPath:
    """测试 /api/submit-url 的异常处理"""

    def test_submit_url_exception_returns_500(self, temp_dir, load_backend_app):
        """submit_task_by_url 抛出非 HTTPException 时应返回 500 且不泄露详情"""
        from apps.web.api.config import settings
        original_debug = settings.debug
        settings.debug = False

        backend = load_backend_app(temp_dir, "submit_url_exc")
        client = TestClient(backend.app)

        try:
            with patch.object(backend.paddle_service, "submit_task", new_callable=AsyncMock) as mock:
                mock.side_effect = RuntimeError("URL_SUBMIT_SECRET")
                resp = client.post("/api/submit-url", json={
                    "fileUrl": "https://example.com/image.jpg",
                    "filename": "test.jpg",
                })
                assert resp.status_code == 500
                data = resp.json()
                assert "URL_SUBMIT_SECRET" not in str(data)
                assert "提交任务失败" in data.get("error", "")
        finally:
            settings.debug = original_debug


# ──────────────────────────────────────────────────
# 9. 根端点前端缺失回退
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestRootEndpointFallback:
    """测试根端点在前端目录缺失时的回退行为"""

    def test_root_returns_json_when_frontend_missing(self):
        """frontend 目录不存在时根端点应返回 JSON 服务信息"""
        from apps.web.api.main import root
        import asyncio

        with patch("apps.web.api.main.Path.exists", return_value=False):
            result = asyncio.run(root())
            assert isinstance(result, dict)
            assert result["status"] == "running"
            assert result["name"] == "DocFlow"
            assert "version" in result
            assert "uptime" in result


# ──────────────────────────────────────────────────
# 10. lifespan 启动事件
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestLifespanStartup:
    """测试应用 lifespan 启动事件"""

    def test_lifespan_warns_when_api_token_missing(self, caplog):
        """API Token 未配置时 lifespan 应记录警告日志"""
        import logging
        from apps.web.api.config import settings
        from apps.web.api.main import lifespan
        import asyncio

        caplog.set_level(logging.WARNING)
        original_key = settings.paddleocr_api_key
        settings.paddleocr_api_key = ""

        class FakeApp:
            pass

        try:
            async def _run_lifespan():
                async with lifespan(FakeApp()):
                    pass

            asyncio.run(_run_lifespan())

            # 验证警告日志中包含 Token 未配置提示
            assert any("Token 未配置" in rec for rec in caplog.messages)
        finally:
            settings.paddleocr_api_key = original_key
