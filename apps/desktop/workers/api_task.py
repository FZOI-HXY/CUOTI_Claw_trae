"""
API 异步调用工作线程
- ApiTask: 通用 API 调用
- UploadWorker: 文件上传
- SubmitWorker: 提交 OCR 任务
- PollWorker: 轮询任务状态
"""
import asyncio
import atexit
import os
from pathlib import Path
from typing import List, Dict
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QThread, pyqtSignal

# 条件导入 httpx：PyInstaller frozen 模式下可能缺少依赖
try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    import urllib.request as _urllib_request
    import urllib.error as _urllib_error
    _HAS_HTTPX = False

import traceback as _traceback

class _SelfPreservingThread(QThread):
    """QThread 基类：防止 Python GC 在运行中回收实例"""

    _active_instances: "set[_SelfPreservingThread]" = set()
    _counter = 0

    def __init__(self, name: str = ""):
        super().__init__()
        _SelfPreservingThread._counter += 1
        thread_name = name or f"Worker-{_SelfPreservingThread._counter}"
        self.setObjectName(thread_name)
        self._cancel_flag = False  # 协作式取消标志
        _SelfPreservingThread._active_instances.add(self)
        # 用 super() 绕过子类 signal name shadow，连接到 QThread.finished
        # 确保 self 只有在 C++ QThread 完全终止后才从保护集合中移除
        # 避免 GC 在 C++ 清理中回收对象导致崩溃
        super(_SelfPreservingThread, self).finished.connect(
            lambda: _SelfPreservingThread._active_instances.discard(self)
        )

    def cancel(self):
        """设置取消标志，通知线程尽快退出"""
        self._cancel_flag = True

    def is_cancelled(self) -> bool:
        """检查是否已请求取消"""
        return self._cancel_flag

    def run(self):
        try:
            self._do_run()
        except Exception:
            _traceback.print_exc()

    def _do_run(self):
        raise NotImplementedError

    @classmethod
    def wait_all(cls, timeout_ms: int = 3000):
        """等待所有活跃线程结束（用于程序关闭时优雅退出）

        通过设置协作式取消标志通知线程退出，而非调用 quit()
        （quit() 对未调用 exec() 的工作线程无效）。
        """
        for t in list(cls._active_instances):
            if t.isRunning():
                print(f"[Claw] 通知线程 {t.objectName()} 取消...", flush=True)
                t.cancel()
                t.wait(timeout_ms)


# ---------------------------------------------------------------------------
# HTTP 请求辅助函数：优先 httpx，降级到 urllib (thread-pool)
# ---------------------------------------------------------------------------

_executor = ThreadPoolExecutor(max_workers=4)
atexit.register(_executor.shutdown)


def _get_auth_token() -> str:
    """S06: 从环境变量读取认证 token"""
    return os.environ.get("CLAW_AUTH_TOKEN", "")


def _get_auth_headers(method: str) -> dict:
    """S06: 获取认证请求头（仅对状态变更操作添加 token）"""
    headers = {}
    if method in ("POST", "DELETE", "PUT"):
        token = _get_auth_token()
        if token:
            headers["X-Claw-Token"] = token
    return headers


def _http_request_sync(method: str, url: str, json_data=None, files_data=None,
                       raw_response: bool = False, timeout: float = 600.0):
    """同步 HTTP 请求（urllib 降级路径），在 thread-pool 中执行"""
    data_bytes = None
    headers = _get_auth_headers(method)
    if json_data is not None:
        import json as _json_mod
        data_bytes = _json_mod.dumps(json_data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if files_data and method in ("POST", "PUT"):
        # multipart fallback: 仅简单字段（不处理文件二进制流，降级路径下上传不可用）
        raise RuntimeError("降级模式下不支持文件上传，请安装 httpx")

    req = _urllib_request.Request(url, data=data_bytes, headers=headers, method=method)
    with _urllib_request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        if resp.status >= 400:
            raise _urllib_error.HTTPError(url, resp.status, "", resp.headers, None)
        if raw_response:
            return body
        import json as _json_mod
        return _json_mod.loads(body.decode("utf-8"))


async def _http_request(method: str, url: str, json_data=None, files_data=None,
                        raw_response: bool = False, timeout: float = 600.0):
    """统一的异步 HTTP 请求入口：httpx 优先，否则线程池 + urllib"""
    # S06: 获取认证请求头
    auth_headers = _get_auth_headers(method)

    if _HAS_HTTPX:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "GET":
                resp = await client.get(url)
            elif method == "POST":
                if files_data:
                    resp = await client.post(url, files=files_data, headers=auth_headers)
                elif json_data is not None:
                    resp = await client.post(url, json=json_data, headers=auth_headers)
                else:
                    resp = await client.post(url, headers=auth_headers)
            elif method == "DELETE":
                resp = await client.delete(url, headers=auth_headers)
            else:
                raise ValueError(f"不支持的方法: {method}")
            resp.raise_for_status()
            if raw_response:
                return resp.content
            return resp.json()
    else:
        # 降级路径：在线程池中执行同步 urllib
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _executor,
            lambda: _http_request_sync(method, url, json_data, files_data, raw_response, timeout)
        )


