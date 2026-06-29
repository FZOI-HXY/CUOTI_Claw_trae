"""
测试: apps/web/api/services/task_service.py - 任务管理服务

覆盖:
  - update_task / has_task / all_tasks / remove_task
  - LRU 淘汰机制
  - image_data 延迟清理
  - 并发安全性
"""

import sys
import time
from pathlib import Path

import pytest


_backend_path = str(Path(__file__).parent.parent / "apps" / "web" / "api")
if _backend_path in sys.path:
    sys.path.remove(_backend_path)
sys.path.insert(0, _backend_path)


@pytest.mark.unit
class TestTaskServiceMethods:
    """测试 TaskService 的核心方法"""

    def test_update_task(self, temp_dir, monkeypatch):
        """update_task 应正确更新任务字段"""
        import sys
        ts_module = sys.modules.get("apps.web.api.services.task_service")
        if ts_module is None:
            import importlib
            ts_module = importlib.import_module("apps.web.api.services.task_service")
        
        db_path = temp_dir / "test_update.db"
        monkeypatch.setattr(ts_module, "_get_db_path", lambda: db_path)
        
        svc = ts_module.TaskService()
        try:
            svc.set_task("task1", {"status": "processing", "file_id": "file1"})
            svc.update_task("task1", status="done", result="completed")
            
            task = svc.get_task("task1")
            assert task["status"] == "done"
            assert task["result"] == "completed"
            assert task["file_id"] == "file1"
        finally:
            svc.close()

    def test_has_task(self, temp_dir, monkeypatch):
        """has_task 应正确检查任务存在性"""
        import sys
        ts_module = sys.modules.get("apps.web.api.services.task_service")
        if ts_module is None:
            import importlib
            ts_module = importlib.import_module("apps.web.api.services.task_service")
        
        db_path = temp_dir / "test_has.db"
        monkeypatch.setattr(ts_module, "_get_db_path", lambda: db_path)
        
        svc = ts_module.TaskService()
        try:
            assert svc.has_task("nonexistent") is False
            
            svc.set_task("task1", {"status": "processing"})
            assert svc.has_task("task1") is True
            
            svc.remove_task("task1")
            assert svc.has_task("task1") is False
        finally:
            svc.close()

    def test_all_tasks(self, temp_dir, monkeypatch):
        """all_tasks 应返回所有任务"""
        import sys
        ts_module = sys.modules.get("apps.web.api.services.task_service")
        if ts_module is None:
            import importlib
            ts_module = importlib.import_module("apps.web.api.services.task_service")
        
        db_path = temp_dir / "test_all.db"
        monkeypatch.setattr(ts_module, "_get_db_path", lambda: db_path)
        
        svc = ts_module.TaskService()
        try:
            svc.set_task("task1", {"status": "processing"})
            svc.set_task("task2", {"status": "done"})
            
            all_tasks = svc.all_tasks()
            assert len(all_tasks) == 2
            assert "task1" in all_tasks
            assert "task2" in all_tasks
        finally:
            svc.close()

    def test_remove_task(self, temp_dir, monkeypatch):
        """remove_task 应正确移除任务"""
        import sys
        ts_module = sys.modules.get("apps.web.api.services.task_service")
        if ts_module is None:
            import importlib
            ts_module = importlib.import_module("apps.web.api.services.task_service")
        
        db_path = temp_dir / "test_remove.db"
        monkeypatch.setattr(ts_module, "_get_db_path", lambda: db_path)
        
        svc = ts_module.TaskService()
        try:
            svc.set_task("task1", {"status": "processing"})
            svc.set_task("task2", {"status": "done"})
            
            svc.remove_task("task1")
            assert svc.get_task("task1") is None
            assert svc.get_task("task2") is not None
            
            svc.remove_task("nonexistent")
        finally:
            svc.close()

    def test_get_task_returns_copy(self, temp_dir, monkeypatch):
        """get_task 应返回字典副本，防止外部修改内部状态"""
        import sys
        ts_module = sys.modules.get("apps.web.api.services.task_service")
        if ts_module is None:
            import importlib
            ts_module = importlib.import_module("apps.web.api.services.task_service")
        
        db_path = temp_dir / "test_copy.db"
        monkeypatch.setattr(ts_module, "_get_db_path", lambda: db_path)
        
        svc = ts_module.TaskService()
        try:
            svc.set_task("task1", {"status": "processing", "value": 1})
            
            task_copy = svc.get_task("task1")
            task_copy["status"] = "modified"
            task_copy["value"] = 999
            
            original = svc.get_task("task1")
            assert original["status"] == "processing"
            assert original["value"] == 1
        finally:
            svc.close()


