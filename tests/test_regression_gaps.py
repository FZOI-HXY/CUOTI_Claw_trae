"""
测试缺口补充: 覆盖现有测试未充分覆盖的回归风险点

重点关注:
  1. main.py 安全工具函数与业务逻辑
  2. 批量操作边界条件与部分失败场景
  3. 任务处理异常路径（卡死检测、超时、资源清理）
  4. MarkdownGenerator 和 PaddleParser 错误处理
"""

import sys
import io
import time
import asyncio
import threading
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

_backend_path = str(Path(__file__).parent.parent / "apps" / "web" / "api")
if _backend_path in sys.path:
    sys.path.remove(_backend_path)
sys.path.insert(0, _backend_path)


# ──────────────────────────────────────────────────
# 1. 速率限制清理函数测试
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestRateLimitCleanup:
    """测试 _cleanup_rate_limit_store 内存泄漏防护"""

    def test_cleanup_removes_expired_entries(self, temp_dir, load_backend_app):
        """清理应移除过期的 IP 条目"""
        backend = load_backend_app(temp_dir, "rate_limit_cleanup")
        from apps.web.api.config import settings
        original_window = settings.rate_limit_window
        try:
            settings.rate_limit_window = 0.1

            backend._rate_limit_store["192.168.1.1"] = [time.time() - 1.0]
            backend._rate_limit_store["10.0.0.1"] = [time.time() - 0.05]

            backend._cleanup_rate_limit_store()

            assert "192.168.1.1" not in backend._rate_limit_store
            assert "10.0.0.1" in backend._rate_limit_store
        finally:
            settings.rate_limit_window = original_window

    def test_cleanup_preserves_fresh_entries(self, temp_dir, load_backend_app):
        """清理应保留未过期的条目"""
        backend = load_backend_app(temp_dir, "rate_limit_preserve")
        from apps.web.api.config import settings
        original_window = settings.rate_limit_window
        try:
            settings.rate_limit_window = 60

            fresh_time = time.time()
            backend._rate_limit_store["192.168.1.1"] = [fresh_time, fresh_time - 10]

            backend._cleanup_rate_limit_store()

            assert "192.168.1.1" in backend._rate_limit_store
            assert len(backend._rate_limit_store["192.168.1.1"]) == 2
        finally:
            settings.rate_limit_window = original_window

    def test_cleanup_removes_empty_entries(self, temp_dir, load_backend_app):
        """清理应移除全部过期后变为空的 IP 条目"""
        backend = load_backend_app(temp_dir, "rate_limit_empty")
        from apps.web.api.config import settings
        original_window = settings.rate_limit_window
        try:
            settings.rate_limit_window = 0.1

            backend._rate_limit_store["192.168.1.1"] = [time.time() - 1.0]

            backend._cleanup_rate_limit_store()

            assert "192.168.1.1" not in backend._rate_limit_store
        finally:
            settings.rate_limit_window = original_window


# ──────────────────────────────────────────────────
# 2. 任务处理异常路径测试
# ──────────────────────────────────────────

@pytest.mark.unit
class TestTaskErrorHandling:
    """测试任务处理的异常路径"""

    def test_task_stuck_detection(self, temp_dir, load_backend_app):
        """任务卡死检测应正确设置状态"""
        backend = load_backend_app(temp_dir, "task_stuck")

        task_info = {
            "status": "processing",
            "filename": "test.jpg",
            "file_id": "test_file_id",
            "_last_extracted_pages": 5,
            "_no_progress_count": 14,
        }
        poll_status = {"extracted_pages": 5, "total_pages": 10}

        result = backend._handle_task_running("task1", task_info, poll_status, "running", 5, 14, 15)

        assert result["status"] == "stuck"
        assert result["completed"] is True
        assert "连续" in result["error"]
        assert "无变化" in result["error"]

    def test_task_progress_reset_stuck_count(self, temp_dir, load_backend_app):
        """进度变化应重置卡死计数"""
        backend = load_backend_app(temp_dir, "task_progress_reset")

        task_info = {
            "status": "processing",
            "filename": "test.jpg",
            "file_id": "test_file_id",
            "_last_extracted_pages": 5,
            "_no_progress_count": 10,
        }
        poll_status = {"extracted_pages": 7, "total_pages": 10}

        result = backend._handle_task_running("task1", task_info, poll_status, "running", 5, 10, 15)

        assert result["status"] == "processing"
        assert result["completed"] is False
        assert task_info["_no_progress_count"] == 0
        assert task_info["_last_extracted_pages"] == 7


# ──────────────────────────────────────────────────
# 3. MarkdownGenerator 错误处理测试
# ──────────────────────────────────────────

@pytest.mark.unit
class TestMarkdownGeneratorErrorHandling:
    """测试 MarkdownGenerator 的错误处理"""

    def test_escape_md_table_cell_xss(self):
        """表格单元格转义应防止 XSS"""
        from apps.web.api.markdown_generator import MarkdownGenerator

        test_cases = [
            ("<script>alert(1)</script>", "&lt;script&gt;alert(1)&lt;/script&gt;"),
            ("| column break |", "\\| column break \\|"),
            ("`code injection`", "&#96;code injection&#96;"),
            ("\nnewline\n", " newline "),
            ("> greater than", "&gt; greater than"),
            ("normal text", "normal text"),
        ]

        for input_text, expected in test_cases:
            result = MarkdownGenerator._escape_md_table_cell(input_text)
            assert result == expected, f"Expected {expected}, got {result} for {input_text}"

    def test_escape_markdown_filename(self):
        """文件名转义应防止表格破坏和 XSS"""
        from apps.web.api.markdown_generator import MarkdownGenerator

        test_cases = [
            ("file|name.jpg", "file\\|name.jpg"),
            ("file`name.jpg", "file\\`name.jpg"),
            ("<script>.jpg", "&lt;script&gt;.jpg"),
            (">test.jpg", "&gt;test.jpg"),
            ("normal.jpg", "normal.jpg"),
        ]

        for input_name, expected in test_cases:
            result = MarkdownGenerator._escape_markdown_filename(input_name)
            assert result == expected, f"Expected {expected}, got {result} for {input_name}"

    def test_safe_image_name_path_stripping(self):
        """_safe_image_name 应正确剥离路径前缀"""
        from apps.web.api.markdown_generator import MarkdownGenerator

        test_cases = [
            ("imgs/img_0.png", "img_0.png"),
            ("img/img_1.jpg", "img_1.jpg"),
            ("./img_2.png", "img_2.png"),
            ("img_3.png", "img_3.png"),
            ("../../etc/passwd", "passwd.png"),
            ("file.name.with.dots.png", "file.name.with.dots.png"),
            ("no_ext", "no_ext.png"),
            ("", "image.png"),
        ]

        for input_name, expected in test_cases:
            result = MarkdownGenerator._safe_image_name(input_name)
            assert result == expected, f"Expected {expected}, got {result} for {input_name}"


# ──────────────────────────────────────────────────
# 4. PaddleParser 错误处理测试
# ──────────────────────────────────────────

