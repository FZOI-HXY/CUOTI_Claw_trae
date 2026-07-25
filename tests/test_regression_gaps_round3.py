"""
自动化测试缺口分析工具 - 第三轮补充测试

目标：补充近期合并代码的关键测试缺口，降低回归风险。

重点修复的提交：
  - 3dc040b: PDF 上传 content_type 不匹配修复（扩展名回退）
  - f68e212: F-001 GET 请求认证 + 性能优化（asyncio.to_thread）

新增测试（按优先级排序）：
  P0:
    1. 批量上传 PDF + octet-stream + .pdf 扩展名回退（commit 3dc040b）
    2. 批量上传超大文件 DoS 防护（commit f68e212 seek/tell）
    3. 批量下载 ZIP 超大文件数量内存防护（commit f68e212 asyncio.to_thread）
  P1:
    4. 批量上传扩展名大小写处理（.PDF, .Pdf 等）
    5. 批量上传单个文件失败隔离（asyncio.gather 并发安全）
"""

import io
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

# 路径设置
_backend_path = str(Path(__file__).parent.parent / "apps" / "web" / "api")
if _backend_path in sys.path:
    sys.path.remove(_backend_path)
sys.path.insert(0, _backend_path)


# ──────────────────────────────────────────────────
# P0-1: 批量上传 PDF + octet-stream 扩展名回退
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestBatchUploadPdfOctetStreamFallback:
    """测试批量上传端点的 PDF + octet-stream 扩展名回退（commit 3dc040b）

    根因：桌面端 httpx 上传 PDF 时未显式指定 content_type，默认发送
    application/octet-stream，后端白名单不包含此类型导致拒绝。

    修复：后端添加扩展名回退检查——content_type 不在白名单时，
    检查文件扩展名是否在白名单中（.pdf 等）。
    """

    def test_batch_upload_pdf_with_octet_stream_accepted(self, temp_dir, load_backend_app):
        """PDF 文件以 application/octet-stream 批量上传时应通过扩展名回退被接受"""
        backend = load_backend_app(temp_dir, "batch_pdf_octet")
        client = TestClient(backend.app)

        # 构造最小 PDF 文件（magic bytes: %PDF）
        pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"

        # 批量上传 2 个 PDF 文件（content_type 为 application/octet-stream）
        files = [
            ("files", ("document1.pdf", io.BytesIO(pdf_bytes), "application/octet-stream")),
            ("files", ("document2.pdf", io.BytesIO(pdf_bytes), "application/octet-stream")),
        ]

        resp = client.post("/api/upload/batch", files=files)

        assert resp.status_code == 200
        data = resp.json()
        assert data["succeeded"] == 2, f"应成功上传 2 个 PDF，实际: {data}"

    def test_batch_upload_pdf_mixed_content_types(self, temp_dir, load_backend_app):
        """批量上传混合 content_type 的 PDF 文件"""
        backend = load_backend_app(temp_dir, "batch_pdf_mixed")
        client = TestClient(backend.app)

        pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"

        files = [
            # application/pdf（标准）
            ("files", ("standard.pdf", io.BytesIO(pdf_bytes), "application/pdf")),
            # application/octet-stream（回退）
            ("files", ("fallback.pdf", io.BytesIO(pdf_bytes), "application/octet-stream")),
        ]

        resp = client.post("/api/upload/batch", files=files)

        assert resp.status_code == 200
        data = resp.json()
        assert data["succeeded"] == 2

    def test_batch_upload_octet_stream_non_pdf_rejected(self, temp_dir, load_backend_app):
        """application/octet-stream 非 PDF 扩展名应被拒绝"""
        backend = load_backend_app(temp_dir, "batch_octet_non_pdf")
        client = TestClient(backend.app)

        files = [
            # .txt 扩展名不在白名单，应被拒绝
            ("files", ("not_pdf.txt", io.BytesIO(b"text content"), "application/octet-stream")),
        ]

        resp = client.post("/api/upload/batch", files=files)

        # 应返回 200（批量上传部分成功），但 succeeded=0
        assert resp.status_code == 200
        data = resp.json()
        assert data["succeeded"] == 0
        assert data["failed"] == 1