@pytest.mark.unit
class TestTaskServiceLRU:
    """测试 LRU 淘汰机制"""

    def test_lru_eviction(self, temp_dir, monkeypatch):
        """超出限制时应淘汰最旧的任务"""
        import sys
        ts_module = sys.modules.get("apps.web.api.services.task_service")
        if ts_module is None:
            import importlib
            ts_module = importlib.import_module("apps.web.api.services.task_service")
        
        db_path = temp_dir / "test_lru.db"
        monkeypatch.setattr(ts_module, "_get_db_path", lambda: db_path)
        
        original_max = ts_module._MAX_TASK_STORE
        ts_module._MAX_TASK_STORE = 3
        
        svc = ts_module.TaskService()
        try:
            svc.set_task("task1", {"data": "oldest"})
            svc.set_task("task2", {"data": "middle"})
            svc.set_task("task3", {"data": "newest"})
            
            assert svc.has_task("task1") is True
            assert svc.has_task("task2") is True
            assert svc.has_task("task3") is True
            
            svc.set_task("task4", {"data": "newest_plus_1"})
            
            assert svc.has_task("task1") is False
            assert svc.has_task("task2") is True
            assert svc.has_task("task3") is True
            assert svc.has_task("task4") is True
        finally:
            svc.close()
            ts_module._MAX_TASK_STORE = original_max

    def test_lru_set_updates_order(self, temp_dir, monkeypatch):
        """set_task 应更新 LRU 顺序"""
        import sys
        ts_module = sys.modules.get("apps.web.api.services.task_service")
        if ts_module is None:
            import importlib
            ts_module = importlib.import_module("apps.web.api.services.task_service")
        
        db_path = temp_dir / "test_lru_order.db"
        monkeypatch.setattr(ts_module, "_get_db_path", lambda: db_path)
        
        original_max = ts_module._MAX_TASK_STORE
        ts_module._MAX_TASK_STORE = 3
        
        svc = ts_module.TaskService()
        try:
            svc.set_task("task1", {"data": "1"})
            svc.set_task("task2", {"data": "2"})
            svc.set_task("task3", {"data": "3"})
            
            svc.set_task("task1", {"data": "1_updated"})
            
            svc.set_task("task4", {"data": "4"})
            
            assert svc.has_task("task1") is True
            assert svc.has_task("task2") is False
        finally:
            svc.close()
            ts_module._MAX_TASK_STORE = original_max


@pytest.mark.unit
class TestImageDataCleanup:
    """测试 image_data 延迟清理"""

    def test_schedule_image_data_cleanup(self, temp_dir, monkeypatch):
        """延迟清理应正确执行"""
        import sys
        ts_module = sys.modules.get("apps.web.api.services.task_service")
        if ts_module is None:
            import importlib
            ts_module = importlib.import_module("apps.web.api.services.task_service")
        
        db_path = temp_dir / "test_cleanup.db"
        monkeypatch.setattr(ts_module, "_get_db_path", lambda: db_path)
        
        svc = ts_module.TaskService()
        try:
            svc.set_task("task1", {"status": "done", "image_data": b"very_large_data", "other": "value"})
            svc.schedule_image_data_cleanup("task1", delay=0.1)
            
            time.sleep(0.2)
            
            task = svc.get_task("task1")
            assert task is not None
            assert "image_data" not in task
            assert task["other"] == "value"
        finally:
            svc.close()

    def test_cancel_cleanup_timer(self, temp_dir, monkeypatch):
        """移除任务应取消清理定时器"""
        import sys
        ts_module = sys.modules.get("apps.web.api.services.task_service")
        if ts_module is None:
            import importlib
            ts_module = importlib.import_module("apps.web.api.services.task_service")
        
        db_path = temp_dir / "test_cancel.db"
        monkeypatch.setattr(ts_module, "_get_db_path", lambda: db_path)
        
        original_delay = ts_module._IMAGE_DATA_CLEANUP_DELAY
        ts_module._IMAGE_DATA_CLEANUP_DELAY = 0.1
        
        svc = ts_module.TaskService()
        try:
            svc.set_task("task1", {"status": "done", "image_data": b"data"})
            svc.schedule_image_data_cleanup("task1")
            
            assert "task1" in svc._cleanup_timers
            
            svc.remove_task("task1")
            
            assert "task1" not in svc._cleanup_timers
        finally:
            svc.close()
            ts_module._IMAGE_DATA_CLEANUP_DELAY = original_delay