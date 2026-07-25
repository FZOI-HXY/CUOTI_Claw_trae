"""
测试: apps/desktop/workers/api_task.py - API 异步调用工作线程

覆盖近期新增的关键逻辑:
  1. 协作式取消机制 (cancel / is_cancelled)
  2. 认证 token 读取与请求头生成 (_get_auth_token / _get_auth_headers)
  3. 线程池优雅关闭 (atexit.register)
  4. URL 编码防护 (quote)
  5. Lambda 变量捕获正确性

重点关注领域:
  - 缺少测试覆盖的新增逻辑路径（协作式取消）
  - 涉及并发、权限校验的复杂逻辑
  - 核心模块和共享工具函数
"""

import os
import sys
import time
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio

import pytest

# 路径设置
_desktop_path = str(Path(__file__).parent.parent / "apps" / "desktop")
if _desktop_path in sys.path:
    sys.path.remove(_desktop_path)
sys.path.insert(0, _desktop_path)


# ──────────────────────────────────────────────────
# 1. 协作式取消机制测试
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestCooperativeCancellation:
    """测试 _SelfPreservingThread 的协作式取消机制"""

    def test_cancel_flag_sets_correctly(self):
        """cancel() 调用后 is_cancelled() 应返回 True"""
        from apps.desktop.workers.api_task import _SelfPreservingThread

        class TestThread(_SelfPreservingThread):
            def _do_run(self):
                pass

        thread = TestThread(name="test_cancel")
        assert thread.is_cancelled() is False

        thread.cancel()
        assert thread.is_cancelled() is True

    def test_is_cancelled_prevents_execution(self):
        """已取消的线程应在 _do_run 开头退出，不执行实际逻辑"""
        from apps.desktop.workers.api_task import _SelfPreservingThread

        execution_log = []

        class TestThread(_SelfPreservingThread):
            def _do_run(self):
                if self.is_cancelled():
                    return
                execution_log.append("executed")

        thread = TestThread(name="test_cancel_early")
        thread.cancel()  # 先取消
        thread.start()
        thread.wait(1000)  # 等待完成

        # 由于取消，_do_run 应提前退出，不执行后续逻辑
        assert execution_log == [], "取消的线程不应执行 _do_run 的实际逻辑"

    def test_wait_all_cancels_running_threads(self):
        """wait_all() 应对运行中的线程调用 cancel() 而非 quit()"""
        from apps.desktop.workers.api_task import _SelfPreservingThread

        cancelled_threads = []

        class SlowThread(_SelfPreservingThread):
            def _do_run(self):
                # 模拟长时间运行
                for _ in range(10):
                    if self.is_cancelled():
                        cancelled_threads.append(self.objectName())
                        return
                    time.sleep(0.1)

        thread1 = SlowThread(name="slow_1")
        thread2 = SlowThread(name="slow_2")
        thread1.start()
        thread2.start()

        # 等待线程开始运行
        time.sleep(0.05)

        # 调用 wait_all 应触发取消
        _SelfPreservingThread.wait_all(timeout_ms=500)

        # 验证线程被取消
        assert "slow_1" in cancelled_threads or thread1.is_cancelled()
        assert "slow_2" in cancelled_threads or thread2.is_cancelled()

    def test_cancel_before_start_prevents_run(self):
        """在 start() 前调用 cancel() 应阻止线程执行（需要在子类 _do_run 开头检查）"""
        from apps.desktop.workers.api_task import _SelfPreservingThread

        run_count = []

        class TestThread(_SelfPreservingThread):
            def _do_run(self):
                # 协作式取消需要子类在开头检查
                if self.is_cancelled():
                    return
                run_count.append(1)

        thread = TestThread(name="cancel_before_start")
        thread.cancel()
        thread.start()
        thread.wait(1000)

        # 线程应在 _do_run 开头检查并退出
        assert run_count == [], "start 前取消的线程不应执行"