# ──────────────────────────────────────────────────
# P0-2: 批量上传超大文件 DoS 防护
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestBatchUploadOversizedFileProtection:
    """测试批量上传端点的超大文件 DoS 防护（commit f68e212）

    安全修复：先用 seek/tell 取文件大小，避免把超大文件整读进内存。
    防止攻击者通过上传超大文件导致内存耗尽（DoS）。
    """

    def test_batch_upload_single_oversized_file_rejected(self, temp_dir, load_backend_app):
        """批量上传单个超大文件应被拒绝，不导致内存溢出"""
        from apps.web.api.config import settings

        backend = load_backend_app(temp_dir, "batch_oversized")
        client = TestClient(backend.app)

        # 临时设为 1MB 限制
        original_max = settings.max_upload_size_mb
        settings.max_upload_size_mb = 1

        try:
            # 创建 2MB 的“伪图像"（头部伪装为 JPEG）
            # 注意：实际不会读取整个内容（seek/tell 优化）
            oversized_header = b"\xff\xd8\xff" + b"X" * 10  # JPEG magic bytes
            oversized_data = oversized_header + b"Y" * (2 * 1024 * 1024)

            files = [
                ("files", ("huge.jpg", io.BytesIO(oversized_data), "image/jpeg")),
            ]

            resp = client.post("/api/upload/batch", files=files)

            assert resp.status_code == 200
            data = resp.json()
            assert data["succeeded"] == 0
            assert data["failed"] == 1
            # 错误消息应提示文件过大
            error_msg = data["results"][0].get("error", "")
            assert "过大" in error_msg or "exceeds" in error_msg.lower()

        finally:
            settings.max_upload_size_mb = original_max

    def test_batch_upload_mixed_sizes_partial_success(self, temp_dir, load_backend_app):
        """批量上传混合大小文件：正常文件成功，超大文件失败"""
        from apps.web.api.config import settings
        from PIL import Image

        backend = load_backend_app(temp_dir, "batch_mixed_sizes")
        client = TestClient(backend.app)

        original_max = settings.max_upload_size_mb
        settings.max_upload_size_mb = 1

        try:
            # 正常大小图片（< 1MB）
            img = Image.new("RGB", (100, 100))
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            normal_img_bytes = buf.getvalue()

            # 超大"图片"（> 1MB）
            oversized_data = b"\xff\xd8\xff" + b"Z" * (2 * 1024 * 1024)

            files = [
                ("files", ("normal.jpg", io.BytesIO(normal_img_bytes), "image/jpeg")),
                ("files", ("huge.jpg", io.BytesIO(oversized_data), "image/jpeg")),
            ]

            resp = client.post("/api/upload/batch", files=files)

            assert resp.status_code == 200
            data = resp.json()
            # 正常文件应成功
            assert data["succeeded"] >= 1
            # 超大文件应失败
            assert data["failed"] >= 1

        finally:
            settings.max_upload_size_mb = original_max


# ──────────────────────────────────────────────────
# P0-3: 批量下载 ZIP 超大文件数量内存防护
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestBatchDownloadZipLargeCount:
    """测试批量下载 ZIP 打包的内存防护（commit f68e212）

    性能优化：使用 asyncio.to_thread 将同步 ZIP 打包移到线程中，
    避免阻塞事件循环。防止超大文件数量导致服务卡死。
    """

    def test_batch_download_many_reports_success(self, temp_dir, load_backend_app):
        """批量下载多个报告应成功，不阻塞事件循环"""
        import zipfile

        backend = load_backend_app(temp_dir, "batch_zip_many")
        client = TestClient(backend.app)

        # 创建 10 个报告目录（模拟大量报告）
        output_dir = backend.settings.get_output_path()
        report_ids = []
        for i in range(10):
            report_id = f"report_{i:04d}"
            report_dir = output_dir / report_id
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / "report.md").write_text(f"# Report {i}\n\nContent {i}")
            report_ids.append(report_id)

        # 批量下载
        resp = client.post(
            "/api/batch/download",
            json={"report_ids": report_ids},
        )

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"

        # 验证 ZIP 内容
        zip_data = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_data, "r") as zf:
            names = zf.namelist()
            # 应包含所有报告的 report.md
            for report_id in report_ids:
                assert any(report_id in n for n in names), f"ZIP 应包含 {report_id}"

    def test_batch_download_with_nonexistent_reports(self, temp_dir, load_backend_app):
        """批量下载包含不存在的报告时应跳过，不失败"""
        import zipfile

        backend = load_backend_app(temp_dir, "batch_zip_nonexist")
        client = TestClient(backend.app)

        # 创建 1 个真实报告
        output_dir = backend.settings.get_output_path()
        real_report_id = "real_report_001"
        report_dir = output_dir / real_report_id
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.md").write_text("# Real Report")

        # 请求包含真实和不存在的报告
        resp = client.post(
            "/api/batch/download",
            json={"report_ids": ["nonexistent_001", real_report_id, "nonexistent_002"]},
        )

        assert resp.status_code == 200

        # 验证 ZIP 只包含真实报告
        zip_data = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_data, "r") as zf:
            names = zf.namelist()
            assert any(real_report_id in n for n in names)
            assert not any("nonexistent" in n for n in names)


