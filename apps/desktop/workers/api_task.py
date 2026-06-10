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

    def __init__(self):
        super().__init__()
        _SelfPreservingThread._active_instances.add(self)

    def run(self):
        try:
            self._do_run()
        except Exception:
            _traceback.print_exc()
        finally:
            _SelfPreservingThread._active_instances.discard(self)

    def _do_run(self):
        raise NotImplementedError


class ApiTask(_SelfPreservingThread):
    """通用 API 异步调用线程"""
    finished = pyqtSignal(object)  # response data
    error = pyqtSignal(str)

    def __init__(self, api_base: str, method: str, endpoint: str,
                 json_data: "dict | None" = None, files_data: "dict | None" = None,
                 raw_response: bool = False):
        super().__init__()
        self.api_base = api_base
        self.method = method
        self.endpoint = endpoint
        self.json_data = json_data
        self.files_data = files_data
        self.raw_response = raw_response

    def _do_run(self):
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
            loop.close()
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class UploadWorker(_SelfPreservingThread):
    """文件上传工作线程"""
    finished = pyqtSignal(dict)  # {index, file_id, ...}
    error = pyqtSignal(int, str)  # index, error

    def __init__(self, api_base: str, file_path: str, index: int):
        super().__init__()
        self.api_base = api_base
        self.file_path = file_path
        self.index = index

    def _do_run(self):
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
            loop.close()
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(self.index, str(e))


class SubmitWorker(_SelfPreservingThread):
    """提交异步 OCR 任务工作线程"""
    finished = pyqtSignal(dict)
    error = pyqtSignal(int, str)

    def __init__(self, api_base: str, file_id: str, index: int):
        super().__init__()
        self.api_base = api_base
        self.file_id = file_id
        self.index = index

    def _do_run(self):
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
            loop.close()
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(self.index, str(e))


class PollWorker(_SelfPreservingThread):
    """轮询任务状态工作线程"""
    finished = pyqtSignal(list)  # [{index, data, error}]
    error = pyqtSignal(str)

    def __init__(self, api_base: str, tasks: List[Dict], index_map: Dict[str, int]):
        super().__init__()
        self.api_base = api_base
        self.tasks = tasks
        self.index_map = index_map

    def _do_run(self):
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
            loop.close()
            self.finished.emit(list(result))
        except Exception as e:
            self.error.emit(str(e))
