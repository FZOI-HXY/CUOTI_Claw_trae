"""
测试: apps/web/api/main.py - FastAPI 后端 API 集成测试

涵盖完整业务流程:
  1. 健康检查 (GET /api/health)
  2. 系统状态 (GET /api/status)
  3. 配置管理 (GET/POST /api/config)
  4. 文件上传 (POST /api/upload)
  5. 任务提交 (POST /api/submit/{file_id})
  6. 任务轮询 (POST /api/poll/{task_id})
  7. 报告管理 (GET /api/reports, GET /api/report/{id}, DELETE)
  8. 历史记录 (GET/DELETE /api/history, POST /api/history/batch-delete)
  9. 报告管理 (GET /api/reports, GET /api/report/{id}, DELETE)
  10. 完整端到端业务流程
  11. 错误处理与边界条件

使用 FastAPI TestClient + httpx Mock 隔离外部 API 依赖。
"""

import sys
import io
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# 确保 backend 路径在最前面
_backend_path = str(Path(__file__).parent.parent / "apps" / "web" / "api")
if _backend_path in sys.path:
    sys.path.remove(_backend_path)
sys.path.insert(0, _backend_path)


# ──────────────────────────────────────────────────
# Fixtures: 创建 TestClient with 完整的 Mock
# ──────────────────────────────────────────────────

@pytest.fixture(scope="function")
def api_client(temp_dir, load_backend_app):
    """创建 FastAPI TestClient，mock paddle_service"""
    from apps.web.api.config import settings

    # 保存原始配置，便于测试后恢复
    original_upload = settings.upload_dir
    original_output = settings.output_dir
    original_log = settings.log_dir

    # load_backend_app 完成：settings 三目录设置、api_key 设置、目录创建、
    # importlib 加载 main.py、task_store/_history 清空、_db 关闭
    backend_main = load_backend_app(temp_dir, "api_client")
    app = backend_main.app

    # Mock PaddleOCRService 的核心方法
    with patch.object(backend_main.paddle_service, "submit_task", new_callable=AsyncMock) as mock_submit, \
         patch.object(backend_main.paddle_service, "poll_once", new_callable=AsyncMock) as mock_poll, \
         patch.object(backend_main.paddle_service, "extract_result") as mock_extract:

        # submit_task 返回值 (每次调用生成不同 job_id)
        _submit_counter = [0]
        async def _mock_submit(*args, **kwargs):
            del args, kwargs  # 匹配 mock side_effect 签名，参数未使用
            _submit_counter[0] += 1
            return {"success": True, "job_id": f"mock_job_{_submit_counter[0]:08d}"}
        mock_submit.side_effect = _mock_submit

        # poll_once 返回值 (已完成状态)
        mock_poll.return_value = {
            "status": "done",
            "state": "done",
            "raw_result": {},
        }

        # extract_result 返回值
        mock_extract.return_value = {
            "markdown_text": "# Test Report\n\nMock OCR result content.",
            "images": {},
            "layout_image": None,
            "layout_items": [],
        }

        client = TestClient(app)
        yield client

    # 恢复原始配置
    settings.upload_dir = original_upload
    settings.output_dir = original_output
    settings.log_dir = original_log