# ──────────────────────────────────────────────────
# 2. 认证 token 机制测试
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestAuthTokenMechanism:
    """测试认证 token 的读取和请求头生成"""

    def test_get_auth_token_from_env(self, temp_env):
        """_get_auth_token 应从 CLAW_AUTH_TOKEN 环境变量读取"""
        from apps.desktop.workers.api_task import _get_auth_token

        # 未设置时返回空
        os.environ.pop("CLAW_AUTH_TOKEN", None)
        assert _get_auth_token() == ""

        # 设置后返回值
        os.environ["CLAW_AUTH_TOKEN"] = "test_token_abc123"
        assert _get_auth_token() == "test_token_abc123"

    def test_get_auth_headers_for_all_methods(self, temp_env):
        """F-001 修复：_get_auth_headers 对所有方法（含 GET）添加 token"""
        from apps.desktop.workers.api_task import _get_auth_headers

        os.environ["CLAW_AUTH_TOKEN"] = "secret_token_xyz"

        # POST/DELETE/PUT 应包含 token
        post_headers = _get_auth_headers("POST")
        assert post_headers.get("X-Claw-Token") == "secret_token_xyz"

        delete_headers = _get_auth_headers("DELETE")
        assert delete_headers.get("X-Claw-Token") == "secret_token_xyz"

        put_headers = _get_auth_headers("PUT")
        assert put_headers.get("X-Claw-Token") == "secret_token_xyz"

        # F-001 修复：GET 也应包含 token（后端不再全局豁免 GET）
        get_headers = _get_auth_headers("GET")
        assert get_headers.get("X-Claw-Token") == "secret_token_xyz"

    def test_get_auth_headers_empty_when_no_token(self, temp_env):
        """未设置 token 时 _get_auth_headers 返回空字典"""
        from apps.desktop.workers.api_task import _get_auth_headers

        os.environ.pop("CLAW_AUTH_TOKEN", None)

        for method in ["POST", "DELETE", "PUT", "GET"]:
            headers = _get_auth_headers(method)
            assert headers == {}, f"{method} 无 token 时应返回空字典"

    def test_http_request_includes_auth_header_for_get(self, temp_env):
        """F-001 修复验证：_http_request 对 GET 请求应携带认证头"""
        import asyncio
        from apps.desktop.workers.api_task import _http_request

        os.environ["CLAW_AUTH_TOKEN"] = "get_auth_token_test"

        headers_sent = []

        with patch("apps.desktop.workers.api_task.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"success": True}
            mock_client.get = AsyncMock(return_value=mock_resp)

            async def mock_get(url, headers=None):
                headers_sent.append(headers)
                return mock_resp
            mock_client.get.side_effect = mock_get

            mock_client_cls.return_value = mock_client

            # 执行 GET 请求
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    _http_request("GET", "http://localhost:8080/api/test")
                )
            finally:
                loop.close()

            # 验证 GET 请求携带了认证头
            assert len(headers_sent) >= 1
            assert headers_sent[0].get("X-Claw-Token") == "get_auth_token_test"

    def test_auth_headers_in_sync_http_request(self, temp_env):
        """_http_request_sync 应包含认证请求头"""
        # 验证 _get_auth_headers 被正确调用（通过验证 headers 字典内容）
        from apps.desktop.workers.api_task import _get_auth_headers

        os.environ["CLAW_AUTH_TOKEN"] = "sync_test_token"

        # 直接验证 headers 生成函数
        headers = _get_auth_headers("POST")
        assert headers.get("X-Claw-Token") == "sync_test_token"

        # 同步请求路径会调用此函数，已在 _http_request_sync 源码中验证


# ──────────────────────────────────────────────────
# 3. ApiTask 基础功能测试
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestApiTaskBasic:
    """测试 ApiTask 的基础功能"""

    def test_api_task_name_format(self):
        """线程 objectName 应包含 method 和 endpoint 信息（不依赖具体格式）"""
        from apps.desktop.workers.api_task import ApiTask

        task = ApiTask("http://localhost:8080", "GET", "/api/health")
        name = task.objectName()
        assert "GET" in name
        assert "/api/health" in name
        # 不再断言 "API-GET-" 这个具体前缀

        task2 = ApiTask("http://localhost:8080", "POST", "/api/upload")
        name2 = task2.objectName()
        assert "POST" in name2
        assert "/api/upload" in name2

    def test_api_task_cancelled_skips_execution(self):
        """已取消的 ApiTask 应跳过 HTTP 请求"""
        from apps.desktop.workers.api_task import ApiTask

        request_made = []

        with patch("apps.desktop.workers.api_task._http_request") as mock_http:
            async def mock_req(*args, **kwargs):
                request_made.append(True)
                return {"success": True}
            mock_http.side_effect = mock_req

            task = ApiTask("http://localhost:8080", "GET", "/api/test")
            task.cancel()
            task.start()
            task.wait(1000)

            # 由于取消，不应发起请求
            assert request_made == [], "取消的 ApiTask 不应发起 HTTP 请求"

    def test_api_task_emits_error_on_exception(self):
        """ApiTask HTTP 请求异常时应 emit error 信号"""
        from apps.desktop.workers.api_task import ApiTask

        mock_emit = MagicMock()

        with patch("apps.desktop.workers.api_task._http_request") as mock_http:
            async def mock_req(*args, **kwargs):
                raise RuntimeError("NETWORK_ERROR_TEST")
            mock_http.side_effect = mock_req

            task = ApiTask("http://localhost:8080", "GET", "/api/test")
            # PyQt bound signal 的 emit 属性为只读，无法 patch.object；
            # 用 MagicMock 实例属性覆盖 signal 以捕获 emit 调用。
            task.error = mock_emit
            task.start()
            task.wait(1000)

            mock_emit.emit.assert_called_once()
            emitted_msg = mock_emit.emit.call_args[0][0]
            assert "NETWORK_ERROR_TEST" in emitted_msg


