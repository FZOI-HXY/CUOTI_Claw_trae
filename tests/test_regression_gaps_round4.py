"""
回归测试缺口补充 (Round 4)

针对近期代码变更中仍未被充分覆盖的关键路径：
  1. Markdown 图片引用的反向匹配（images key 含前缀，markdown 引用为裸文件名）
  2. TaskService 数据库索引初始化
  3. TaskService 在数据库异常时的内存回退行为
  4. PaddleOCRService 单个结果 URL 下载时的 SSRF 校验失败路径

所有测试均为确定性、隔离的单元测试，不依赖外部服务。
"""

import sys
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

_backend_path = str(Path(__file__).parent.parent / "apps" / "web" / "api")
if _backend_path in sys.path:
    sys.path.remove(_backend_path)
sys.path.insert(0, _backend_path)


@pytest.fixture
def svc_factory(temp_dir, monkeypatch):
    """返回 TaskService 工厂，与 test_task_service.py 保持一致。"""
    import importlib
    ts_module = importlib.import_module("apps.web.api.services.task_service")

    def _create(name="default"):
        db_path = temp_dir / f"test_{name}.db"
        monkeypatch.setattr(ts_module, "_get_db_path", lambda: db_path)
        return ts_module.TaskService(), db_path
    return _create


# ──────────────────────────────────────────────────
# 1. MarkdownGenerator 图片引用反向匹配
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestMarkdownImageReverseMatch:
    """测试 _replace_image_refs 的反向匹配逻辑。

    场景：images 字典的 key 包含前缀（如 imgs/foo.png），
    但 PaddleOCR 返回的 Markdown 中引用的是裸文件名（foo.png）。
    反向匹配能确保此类引用仍被正确替换为本地 imgs/ 路径。
    """

    def test_reverse_match_images_key_has_prefix(self):
        """images key 含 imgs/ 前缀，markdown 引用裸文件名时应匹配"""
        from apps.web.api.markdown_generator import MarkdownGenerator

        mg = MarkdownGenerator(output_dir=Path("/tmp"))
        images = {"imgs/foo.png": "data:image/png;base64,test"}

        md = "# Report\n\n![Alt](foo.png)"
        result = mg._replace_image_refs(md, images)

        assert "imgs/foo.png" in result
        assert "](foo.png)" not in result

    def test_reverse_match_images_key_has_img_prefix(self):
        """images key 含 img/ 前缀（无 s），markdown 引用裸文件名时应匹配"""
        from apps.web.api.markdown_generator import MarkdownGenerator

        mg = MarkdownGenerator(output_dir=Path("/tmp"))
        images = {"img/chart_0.jpg": "data:image/png;base64,test"}

        md = '<img src="chart_0.jpg" alt="Chart" />'
        result = mg._replace_image_refs(md, images)

        assert 'src="imgs/chart_0.jpg"' in result

    def test_reverse_match_no_match_returns_original(self):
        """反向匹配失败时应保留原始引用"""
        from apps.web.api.markdown_generator import MarkdownGenerator

        mg = MarkdownGenerator(output_dir=Path("/tmp"))
        images = {"imgs/other.png": "data:image/png;base64,test"}

        md = "![Alt](missing.png)"
        result = mg._replace_image_refs(md, images)

        assert result == "![Alt](missing.png)"


# ──────────────────────────────────────────────────
# 2. TaskService 数据库索引初始化
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestTaskServiceDbIndex:
    """测试 _init_db 创建的索引是否存在。

    索引对历史记录分页和 file_id 关联查询的性能至关重要，
    需要确保每次初始化数据库时都被创建。
    """

    def test_init_db_creates_history_indexes(self, temp_dir, monkeypatch):
        """数据库初始化后应包含预期的两个索引"""
        import importlib
        ts_module = importlib.import_module("apps.web.api.services.task_service")

        db_path = temp_dir / "index_test.db"
        monkeypatch.setattr(ts_module, "_get_db_path", lambda: db_path)

        # 强制重新初始化数据库
        db = ts_module._init_db()
        try:
            cursor = db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='history'"
            )
            index_names = {row[0] for row in cursor.fetchall()}

            assert "idx_history_timestamp" in index_names
            assert "idx_history_file_id" in index_names
        finally:
            db.close()