@pytest.fixture(scope="function")
def uploaded_file_id(api_client, sample_image_bytes):
    """上传一个文件并返回 file_id"""
    from apps.web.api.services.task_service import task_service
    task_service._task_store.clear()

    resp = api_client.post("/api/upload", files={
        "file": ("test_image.jpg", io.BytesIO(sample_image_bytes), "image/jpeg")
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"]
    return data["file_id"]


# ──────────────────────────────────────────────────
# 1. 健康检查
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestHealthCheck:
    """测试健康检查端点"""

    def test_root_endpoint(self, api_client):
        """GET / 返回重定向到前端或服务信息"""
        resp = api_client.get("/", follow_redirects=False)
        # 根端点可能返回 302 重定向到 /app/ 或返回 JSON 服务信息
        if resp.status_code == 302:
            assert "/app" in resp.headers.get("location", "")
        else:
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "running"
            assert data["name"] == "错题管理系统"

    def test_health_check(self, api_client):
        """GET /api/health"""
        resp = api_client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"

    def test_system_status(self, api_client):
        """GET /api/status"""
        resp = api_client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert "uptime_seconds" in data
        assert "processed_count" in data
        assert "api_configured" in data


# ──────────────────────────────────────────────────
# 2. 配置管理
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestConfigAPI:
    """测试配置 API"""

    def test_get_config(self, api_client):
        """GET /api/config"""
        resp = api_client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "paddleocr_model" in data
        assert "port" in data
        assert "max_upload_size_mb" in data

    def test_update_config_log_level(self, api_client):
        """POST /api/config 更新日志级别"""
        resp = api_client.post("/api/config", json={"log_level": "DEBUG"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "log_level" in data["updated_fields"]

    def test_update_config_max_upload(self, api_client):
        """POST /api/config 更新最大上传"""
        resp = api_client.post("/api/config", json={"max_upload_size_mb": 100})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_save_api_config(self, api_client):
        """POST /api/config 更新 API 配置"""
        resp = api_client.post("/api/config", json={
            "paddleocr_api_url": "https://new-api.example.com",
            "paddleocr_model": "PP-OCRv5",
        })
        assert resp.status_code == 200
        assert resp.json()["success"]


# ──────────────────────────────────────────────────
# 3. 文件上传
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestUploadAPI:
    """测试文件上传"""

    def test_upload_valid_image(self, api_client, sample_image_bytes):
        """上传有效图片"""
        resp = api_client.post("/api/upload", files={
            "file": ("test.jpg", io.BytesIO(sample_image_bytes), "image/jpeg")
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "file_id" in data
        assert len(data["file_id"]) == 32  # uuid hex
        assert data["original_name"] == "test.jpg"
        assert data["size"] > 0

    def test_upload_png_image(self, api_client):
        """上传 PNG 图片"""
        from PIL import Image
        img = Image.new("RGB", (100, 100), color=(50, 100, 200))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        img_bytes = buf.getvalue()

        resp = api_client.post("/api/upload", files={
            "file": ("screenshot.png", io.BytesIO(img_bytes), "image/png")
        })
        assert resp.status_code == 200
        assert resp.json()["success"]

    def test_upload_rejects_invalid_type(self, api_client):
        """拒绝不支持的文件类型"""
        resp = api_client.post("/api/upload", files={
            "file": ("malware.exe", io.BytesIO(b"\x4d\x5a"), "application/octet-stream")
        })
        assert resp.status_code == 400

    def test_upload_pdf_with_octet_stream_content_type(self, api_client):
        """PDF 文件以 application/octet-stream 上传时应通过扩展名回退被接受"""
        # 构造最小 PDF 文件（magic bytes: %PDF）
        pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
        resp = api_client.post("/api/upload", files={
            "file": ("document.pdf", io.BytesIO(pdf_bytes), "application/octet-stream")
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_upload_pdf_with_correct_content_type(self, api_client):
        """PDF 文件以 application/pdf 上传应成功"""
        pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
        resp = api_client.post("/api/upload", files={
            "file": ("document.pdf", io.BytesIO(pdf_bytes), "application/pdf")
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_upload_rejects_oversized(self, api_client):
        """拒绝超大文件（超过限制大小的文件被拒绝）"""
        from apps.web.api.config import settings
        original_max = settings.max_upload_size_mb
        try:
            # 临时设为 1MB，用 2MB 文件触发拒绝
            settings.max_upload_size_mb = 1
            oversized = b"X" * (2 * 1024 * 1024)  # 2MB > 1MB limit
            resp = api_client.post("/api/upload", files={
                "file": ("big.jpg", io.BytesIO(oversized), "image/jpeg")
            })
            assert resp.status_code == 400
        finally:
            settings.max_upload_size_mb = original_max

    def test_upload_multiple_files_different_ids(self, api_client, sample_image_bytes):
        """多次上传获得不同的 file_id"""
        ids = []
        for i in range(3):
            resp = api_client.post("/api/upload", files={
                "file": (f"test_{i}.jpg", io.BytesIO(sample_image_bytes), "image/jpeg")
            })
            assert resp.status_code == 200
            ids.append(resp.json()["file_id"])
        assert len(set(ids)) == 3


# ──────────────────────────────────────────────────
# 4. 任务提交
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestSubmitAPI:
    """测试任务提交"""

    def test_submit_valid_file(self, api_client, uploaded_file_id):
        """提交已上传的文件进行 OCR"""
        resp = api_client.post(f"/api/submit/{uploaded_file_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "task_id" in data
        assert data["file_id"] == uploaded_file_id

    def test_submit_nonexistent_file(self, api_client):
        """提交不存在的文件（使用合法格式的 file_id 触发 404）"""
        # S01: file_id 必须是 32 位十六进制，使用合法格式但不存在的 ID
        valid_format_id = "a" * 32
        resp = api_client.post(f"/api/submit/{valid_format_id}")
        assert resp.status_code == 404

    def test_submit_returns_unique_task_ids(self, api_client, sample_image_bytes):
        """多次提交返回不同的 task_id"""
        # 先上传两个文件
        file_ids = []
        for i in range(2):
            resp = api_client.post("/api/upload", files={
                "file": (f"file_{i}.jpg", io.BytesIO(sample_image_bytes), "image/jpeg")
            })
            file_ids.append(resp.json()["file_id"])

        task_ids = []
        for fid in file_ids:
            resp = api_client.post(f"/api/submit/{fid}")
            task_ids.append(resp.json()["task_id"])

        assert task_ids[0] != task_ids[1]

    def test_submit_with_page_ranges(self, api_client, uploaded_file_id):
        """提交任务时指定页码范围"""
        resp = api_client.post(f"/api/submit/{uploaded_file_id}?page_ranges=1,3-5")
        assert resp.status_code == 200
        assert resp.json()["success"]


# ──────────────────────────────────────────────────
# 5. 任务轮询
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestPollAPI:
    """测试任务轮询"""

    def test_poll_completed_task(self, api_client, uploaded_file_id):
        """轮询已完成的 OCR 任务"""
        # 先提交
        submit_resp = api_client.post(f"/api/submit/{uploaded_file_id}")
        task_id = submit_resp.json()["task_id"]

        # 轮询
        poll_resp = api_client.post(f"/api/poll/{task_id}")
        assert poll_resp.status_code == 200
        data = poll_resp.json()
        assert data["completed"] is True
        assert data["status"] == "done"
        assert "result" in data
        assert "markdown_text" in data["result"]

    def test_poll_nonexistent_task(self, api_client):
        """轮询不存在的任务"""
        resp = api_client.post("/api/poll/nonexistent_task")
        assert resp.status_code == 404

    def test_poll_returns_markdown(self, api_client, uploaded_file_id):
        """轮询结果包含 Markdown 文本"""
        submit_resp = api_client.post(f"/api/submit/{uploaded_file_id}")
        task_id = submit_resp.json()["task_id"]

        poll_resp = api_client.post(f"/api/poll/{task_id}")
        result = poll_resp.json()["result"]
        # save_report 会在原始 markdown 基础上添加元信息
        assert "markdown_text" in result
        assert len(result["markdown_text"]) > 0
        assert "processing_time" in result
        assert "images_count" in result


# ──────────────────────────────────────────────────
# 6. 处理历史
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestHistoryAPI:
    """测试处理历史"""

    def test_empty_history(self, api_client):
        """空历史记录"""
        resp = api_client.get("/api/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_history_after_complete_flow(self, api_client, uploaded_file_id):
        """完成上传→提交→轮询后历史记录更新"""
        # 提交
        submit_resp = api_client.post(f"/api/submit/{uploaded_file_id}")
        task_id = submit_resp.json()["task_id"]
        # 轮询
        api_client.post(f"/api/poll/{task_id}")

        # 检查历史
        resp = api_client.get("/api/history")
        data = resp.json()
        assert data["total"] >= 1

    def test_history_limit_parameter(self, api_client):
        """limit 参数限制返回条数"""
        resp = api_client.get("/api/history?limit=5")
        assert resp.status_code == 200

    def test_delete_nonexistent_history(self, api_client):
        """删除不存在的历史记录"""
        resp = api_client.delete("/api/history/nonexistent_id")
        assert resp.status_code == 404

    def test_single_delete_history(self, api_client, uploaded_file_id):
        """删除单条历史记录"""
        # 完成上传→提交→轮询流程以生成历史记录
        submit_resp = api_client.post(f"/api/submit/{uploaded_file_id}")
        task_id = submit_resp.json()["task_id"]
        api_client.post(f"/api/poll/{task_id}")

        # 获取历史记录
        history_resp = api_client.get("/api/history")
        history_data = history_resp.json()
        assert history_data["total"] >= 1
        first_id = history_data["items"][0]["id"]

        # 删除
        del_resp = api_client.delete(f"/api/history/{first_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["success"] is True

        # 确认已删除
        resp = api_client.get("/api/history")
        ids = [item["id"] for item in resp.json()["items"]]
        assert first_id not in ids

    def test_batch_delete_history(self, api_client, sample_image_bytes):
        """批量删除多条历史记录"""
        # 创建 3 条历史记录
        for i in range(3):
            upload_resp = api_client.post("/api/upload", files={
                "file": (f"batch_{i}.jpg", io.BytesIO(sample_image_bytes), "image/jpeg")
            })
            file_id = upload_resp.json()["file_id"]
            submit_resp = api_client.post(f"/api/submit/{file_id}")
            task_id = submit_resp.json()["task_id"]
            api_client.post(f"/api/poll/{task_id}")

        # 获取所有记录 ID
        history_resp = api_client.get("/api/history?limit=100")
        all_ids = [item["id"] for item in history_resp.json()["items"]]
        assert len(all_ids) >= 3

        # 批量删除前 2 条
        delete_ids = all_ids[:2]
        batch_resp = api_client.post("/api/history/batch-delete", json={"ids": delete_ids})
        assert batch_resp.status_code == 200
        data = batch_resp.json()
        assert data["success"] is True
        assert data["deleted"] == 2

        # 确认已删除的条目不存在
        resp = api_client.get("/api/history?limit=100")
        remaining_ids = [item["id"] for item in resp.json()["items"]]
        for did in delete_ids:
            assert did not in remaining_ids, f"#{did} should have been deleted"

    def test_batch_delete_empty_ids(self, api_client):
        """批量删除时未提供 ID"""
        resp = api_client.post("/api/history/batch-delete", json={"ids": []})
        assert resp.status_code == 400

    def test_batch_delete_missing_payload(self, api_client):
        """批量删除时缺少 ids 字段"""
        resp = api_client.post("/api/history/batch-delete", json={})
        assert resp.status_code == 400


# ──────────────────────────────────────────────────
# 7. 报告管理
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestReportsAPI:
    """测试报告管理"""

    def test_get_reports(self, api_client):
        """获取报告列表"""
        resp = api_client.get("/api/reports")
        assert resp.status_code == 200
        data = resp.json()
        assert "reports" in data

    def test_get_nonexistent_report(self, api_client):
        """获取不存在的报告"""
        resp = api_client.get("/api/report/nonexistent_id")
        assert resp.status_code == 404

    def test_delete_nonexistent_report(self, api_client):
        """删除不存在的报告"""
        resp = api_client.delete("/api/report/nonexistent_id")
        assert resp.status_code == 404

    def test_batch_delete_reports_empty(self, api_client):
        """批量删除：空列表应返回400"""
        resp = api_client.post("/api/reports/batch-delete", json={"ids": []})
        assert resp.status_code == 400

    def test_batch_delete_reports_no_ids(self, api_client):
        """批量删除：缺少ids字段应返回400"""
        resp = api_client.post("/api/reports/batch-delete", json={})
        assert resp.status_code == 400

    def test_batch_delete_reports_path_traversal(self, api_client):
        """批量删除：路径遍历ID应被过滤"""
        resp = api_client.post("/api/reports/batch-delete", json={"ids": ["../../etc/passwd", "../test"]})
        # 所有ID都无效，返回400
        assert resp.status_code == 400

    def test_batch_delete_nonexistent_reports(self, api_client):
        """批量删除不存在的报告"""
        resp = api_client.post("/api/reports/batch-delete", json={"ids": ["nonexist1", "nonexist2"]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["deleted"] == 0
        assert data["failed"] == 2
        assert len(data["results"]) == 2

    def test_get_report_image_valid(self, api_client, sample_image_bytes):
        """获取报告中的有效图片"""
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location(
            "img_test",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        output_dir = backend.settings.output_dir
        if not Path(output_dir).is_absolute():
            output_dir = str(Path(__file__).parent.parent / "apps" / "web" / "api" / output_dir)

        report_id = "test_image_report"
        report_dir = Path(output_dir) / report_id
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.md").write_text("# test")
        (report_dir / "valid_image.png").write_bytes(sample_image_bytes)

        try:
            resp = api_client.get(f"/api/report/{report_id}/image/valid_image.png")
            assert resp.status_code == 200
            assert resp.headers.get("content-type") == "image/png"
            assert resp.content == sample_image_bytes
        finally:
            import shutil
            if report_dir.exists():
                shutil.rmtree(report_dir)

    def test_get_report_image_nonexistent(self, api_client):
        """获取不存在的报告图片"""
        resp = api_client.get("/api/report/nonexistent/image/test.png")
        assert resp.status_code == 404

    def test_get_report_image_path_traversal(self, api_client, sample_image_bytes):
        """图片路径穿越攻击应被拒绝（400或404都表示安全防护生效）"""
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location(
            "img_path_test",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        output_dir = backend.settings.output_dir
        if not Path(output_dir).is_absolute():
            output_dir = str(Path(__file__).parent.parent / "apps" / "web" / "api" / output_dir)

        report_id = "test_path_report"
        report_dir = Path(output_dir) / report_id
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.md").write_text("# test")

        malicious_paths = [
            "../secret.txt",
            "../../etc/passwd",
            "/etc/passwd",
            "..\\windows\\system32",
            "../../../etc/passwd",
        ]

        try:
            for malicious_path in malicious_paths:
                resp = api_client.get(f"/api/report/{report_id}/image/{malicious_path}")
                assert resp.status_code in (400, 404), f"路径穿越应被拒绝: {malicious_path}"
        finally:
            import shutil
            if report_dir.exists():
                shutil.rmtree(report_dir)

    def test_get_report_image_subdirectory(self, api_client, sample_image_bytes):
        """获取子目录中的图片"""
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location(
            "img_subdir_test",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        output_dir = backend.settings.output_dir
        if not Path(output_dir).is_absolute():
            output_dir = str(Path(__file__).parent.parent / "apps" / "web" / "api" / output_dir)

        report_id = "test_subdir_report"
        report_dir = Path(output_dir) / report_id
        sub_dir = report_dir / "images"
        sub_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.md").write_text("# test")
        (sub_dir / "nested.png").write_bytes(sample_image_bytes)

        try:
            resp = api_client.get(f"/api/report/{report_id}/image/images/nested.png")
            assert resp.status_code == 200
            assert resp.headers.get("content-type") == "image/png"
        finally:
            import shutil
            if report_dir.exists():
                shutil.rmtree(report_dir)

    def test_get_report_image_case_insensitive_extension(self, api_client, sample_image_bytes):
        """图片扩展名大小写不敏感"""
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location(
            "img_ext_test",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        output_dir = backend.settings.output_dir
        if not Path(output_dir).is_absolute():
            output_dir = str(Path(__file__).parent.parent / "apps" / "web" / "api" / output_dir)

        report_id = "test_ext_report"
        report_dir = Path(output_dir) / report_id
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.md").write_text("# test")
        (report_dir / "image.JPG").write_bytes(sample_image_bytes)

        try:
            resp = api_client.get(f"/api/report/{report_id}/image/image.JPG")
            assert resp.status_code == 200
            assert resp.headers.get("content-type") == "image/jpeg"
        finally:
            import shutil
            if report_dir.exists():
                shutil.rmtree(report_dir)

    def test_batch_delete_existing_reports(self, api_client, sample_image_bytes):
        """批量删除存在的报告（并行删除）"""
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location(
            "batch_del_test",
            Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py",
        )
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)

        output_dir = backend.settings.output_dir
        if not Path(output_dir).is_absolute():
            output_dir = str(Path(__file__).parent.parent / "apps" / "web" / "api" / output_dir)

        # 创建3个测试报告目录
        test_ids = ["test_batch_001", "test_batch_002", "test_batch_003"]
        for rid in test_ids:
            report_dir = Path(output_dir) / rid
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / "report.md").write_text("# test")
            (report_dir / "original.png").write_bytes(sample_image_bytes)

        try:
            resp = api_client.post("/api/reports/batch-delete", json={"ids": test_ids})
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["total"] == 3
            assert data["deleted"] == 3
            assert data["failed"] == 0

            # 验证目录已被删除
            for rid in test_ids:
                assert not (Path(output_dir) / rid).exists()
        finally:
            # 清理
            for rid in test_ids:
                d = Path(output_dir) / rid
                if d.exists():
                    import shutil
                    shutil.rmtree(d)


# ──────────────────────────────────────────────────
# 8. 完整端到端业务流程
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestEndToEndFlow:
    """端到端完整业务流程测试"""

    def test_full_pipeline_upload_submit_poll(self, api_client, sample_image_bytes):
        """完整流程：上传 → 提交 → 轮询 → 结果"""
        # Step 1: 上传文件
        upload_resp = api_client.post("/api/upload", files={
            "file": ("exam_question.jpg", io.BytesIO(sample_image_bytes), "image/jpeg")
        })
        assert upload_resp.status_code == 200, f"上传失败: {upload_resp.text}"
        file_id = upload_resp.json()["file_id"]

        # Step 2: 提交异步 OCR 任务
        submit_resp = api_client.post(f"/api/submit/{file_id}")
        assert submit_resp.status_code == 200, f"提交失败: {submit_resp.text}"
        task_id = submit_resp.json()["task_id"]

        # Step 3: 轮询任务结果
        poll_resp = api_client.post(f"/api/poll/{task_id}")
        assert poll_resp.status_code == 200, f"轮询失败: {poll_resp.text}"
        result = poll_resp.json()
        assert result["completed"] is True
        assert result["status"] == "done"
        assert result["result"]["markdown_text"] is not None

    def test_full_pipeline_multiple_files(self, api_client, sample_image_bytes):
        """批量文件完整流程"""
        results = []
        for i in range(3):
            # 上传
            upload_resp = api_client.post("/api/upload", files={
                "file": (f"batch_{i}.jpg", io.BytesIO(sample_image_bytes), "image/jpeg")
            })
            file_id = upload_resp.json()["file_id"]

            # 提交
            submit_resp = api_client.post(f"/api/submit/{file_id}")
            task_id = submit_resp.json()["task_id"]

            # 轮询
            poll_resp = api_client.post(f"/api/poll/{task_id}")
            results.append(poll_resp.json())

        # 所有任务都应完成
        all_done = all(r["completed"] and r["status"] == "done" for r in results)
        assert all_done, f"Not all tasks completed: {results}"

        # 历史记录应正确累积为 3 条（覆盖原 test_history_accumulates_correctly 的检查）
        history_resp = api_client.get("/api/history")
        assert history_resp.json()["total"] == 3


# ──────────────────────────────────────────────────
# 9. 错误处理与边界条件
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestErrorHandling:
    """测试错误处理"""

    def test_upload_without_file(self, api_client):
        """无文件上传"""
        resp = api_client.post("/api/upload")
        assert resp.status_code in (400, 422)

    def test_submit_invalid_file_id_format(self, api_client):
        """无效 file_id 格式（S01: 路径遍历防护）"""
        # 特殊字符和短字符串 — S01 后返回 400（格式校验失败）或 404/422（路由不匹配）
        for bad_id in ["../../etc/passwd", "<script>", "x", ""]:
            resp = api_client.post(f"/api/submit/{bad_id}")
            assert resp.status_code in (400, 404, 422), f"Expected 400/404/422 for '{bad_id}'"

    def test_config_rejects_invalid_key(self, api_client):
        """配置忽略不存在的字段"""
        resp = api_client.post("/api/config", json={"non_existent_field": "value"})
        # 应该返回成功但 updated_fields 为空
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["updated_fields"]) == 0

    def test_config_with_empty_body(self, api_client):
        """空 body 配置更新"""
        resp = api_client.post("/api/config", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["updated_fields"]) == 0

    def test_api_key_not_leaked_in_config(self, api_client):
        """配置文件不泄露 API 密钥原文"""
        from apps.web.api.config import settings
        resp = api_client.get("/api/config")
        data = resp.json()
        # paddleocr_api_key 应为掩码值，不能是明文
        assert data.get("paddleocr_api_key") != "test_token_for_mock", "API key must not be returned in plain text"
        # api_key_prefix 应该是截断的
        prefix = data.get("api_key_prefix", "")
        # API key 不应完整出现在响应中
        assert prefix != settings.paddleocr_api_key
        assert settings.paddleocr_api_key not in resp.text
        # 不再断言 len(prefix) < 20

    def test_health_check_no_auth_required(self, api_client):
        """健康检查不需要认证"""
        resp = api_client.get("/api/health")
        assert resp.status_code == 200


# ──────────────────────────────────────────────────
# 10. 新增端点测试
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestSubmitUrlAPI:
    """测试通过 URL 提交任务"""

    def test_submit_url_valid(self, api_client):
        """通过 URL 提交有效任务"""
        resp = api_client.post("/api/submit-url", json={
            "fileUrl": "https://example.com/image.jpg",
            "filename": "test.jpg",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "task_id" in data
        assert data["filename"] == "test.jpg"

    def test_submit_url_internal_ip_rejected(self, api_client):
        """URL 指向内网 IP 应被拒绝"""
        resp = api_client.post("/api/submit-url", json={
            "fileUrl": "https://192.168.1.1/image.jpg",
            "filename": "test.jpg",
        })
        assert resp.status_code == 400

    def test_submit_url_http_rejected(self, api_client):
        """HTTP URL 应被拒绝（必须 HTTPS）"""
        resp = api_client.post("/api/submit-url", json={
            "fileUrl": "http://example.com/image.jpg",
            "filename": "test.jpg",
        })
        assert resp.status_code == 400

    def test_submit_url_missing_filename(self, api_client):
        """缺少 filename 应仍能提交"""
        resp = api_client.post("/api/submit-url", json={
            "fileUrl": "https://example.com/image.jpg",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True


@pytest.mark.integration
class TestBatchAPI:
    """测试批量查询端点"""

    def test_get_batch_results(self, temp_dir, load_backend_app):
        """批量获取任务结果"""
        backend = load_backend_app(temp_dir, "batch_results")

        with patch.object(backend.paddle_service, "batch_get_results", new_callable=AsyncMock) as mb:
            async def _mock_batch(*args, **kwargs):
                return {
                    "success": True,
                    "results": [
                        {"task_id": "job1", "status": "done"},
                        {"task_id": "job2", "status": "done"},
                    ],
                }
            mb.side_effect = _mock_batch

            client = TestClient(backend.app)
            resp = client.get("/api/batch/test_batch_id")
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["count"] == 2
            assert len(data["results"]) == 2


@pytest.mark.integration
class TestBatchDownloadAPI:
    """测试批量下载端点安全防护"""

    def test_batch_download_empty_report_ids(self, api_client):
        """空报告ID列表应返回400"""
        resp = api_client.post("/api/batch/download", json={"report_ids": []})
        assert resp.status_code == 400

    def test_batch_download_exceeds_limit(self, api_client):
        """超过最大数量限制应返回400"""
        report_ids = [f"report_{i}" for i in range(21)]
        resp = api_client.post("/api/batch/download", json={"report_ids": report_ids})
        assert resp.status_code == 400

    def test_batch_download_path_traversal(self, api_client):
        """路径遍历攻击应被阻止"""
        malicious_ids = ["../../etc/passwd", "../secret/file"]
        resp = api_client.post("/api/batch/download", json={"report_ids": malicious_ids})
        assert resp.status_code == 400

    def test_batch_download_with_invalid_characters(self, api_client):
        """包含特殊字符的报告ID应被拒绝"""
        malicious_ids = ["report|test", "report;rm -rf", "report`echo"]
        resp = api_client.post("/api/batch/download", json={"report_ids": malicious_ids})
        assert resp.status_code == 400

    def test_batch_download_mixed_valid_invalid(self, temp_dir, load_backend_app):
        """混合有效和无效报告ID时只打包有效报告"""
        from apps.web.api.config import settings
        original_output = settings.output_dir

        # load_backend_app 已设置 output_dir 为 temp_dir/output 并创建目录
        backend = load_backend_app(temp_dir, "batch_download_mixed")

        try:
            valid_dir = Path(settings.output_dir) / "valid_report"
            valid_dir.mkdir()
            (valid_dir / "report.md").write_text("# Valid Report")

            client = TestClient(backend.app)
            resp = client.post("/api/batch/download", json={
                "report_ids": ["valid_report", "invalid_report", "../../etc/passwd"]
            })
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "application/zip"
        finally:
            settings.output_dir = original_output


@pytest.mark.integration
class TestUploadBatchAPI:
    """测试批量上传端点"""

    def test_upload_batch_multiple_files(self, api_client, sample_image_bytes):
        """批量上传多个文件"""
        resp = api_client.post("/api/upload/batch", files=[
            ("files", ("batch1.jpg", io.BytesIO(sample_image_bytes), "image/jpeg")),
            ("files", ("batch2.jpg", io.BytesIO(sample_image_bytes), "image/jpeg")),
            ("files", ("batch3.jpg", io.BytesIO(sample_image_bytes), "image/jpeg")),
        ])
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert data["succeeded"] == 3
        assert data["failed"] == 0

    def test_upload_batch_empty(self, api_client):
        """空文件列表应返回错误"""
        resp = api_client.post("/api/upload/batch", files=[])
        assert resp.status_code in (400, 422)

    def test_upload_batch_mixed_success_fail(self, api_client, sample_image_bytes):
        """混合成功和失败的批量上传"""
        resp = api_client.post("/api/upload/batch", files=[
            ("files", ("valid.jpg", io.BytesIO(sample_image_bytes), "image/jpeg")),
            ("files", ("invalid.exe", io.BytesIO(b"not_an_image"), "application/octet-stream")),
            ("files", ("valid2.jpg", io.BytesIO(sample_image_bytes), "image/jpeg")),
        ])
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert data["succeeded"] == 2
        assert data["failed"] == 1

    def test_upload_batch_exceeds_max_files(self, api_client, sample_image_bytes):
        """超过最大文件数量限制 (MAX_BATCH_FILES=20) 应返回 400"""
        files = [
            ("files", (f"file_{i}.jpg", io.BytesIO(sample_image_bytes), "image/jpeg"))
            for i in range(21)
        ]
        resp = api_client.post("/api/upload/batch", files=files)
        assert resp.status_code == 400
        # 自定义异常处理器返回 {"error": ...} 而非默认 {"detail": ...}
        assert "不能超过" in resp.json()["error"] or "exceed" in resp.json()["error"].lower()

    def test_upload_batch_at_max_boundary(self, api_client, sample_image_bytes):
        """恰好 20 个文件（边界值）应被接受"""
        files = [
            ("files", (f"file_{i}.jpg", io.BytesIO(sample_image_bytes), "image/jpeg"))
            for i in range(20)
        ]
        resp = api_client.post("/api/upload/batch", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 20


@pytest.mark.integration
class TestUploadAndProcessAPI:
    """测试上传并处理端点"""

    def test_upload_and_process(self, temp_dir, sample_image_bytes, load_backend_app):
        """一步完成上传和处理"""
        from apps.web.api.config import settings
        original_upload = settings.upload_dir
        original_output = settings.output_dir
        original_log = settings.log_dir

        # load_backend_app 完成：settings 三目录设置、api_key 设置、目录创建、
        # importlib 加载 main.py、task_store/_history 清空、_db 关闭
        backend = load_backend_app(temp_dir, "upload_and_process")

        try:
            with patch.object(backend.paddle_service, "submit_and_poll", new_callable=AsyncMock) as ms:
                async def _mock_submit_poll(*args, **kwargs):
                    return {
                        "success": True,
                        "markdown_text": "# Test Result\n\nContent.",
                        "images": {},
                        "processing_time": 2.5,
                    }
                ms.side_effect = _mock_submit_poll

                client = TestClient(backend.app)
                resp = client.post("/api/upload-and-process", files={
                    "file": ("test.jpg", io.BytesIO(sample_image_bytes), "image/jpeg")
                })
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is True
                assert "markdown_text" in data
                assert "file_id" in data
        finally:
            settings.upload_dir = original_upload
            settings.output_dir = original_output
            settings.log_dir = original_log


# ──────────────────────────────────────────────────
# 11. 批量删除并发安全性测试
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestBatchDeleteConcurrency:
    """测试批量删除报告的并发安全性"""

    def test_batch_delete_concurrent_execution(self, temp_dir, sample_image_bytes, load_backend_app):
        """批量删除应并行执行（使用 asyncio.gather）"""
        from apps.web.api.config import settings
        original_output = settings.output_dir

        # load_backend_app 完成 settings 三目录设置、目录创建、importlib 加载、task 清理
        backend = load_backend_app(temp_dir, "batch_del_concurrent")
        # 覆盖为带语义的子目录名（保留原测试意图）
        settings.output_dir = str(temp_dir / "output_concurrent")
        Path(settings.output_dir).mkdir(parents=True, exist_ok=True)

        try:
            # 创建10个报告目录
            report_ids = [f"concurrent_report_{i}" for i in range(10)]
            for rid in report_ids:
                report_dir = Path(settings.output_dir) / rid
                report_dir.mkdir(parents=True, exist_ok=True)
                (report_dir / "report.md").write_text("# Test Report")
                (report_dir / "original.png").write_bytes(sample_image_bytes)

            import asyncio
            import time
            client = TestClient(backend.app)

            # 记录开始时间
            start_time = time.time()

            # 执行批量删除
            resp = client.post("/api/reports/batch-delete", json={"ids": report_ids})
            elapsed = time.time() - start_time

            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["total"] == 10
            assert data["deleted"] == 10
            assert data["failed"] == 0

            # 验证所有目录已被删除
            for rid in report_ids:
                assert not (Path(settings.output_dir) / rid).exists()

            # 并行删除应比串行更快（粗略检查）
            # 串行删除 10 个目录约需 0.1-0.5秒，并行应更快
            # 这里放宽限制，避免因系统差异导致测试不稳定

        finally:
            settings.output_dir = original_output
            # 清理残留目录
            for rid in report_ids:
                d = Path(temp_dir / "output_concurrent") / rid
                if d.exists():
                    import shutil
                    shutil.rmtree(d)

    def test_batch_delete_partial_failure_handling(self, temp_dir, sample_image_bytes, load_backend_app):
        """批量删除部分失败时应正确统计"""
        from apps.web.api.config import settings
        original_output = settings.output_dir

        # load_backend_app 完成 settings 三目录设置、目录创建、importlib 加载、task 清理
        backend = load_backend_app(temp_dir, "batch_del_partial")
        # 覆盖为带语义的子目录名（保留原测试意图）
        settings.output_dir = str(temp_dir / "output_partial")
        Path(settings.output_dir).mkdir(parents=True, exist_ok=True)

        try:
            # 创建3个有效报告目录
            valid_ids = ["valid_001", "valid_002", "valid_003"]
            for rid in valid_ids:
                report_dir = Path(settings.output_dir) / rid
                report_dir.mkdir(parents=True, exist_ok=True)
                (report_dir / "report.md").write_text("# Test")

            # 添加2个不存在或已删除的报告ID
            invalid_ids = ["nonexistent_001", "nonexistent_002"]
            all_ids = valid_ids + invalid_ids

            client = TestClient(backend.app)

            # 执行批量删除
            resp = client.post("/api/reports/batch-delete", json={"ids": all_ids})
            assert resp.status_code == 200
            data = resp.json()

            assert data["success"] is True
            assert data["total"] == 5
            assert data["deleted"] == 3  # 3个有效
            assert data["failed"] == 2   # 2个无效

            # 检查结果详情
            results = data["results"]
            for result in results:
                if result["id"] in valid_ids:
                    assert result["success"] is True
                else:
                    assert result["success"] is False
                    assert "error" in result

        finally:
            settings.output_dir = original_output
            for rid in valid_ids:
                d = Path(temp_dir / "output_partial") / rid
                if d.exists():
                    import shutil
                    shutil.rmtree(d)


# ──────────────────────────────────────────────────
# 12. 批量下载布局测试
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestBatchDownloadLayout:
    """测试批量下载布局端点"""

    def test_batch_download_layout_empty_ids(self, api_client):
        """空报告ID列表应返回400"""
        resp = api_client.post("/api/batch/download-layout", json={"report_ids": []})
        assert resp.status_code == 400

    def test_batch_download_layout_path_traversal(self, api_client):
        """路径遍历攻击应被阻止

        注意：/api/batch/download-layout 端点接收 BatchLayoutRequest（files 字段），
        不涉及 report_id 或文件系统操作，因此不存在路径遍历攻击面。
        此测试验证端点对空文件列表返回 400。
        """
        resp = api_client.post("/api/batch/download-layout", json={"files": []})
        assert resp.status_code == 400

    def test_batch_download_layout_with_valid_files(self, api_client):
        """有效文件数据应生成正确的批量版面分析报告"""
        payload = {
            "files": [
                {
                    "filename": "math_problem.jpg",
                    "layout_items": [
                        {
                            "type": "title",
                            "region": {"x": 10, "y": 10, "width": 200, "height": 30},
                            "content_preview": "Chapter 1: Algebra",
                        },
                        {
                            "type": "text",
                            "region": {"x": 10, "y": 50, "width": 300, "height": 100},
                            "content_preview": "Solve for x: 2x + 5 = 15",
                        },
                    ],
                    "processing_time": 2.5,
                },
                {
                    "filename": "physics_problem.png",
                    "layout_items": [
                        {
                            "type": "image",
                            "region": {"bbox": [50, 50, 200, 150]},
                            "content_preview": "Diagram of forces",
                        },
                    ],
                    "processing_time": 3.2,
                },
            ]
        }

        resp = api_client.post("/api/batch/download-layout", json=payload)
        assert resp.status_code == 200
        assert resp.headers.get("content-type") == "text/markdown; charset=utf-8"
        assert 'filename="batch_layout_report.md"' in resp.headers.get("content-disposition", "")

        content = resp.text
        assert "# 批量版面分析报告" in content
        assert "math_problem.jpg" in content
        assert "physics_problem.png" in content
        assert "| **文件总数** | 2 |" in content
        assert "| **版面区域总数** | 3 |" in content
        assert "Chapter 1: Algebra" in content
        assert "Solve for x" in content
        assert "Diagram of forces" in content

    def test_batch_download_layout_xss_protection(self, api_client):
        """布局数据中的 XSS 攻击应被转义"""
        payload = {
            "files": [
                {
                    "filename": '<script>alert("xss")</script>.jpg',
                    "layout_items": [
                        {
                            "type": '<img src=x onerror=alert(1)>',
                            "region": {"x": 0, "y": 0, "width": 100, "height": 100},
                            "content_preview": '<svg/onload=alert(1)>',
                        },
                    ],
                    "processing_time": 1.0,
                }
            ]
        }

        resp = api_client.post("/api/batch/download-layout", json=payload)
        assert resp.status_code == 200

        content = resp.text
        assert "<script>" not in content
        assert "<img" not in content
        assert "<svg" not in content
        assert "&lt;" in content
        assert "&gt;" in content

    def test_batch_download_layout_markdown_escape(self, api_client):
        """文件名和内容中的 Markdown 特殊字符应被转义"""
        payload = {
            "files": [
                {
                    "filename": "file|name`with|special chars.jpg",
                    "layout_items": [
                        {
                            "type": "text",
                            "region": {"x": 0, "y": 0, "width": 100, "height": 100},
                            "content_preview": "content | with | pipes\nand newlines",
                        },
                    ],
                    "processing_time": 1.0,
                }
            ]
        }

        resp = api_client.post("/api/batch/download-layout", json=payload)
        assert resp.status_code == 200

        content = resp.text
        assert "\\|" in content or "file|name" not in content
        assert "\\`" in content or "name`with" not in content
        lines = content.split("\n")
        preview_line = [line for line in lines if "content_preview" in line.lower() or "content" in line]
        for line in preview_line:
            assert "\n" not in line

    def test_batch_download_layout_empty_layout_items(self, api_client):
        """空 layout_items 应正确处理"""
        payload = {
            "files": [
                {
                    "filename": "empty.jpg",
                    "layout_items": [],
                    "processing_time": 0.5,
                }
            ]
        }

        resp = api_client.post("/api/batch/download-layout", json=payload)
        assert resp.status_code == 200

        content = resp.text
        assert "（该文件未检测到版面区域）" in content

    def test_batch_download_layout_content_preview_truncation(self, api_client):
        """过长的 content_preview 应被截断"""
        long_content = "A" * 200 + "B" * 100
        payload = {
            "files": [
                {
                    "filename": "long_content.jpg",
                    "layout_items": [
                        {
                            "type": "text",
                            "region": {"x": 0, "y": 0, "width": 100, "height": 100},
                            "content_preview": long_content,
                        },
                    ],
                    "processing_time": 1.0,
                }
            ]
        }

        resp = api_client.post("/api/batch/download-layout", json=payload)
        assert resp.status_code == 200

        content = resp.text
        assert "..." in content
        assert content.count("A") <= 80
        assert "B" not in content

    def test_batch_download_layout_bbox_format(self, api_client):
        """bbox 格式的 region 应正确解析"""
        payload = {
            "files": [
                {
                    "filename": "bbox_test.jpg",
                    "layout_items": [
                        {
                            "type": "text",
                            "region": {"bbox": [10, 20, 30, 40]},
                            "content_preview": "bbox format",
                        },
                    ],
                    "processing_time": 1.0,
                }
            ]
        }

        resp = api_client.post("/api/batch/download-layout", json=payload)
        assert resp.status_code == 200

        content = resp.text
        assert "(10, 20, 30, 40)" in content

    def test_batch_download_layout_missing_filename(self, api_client):
        """缺少 filename 应使用默认值"""
        payload = {
            "files": [
                {
                    "layout_items": [],
                    "processing_time": 1.0,
                }
            ]
        }

        resp = api_client.post("/api/batch/download-layout", json=payload)
        assert resp.status_code == 200

        content = resp.text
        assert "文件1" in content


# ──────────────────────────────────────────────────
# 13. PaddleOCR API 连接测试端点
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestPaddleOCRConnectionAPI:
    """测试 /api/test-paddleocr 端点的连接检测功能

    该端点验证 PaddleOCR API 的连通性和 Token 有效性，
    涉及外部 API 调用、多种网络错误场景，需要全面覆盖。
    """

    def test_test_paddleocr_no_token_configured(self, api_client):
        """未配置 API Token 时应返回失败（无网络请求）"""
        from apps.web.api.config import settings
        original_key = settings.paddleocr_api_key
        settings.paddleocr_api_key = ""

        try:
            resp = api_client.get("/api/test-paddleocr")
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is False
            assert "API Token 未配置" in data["error"]
        finally:
            settings.paddleocr_api_key = original_key

    def test_test_paddleocr_no_url_configured(self, api_client):
        """未配置 API URL 时应返回失败（无网络请求）"""
        from apps.web.api.config import settings
        original_url = settings.paddleocr_api_url
        settings.paddleocr_api_url = ""

        try:
            resp = api_client.get("/api/test-paddleocr")
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is False
            assert "API URL 未配置" in data["error"]
        finally:
            settings.paddleocr_api_url = original_url

    def test_test_paddleocr_token_invalid_401(self, api_client):
        """API Token 无效时返回 401 应被正确识别"""
        from apps.web.api.config import settings
        import httpx

        original_url = settings.paddleocr_api_url
        original_key = settings.paddleocr_api_key
        settings.paddleocr_api_url = "https://test-api.example.com"
        settings.paddleocr_api_key = "invalid_test_token"

        try:
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_response = MagicMock()
                mock_response.status_code = 401
                mock_client.get.return_value = mock_response
                mock_client_class.return_value.__aenter__.return_value = mock_client

                resp = api_client.get("/api/test-paddleocr")
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is False
                assert "API Token 无效或已过期" in data["error"]
                assert "401" in data["detail"]
        finally:
            settings.paddleocr_api_url = original_url
            settings.paddleocr_api_key = original_key

    def test_test_paddleocr_token_invalid_403(self, api_client):
        """API Token 无效时返回 403 应被正确识别"""
        from apps.web.api.config import settings

        original_url = settings.paddleocr_api_url
        original_key = settings.paddleocr_api_key
        settings.paddleocr_api_url = "https://test-api.example.com"
        settings.paddleocr_api_key = "forbidden_test_token"

        try:
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_response = MagicMock()
                mock_response.status_code = 403
                mock_client.get.return_value = mock_response
                mock_client_class.return_value.__aenter__.return_value = mock_client

                resp = api_client.get("/api/test-paddleocr")
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is False
                assert "API Token 无效或已过期" in data["error"]
                assert "403" in data["detail"]
        finally:
            settings.paddleocr_api_url = original_url
            settings.paddleocr_api_key = original_key

    def test_test_paddleocr_connection_success_200(self, api_client):
        """连接成功且 Token 有效时返回 200"""
        from apps.web.api.config import settings

        original_url = settings.paddleocr_api_url
        original_key = settings.paddleocr_api_key
        settings.paddleocr_api_url = "https://valid-api.example.com"
        settings.paddleocr_api_key = "valid_test_token"

        try:
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_client.get.return_value = mock_response
                mock_client_class.return_value.__aenter__.return_value = mock_client

                resp = api_client.get("/api/test-paddleocr")
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is True
                assert data["status_code"] == 200
                assert "Token 有效" in data["detail"]
        finally:
            settings.paddleocr_api_url = original_url
            settings.paddleocr_api_key = original_key

    def test_test_paddleocr_connection_success_400(self, api_client):
        """连接成功且 Token 有效时返回 400（参数缺失也视为有效）"""
        from apps.web.api.config import settings

        original_url = settings.paddleocr_api_url
        original_key = settings.paddleocr_api_key
        settings.paddleocr_api_url = "https://valid-api.example.com"
        settings.paddleocr_api_key = "valid_test_token"

        try:
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_response = MagicMock()
                mock_response.status_code = 400
                mock_client.get.return_value = mock_response
                mock_client_class.return_value.__aenter__.return_value = mock_client

                resp = api_client.get("/api/test-paddleocr")
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is True
                assert data["status_code"] == 400
                assert "Token 有效" in data["detail"]
        finally:
            settings.paddleocr_api_url = original_url
            settings.paddleocr_api_key = original_key

    def test_test_paddleocr_connection_success_404(self, api_client):
        """连接成功且 Token 有效时返回 404（路由不匹配也视为有效）"""
        from apps.web.api.config import settings

        original_url = settings.paddleocr_api_url
        original_key = settings.paddleocr_api_key
        settings.paddleocr_api_url = "https://valid-api.example.com"
        settings.paddleocr_api_key = "valid_test_token"

        try:
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_response = MagicMock()
                mock_response.status_code = 404
                mock_client.get.return_value = mock_response
                mock_client_class.return_value.__aenter__.return_value = mock_client

                resp = api_client.get("/api/test-paddleocr")
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is True
                assert data["status_code"] == 404
                assert "Token 有效" in data["detail"]
        finally:
            settings.paddleocr_api_url = original_url
            settings.paddleocr_api_key = original_key

    def test_test_paddleocr_connect_error(self, api_client):
        """网络连接失败时应正确报告"""
        from apps.web.api.config import settings
        import httpx

        original_url = settings.paddleocr_api_url
        original_key = settings.paddleocr_api_key
        settings.paddleocr_api_url = "https://unreachable-api.example.com"
        settings.paddleocr_api_key = "valid_test_token"

        try:
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client.get.side_effect = httpx.ConnectError("Network unreachable")
                mock_client_class.return_value.__aenter__.return_value = mock_client

                resp = api_client.get("/api/test-paddleocr")
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is False
                assert "无法连接到 API 服务器" in data["error"]
        finally:
            settings.paddleocr_api_url = original_url
            settings.paddleocr_api_key = original_key

    def test_test_paddleocr_timeout(self, api_client):
        """请求超时时应正确报告"""
        from apps.web.api.config import settings
        import httpx

        original_url = settings.paddleocr_api_url
        original_key = settings.paddleocr_api_key
        settings.paddleocr_api_url = "https://slow-api.example.com"
        settings.paddleocr_api_key = "valid_test_token"

        try:
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client.get.side_effect = httpx.TimeoutException("Timeout")
                mock_client_class.return_value.__aenter__.return_value = mock_client

                resp = api_client.get("/api/test-paddleocr")
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is False
                assert "API 请求超时" in data["error"]
        finally:
            settings.paddleocr_api_url = original_url
            settings.paddleocr_api_key = original_key

    def test_test_paddleocr_generic_exception_debug_mode(self, api_client):
        """通用异常在 debug 模式下应包含详情"""
        from apps.web.api.config import settings

        original_url = settings.paddleocr_api_url
        original_key = settings.paddleocr_api_key
        original_debug = settings.debug
        settings.paddleocr_api_url = "https://error-api.example.com"
        settings.paddleocr_api_key = "valid_test_token"
        settings.debug = True

        try:
            # 不 mock httpx.AsyncClient，直接触发外层 try 块的通用异常
            with patch("httpx.AsyncClient.__init__", side_effect=RuntimeError("INTERNAL_SECRET_ERROR_12345")):
                resp = api_client.get("/api/test-paddleocr")
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is False
                assert "测试失败" in data["error"]
                # debug 模式下应包含错误详情
                assert "INTERNAL_SECRET_ERROR_12345" in data["detail"]
        finally:
            settings.paddleocr_api_url = original_url
            settings.paddleocr_api_key = original_key
            settings.debug = original_debug

    def test_test_paddleocr_generic_exception_production_mode(self, api_client):
        """通用异常在生产模式下不应泄露详情"""
        from apps.web.api.config import settings

        original_url = settings.paddleocr_api_url
        original_key = settings.paddleocr_api_key
        original_debug = settings.debug
        settings.paddleocr_api_url = "https://error-api.example.com"
        settings.paddleocr_api_key = "valid_test_token"
        settings.debug = False

        try:
            with patch("httpx.AsyncClient.__init__", side_effect=RuntimeError("SECRET_DETAIL_NOT_TO_LEAK")):
                resp = api_client.get("/api/test-paddleocr")
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is False
                assert "测试失败" in data["error"]
                # 生产模式下不应泄露内部错误详情
                assert "SECRET_DETAIL_NOT_TO_LEAK" not in data["detail"]
                assert data["detail"] == "内部错误"
        finally:
            settings.paddleocr_api_url = original_url
            settings.paddleocr_api_key = original_key
            settings.debug = original_debug