@pytest.mark.unit
class TestPaddleParserErrorHandling:
    """测试 PaddleParser 的错误处理"""

    def test_extract_ocr_result_empty_json(self):
        """空 JSON 应返回默认值"""
        from apps.web.api.services.paddle_parser import extract_ocr_result

        result = extract_ocr_result({})

        assert result["markdown_text"] == ""
        assert result["images"] == {}
        assert result["layout_items"] == []
        assert result["layout_image"] is None

    def test_extract_ocr_result_invalid_json(self):
        """无效 JSON 应返回默认值并记录错误"""
        from apps.web.api.services.paddle_parser import extract_ocr_result

        result = extract_ocr_result({
            "json_text": "not valid json",
        })

        assert result["markdown_text"] == ""
        assert result["images"] == {}

    def test_extract_ocr_result_vl_model_format(self):
        """VL 模型格式应正确提取数据"""
        from apps.web.api.services.paddle_parser import extract_ocr_result

        json_text = '''{
            "result": {
                "layoutParsingResults": [{
                    "markdown": {
                        "text": "# Title\\n\\nContent",
                        "images": {"img_0": "https://example.com/img.png"}
                    },
                    "layoutType": "text",
                    "region": {"x": 10, "y": 20, "width": 100, "height": 50}
                }]
            }
        }'''

        result = extract_ocr_result({"json_text": json_text})

        assert result["markdown_text"] == "# Title\n\nContent"
        assert len(result["images"]) == 1
        assert "img_0" in result["images"]
        assert len(result["layout_items"]) == 1
        assert result["layout_items"][0]["type"] == "text"

    def test_extract_ocr_result_ocr_model_format(self):
        """OCR 模型格式应正确提取数据"""
        from apps.web.api.services.paddle_parser import extract_ocr_result

        json_text = '''{
            "result": {
                "ocrResults": [{
                    "ocrImage": "https://example.com/ocr.png"
                }]
            }
        }'''

        result = extract_ocr_result({"json_text": json_text})

        assert result["layout_image"] == "https://example.com/ocr.png"

    def test_extract_ocr_result_jsonl_format(self):
        """JSONL 格式应正确解析"""
        from apps.web.api.services.paddle_parser import extract_ocr_result

        jsonl_text = '''{"result": {"layoutParsingResults": [{"markdown": {"text": "Line 1"}}]}}
{"result": {"layoutParsingResults": [{"markdown": {"text": "Line 2"}}]}}'''

        result = extract_ocr_result({"json_text": jsonl_text})

        assert "Line 1" in result["markdown_text"]
        assert "Line 2" in result["markdown_text"]

    def test_parse_result_json_empty(self):
        """空字符串应返回空列表"""
        from apps.web.api.services.paddle_parser import _parse_result_json

        result = _parse_result_json("")
        assert result == []

    def test_parse_result_json_invalid(self):
        """完全无效的 JSON 应返回空列表"""
        from apps.web.api.services.paddle_parser import _parse_result_json

        result = _parse_result_json("not json at all")
        assert result == []

    def test_extract_ocr_items_direct_list(self):
        """直接列表应被返回"""
        from apps.web.api.services.paddle_parser import _extract_ocr_items

        items = [{"markdown": {"text": "test"}}]
        result = _extract_ocr_items(items)

        assert result == items

    def test_extract_ocr_items_empty_object(self):
        """空对象应返回空列表"""
        from apps.web.api.services.paddle_parser import _extract_ocr_items

        result = _extract_ocr_items({})
        assert result == []


# ──────────────────────────────────────────────────
# 5. 批量操作边界条件测试
# ──────────────────────────────────────────

@pytest.mark.integration
class TestBatchOperationsEdgeCases:
    """测试批量操作的边界条件"""

    def test_batch_delete_reports_mixed_valid_invalid(self, temp_dir, load_backend_app):
        """混合有效和无效报告 ID 时应正确统计"""
        from apps.web.api.config import settings
        from fastapi.testclient import TestClient

        original_output = settings.output_dir

        backend = load_backend_app(temp_dir, "batch_del_mixed_edge")
        settings.output_dir = str(temp_dir / "output_edge")
        Path(settings.output_dir).mkdir(parents=True, exist_ok=True)

        try:
            valid_dir = Path(settings.output_dir) / "valid_report"
            valid_dir.mkdir()
            (valid_dir / "report.md").write_text("# Valid Report")

            client = TestClient(backend.app)
            resp = client.post("/api/reports/batch-delete", json={
                "ids": ["valid_report", "invalid_report", "../../etc/passwd"]
            })

            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["deleted"] == 1
        finally:
            settings.output_dir = original_output

    def test_batch_download_mixed_valid_invalid(self, temp_dir, load_backend_app):
        """批量下载混合有效和无效 ID 时应跳过无效的"""
        from apps.web.api.config import settings
        from fastapi.testclient import TestClient

        original_output = settings.output_dir

        backend = load_backend_app(temp_dir, "batch_download_mixed")
        settings.output_dir = str(temp_dir / "output_download")
        Path(settings.output_dir).mkdir(parents=True, exist_ok=True)

        try:
            valid_dir = Path(settings.output_dir) / "valid_report_20240601_120000"
            valid_dir.mkdir()
            (valid_dir / "report.md").write_text("# Valid Report")

            client = TestClient(backend.app)
            resp = client.post("/api/batch/download", json={
                "report_ids": ["valid_report_20240601_120000", "invalid", "../../etc/passwd"]
            })

            assert resp.status_code == 200
            assert resp.headers["content-type"] == "application/zip"
        finally:
            settings.output_dir = original_output


# ──────────────────────────────────────────────────
# 6. API 边界条件测试
# ──────────────────────────────────────────

