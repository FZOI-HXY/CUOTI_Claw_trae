"""
API 异步调用工作线程
- ApiTask: 通用 API 调用
- UploadWorker: 文件上传
- SubmitWorker: 提交 OCR 任务
- PollWorker: 轮询任务状态
"""
import asyncio
from pathlib import Path
from typing import List, Dict

from PyQt6.QtCore import QThread, pyqtSignal
import httpx

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
        _SelfPreservingThread._active_instances.add(self)
        # 用 super() 绕过子类 signal name shadow，连接到 QThread.finished
        # 确保 self 只有在 C++ QThread 完全终止后才从保护集合中移除
        # 避免 GC 在 C++ 清理中回收对象导致崩溃
        super(_SelfPreservingThread, self).finished.connect(
            lambda: _SelfPreservingThread._active_instances.discard(self)
        )

    def run(self):
        try:
            self._do_run()
        except Exception:
            _traceback.print_exc()

    def _do_run(self):
        raise NotImplementedError

    @classmethod
    def wait_all(cls, timeout_ms: int = 3000):
        """等待所有活跃线程结束（用于程序关闭时优雅退出）"""
        for t in list(cls._active_instances):
            if t.isRunning():
                print(f"[Claw] 等待线程 {t.objectName()} 结束...", flush=True)
                t.quit()
                t.wait(timeout_ms)


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
        loop = None
        try:
            async def _do():
                async with httpx.AsyncClient(timeout=600.0) as client:
                    url = f"{self.api_base}{self.endpoint}"
                    if self.method == "GET":
                        resp = await client.get(url)
                    elif self.method == "POST":
                        if self.files_data:
                            resp = await client.post(url, files=self.files_data)
                        elif self.json_data:
                            resp = await client.post(url, json=self.json_data)
                        else:
                            resp = await client.post(url)
                    elif self.method == "DELETE":
                        resp = await client.delete(url)
                    else:
                        raise ValueError(f"不支持的方法: {self.method}")
                    resp.raise_for_status()
                    if self.raw_response:
                        return resp.content
                    return resp.json()
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
        loop = None
        try:
            async def _do():
                async with httpx.AsyncClient(timeout=120.0) as client:
                    with open(self.file_path, "rb") as f:
                        files = {"file": (Path(self.file_path).name, f)}
                        resp = await client.post(f"{self.api_base}/api/upload", files=files)
                        resp.raise_for_status()
                        data = resp.json()
                        data["_index"] = self.index
                        return data
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
        loop = None
        try:
            async def _do():
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(f"{self.api_base}/api/submit/{self.file_id}")
                    resp.raise_for_status()
                    data = resp.json()
                    data["_index"] = self.index
                    return data
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(_do())
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
        loop = None
        try:
            async def _poll_one(client, task_id, idx):
                try:
                    resp = await client.post(f"{self.api_base}/api/poll/{task_id}")
                    resp.raise_for_status()
                    data = resp.json()
                    return {"index": idx, "data": data, "task_id": task_id}
                except Exception as e:
                    return {"index": idx, "error": str(e), "task_id": task_id}

            async def _do():
                async with httpx.AsyncClient(timeout=30.0) as client:
                    coros = [_poll_one(client, t["task_id"], t["index"])
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