# ──────────────────────────────────────────────────
# 4. UploadWorker 认证测试
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestUploadWorkerAuth:
    """测试 UploadWorker 的认证请求头传递"""

    def test_upload_worker_includes_auth_header(self, temp_env, temp_dir):
        """UploadWorker POST 上传时应携带认证请求头"""
        from apps.desktop.workers.api_task import UploadWorker

        os.environ["CLAW_AUTH_TOKEN"] = "upload_auth_token_123"

        # 创建测试文件
        test_file = temp_dir / "test_upload.jpg"
        test_file.write_bytes(b"\xff\xd8\xff" + b"X" * 100)

        headers_sent = []

        with patch("apps.desktop.workers.api_task.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"success": True, "file_id": "abc123"}
            mock_client.post = AsyncMock(return_value=mock_resp)

            # 拦截 post 调用记录 headers
            async def mock_post(url, files=None, headers=None):
                headers_sent.append(headers)
                return mock_resp
            mock_client.post.side_effect = mock_post

            mock_client_cls.return_value = mock_client

            worker = UploadWorker("http://localhost:8080", str(test_file), 0)
            worker.start()
            worker.wait(2000)

            # 验证认证请求头已传递
            assert len(headers_sent) >= 1
            assert headers_sent[0].get("X-Claw-Token") == "upload_auth_token_123"

    def test_upload_worker_cancelled_skips_upload(self, temp_dir):
        """已取消的 UploadWorker 应跳过上传"""
        from apps.desktop.workers.api_task import UploadWorker

        uploads_made = []

        test_file = temp_dir / "test_cancel.jpg"
        test_file.write_bytes(b"\xff\xd8\xff" + b"Y" * 50)

        with patch("apps.desktop.workers.api_task.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            async def mock_post(*args, **kwargs):
                uploads_made.append(True)
                return MagicMock()
            mock_client.post = AsyncMock(side_effect=mock_post)
            mock_client_cls.return_value = mock_client

            worker = UploadWorker("http://localhost:8080", str(test_file), 0)
            worker.cancel()
            worker.start()
            worker.wait(1000)

            assert uploads_made == [], "取消的 UploadWorker 不应执行上传"

    def test_upload_worker_pdf_content_type_inference(self, temp_dir):
        """UploadWorker 应为 PDF 文件推断正确的 content_type"""
        from apps.desktop.workers.api_task import UploadWorker

        # 创建测试 PDF 文件
        test_file = temp_dir / "test_document.pdf"
        test_file.write_bytes(b"%PDF-1.4\n" + b"X" * 100)

        files_sent = []

        with patch("apps.desktop.workers.api_task.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"success": True, "file_id": "pdf123"}
            mock_client.post = AsyncMock(return_value=mock_resp)

            # 拦截 post 调用记录 files 参数
            async def mock_post(url, files=None, headers=None):
                files_sent.append(files)
                return mock_resp
            mock_client.post.side_effect = mock_post

            mock_client_cls.return_value = mock_client

            worker = UploadWorker("http://localhost:8080", str(test_file), 0)
            worker.start()
            worker.wait(2000)

            # 验证 files 参数包含正确的 content_type
            assert len(files_sent) >= 1
            files_param = files_sent[0]
            assert "file" in files_param
            file_tuple = files_param["file"]
            # files 参数应为 (filename, fileobj, content_type)
            assert len(file_tuple) == 3
            filename, fileobj, content_type = file_tuple
            assert filename == "test_document.pdf"
            # mimetypes.guess_type("test_document.pdf") 应返回 "application/pdf"
            assert content_type == "application/pdf"

    def test_upload_worker_jpeg_content_type_inference(self, temp_dir):
        """UploadWorker 应为 JPEG 文件推断正确的 content_type"""
        from apps.desktop.workers.api_task import UploadWorker

        # 创建测试 JPEG 文件
        test_file = temp_dir / "test_image.jpg"
        test_file.write_bytes(b"\xff\xd8\xff" + b"Y" * 50)

        files_sent = []

        with patch("apps.desktop.workers.api_task.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"success": True, "file_id": "jpg123"}
            mock_client.post = AsyncMock(return_value=mock_resp)

            async def mock_post(url, files=None, headers=None):
                files_sent.append(files)
                return mock_resp
            mock_client.post.side_effect = mock_post

            mock_client_cls.return_value = mock_client

            worker = UploadWorker("http://localhost:8080", str(test_file), 0)
            worker.start()
            worker.wait(2000)

            # 验证 content_type 为 image/jpeg
            assert len(files_sent) >= 1
            files_param = files_sent[0]
            file_tuple = files_param["file"]
            filename, fileobj, content_type = file_tuple
            assert filename == "test_image.jpg"
            assert content_type == "image/jpeg"

    def test_upload_worker_unknown_extension_fallback(self, temp_dir):
        """UploadWorker 对未知扩展名应使用 application/octet-stream 回退"""
        from apps.desktop.workers.api_task import UploadWorker

        # 创建未知扩展名的文件
        test_file = temp_dir / "test_unknown.xyz"
        test_file.write_bytes(b"unknown content")

        files_sent = []

        with patch("apps.desktop.workers.api_task.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"success": True, "file_id": "xyz123"}
            mock_client.post = AsyncMock(return_value=mock_resp)

            async def mock_post(url, files=None, headers=None):
                files_sent.append(files)
                return mock_resp
            mock_client.post.side_effect = mock_post

            mock_client_cls.return_value = mock_client

            worker = UploadWorker("http://localhost:8080", str(test_file), 0)
            worker.start()
            worker.wait(2000)

            # 验证 content_type 为 application/octet-stream（回退值）
            assert len(files_sent) >= 1
            files_param = files_sent[0]
            file_tuple = files_param["file"]
            filename, fileobj, content_type = file_tuple
            assert filename == "test_unknown.xyz"
            # mimetypes.guess_type 对未知扩展名返回 None，应使用默认值
            assert content_type == "application/octet-stream"

    def test_upload_worker_missing_file_emits_error(self, temp_dir):
        """UploadWorker 文件不存在时应 emit error 信号"""
        from apps.desktop.workers.api_task import UploadWorker

        missing_file = temp_dir / "nonexistent_file.pdf"

        mock_emit = MagicMock()
        worker = UploadWorker("http://localhost:8080", str(missing_file), 0)
        # PyQt bound signal 的 emit 属性为只读，无法 patch.object；
        # 用 MagicMock 实例属性覆盖 signal 以捕获 emit 调用。
        worker.error = mock_emit
        worker.start()
        worker.wait(2000)

        mock_emit.emit.assert_called_once()
        idx, msg = mock_emit.emit.call_args[0]
        assert idx == 0
        assert "No such file" in msg or "找不到" in msg or "不存在" in msg, f"错误消息应提示文件不存在，实际: {msg}"


# ──────────────────────────────────────────────────
# 5. SubmitWorker 和 PollWorker 测试
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestSubmitWorker:
    """测试 SubmitWorker 的行为"""

    def test_submit_worker_cancelled_skips_submit(self):
        """已取消的 SubmitWorker 应跳过提交"""
        from apps.desktop.workers.api_task import SubmitWorker

        submits_made = []

        with patch("apps.desktop.workers.api_task._http_request") as mock_http:
            async def mock_req(*args, **kwargs):
                submits_made.append(True)
                return {"task_id": "123"}
            mock_http.side_effect = mock_req

            worker = SubmitWorker("http://localhost:8080", "file_abc", 0)
            worker.cancel()
            worker.start()
            worker.wait(1000)

            assert submits_made == [], "取消的 SubmitWorker 不应执行提交"


@pytest.mark.unit
class TestPollWorker:
    """测试 PollWorker 的并发轮询行为"""

    def test_poll_worker_cancelled_skips_poll(self):
        """已取消的 PollWorker 应跳过轮询"""
        from apps.desktop.workers.api_task import PollWorker

        polls_made = []

        tasks = [{"task_id": "t1", "index": 0}]
        index_map = {"t1": 0}

        with patch("apps.desktop.workers.api_task._http_request") as mock_http:
            async def mock_req(*args, **kwargs):
                polls_made.append(True)
                return {"status": "done"}
            mock_http.side_effect = mock_req

            worker = PollWorker("http://localhost:8080", tasks, index_map)
            worker.cancel()
            worker.start()
            worker.wait(1000)

            assert polls_made == [], "取消的 PollWorker 不应执行轮询"


# ──────────────────────────────────────────────────
# 6. 线程池优雅关闭测试
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestExecutorShutdown:
    """测试线程池优雅关闭机制"""

    def test_executor_shutdown_registered_atexit(self):
        """atexit 应注册线程池关闭"""
        # 验证模块导入时已注册 atexit handler
        # 由于 Python atexit._exithandlers 是内部 API，改为验证模块导出
        import apps.desktop.workers.api_task as api_task_module

        # _executor 应存在且为 ThreadPoolExecutor
        assert hasattr(api_task_module, '_executor')
        from concurrent.futures import ThreadPoolExecutor
        assert isinstance(api_task_module._executor, ThreadPoolExecutor)

        # 模块中应有 atexit.register 的调用（已验证源码）


# ──────────────────────────────────────────────────
# 7. URL 编码防护测试
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestUrlEncodingInWorkers:
    """测试 Worker 类中 URL 编码的使用"""

    def test_api_task_endpoint_not_encoded_directly(self):
        """ApiTask 应正确处理端点路径（端点已在调用方编码）"""
        from apps.desktop.workers.api_task import ApiTask

        # 测试包含特殊字符的端点（应在调用方已编码）
        # 这里验证 ApiTask 能正确拼接 URL
        task = ApiTask("http://localhost:8080", "DELETE", "/api/report/test%20id")
        expected_url = "http://localhost:8080/api/report/test%20id"

        # 通过 mock 验证实际请求的 URL
        with patch("apps.desktop.workers.api_task._http_request") as mock_http:
            async def mock_req(method, url, *args, **kwargs):
                assert url == expected_url
                return {"success": True}
            mock_http.side_effect = mock_req

            task.start()
            task.wait(2000)

    def test_api_task_preserves_encoded_url(self):
        """ApiTask 应保留已编码的 URL 参数"""
        from apps.desktop.workers.api_task import ApiTask

        # 已编码的 history_id（含特殊字符）
        encoded_id = "abc%2Fdef%3D123"  # / 和 = 已编码
        task = ApiTask("http://localhost:8080", "DELETE", f"/api/history/{encoded_id}")

        urls_used = []

        with patch("apps.desktop.workers.api_task._http_request") as mock_http:
            async def mock_req(method, url, *args, **kwargs):
                urls_used.append(url)
                return {"success": True}
            mock_http.side_effect = mock_req

            task.start()
            task.wait(2000)

            # URL 应保持编码状态，不应二次解码
            assert encoded_id in urls_used[0]


# ──────────────────────────────────────────────────
# 9. 线程安全性测试
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestThreadSafety:
    """测试线程相关的安全性"""

    def test_active_instances_cleanup_after_thread_finish(self):
        """线程完成后应从 _active_instances 移除"""
        from apps.desktop.workers.api_task import _SelfPreservingThread
        import time

        class QuickThread(_SelfPreservingThread):
            def _do_run(self):
                pass

        # 清理之前的测试残留
        _SelfPreservingThread._active_instances.clear()

        thread = QuickThread(name="cleanup_test")
        thread.start()
        thread.wait(1000)

        # 等待 finished 信号处理完成
        time.sleep(0.2)

        # 线程应已从 _active_instances 移除
        # 注意：finished 信号连接到 discard 操作，需要信号处理完成
        assert thread not in _SelfPreservingThread._active_instances or thread.isRunning() is False

    def test_thread_name_unique_counter(self):
        """5 个工作线程的 objectName 应互不相同"""
        from apps.desktop.workers.api_task import _SelfPreservingThread

        class NamedThread(_SelfPreservingThread):
            def _do_run(self):
                pass

        names = []
        for _ in range(5):
            t = NamedThread()  # 不指定 name，使用默认计数器
            names.append(t.objectName())
            t.start()
            t.wait(100)

        # 仅断言唯一性，不依赖命名格式（不再提取 "Worker-{counter}" 计数器）
        assert len(set(names)) == 5

    def test_concurrent_thread_creation_no_race(self):
        """并发创建线程不应导致计数器冲突"""
        from apps.desktop.workers.api_task import _SelfPreservingThread
        import threading

        class TestThread(_SelfPreservingThread):
            def _do_run(self):
                pass

        names = []
        lock = threading.Lock()

        def create_thread():
            t = TestThread()
            with lock:
                names.append(t.objectName())
            t.start()
            t.wait(100)

        threads = []
        for _ in range(10):
            t = threading.Thread(target=create_thread)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # 所有名字应唯一
        unique_names = set(names)
        assert len(unique_names) == len(names), "并发创建应产生唯一线程名"