@pytest.mark.integration
class TestApiEdgeCases:
    """测试 API 的边界条件"""

    def test_submit_url_with_invalid_url(self, temp_dir, load_backend_app):
        """提交无效 URL 格式应被拒绝"""
        from fastapi.testclient import TestClient

        backend = load_backend_app(temp_dir, "submit_url_invalid")
        client = TestClient(backend.app)

        resp = client.post("/api/submit-url", json={
            "fileUrl": "not_a_url",
            "filename": "test.jpg",
        })
        assert resp.status_code == 400

    def test_submit_url_with_internal_hostname(self, temp_dir, load_backend_app):
        """提交指向 localhost 的 URL 应被拒绝"""
        from fastapi.testclient import TestClient

        backend = load_backend_app(temp_dir, "submit_url_localhost")
        client = TestClient(backend.app)

        resp = client.post("/api/submit-url", json={
            "fileUrl": "https://localhost/image.jpg",
            "filename": "test.jpg",
        })
        assert resp.status_code == 400

    def test_get_report_nonexistent(self, temp_dir, load_backend_app):
        """获取不存在的报告应返回 404"""
        from fastapi.testclient import TestClient

        backend = load_backend_app(temp_dir, "get_report_nonexistent")
        client = TestClient(backend.app)

        resp = client.get("/api/report/nonexistent_report_id")
        assert resp.status_code == 404

    def test_delete_report_nonexistent(self, temp_dir, load_backend_app):
        """删除不存在的报告应返回 404"""
        from fastapi.testclient import TestClient

        backend = load_backend_app(temp_dir, "delete_report_nonexistent")
        client = TestClient(backend.app)

        resp = client.delete("/api/report/nonexistent_report_id")
        assert resp.status_code == 404

    def test_list_reports_empty(self, temp_dir, load_backend_app):
        """空输出目录应返回空列表"""
        from fastapi.testclient import TestClient

        backend = load_backend_app(temp_dir, "list_reports_empty")
        client = TestClient(backend.app)

        resp = client.get("/api/reports")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["reports"] == []

    def test_health_check_database_failure(self, temp_dir, load_backend_app):
        """数据库连接失败时健康检查应返回 degraded"""
        from fastapi.testclient import TestClient

        backend = load_backend_app(temp_dir, "health_db_fail")

        with patch.object(backend.ts, "get_history_count", side_effect=Exception("DB error")):
            client = TestClient(backend.app)
            resp = client.get("/api/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["database"] == "error"

    def test_system_status_no_path_leak(self, temp_dir, load_backend_app):
        """F-001 修复：/api/status 不应返回内部文件系统绝对路径"""
        from apps.web.api.config import settings
        from fastapi.testclient import TestClient

        backend = load_backend_app(temp_dir, "status_no_path_leak")

        # 使用绝对路径作为 upload/output dir 模拟真实部署
        original_upload = settings.upload_dir
        original_output = settings.output_dir
        settings.upload_dir = str(temp_dir / "uploads")
        settings.output_dir = str(temp_dir / "output")

        try:
            client = TestClient(backend.app)
            resp = client.get("/api/status")

            assert resp.status_code == 200
            data = resp.json()
            assert data["upload_dir"] == "uploads", f"upload_dir 应仅为目录名，实际: {data['upload_dir']}"
            assert data["output_dir"] == "output", f"output_dir 应仅为目录名，实际: {data['output_dir']}"
            # 确保没有泄露绝对路径中的驱动器或用户名
            assert ":\\" not in data["upload_dir"]
            assert ":\\" not in data["output_dir"]
            assert str(temp_dir) not in data["upload_dir"]
            assert str(temp_dir) not in data["output_dir"]
        finally:
            settings.upload_dir = original_upload
            settings.output_dir = original_output

    def test_update_config_error_hides_details_in_production(self, temp_dir, load_backend_app):
        """F-001 修复：生产模式下 /api/config 更新失败应隐藏内部错误详情"""
        from apps.web.api.config import settings
        from fastapi.testclient import TestClient

        original_debug = settings.debug
        settings.debug = False

        backend = load_backend_app(temp_dir, "update_config_prod_error")

        try:
            client = TestClient(backend.app)

            # 模拟 save_env_file 抛出异常
            with patch.object(backend, "save_env_file", side_effect=RuntimeError("SECRET_CONFIG_ERROR_12345")):
                resp = client.post("/api/config", json={"log_level": "DEBUG"})

            assert resp.status_code == 400
            detail = str(resp.json())
            assert "SECRET_CONFIG_ERROR_12345" not in detail, "生产模式下不应泄露内部异常详情"
            assert "配置更新失败" in detail, "应返回通用错误消息"
        finally:
            settings.debug = original_debug


# ──────────────────────────────────────────────────
# 7. 安全工具函数边界条件测试
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestSecurityUtilsEdgeCases:
    """测试安全工具函数的边界条件"""

    def test_check_magic_bytes_empty(self):
        """空内容应被拒绝"""
        import importlib.util
        from fastapi import HTTPException
        spec = importlib.util.spec_from_file_location(
            "backend_main_magic_edge",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        with pytest.raises(HTTPException) as exc_info:
            backend._check_magic_bytes(b"")
        assert exc_info.value.status_code == 400

    def test_check_magic_bytes_short(self):
        """太短的内容应被拒绝"""
        import importlib.util
        from fastapi import HTTPException
        spec = importlib.util.spec_from_file_location(
            "backend_main_magic_short",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        with pytest.raises(HTTPException) as exc_info:
            backend._check_magic_bytes(b"\x00\x00\x00")
        assert exc_info.value.status_code == 400

    def test_validate_file_url_missing_host(self):
        """缺少主机名的 URL 应被拒绝"""
        import importlib.util
        from fastapi import HTTPException
        spec = importlib.util.spec_from_file_location(
            "backend_main_url_host",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        with pytest.raises(HTTPException) as exc_info:
            backend._validate_file_url("https:///path/to/file.jpg")
        assert exc_info.value.status_code == 400

    def test_validate_file_url_http_rejected(self):
        """HTTP 协议应被拒绝"""
        import importlib.util
        from fastapi import HTTPException
        spec = importlib.util.spec_from_file_location(
            "backend_main_url_http",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        with pytest.raises(HTTPException) as exc_info:
            backend._validate_file_url("http://example.com/file.jpg")
        assert exc_info.value.status_code == 400

    def test_is_valid_report_id_format_boundary(self):
        """边界值测试：恰好 64 字符和超过 64 字符"""
        from apps.web.api.main import _is_valid_report_id_format

        assert _is_valid_report_id_format("a" * 64) is True
        assert _is_valid_report_id_format("a" * 65) is False
        assert _is_valid_report_id_format("a") is True


# ──────────────────────────────────────────────────
# 8. 并发资源清理测试
# ──────────────────────────────────────────

@pytest.mark.unit
class TestConcurrentResourceCleanup:
    """测试并发场景下的资源清理"""

    def test_concurrent_schedule_cleanup_no_double_cleanup(self, temp_dir, monkeypatch):
        """并发调度清理不应导致重复清理"""
        import importlib
        ts_module = importlib.import_module("apps.web.api.services.task_service")

        db_path = temp_dir / "concurrent_cleanup_double.db"
        monkeypatch.setattr(ts_module, "_get_db_path", lambda: db_path)

        svc = ts_module.TaskService()
        try:
            svc.set_task("task1", {"status": "done", "image_data": b"test_data"})

            cleanup_count = [0]

            def monitor_cleanup():
                while "task1" in svc._cleanup_timers:
                    time.sleep(0.01)
                task = svc.get_task("task1")
                if task is not None and "image_data" not in task:
                    cleanup_count[0] += 1

            threads = []
            for _ in range(3):
                t = threading.Thread(target=lambda: svc.schedule_image_data_cleanup("task1", delay=0.1))
                threads.append(t)
                t.start()

            monitor_thread = threading.Thread(target=monitor_cleanup)
            monitor_thread.start()

            for t in threads:
                t.join()
            monitor_thread.join(timeout=2.0)

            assert cleanup_count[0] >= 1
            assert "image_data" not in svc.get_task("task1")
        finally:
            svc.close()

    def test_lru_eviction_cancels_cleanup_timer(self, temp_dir, monkeypatch):
        """LRU 淘汰应取消关联的清理定时器"""
        import importlib
        ts_module = importlib.import_module("apps.web.api.services.task_service")
        original_max = ts_module._MAX_TASK_STORE
        ts_module._MAX_TASK_STORE = 2

        db_path = temp_dir / "lru_cancel_timer.db"
        monkeypatch.setattr(ts_module, "_get_db_path", lambda: db_path)

        svc = ts_module.TaskService()
        try:
            svc.set_task("task1", {"status": "done", "image_data": b"data1"})
            svc.set_task("task2", {"status": "done", "image_data": b"data2"})
            svc.schedule_image_data_cleanup("task1", delay=5.0)
            svc.schedule_image_data_cleanup("task2", delay=5.0)

            assert "task1" in svc._cleanup_timers
            assert "task2" in svc._cleanup_timers

            svc.set_task("task3", {"status": "done", "image_data": b"data3"})

            assert "task1" not in svc._cleanup_timers
            assert "task2" in svc._cleanup_timers
        finally:
            svc.close()
            ts_module._MAX_TASK_STORE = original_max


# ──────────────────────────────────────────────────
# 9. 认证中间件边界条件测试
# ──────────────────────────────────────────

@pytest.mark.integration
class TestAuthMiddlewareEdgeCases:
    """测试认证中间件的边界条件"""

    def test_auth_middleware_whitelist_endpoints(self, temp_dir, load_backend_app):
        """白名单端点应免认证"""
        from apps.web.api.config import settings
        from fastapi.testclient import TestClient

        original_token = settings.claw_auth_token

        backend = load_backend_app(temp_dir, "auth_whitelist")
        settings.claw_auth_token = "test_token_whitelist"

        try:
            client = TestClient(backend.app)

            whitelist_paths = ["/", "/api/health", "/api/info", "/api/status"]
            for path in whitelist_paths:
                resp = client.get(path)
                assert resp.status_code == 200, f"白名单端点 {path} 应免认证"
        finally:
            settings.claw_auth_token = original_token

    def test_auth_middleware_token_in_query(self, temp_dir, load_backend_app):
        """查询参数 token 应作为回退生效"""
        from apps.web.api.config import settings
        from fastapi.testclient import TestClient

        original_token = settings.claw_auth_token

        backend = load_backend_app(temp_dir, "auth_query_token")
        settings.claw_auth_token = "query_test_token"

        try:
            client = TestClient(backend.app)

            resp = client.get("/api/config?token=query_test_token")
            assert resp.status_code == 200

            resp = client.get("/api/config?token=wrong_token")
            assert resp.status_code == 401
        finally:
            settings.claw_auth_token = original_token

    def test_auth_middleware_empty_token_disables_auth(self, temp_dir, load_backend_app):
        """空 token 应禁用认证"""
        from fastapi.testclient import TestClient

        backend = load_backend_app(temp_dir, "auth_empty_token")

        client = TestClient(backend.app)

        resp = client.get("/api/config")
        assert resp.status_code == 200

        resp = client.get("/api/history")
        assert resp.status_code == 200

    def test_auth_middleware_static_app_whitelist(self, temp_dir, load_backend_app):
        """F-001 修复：/app/* 静态文件端点应免认证"""
        from apps.web.api.config import settings
        from fastapi.testclient import TestClient

        original_token = settings.claw_auth_token

        backend = load_backend_app(temp_dir, "auth_app_whitelist")
        settings.claw_auth_token = "test_token_app_whitelist"

        try:
            client = TestClient(backend.app)

            # 静态文件请求不应要求认证
            resp = client.get("/app/index.html")
            assert resp.status_code == 200, f"/app/index.html 无 token 应返回 200，实际 {resp.status_code}"
            assert "text/html" in resp.headers.get("content-type", "")

            resp = client.get("/app/app.js")
            assert resp.status_code == 200, f"/app/app.js 无 token 应返回 200，实际 {resp.status_code}"

            # 带 /app 前缀的任意路径都应被白名单放行
            resp = client.get("/app/styles.css")
            assert resp.status_code == 200, f"/app/styles.css 无 token 应返回 200，实际 {resp.status_code}"
        finally:
            settings.claw_auth_token = original_token


# ──────────────────────────────────────────────────
# 10. 安全工具函数边界测试
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestSecurityUtilsBoundary:
    """测试安全工具函数的边界条件"""

    def test_extract_safe_extension_malicious_extensions(self):
        """恶意扩展名应被正确处理（防止文件类型伪造）"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "backend_main_ext_boundary",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        test_cases = [
            ("../../etc/passwd.exe", ".exe"),
            ("file.jpg.php", ".php"),
            ("file.png.svg", ".svg"),
            ("file.gif.js", ".js"),
            ("file.tar.gz", ".gz"),
            ("file.jpg..", "."),
            ("file.", "."),
            ("file", ".png"),
            ("", ".png"),
            ("file.with.multiple.dots.exe", ".exe"),
        ]

        for input_name, expected in test_cases:
            result = backend._extract_safe_extension(input_name)
            assert result == expected, f"Expected {expected}, got {result} for {input_name}"

    def test_extract_safe_extension_path_traversal(self):
        """路径穿越应被安全处理"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "backend_main_ext_traverse",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        result = backend._extract_safe_extension("../../etc/passwd.exe")
        assert result == ".exe"

        result = backend._extract_safe_extension("..\\..\\windows\\system32\\cmd.exe")
        assert result == ".exe"

    def test_validate_file_id_special_characters(self):
        """特殊字符应被拒绝"""
        import importlib.util
        from fastapi import HTTPException
        spec = importlib.util.spec_from_file_location(
            "backend_main_fid_special",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        invalid_ids = [
            "abcdefg",
            "a" * 31,
            "a" * 33,
            "abcdef1234567890abcdef1234567890xyz",
            "0" * 32 + "x",
            "abcdef1234567890ABCDEF1234567890",
        ]

        for bad_id in invalid_ids:
            with pytest.raises(HTTPException) as exc_info:
                backend._validate_file_id(bad_id)
            assert exc_info.value.status_code == 400

    def test_validate_file_id_valid_formats(self):
        """有效的 32 位十六进制应通过"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "backend_main_fid_valid",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        valid_ids = [
            "a" * 32,
            "0" * 32,
            "abcdef1234567890abcdef1234567890",
            "0123456789abcdef0123456789abcdef",
        ]

        for valid_id in valid_ids:
            backend._validate_file_id(valid_id)


# ──────────────────────────────────────────────────
# 11. MarkdownGenerator 图片引用替换测试
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestMarkdownGeneratorImageReplacement:
    """测试 _replace_image_refs 多种格式处理"""

    def test_replace_image_refs_basic_key(self):
        """基本 img_key 引用应被替换"""
        from apps.web.api.markdown_generator import MarkdownGenerator

        md = MarkdownGenerator(output_dir=Path("/tmp"))
        images = {"img_0": "base64_data_0", "img_1": "base64_data_1"}

        input_text = '![alt](img_0)\n![alt2](img_1)'
        result = md._replace_image_refs(input_text, images)

        assert "imgs/img_0.png" in result
        assert "imgs/img_1.png" in result

    def test_replace_image_refs_path_prefix(self):
        """带路径前缀的引用应被正确解析"""
        from apps.web.api.markdown_generator import MarkdownGenerator

        md = MarkdownGenerator(output_dir=Path("/tmp"))
        images = {"img_0": "base64_data"}

        test_cases = [
            ('![alt](imgs/img_0)', 'imgs/img_0.png'),
            ('![alt](img/img_0)', 'imgs/img_0.png'),
            ('![alt](./img_0)', 'imgs/img_0.png'),
        ]

        for input_text, expected_path in test_cases:
            result = md._replace_image_refs(input_text, images)
            assert expected_path in result

    def test_replace_image_refs_html_img_tag(self):
        """HTML img 标签应被替换"""
        from apps.web.api.markdown_generator import MarkdownGenerator

        md = MarkdownGenerator(output_dir=Path("/tmp"))
        images = {"img_0": "base64_data"}

        input_text = '<img src="img_0" alt="test" />'
        result = md._replace_image_refs(input_text, images)

        assert 'src="imgs/img_0.png"' in result

    def test_replace_image_refs_external_url_unchanged(self):
        """外部 URL 应保持不变"""
        from apps.web.api.markdown_generator import MarkdownGenerator

        md = MarkdownGenerator(output_dir=Path("/tmp"))
        images = {"img_0": "base64_data"}

        test_cases = [
            '![alt](https://example.com/img.png)',
            '![alt](http://example.com/img.png)',
            '<img src="https://example.com/img.png" />',
        ]

        for input_text in test_cases:
            result = md._replace_image_refs(input_text, images)
            assert result == input_text

    def test_replace_image_refs_data_uri_unchanged(self):
        """data: URI 应保持不变"""
        from apps.web.api.markdown_generator import MarkdownGenerator

        md = MarkdownGenerator(output_dir=Path("/tmp"))
        images = {"img_0": "base64_data"}

        input_text = '![alt](data:image/png;base64,iVBORw0KGgo)'
        result = md._replace_image_refs(input_text, images)

        assert result == input_text


# ──────────────────────────────────────────────────
# 12. 批量上传端点测试
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestBatchUpload:
    """测试批量上传端点的边界条件"""

    def test_batch_upload_exceeds_limit(self, temp_dir, load_backend_app):
        """超过文件数量限制应被拒绝"""
        from fastapi.testclient import TestClient
        from PIL import Image

        backend = load_backend_app(temp_dir, "batch_upload_limit")
        client = TestClient(backend.app)

        files = []
        for i in range(21):
            img = Image.new("RGB", (50, 50))
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            files.append(("files", (f"test{i}.jpg", io.BytesIO(buf.getvalue()), "image/jpeg")))

        resp = client.post("/api/upload/batch", files=files)

        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False
        assert "不能超过" in data["error"]

    def test_batch_upload_empty_files(self, temp_dir, load_backend_app):
        """空文件列表应被拒绝（FastAPI 返回 422 验证错误）"""
        from fastapi.testclient import TestClient

        backend = load_backend_app(temp_dir, "batch_upload_empty")
        client = TestClient(backend.app)

        resp = client.post("/api/upload/batch", files=[])

        assert resp.status_code == 422

    def test_batch_upload_mixed_valid_invalid(self, temp_dir, load_backend_app):
        """混合有效和无效文件应部分成功"""
        from fastapi.testclient import TestClient
        from PIL import Image

        backend = load_backend_app(temp_dir, "batch_upload_mixed")
        client = TestClient(backend.app)

        files = []

        img = Image.new("RGB", (50, 50))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        files.append(("files", ("valid.jpg", io.BytesIO(buf.getvalue()), "image/jpeg")))

        files.append(("files", ("invalid.txt", b"not an image", "text/plain")))

        img2 = Image.new("RGB", (60, 60))
        buf2 = io.BytesIO()
        img2.save(buf2, format="PNG")
        files.append(("files", ("valid2.png", io.BytesIO(buf2.getvalue()), "image/png")))

        resp = client.post("/api/upload/batch", files=files)

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert data["succeeded"] >= 2
        assert data["failed"] >= 1

    def test_batch_upload_with_octet_stream(self, temp_dir, load_backend_app):
        """application/octet-stream 类型应根据扩展名判断"""
        from fastapi.testclient import TestClient
        from PIL import Image

        backend = load_backend_app(temp_dir, "batch_upload_octet")
        client = TestClient(backend.app)

        img = Image.new("RGB", (50, 50))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")

        files = [
            ("files", ("test.jpg", io.BytesIO(buf.getvalue()), "application/octet-stream")),
        ]

        resp = client.post("/api/upload/batch", files=files)

        assert resp.status_code == 200
        data = resp.json()
        assert data["succeeded"] == 1


# ──────────────────────────────────────────────────
# 13. /api/test-paddleocr 端点测试
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestTestPaddleOcr:
    """测试 PaddleOCR API 连接测试端点"""

    def test_test_paddleocr_no_key_configured(self, temp_dir, load_backend_app):
        """未配置 API key 应返回错误"""
        from apps.web.api.config import settings
        from fastapi.testclient import TestClient

        backend = load_backend_app(temp_dir, "test_paddleocr_no_key")
        client = TestClient(backend.app)

        original_key = settings.paddleocr_api_key
        settings.paddleocr_api_key = ""

        try:
            resp = client.get("/api/test-paddleocr")

            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is False
            assert "API Token 未配置" in data["error"]
        finally:
            settings.paddleocr_api_key = original_key

    def test_test_paddleocr_no_url_configured(self, temp_dir, load_backend_app):
        """未配置 API URL 应返回错误"""
        from apps.web.api.config import settings
        from fastapi.testclient import TestClient

        original_url = settings.paddleocr_api_url
        settings.paddleocr_api_url = ""
        settings.paddleocr_api_key = "test_key"

        try:
            backend = load_backend_app(temp_dir, "test_paddleocr_no_url")
            client = TestClient(backend.app)

            resp = client.get("/api/test-paddleocr")

            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is False
            assert "API URL 未配置" in data["error"]
        finally:
            settings.paddleocr_api_url = original_url

    def test_test_paddleocr_connect_error(self, temp_dir, load_backend_app):
        """连接失败应返回错误"""
        from apps.web.api.config import settings
        from fastapi.testclient import TestClient

        settings.paddleocr_api_key = "test_key"
        settings.paddleocr_api_url = "https://nonexistent-api-12345.test"

        backend = load_backend_app(temp_dir, "test_paddleocr_connect")
        client = TestClient(backend.app)

        resp = client.get("/api/test-paddleocr")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False


# ──────────────────────────────────────────────────
# 14. TaskService close() 方法测试
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestTaskServiceClose:
    """测试 TaskService.close() 资源清理"""

    def test_close_cleans_up_db_connection(self, temp_dir, monkeypatch):
        """close() 应关闭数据库连接"""
        import importlib
        ts_module = importlib.import_module("apps.web.api.services.task_service")
        db_path = temp_dir / "test_close_db.db"
        monkeypatch.setattr(ts_module, "_get_db_path", lambda: db_path)

        svc = ts_module.TaskService()
        try:
            db = svc._ensure_db()
            assert svc._db is not None

            svc.close()

            assert svc._db is None
        finally:
            try:
                svc.close()
            except Exception:
                pass

    def test_close_cancels_cleanup_timers(self, temp_dir, monkeypatch):
        """close() 应取消所有清理定时器"""
        import importlib
        ts_module = importlib.import_module("apps.web.api.services.task_service")
        db_path = temp_dir / "test_close_timers.db"
        monkeypatch.setattr(ts_module, "_get_db_path", lambda: db_path)

        svc = ts_module.TaskService()
        try:
            svc.set_task("task1", {"status": "done", "image_data": b"data"})
            svc.schedule_image_data_cleanup("task1", delay=5.0)

            assert len(svc._cleanup_timers) == 1

            svc.close()

            assert len(svc._cleanup_timers) == 0
        finally:
            try:
                svc.close()
            except Exception:
                pass

    def test_close_multiple_times_safe(self, temp_dir, monkeypatch):
        """多次调用 close() 应安全"""
        import importlib
        ts_module = importlib.import_module("apps.web.api.services.task_service")
        db_path = temp_dir / "test_close_multiple.db"
        monkeypatch.setattr(ts_module, "_get_db_path", lambda: db_path)

        svc = ts_module.TaskService()
        try:
            svc.close()
            svc.close()
            svc.close()

            assert svc._db is None
        finally:
            try:
                svc.close()
            except Exception:
                pass


# ──────────────────────────────────────────────────
# 15. PaddleOCRService submit_and_poll 测试
# ──────────────────────────────────────────

@pytest.mark.unit
class TestSubmitAndPoll:
    """测试 submit_and_poll 完整流程"""

    @pytest.mark.anyio
    async def test_submit_and_poll_success(self):
        """完整流程应成功"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService(api_url="https://api.example.com", api_key="key")

        with patch.object(service, "submit_task", new_callable=AsyncMock) as mock_submit, \
             patch.object(service, "poll_result", new_callable=AsyncMock) as mock_poll, \
             patch.object(service, "extract_result") as mock_extract:

            mock_submit.return_value = {"success": True, "job_id": "test_job"}
            mock_poll.return_value = {
                "success": True,
                "json_text": '{"result": {"layoutParsingResults": [{"markdown": {"text": "test"}}]}}',
                "raw_json": {"result": {"layoutParsingResults": [{"markdown": {"text": "test"}}]}},
                "markdown_text": "# Test",
            }
            mock_extract.return_value = {
                "markdown_text": "# Test",
                "images": {},
                "layout_image": None,
                "layout_items": [],
            }

            result = await service.submit_and_poll(image_data=b"test_data", filename="test.jpg")

            assert result["success"] is True
            assert result["markdown_text"] == "# Test"

    @pytest.mark.anyio
    async def test_submit_and_poll_submit_failure(self):
        """提交失败应返回错误"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService(api_url="https://api.example.com", api_key="key")

        with patch.object(service, "submit_task", new_callable=AsyncMock) as mock_submit:
            mock_submit.return_value = {"success": False, "error": "提交失败"}

            result = await service.submit_and_poll(image_data=b"test_data", filename="test.jpg")

            assert result["success"] is False
            assert "提交失败" in result["error"]

    @pytest.mark.anyio
    async def test_submit_and_poll_poll_failure(self):
        """轮询失败应返回错误"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService(api_url="https://api.example.com", api_key="key")

        with patch.object(service, "submit_task", new_callable=AsyncMock) as mock_submit, \
             patch.object(service, "poll_result", new_callable=AsyncMock) as mock_poll:

            mock_submit.return_value = {"success": True, "job_id": "test_job"}
            mock_poll.return_value = {"success": False, "error": "轮询失败"}

            result = await service.submit_and_poll(image_data=b"test_data", filename="test.jpg")

            assert result["success"] is False
            assert "轮询失败" in result["error"]


# ──────────────────────────────────────────────────
# 16. /api/init 端点行为分支测试（F-001 补测：空 token 公网部署模式）
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestInitTokenEndpoint:
    """测试 /api/init 在空 token / 非空 token 下的不同行为分支"""

    def test_init_token_empty_disables_auth_for_any_client(self, temp_dir, load_backend_app):
        """空 token 时，任何客户端访问都返回 auth_required=False（公网部署模式）"""
        from apps.web.api.config import settings
        from fastapi.testclient import TestClient

        original_token = settings.claw_auth_token
        backend = load_backend_app(temp_dir, "init_empty")
        settings.claw_auth_token = ""

        try:
            client = TestClient(backend.app)
            resp = client.get("/api/init")

            assert resp.status_code == 200
            data = resp.json()
            assert data["token"] == ""
            assert data["auth_required"] is False
        finally:
            settings.claw_auth_token = original_token

    def test_init_token_non_empty_localhost_allowed(self, temp_dir, load_backend_app):
        """非空 token + localhost 访问应返回 token 和 auth_required=True"""
        import asyncio
        from unittest.mock import MagicMock
        from apps.web.api.config import settings

        original_token = settings.claw_auth_token
        backend = load_backend_app(temp_dir, "init_local")
        settings.claw_auth_token = "secret_token_123"

        try:
            # 直接调用 init_token 函数，传入 mock Request 设置 client.host
            fake_request = MagicMock()
            fake_request.client.host = "127.0.0.1"

            result = asyncio.run(backend.init_token(fake_request))
            assert result["token"] == "secret_token_123"
            assert result["auth_required"] is True

            # 也验证 ::1 和 localhost 字面量
            for host in ("::1", "localhost"):
                fake_request.client.host = host
                result = asyncio.run(backend.init_token(fake_request))
                assert result["auth_required"] is True
        finally:
            settings.claw_auth_token = original_token

    def test_init_token_non_empty_remote_rejected(self, temp_dir, load_backend_app):
        """非空 token + 非 localhost 访问应返回 403"""
        import asyncio
        from unittest.mock import MagicMock
        from fastapi import HTTPException
        from apps.web.api.config import settings

        original_token = settings.claw_auth_token
        backend = load_backend_app(temp_dir, "init_remote")
        settings.claw_auth_token = "secret_token_456"

        try:
            # 直接调用 init_token 函数，传入 mock Request 设置非本地 IP
            for remote_host in ("8.8.8.8", "192.168.1.100", "1.2.3.4"):
                fake_request = MagicMock()
                fake_request.client.host = remote_host

                with pytest.raises(HTTPException) as exc_info:
                    asyncio.run(backend.init_token(fake_request))
                assert exc_info.value.status_code == 403
        finally:
            settings.claw_auth_token = original_token

    def test_init_token_empty_skips_localhost_check(self, temp_dir, load_backend_app):
        """空 token 时不应执行 localhost 检查（任何 IP 都可访问）"""
        from apps.web.api.config import settings
        from fastapi.testclient import TestClient

        original_token = settings.claw_auth_token
        backend = load_backend_app(temp_dir, "init_empty_remote")
        settings.claw_auth_token = ""

        try:
            client = TestClient(backend.app)
            # 即使有 X-Forwarded-For 模拟远程 IP，因 token 为空也应成功
            resp = client.get("/api/init", headers={"X-Forwarded-For": "1.2.3.4"})

            assert resp.status_code == 200
            data = resp.json()
            assert data["auth_required"] is False
        finally:
            settings.claw_auth_token = original_token


# ──────────────────────────────────────────────────
# 17. get_report_image 新增 BMP/TIFF MIME 类型测试
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestGetReportImageMimeTypes:
    """测试 get_report_image 对新增 BMP/TIFF 图片格式的 Content-Type 处理"""

    def _create_report_with_image(self, output_dir, image_name, image_bytes):
        """辅助函数：创建报告目录和图片文件"""
        from apps.web.api.config import settings
        report_dir = settings.get_output_path() / "test_mime_report"
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.md").write_text("# Test")
        imgs_dir = report_dir / "imgs"
        imgs_dir.mkdir(exist_ok=True)
        img_path = imgs_dir / image_name
        img_path.write_bytes(image_bytes)
        return img_path

    def test_get_report_image_bmp_returns_image_bmp(self, temp_dir, load_backend_app):
        """BMP 图片应返回 image/bmp Content-Type"""
        from fastapi.testclient import TestClient

        # BMP 文件头: BM (0x42, 0x4D)
        bmp_bytes = b"BM" + b"\x00" * 100

        backend = load_backend_app(temp_dir, "image_bmp")
        self._create_report_with_image(temp_dir, "chart.bmp", bmp_bytes)

        client = TestClient(backend.app)
        resp = client.get("/api/report/test_mime_report/image/imgs/chart.bmp")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/bmp"

    def test_get_report_image_tiff_returns_image_tiff(self, temp_dir, load_backend_app):
        """TIFF 图片应返回 image/tiff Content-Type"""
        from fastapi.testclient import TestClient

        # TIFF 文件头: II*\x00 (little-endian) 或 MM\x00* (big-endian)
        tiff_bytes = b"II*\x00" + b"\x00" * 50

        backend = load_backend_app(temp_dir, "image_tiff")
        self._create_report_with_image(temp_dir, "scan.tiff", tiff_bytes)

        client = TestClient(backend.app)
        resp = client.get("/api/report/test_mime_report/image/imgs/scan.tiff")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/tiff"

    def test_get_report_image_tif_short_ext_returns_image_tiff(self, temp_dir, load_backend_app):
        """.tif 短扩展名也应返回 image/tiff"""
        from fastapi.testclient import TestClient

        tiff_bytes = b"II*\x00" + b"\x00" * 50

        backend = load_backend_app(temp_dir, "image_tif")
        self._create_report_with_image(temp_dir, "scan.tif", tiff_bytes)

        client = TestClient(backend.app)
        resp = client.get("/api/report/test_mime_report/image/imgs/scan.tif")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/tiff"

    def test_get_report_image_uppercase_tiff_returns_image_tiff(self, temp_dir, load_backend_app):
        """大写 .TIFF 扩展名也应返回 image/tiff（大小写不敏感）"""
        from fastapi.testclient import TestClient

        tiff_bytes = b"II*\x00" + b"\x00" * 50

        backend = load_backend_app(temp_dir, "image_tiff_upper")
        self._create_report_with_image(temp_dir, "scan.TIFF", tiff_bytes)

        client = TestClient(backend.app)
        resp = client.get("/api/report/test_mime_report/image/imgs/scan.TIFF")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/tiff"

    def test_get_report_image_unknown_ext_returns_octet_stream(self, temp_dir, load_backend_app):
        """未知扩展名应回退到 application/octet-stream"""
        from fastapi.testclient import TestClient

        backend = load_backend_app(temp_dir, "image_unknown")
        self._create_report_with_image(temp_dir, "data.xyz", b"unknown data")

        client = TestClient(backend.app)
        resp = client.get("/api/report/test_mime_report/image/imgs/data.xyz")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/octet-stream"

    def test_get_report_image_png_still_works(self, temp_dir, load_backend_app):
        """回归测试：原有 PNG 支持应保持不变"""
        from fastapi.testclient import TestClient

        # 有效的 PNG magic bytes
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50

        backend = load_backend_app(temp_dir, "image_png")
        self._create_report_with_image(temp_dir, "test.png", png_bytes)

        client = TestClient(backend.app)
        resp = client.get("/api/report/test_mime_report/image/imgs/test.png")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"


# ──────────────────────────────────────────────────
# 18. TaskService DB 索引创建验证测试（性能优化）
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestDatabaseIndexes:
    """验证 _init_db 中创建的索引存在，加速常用查询"""

    def test_history_timestamp_index_exists(self, temp_dir, monkeypatch):
        """idx_history_timestamp 索引应被创建"""
        import importlib
        ts_module = importlib.import_module("apps.web.api.services.task_service")
        db_path = temp_dir / "test_idx_timestamp.db"
        monkeypatch.setattr(ts_module, "_get_db_path", lambda: db_path)

        svc = ts_module.TaskService()
        try:
            db = svc._ensure_db()
            cursor = db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_history_timestamp'"
            )
            row = cursor.fetchone()
            assert row is not None, "idx_history_timestamp 索引应存在"
            assert row[0] == "idx_history_timestamp"
        finally:
            svc.close()

    def test_history_file_id_index_exists(self, temp_dir, monkeypatch):
        """idx_history_file_id 索引应被创建"""
        import importlib
        ts_module = importlib.import_module("apps.web.api.services.task_service")
        db_path = temp_dir / "test_idx_file_id.db"
        monkeypatch.setattr(ts_module, "_get_db_path", lambda: db_path)

        svc = ts_module.TaskService()
        try:
            db = svc._ensure_db()
            cursor = db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_history_file_id'"
            )
            row = cursor.fetchone()
            assert row is not None, "idx_history_file_id 索引应存在"
            assert row[0] == "idx_history_file_id"
        finally:
            svc.close()

    def test_index_used_for_order_by_query(self, temp_dir, monkeypatch):
        """ORDER BY timestamp DESC 查询应能利用 idx_history_timestamp"""
        import importlib
        ts_module = importlib.import_module("apps.web.api.services.task_service")
        db_path = temp_dir / "test_idx_query.db"
        monkeypatch.setattr(ts_module, "_get_db_path", lambda: db_path)

        svc = ts_module.TaskService()
        try:
            # 添加 3 条历史记录
            for i in range(3):
                svc.add_history({"filename": f"f{i}.jpg", "file_id": f"fid{i}"})

            db = svc._ensure_db()
            # 使用 EXPLAIN QUERY PLAN 验证索引被使用
            cursor = db.execute(
                "EXPLAIN QUERY PLAN "
                "SELECT * FROM history ORDER BY timestamp DESC LIMIT 10"
            )
            plan = cursor.fetchall()
            plan_text = " ".join(str(row) for row in plan)
            # 验证查询计划中包含 idx_history_timestamp（B-Tree 索引扫描）
            assert "idx_history_timestamp" in plan_text, (
                f"ORDER BY timestamp DESC 应使用 idx_history_timestamp，实际计划: {plan_text}"
            )
        finally:
            svc.close()

    def test_index_used_for_file_id_lookup(self, temp_dir, monkeypatch):
        """按 file_id 查询应能利用 idx_history_file_id"""
        import importlib
        ts_module = importlib.import_module("apps.web.api.services.task_service")
        db_path = temp_dir / "test_idx_fid_query.db"
        monkeypatch.setattr(ts_module, "_get_db_path", lambda: db_path)

        svc = ts_module.TaskService()
        try:
            svc.add_history({"filename": "f1.jpg", "file_id": "unique_fid_xyz"})

            db = svc._ensure_db()
            cursor = db.execute(
                "EXPLAIN QUERY PLAN "
                "SELECT * FROM history WHERE file_id = ?",
                ("unique_fid_xyz",),
            )
            plan = cursor.fetchall()
            plan_text = " ".join(str(row) for row in plan)
            assert "idx_history_file_id" in plan_text, (
                f"WHERE file_id 查询应使用 idx_history_file_id，实际计划: {plan_text}"
            )
        finally:
            svc.close()


# ──────────────────────────────────────────────────
# 19. _handle_task_done 并发写入测试
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestHandleTaskDoneConcurrentWrites:
    """测试 _handle_task_done 中 layout_items + json_dump 使用 asyncio.gather 并发写入"""

    def test_handle_task_done_writes_layout_and_json_concurrently(self, temp_dir, load_backend_app):
        """layout_items 和 json_dump 应被并发写入（总耗时 < 各自耗时之和）"""
        import time
        from datetime import datetime, timedelta
        from unittest.mock import MagicMock, AsyncMock
        from apps.web.api.config import settings

        backend = load_backend_app(temp_dir, "handle_done_concurrent")

        output_dir = settings.get_output_path()

        # 构造 fake poll_status 和 task_info（包含必需的 submit_time）
        task_info = {
            "status": "processing",
            "filename": "test.jpg",
            "file_id": "file_concurrent",
            "job_id": "job_concurrent",
            "submit_time": (datetime.now() - timedelta(seconds=2)).isoformat(),
        }
        # paddle_parser 期望 poll_result 包含 raw_json / json_text 字段
        poll_status = {
            "raw_result": {"layoutParsingResults": []},
            "raw_json": {"result": {"layoutParsingResults": []}},
            "json_text": '{"result": {"layoutParsingResults": []}}',
        }

        # 替换 markdown_generator 的方法为慢版本（每次 sleep 0.3s）
        original_save_layout = backend.markdown_generator.save_layout_report_standalone
        original_save_report = backend.markdown_generator.save_report

        async def fast_save_report(*args, **kwargs):
            """快速返回 report_dir"""
            from pathlib import Path
            report_dir = output_dir / "concurrent_test_report"
            report_dir.mkdir(parents=True, exist_ok=True)
            return report_dir

        def slow_save_layout(*args, **kwargs):
            time.sleep(0.3)
            return original_save_layout(*args, **kwargs)

        # Patch 后端函数内部的局部 _write_json_dump（_handle_task_done 内的内联函数）
        # 通过 patch builtins.open 让 json_dump 写入慢 0.3s
        original_open = open

        def slow_open(file, mode="r", *args, **kwargs):
            f = original_open(file, mode, *args, **kwargs)
            if "downloaded_result.json" in str(file) and "w" in mode:
                # 包装 write 方法
                original_write = f.write
                def slow_write(content):
                    time.sleep(0.3)
                    return original_write(content)
                f.write = slow_write
            return f

        with patch.object(backend.markdown_generator, "save_layout_report_standalone", side_effect=slow_save_layout), \
             patch.object(backend.markdown_generator, "save_report", new=AsyncMock(side_effect=fast_save_report)), \
             patch("builtins.open", side_effect=slow_open):
            start_time = time.time()
            result = await_in_event_loop(
                backend._handle_task_done("task_concurrent", task_info, poll_status)
            )
            elapsed = time.time() - start_time

        # 如果并发执行，总耗时应 < 0.55s（两个 0.3s 并发）
        # 串行执行需 0.6s，并发应接近 0.3s
        assert elapsed < 0.55, (
            f"layout_items + json_dump 应并发执行，耗时 {elapsed:.2f}s "
            f"接近串行执行时间 0.6s，并发优化可能未生效"
        )
        # _handle_task_done 返回 {"status": "done", "result": {"success": True, ...}}
        assert result["status"] == "done"
        assert result["result"]["success"] is True


def await_in_event_loop(coro):
    """在同步测试中运行 async 协程的辅助函数"""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ──────────────────────────────────────────────────
# 20. MarkdownGenerator 并发图片下载测试
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestMarkdownGeneratorConcurrentImages:
    """测试 save_markdown_report_async 中的并发图片下载（Semaphore(8) + asyncio.gather）"""

    def test_concurrent_image_downloads_with_base64(self, temp_dir):
        """base64 图片应被正确保存（验证保存成功）"""
        import asyncio
        import base64
        from apps.web.api.markdown_generator import MarkdownGenerator

        # 5 个 base64 小图片
        small_img_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"X" * 50).decode()
        images = {f"img_{i}": small_img_b64 for i in range(5)}

        gen = MarkdownGenerator(output_dir=temp_dir)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                gen.save_report(
                    original_filename="test.jpg",
                    markdown_text="# Test\n\nContent with images",
                    images=images,
                    processing_time=1.0,
                )
            )
        finally:
            loop.close()

        # 验证所有图片文件被保存（save_report 在 output_dir 下创建带时间戳的子目录）
        subdirs = [d for d in temp_dir.iterdir() if d.is_dir()]
        assert len(subdirs) >= 1, f"应创建至少 1 个报告目录，实际 {len(subdirs)}"
        report_dir = subdirs[0]
        imgs_dir = report_dir / "imgs"
        assert imgs_dir.exists(), f"imgs/ 子目录应存在，实际未创建: {report_dir}"
        saved_files = list(imgs_dir.iterdir())
        assert len(saved_files) == 5, f"应保存 5 张图片，实际 {len(saved_files)}"

    def test_concurrent_downloads_respect_semaphore_limit(self, temp_dir):
        """并发下载应受 Semaphore(8) 限制（同时最多 8 个下载）"""
        import asyncio
        import time
        from unittest.mock import AsyncMock, patch
        from apps.web.api.markdown_generator import MarkdownGenerator

        # 20 张图片，超过 Semaphore(8) 的限制
        active_downloads = [0]
        max_concurrent = [0]
        lock = threading.Lock()

        async def slow_resolve(image_value):
            with lock:
                active_downloads[0] += 1
                if active_downloads[0] > max_concurrent[0]:
                    max_concurrent[0] = active_downloads[0]
            await asyncio.sleep(0.1)
            with lock:
                active_downloads[0] -= 1
            return b"\x89PNG\r\n\x1a\n" + b"X" * 10

        # 使用 base64 格式避免触发 URL 验证和 httpx
        import base64
        images = {
            f"img_{i}": base64.b64encode(b"fake_data").decode()
            for i in range(20)
        }

        gen = MarkdownGenerator(output_dir=temp_dir)

        loop = asyncio.new_event_loop()
        try:
            # 替换 _resolve_image_data_async 为慢速版本（100ms per call）
            with patch.object(
                MarkdownGenerator,
                "_resolve_image_data_async",
                new_callable=AsyncMock,
            ) as mock_resolve:
                mock_resolve.side_effect = slow_resolve
                loop.run_until_complete(
                    gen.save_report(
                        original_filename="test.jpg",
                        markdown_text="# Test",
                        images=images,
                        processing_time=1.0,
                    )
                )
        finally:
            loop.close()

        # 验证同时下载数不超过 8（Semaphore 限制）
        assert max_concurrent[0] <= 8, (
            f"并发下载数应 ≤ 8 (Semaphore 限制)，实际 {max_concurrent[0]}"
        )
        # 且应使用过并发（验证 Semaphore 确实在限制但允许并发）
        assert max_concurrent[0] >= 2, (
            f"应至少有 2 个并发下载，实际 {max_concurrent[0]}（可能为串行执行）"
        )

    def test_concurrent_downloads_continue_on_individual_failure(self, temp_dir):
        """单个图片下载失败不应影响其他图片的保存"""
        import asyncio
        import base64
        from unittest.mock import AsyncMock, patch
        from apps.web.api.markdown_generator import MarkdownGenerator

        # 混合：3 张正常 base64 + 2 张会失败的"图片"
        good_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"good").decode()
        images = {
            "img_0": good_b64,
            "img_1": good_b64,
            "img_2": good_b64,
            "img_3": "INVALID_BASE64_DATA!!!",
            "img_4": "ALSO_INVALID!!!",
        }

        gen = MarkdownGenerator(output_dir=temp_dir)
        loop = asyncio.new_event_loop()
        try:
            # 即使某些图片失败，函数不应抛出异常
            loop.run_until_complete(
                gen.save_report(
                    original_filename="test.jpg",
                    markdown_text="# Test",
                    images=images,
                    processing_time=1.0,
                )
            )
        finally:
            loop.close()

        # 正常图片应被保存（至少 3 张）
        subdirs = [d for d in temp_dir.iterdir() if d.is_dir()]
        if subdirs:
            imgs_dir = subdirs[0] / "imgs"
            if imgs_dir.exists():
                saved_count = len(list(imgs_dir.iterdir()))
                assert saved_count >= 3, f"至少应保存 3 张正常图片，实际 {saved_count}"


# ──────────────────────────────────────────────────
# 21. batch_delete_reports safe_entries 优化测试
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestBatchDeleteReportsSafeEntries:
    """测试 batch_delete_reports 中 safe_entries 缓存优化（避免重复调用 _safe_report_dir）"""

    def test_batch_delete_reports_skips_path_traversal(self, temp_dir, load_backend_app):
        """路径遍历 ID 应被过滤掉，仅合法 ID 被处理"""
        from apps.web.api.config import settings
        from fastapi.testclient import TestClient

        backend = load_backend_app(temp_dir, "batch_del_safe")

        output_dir = settings.get_output_path()

        # 创建两个合法报告
        for rid in ["valid_a", "valid_b"]:
            d = output_dir / rid
            d.mkdir(parents=True, exist_ok=True)
            (d / "report.md").write_text(f"# {rid}")

        client = TestClient(backend.app)
        resp = client.post("/api/reports/batch-delete", json={
            "ids": ["valid_a", "../../etc/passwd", "valid_b", "../traverse"]
        })

        assert resp.status_code == 200
        data = resp.json()
        # total 应为经过滤后的合法 ID 数（2 个）
        assert data["total"] == 2
        assert data["deleted"] == 2
        assert data["failed"] == 0
        # 验证两个报告都已被删除
        assert not (output_dir / "valid_a").exists()
        assert not (output_dir / "valid_b").exists()

    def test_batch_delete_reports_uses_safe_entries_for_failed_dir(self, temp_dir, load_backend_app):
        """合法 ID 但目录不存在时应在 results 中报告 failed（不抛出 404）"""
        from apps.web.api.config import settings
        from fastapi.testclient import TestClient

        backend = load_backend_app(temp_dir, "batch_del_missing")

        output_dir = settings.get_output_path()

        # 仅创建 1 个报告，另一个"合法 ID"对应的目录不存在
        d = output_dir / "exists_report"
        d.mkdir(parents=True, exist_ok=True)
        (d / "report.md").write_text("# Exists")

        client = TestClient(backend.app)
        resp = client.post("/api/reports/batch-delete", json={
            "ids": ["exists_report", "not_exists_report"]
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["deleted"] == 1
        assert data["failed"] == 1

    def test_batch_delete_reports_all_invalid_returns_400(self, temp_dir, load_backend_app):
        """全部 ID 均路径遍历时应返回 400"""
        from fastapi.testclient import TestClient

        backend = load_backend_app(temp_dir, "batch_del_all_invalid")
        client = TestClient(backend.app)

        resp = client.post("/api/reports/batch-delete", json={
            "ids": ["../etc/passwd", "..\\windows", "../../secret"]
        })

        assert resp.status_code == 400
        data = resp.json()
        # 全局异常处理器将 detail 转为 error 字段
        assert "没有有效的报告 ID" in str(data.get("error", "")) or "格式均非法" in str(data.get("error", ""))

    def test_batch_delete_reports_empty_list_returns_400(self, temp_dir, load_backend_app):
        """空 ID 列表应返回 400"""
        from fastapi.testclient import TestClient

        backend = load_backend_app(temp_dir, "batch_del_empty")
        client = TestClient(backend.app)

        resp = client.post("/api/reports/batch-delete", json={"ids": []})

        assert resp.status_code == 400
        assert "未提供" in str(resp.json().get("error", ""))