class ApiTask(_SelfPreservingThread):
    """通用 API 异步调用线程"""
    finished = pyqtSignal(object)  # response data
    error = pyqtSignal(str)

    def __init__(self, api_base: str, method: str, endpoint: str,
                 json_data: "dict | None" = None, files_data: "dict | None" = None,
                 raw_response: bool = False):
        super().__init__(f"API-{method}-{endpoint}")
        self.api_base = api_base
        self.method = method
        self.endpoint = endpoint
        self.json_data = json_data
        self.files_data = files_data
        self.raw_response = raw_response

    def _do_run(self):
        if self.is_cancelled():
            return
        loop = None
        try:
            url = f"{self.api_base}{self.endpoint}"

            async def _do():
                return await _http_request(
                    self.method, url,
                    json_data=self.json_data,
                    files_data=self.files_data,
                    raw_response=self.raw_response,
                    timeout=600.0,
                )

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(_do())
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if loop is not None and not loop.is_closed():
                loop.close()


class UploadWorker(_SelfPreservingThread):
    """文件上传工作线程"""
    finished = pyqtSignal(dict)  # {index, file_id, ...}
    error = pyqtSignal(int, str)  # index, error

    def __init__(self, api_base: str, file_path: str, index: int):
        name = Path(file_path).name
        super().__init__(f"Upload-{name}")
        self.api_base = api_base
        self.file_path = file_path
        self.index = index

    def _do_run(self):
        if self.is_cancelled():
            return
        loop = None
        try:
            async def _do():
                if _HAS_HTTPX:
                    # S06: 添加认证请求头
                    upload_headers = _get_auth_headers("POST")
                    async with httpx.AsyncClient(timeout=120.0) as client:
                        with open(self.file_path, "rb") as f:
                            files = {"file": (Path(self.file_path).name, f)}
                            resp = await client.post(
                                f"{self.api_base}/api/upload",
                                files=files,
                                headers=upload_headers,
                            )
                            resp.raise_for_status()
                            data = resp.json()
                            data["_index"] = self.index
                            return data
                else:
                    raise RuntimeError(
                        "文件上传需要 httpx 库（当前为 urllib 降级模式），"
                        "请安装: pip install httpx"
                    )
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(_do())
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(self.index, str(e))
        finally:
            if loop is not None and not loop.is_closed():
                loop.close()


class SubmitWorker(_SelfPreservingThread):
    """提交异步 OCR 任务工作线程"""
    finished = pyqtSignal(dict)
    error = pyqtSignal(int, str)

    def __init__(self, api_base: str, file_id: str, index: int):
        super().__init__(f"Submit-{file_id[:8]}")
        self.api_base = api_base
        self.file_id = file_id
        self.index = index

    def _do_run(self):
        if self.is_cancelled():
            return
        loop = None
        try:
            async def _do():
                return await _http_request(
                    "POST", f"{self.api_base}/api/submit/{self.file_id}",
                    timeout=60.0,
                )
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(_do())
            if not isinstance(result, dict):
                raise TypeError(f"SubmitWorker 期望 dict，收到 {type(result)}")
            result["_index"] = self.index
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(self.index, str(e))
        finally:
            if loop is not None and not loop.is_closed():
                loop.close()


class PollWorker(_SelfPreservingThread):
    """轮询任务状态工作线程"""
    finished = pyqtSignal(list)  # [{index, data, error}]
    error = pyqtSignal(str)

    def __init__(self, api_base: str, tasks: List[Dict], index_map: Dict[str, int]):
        super().__init__(f"Poll-{len(tasks)}tasks")
        self.api_base = api_base
        self.tasks = tasks
        self.index_map = index_map

    def _do_run(self):
        if self.is_cancelled():
            return
        loop = None
        try:
            async def _poll_one(task_id, idx):
                try:
                    # timeout=95s：比后端 wait_for(90s) 多 5s 余量，
                    # 避免任务首次 done 下载 JSON+MD 时前端先超时断连
                    result = await _http_request(
                        "POST", f"{self.api_base}/api/poll/{task_id}",
                        timeout=95.0,
                    )
                    return {"index": idx, "data": result, "task_id": task_id}
                except Exception as e:
                    return {"index": idx, "error": str(e), "task_id": task_id}

            async def _do():
                coros = [_poll_one(t["task_id"], t["index"])
                         for t in self.tasks]
                return await asyncio.gather(*coros)

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(_do())
            self.finished.emit(list(result))
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if loop is not None and not loop.is_closed():
                loop.close()