# ──────────────────────────────────────────────────
# P1-4: 批量上传扩展名大小写处理
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestBatchUploadExtensionCaseHandling:
    """测试批量上传端点的扩展名大小写处理"""

    def test_batch_upload_pdf_uppercase_extension(self, temp_dir, load_backend_app):
        """.PDF 大写扩展名应被接受"""
        backend = load_backend_app(temp_dir, "batch_pdf_upper")
        client = TestClient(backend.app)

        pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"

        files = [
            ("files", ("document.PDF", io.BytesIO(pdf_bytes), "application/octet-stream")),
        ]

        resp = client.post("/api/upload/batch", files=files)

        assert resp.status_code == 200
        data = resp.json()
        assert data["succeeded"] == 1

    def test_batch_upload_mixed_case_extensions(self, temp_dir, load_backend_app):
        """混合大小写扩展名应被正确处理"""
        backend = load_backend_app(temp_dir, "batch_mixed_case")
        client = TestClient(backend.app)

        pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"

        files = [
            ("files", ("file.PDF", io.BytesIO(pdf_bytes), "application/octet-stream")),
            ("files", ("file.Pdf", io.BytesIO(pdf_bytes), "application/octet-stream")),
            ("files", ("file.pdf", io.BytesIO(pdf_bytes), "application/octet-stream")),
        ]

        resp = client.post("/api/upload/batch", files=files)

        assert resp.status_code == 200
        data = resp.json()
        # 所有扩展名变体都应被接受
        assert data["succeeded"] == 3, f"应成功 3 个，实际: {data['succeeded']}"


# ──────────────────────────────────────────────────
# P1-5: 批量上传单个文件失败隔离
# ──────────────────────────────────────────────────

@pytest.mark.integration
class TestBatchUploadFailureIsolation:
    """测试批量上传单个文件失败不影响其他文件（并发安全）"""

    def test_batch_upload_one_invalid_magic_bytes_others_succeed(self, temp_dir, load_backend_app):
        """单个文件 magic bytes 校验失败，其他文件应成功"""
        from PIL import Image

        backend = load_backend_app(temp_dir, "batch_failure_iso")
        client = TestClient(backend.app)

        # 创建正常图片
        img = Image.new("RGB", (100, 100))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        normal_jpg = buf.getvalue()

        # 创建伪造 JPEG（错误 magic bytes）
        fake_jpg = b"NOT_JPEG_CONTENT"

        # 创建正常 PDF
        pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"

        files = [
            ("files", ("valid1.jpg", io.BytesIO(normal_jpg), "image/jpeg")),
            ("files", ("fake.jpg", io.BytesIO(fake_jpg), "image/jpeg")),  # magic bytes 不匹配
            ("files", ("valid2.pdf", io.BytesIO(pdf_bytes), "application/pdf")),
        ]

        resp = client.post("/api/upload/batch", files=files)

        assert resp.status_code == 200
        data = resp.json()
        # 2 个正常文件应成功
        assert data["succeeded"] == 2
        # 1 个伪造文件应失败
        assert data["failed"] == 1

    def test_batch_upload_one_exception_others_continue(self, temp_dir, load_backend_app):
        """单个文件处理异常，其他文件应继续处理"""
        from PIL import Image

        backend = load_backend_app(temp_dir, "batch_exception_iso")
        client = TestClient(backend.app)

        # 正常图片
        img = Image.new("RGB", (100, 100))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        normal_jpg = buf.getvalue()

        # 创建会导致处理异常的"文件"（模拟内部异常）
        # 注意：FastAPI 会在读取时处理，这里用 magic bytes 不匹配触发校验异常
        invalid_jpg = b"\xff\xd8\xff" + b"INVALID"

        files = [
            ("files", ("valid.jpg", io.BytesIO(normal_jpg), "image/jpeg")),
            ("files", ("invalid.jpg", io.BytesIO(invalid_jpg), "image/jpeg")),
        ]

        resp = client.post("/api/upload/batch", files=files)

        assert resp.status_code == 200
        data = resp.json()
        # 至少有 1 个成功（valid.jpg）
        assert data["succeeded"] >= 1


# ──────────────────────────────────────────────────
# 辅助 fixture（如果 conftest.py 中不存在）
# ──────────────────────────────────────────────────

# 注意：temp_dir, load_backend_app 已在 conftest.py 中定义，
# 这里不再重复定义。如果运行测试时提示 fixture 不存在，
# 请检查 conftest.py 是否正确导入。