# ──────────────────────────────────────────────────
# 3. TaskService 数据库异常回退
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestTaskServiceDbFailureFallback:
    """测试数据库操作异常时 TaskService 回退到内存计数的正确性。

    这些路径保证即使 SQLite 临时不可用，内存中的热数据仍能被正确返回，
    避免前端分页或删除操作出现不可预期的错误。
    """

    def _broken_service(self, svc_factory, monkeypatch):
        """创建服务后让后续 DB 操作异常，模拟数据库不可用。"""
        import importlib
        ts_module = importlib.import_module("apps.web.api.services.task_service")

        svc, db_path = svc_factory("db_failure")
        svc.add_history({"id": "mem_1", "filename": "f1.jpg"})
        svc.add_history({"id": "mem_2", "filename": "f2.jpg"})

        # 强制 _ensure_db 抛出异常，模拟 SQLite 不可用
        def _raise_db_error():
            raise sqlite3.OperationalError("database is locked")
        monkeypatch.setattr(svc, "_ensure_db", _raise_db_error)
        return svc, db_path

    def test_get_history_count_falls_back_to_memory_on_db_error(self, svc_factory, monkeypatch):
        """DB COUNT 异常时应回退到内存 deque 长度"""
        svc, _ = self._broken_service(svc_factory, monkeypatch)
        try:
            count = svc.get_history_count()
            assert count == 2
        finally:
            svc.close()

    def test_get_history_with_count_falls_back_to_memory_on_db_error(self, svc_factory, monkeypatch):
        """DB COUNT 异常时 get_history_with_count 应回退到内存长度"""
        svc, _ = self._broken_service(svc_factory, monkeypatch)
        try:
            items, total = svc.get_history_with_count(limit=10, offset=0)
            assert len(items) == 2
            assert total == 2
        finally:
            svc.close()

    def test_delete_history_returns_true_when_in_memory_despite_db_error(self, svc_factory, monkeypatch):
        """内存命中但 DB 异常时，delete_history 仍应返回 True"""
        svc, _ = self._broken_service(svc_factory, monkeypatch)
        try:
            result = svc.delete_history("mem_1")
            assert result is True
            # 内存中应已删除
            assert "mem_1" not in {h["id"] for h in svc._history}
        finally:
            svc.close()

    def test_batch_delete_history_returns_memory_count_despite_db_error(self, svc_factory, monkeypatch):
        """内存命中但 DB 异常时，batch_delete_history 应返回内存删除数"""
        svc, _ = self._broken_service(svc_factory, monkeypatch)
        try:
            deleted = svc.batch_delete_history(["mem_1", "mem_2"])
            assert deleted == 2
            # 内存中应已删除
            assert len(svc._history) == 0
        finally:
            svc.close()


# ──────────────────────────────────────────────────
# 4. PaddleOCRService 单个 URL 下载的 SSRF 校验失败
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestPaddleServiceUrlValidationFailure:
    """测试 _download_result_json / _download_markdown_result 对 SSRF URL 的处理。

    这两个独立函数是结果下载的公共入口，需要在 SSRF 校验失败时以可预期的方式失败：
    paddle_service.py（httpx 版）直接抛出 ResultUrlValidationError，
    由上层调用方（如 _download_results_concurrent）捕获并转换为错误状态。
    """

    @pytest.mark.anyio
    async def test_download_result_json_rejects_internal_url(self):
        """_download_result_json 遇到内网 URL 应抛出 ResultUrlValidationError"""
        from apps.web.api.paddle_service import PaddleOCRService, ResultUrlValidationError

        service = PaddleOCRService(api_url="https://api.example.com", api_key="key")

        with pytest.raises(ResultUrlValidationError):
            await service._download_result_json("https://127.0.0.1/result.jsonl")

    @pytest.mark.anyio
    async def test_download_markdown_result_rejects_internal_url(self):
        """_download_markdown_result 遇到内网 URL 应抛出 ResultUrlValidationError"""
        from apps.web.api.paddle_service import PaddleOCRService, ResultUrlValidationError

        service = PaddleOCRService(api_url="https://api.example.com", api_key="key")

        with pytest.raises(ResultUrlValidationError):
            await service._download_markdown_result("https://192.168.1.1/result.md")

    @pytest.mark.anyio
    async def test_download_result_json_accepts_public_url(self):
        """公网 URL 应正常下载"""
        from apps.web.api.paddle_service import PaddleOCRService

        service = PaddleOCRService(api_url="https://api.example.com", api_key="key")

        mock_response = MagicMock()
        mock_response.text = '{"result": {}}'
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("apps.web.api.paddle_service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

            json_text, raw_json = await service._download_result_json(
                "https://example.com/result.jsonl"
            )

        assert json_text == '{"result": {}}'
        assert raw_json == {"result": {}}
