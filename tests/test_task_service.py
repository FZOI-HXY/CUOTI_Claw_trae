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
import threading
from pathlib import Path

import pytest


_backend_path = str(Path(__file__).parent.parent / "apps" / "web" / "api")
if _backend_path in sys.path:
    sys.path.remove(_backend_path)
sys.path.insert(0, _backend_path)


@pytest.fixture
def svc_factory(temp_dir, monkeypatch):
    """返回工厂函数：调用 (name) 返回 (svc, db_path)

    替代 20+ 处手动 monkeypatch _get_db_path + TaskService() 模板。
    每次调用生成独立的 db_path（基于 name 参数），避免类间污染。
    """
    import importlib
    ts_module = importlib.import_module("apps.web.api.services.task_service")

    def _create(name="default"):
        db_path = temp_dir / f"test_{name}.db"
        monkeypatch.setattr(ts_module, "_get_db_path", lambda: db_path)
        return ts_module.TaskService(), db_path
    return _create


@pytest.mark.unit
class TestTaskServiceMethods:
    """测试 TaskService 的核心方法"""

    def test_update_task(self, svc_factory):
        """update_task 应正确更新任务字段"""
        svc, db_path = svc_factory("update")
        try:
            svc.set_task("task1", {"status": "processing", "file_id": "file1"})
            svc.update_task("task1", status="done", result="completed")

            task = svc.get_task("task1")
            assert task["status"] == "done"
            assert task["result"] == "completed"
            assert task["file_id"] == "file1"
        finally:
            svc.close()

    def test_has_task(self, svc_factory):
        """has_task 应正确检查任务存在性"""
        svc, db_path = svc_factory("has")
        try:
            assert svc.has_task("nonexistent") is False

            svc.set_task("task1", {"status": "processing"})
            assert svc.has_task("task1") is True

            svc.remove_task("task1")
            assert svc.has_task("task1") is False
        finally:
            svc.close()

    def test_all_tasks(self, svc_factory):
        """all_tasks 应返回所有任务"""
        svc, db_path = svc_factory("all")
        try:
            svc.set_task("task1", {"status": "processing"})
            svc.set_task("task2", {"status": "done"})

            all_tasks = svc.all_tasks()
            assert len(all_tasks) == 2
            assert "task1" in all_tasks
            assert "task2" in all_tasks
        finally:
            svc.close()

    def test_remove_task(self, svc_factory):
        """remove_task 应正确移除任务"""
        svc, db_path = svc_factory("remove")
        try:
            svc.set_task("task1", {"status": "processing"})
            svc.set_task("task2", {"status": "done"})

            svc.remove_task("task1")
            assert svc.get_task("task1") is None
            assert svc.get_task("task2") is not None

            svc.remove_task("nonexistent")
        finally:
            svc.close()

    def test_get_task_returns_copy(self, svc_factory):
        """get_task 应返回字典副本，防止外部修改内部状态"""
        svc, db_path = svc_factory("copy")
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

    def test_lru_eviction(self, svc_factory):
        """超出限制时应淘汰最旧的任务"""
        import importlib
        ts_module = importlib.import_module("apps.web.api.services.task_service")
        original_max = ts_module._MAX_TASK_STORE
        ts_module._MAX_TASK_STORE = 3

        svc, db_path = svc_factory("lru")
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

    def test_lru_set_updates_order(self, svc_factory):
        """set_task 应更新 LRU 顺序"""
        import importlib
        ts_module = importlib.import_module("apps.web.api.services.task_service")
        original_max = ts_module._MAX_TASK_STORE
        ts_module._MAX_TASK_STORE = 3

        svc, db_path = svc_factory("lru_order")
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

    def test_schedule_image_data_cleanup(self, svc_factory):
        """延迟清理应正确执行"""
        svc, db_path = svc_factory("cleanup")
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

    def test_cancel_cleanup_timer(self, svc_factory):
        """移除任务应取消清理定时器"""
        import importlib
        ts_module = importlib.import_module("apps.web.api.services.task_service")
        original_delay = ts_module._IMAGE_DATA_CLEANUP_DELAY
        ts_module._IMAGE_DATA_CLEANUP_DELAY = 0.1

        svc, db_path = svc_factory("cancel")
        try:
            svc.set_task("task1", {"status": "done", "image_data": b"data"})
            svc.schedule_image_data_cleanup("task1")

            assert "task1" in svc._cleanup_timers

            svc.remove_task("task1")

            assert "task1" not in svc._cleanup_timers
        finally:
            svc.close()
            ts_module._IMAGE_DATA_CLEANUP_DELAY = original_delay


@pytest.mark.unit
class TestTaskServiceConcurrency:
    """测试并发安全性"""

    def test_concurrent_set_and_get(self, svc_factory):
        """并发 set_task 和 get_task 应保持数据一致性"""
        svc, db_path = svc_factory("concurrent_set")
        try:
            errors = []

            def writer(task_id_base):
                try:
                    # 每线程写入 30 个任务，5 线程共 150 个，不超过 LRU 上限 200
                    for i in range(30):
                        svc.set_task(f"{task_id_base}_{i}", {"value": i})
                except Exception as e:
                    errors.append(str(e))

            threads = []
            for i in range(5):
                t = threading.Thread(target=writer, args=(f"thread{i}",))
                threads.append(t)
                t.start()

            for t in threads:
                t.join()

            assert len(errors) == 0, f"并发写入错误: {errors}"

            for i in range(5):
                for j in range(30):
                    task = svc.get_task(f"thread{i}_{j}")
                    assert task is not None
                    assert task["value"] == j
        finally:
            svc.close()

    def test_concurrent_update_task(self, svc_factory):
        """并发 update_task 应正确更新任务"""
        svc, db_path = svc_factory("concurrent_update")
        try:
            svc.set_task("shared_task", {"counter": 0})

            errors = []

            def incrementer():
                try:
                    for _ in range(100):
                        task = svc.get_task("shared_task")
                        svc.update_task("shared_task", counter=task["counter"] + 1)
                except Exception as e:
                    errors.append(str(e))

            threads = []
            for _ in range(10):
                t = threading.Thread(target=incrementer)
                threads.append(t)
                t.start()

            for t in threads:
                t.join()

            assert len(errors) == 0, f"并发更新错误: {errors}"

            task = svc.get_task("shared_task")
            assert task["counter"] == 1000
        finally:
            svc.close()

    def test_concurrent_add_history(self, svc_factory):
        """并发 add_history 应保持数据一致性"""
        svc, db_path = svc_factory("concurrent_history")
        try:
            errors = []

            def add_records(thread_id):
                try:
                    for i in range(20):
                        svc.add_history({
                            "filename": f"file_{thread_id}_{i}.jpg",
                            "success": True,
                            "processing_time": 1.0,
                        })
                except Exception as e:
                    errors.append(str(e))

            threads = []
            for i in range(5):
                t = threading.Thread(target=add_records, args=(i,))
                threads.append(t)
                t.start()

            for t in threads:
                t.join()

            assert len(errors) == 0, f"并发添加历史错误: {errors}"

            total = svc.get_history_count()
            assert total == 100
        finally:
            svc.close()

    def test_concurrent_remove_and_add(self, svc_factory):
        """并发 remove_task 和 set_task 不应冲突"""
        svc, db_path = svc_factory("concurrent_remove")
        try:
            for i in range(20):
                svc.set_task(f"task_{i}", {"value": i})

            errors = []

            def remover():
                try:
                    for i in range(20):
                        svc.remove_task(f"task_{i}")
                except Exception as e:
                    errors.append(str(e))

            def adder():
                try:
                    for i in range(20):
                        svc.set_task(f"task_{i}", {"value": i * 2})
                except Exception as e:
                    errors.append(str(e))

            t1 = threading.Thread(target=remover)
            t2 = threading.Thread(target=adder)

            t1.start()
            t2.start()
            t1.join()
            t2.join()

            assert len(errors) == 0, f"并发移除/添加错误: {errors}"

            for i in range(20):
                task = svc.get_task(f"task_{i}")
                assert task is not None
        finally:
            svc.close()


@pytest.mark.unit
class TestPollMutex:
    """测试并发轮询互斥机制（防止 TOCTOU 竞态）"""

    def test_try_acquire_poll_basic(self, svc_factory):
        """try_acquire_poll 应实现互斥：同一 task_id 只能被获取一次"""
        svc, db_path = svc_factory("poll_mutex")
        try:
            # 首次获取应成功
            assert svc.try_acquire_poll("task1") is True
            # 重复获取同一 task_id 应失败
            assert svc.try_acquire_poll("task1") is False
            # 不同 task_id 应可获取
            assert svc.try_acquire_poll("task2") is True

            # 释放后应可重新获取
            svc.release_poll("task1")
            assert svc.try_acquire_poll("task1") is True

            svc.release_poll("task1")
            svc.release_poll("task2")
        finally:
            svc.close()

    def test_poll_mutex_prevents_concurrent_processing(self, svc_factory):
        """并发轮询互斥应防止同一 task_id 被多个线程同时处理"""
        svc, db_path = svc_factory("poll_concurrent")
        try:
            acquired_count = [0]
            rejected_count = [0]
            barrier = threading.Barrier(3, timeout=5)

            def try_poll(task_id):
                try:
                    barrier.wait()
                    if svc.try_acquire_poll(task_id):
                        acquired_count[0] += 1
                        time.sleep(0.1)  # 模拟处理
                        svc.release_poll(task_id)
                    else:
                        rejected_count[0] += 1
                except Exception:
                    pass

            # 3 个线程同时尝试获取同一 task_id 的轮询权
            threads = [threading.Thread(target=try_poll, args=("task1",)) for _ in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # 恰好只有 1 个线程应成功获取
            assert acquired_count[0] == 1, f"应有1个获取成功，实际{acquired_count[0]}"
            assert rejected_count[0] == 2, f"应有2个被拒绝，实际{rejected_count[0]}"
        finally:
            svc.close()


@pytest.mark.unit
class TestScheduleCleanupThreadSafety:
    """测试 schedule_image_data_cleanup 的线程安全性"""

    def test_schedule_cleanup_under_lock(self, svc_factory):
        """schedule_image_data_cleanup 应在锁内修改 _cleanup_timers"""
        svc, db_path = svc_factory("cleanup_lock")
        try:
            svc.set_task("task1", {"status": "done", "image_data": b"data"})
            svc.schedule_image_data_cleanup("task1", delay=5.0)

            # 验证定时器已注册
            assert "task1" in svc._cleanup_timers

            # 再次调度应替换旧定时器（而非泄漏两个定时器）
            old_timer = svc._cleanup_timers["task1"]
            svc.schedule_image_data_cleanup("task1", delay=5.0)
            new_timer = svc._cleanup_timers["task1"]

            # 旧定时器应已被取消
            assert old_timer is not new_timer
            # 只应有一个定时器
            assert len([k for k in svc._cleanup_timers if k == "task1"]) == 1
        finally:
            svc.close()

    def test_concurrent_schedule_cleanup_no_orphan_timers(self, svc_factory):
        """并发 schedule_image_data_cleanup 不应产生孤立定时器"""
        svc, db_path = svc_factory("cleanup_concurrent")
        try:
            svc.set_task("task1", {"status": "done", "image_data": b"data"})

            errors = []

            def schedule_repeated(task_id):
                try:
                    for _ in range(20):
                        svc.schedule_image_data_cleanup(task_id, delay=5.0)
                except Exception as e:
                    errors.append(str(e))

            threads = [threading.Thread(target=schedule_repeated, args=("task1",)) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0, f"并发调度清理错误: {errors}"

            # 并发调度后应恰好只有 1 个定时器（无孤立定时器泄漏）
            assert "task1" in svc._cleanup_timers
            assert len([k for k in svc._cleanup_timers if k == "task1"]) == 1
        finally:
            svc.close()


@pytest.mark.unit
class TestGetHistoryWithCount:
    """测试 get_history_with_count 一次性获取分页数据和总数"""

    def test_returns_items_and_total_tuple(self, svc_factory):
        """应返回 (items, total) 元组"""
        svc, db_path = svc_factory("history_count_tuple")
        try:
            for i in range(10):
                svc.add_history({"filename": f"file_{i}.jpg", "success": True})

            items, total = svc.get_history_with_count(limit=5, offset=0)

            assert isinstance(items, list)
            assert len(items) == 5
            assert total == 10
        finally:
            svc.close()

    def test_offset_pagination(self, svc_factory):
        """分页 offset 应正确跳过记录"""
        svc, db_path = svc_factory("history_count_offset")
        try:
            for i in range(8):
                svc.add_history({"filename": f"file_{i}.jpg", "success": True})

            items_page1, total = svc.get_history_with_count(limit=3, offset=0)
            items_page2, _ = svc.get_history_with_count(limit=3, offset=3)

            assert len(items_page1) == 3
            assert len(items_page2) == 3
            assert total == 8
            # 两页不应有重叠
            ids_page1 = {h["id"] for h in items_page1}
            ids_page2 = {h["id"] for h in items_page2}
            assert ids_page1.isdisjoint(ids_page2)
        finally:
            svc.close()

    def test_total_reflects_db_not_memory(self, svc_factory):
        """total 应以 DB 为准，不受内存 deque maxlen 截断影响"""
        import importlib
        ts_module = importlib.import_module("apps.web.api.services.task_service")
        original_max = ts_module._MAX_HISTORY
        ts_module._MAX_HISTORY = 5
        try:
            svc, db_path = svc_factory("history_count_db")
            try:
                # 添加 10 条记录，内存 deque 只保留最新 5 条
                for i in range(10):
                    svc.add_history({"filename": f"file_{i}.jpg", "success": True})

                items, total = svc.get_history_with_count(limit=50, offset=0)

                # 内存只返回 deque 中的 5 条
                assert len(items) == 5
                # 但 total 应为 DB 全量 10 条
                assert total == 10
            finally:
                svc.close()
        finally:
            ts_module._MAX_HISTORY = original_max


@pytest.mark.unit
class TestDequeEvictionAndDbCount:
    """测试 deque(maxlen) 自动淘汰与 DB 计数的差异"""

    def test_memory_evicts_oldest_but_db_retains_all(self, svc_factory):
        """内存 deque 超出 maxlen 时淘汰最旧记录，但 DB 保留全量"""
        import importlib
        ts_module = importlib.import_module("apps.web.api.services.task_service")
        original_max = ts_module._MAX_HISTORY
        ts_module._MAX_HISTORY = 3
        try:
            svc, db_path = svc_factory("deque_eviction")
            try:
                for i in range(5):
                    svc.add_history({"id": f"id_{i}", "filename": f"file_{i}.jpg"})

                # 内存 deque 只保留最新 3 条（id_4, id_3, id_2）
                assert len(svc._history) == 3
                memory_ids = {h["id"] for h in svc._history}
                assert "id_4" in memory_ids
                assert "id_3" in memory_ids
                assert "id_2" in memory_ids
                # id_0, id_1 已被内存淘汰
                assert "id_0" not in memory_ids
                assert "id_1" not in memory_ids

                # DB 仍保留全部 5 条
                assert svc.get_history_count() == 5
            finally:
                svc.close()
        finally:
            ts_module._MAX_HISTORY = original_max

    def test_get_history_count_uses_db(self, svc_factory):
        """get_history_count 应返回 DB 总数而非内存条数"""
        import importlib
        ts_module = importlib.import_module("apps.web.api.services.task_service")
        original_max = ts_module._MAX_HISTORY
        ts_module._MAX_HISTORY = 5
        try:
            svc, db_path = svc_factory("count_db")
            try:
                for i in range(8):
                    svc.add_history({"filename": f"f{i}.jpg"})

                # 内存只有 5 条，DB 有 8 条
                assert len(svc._history) == 5
                assert svc.get_history_count() == 8
            finally:
                svc.close()
        finally:
            ts_module._MAX_HISTORY = original_max


@pytest.mark.unit
class TestDeleteHistoryDbRowcount:
    """测试 delete_history / batch_delete_history 的 DB rowcount 逻辑"""

    def test_delete_history_for_db_only_record(self, svc_factory):
        """删除已从内存淘汰但仍在 DB 中的记录应成功"""
        import importlib
        ts_module = importlib.import_module("apps.web.api.services.task_service")
        original_max = ts_module._MAX_HISTORY
        ts_module._MAX_HISTORY = 3
        try:
            svc, db_path = svc_factory("delete_db_only")
            try:
                # 添加 5 条，前 2 条会被内存淘汰
                for i in range(5):
                    svc.add_history({"id": f"evict_{i}", "filename": f"f{i}.jpg"})

                # id_0 已从内存淘汰，但仍在 DB
                assert "evict_0" not in {h["id"] for h in svc._history}
                assert svc.get_history_count() == 5

                # 删除应成功（DB rowcount > 0）
                result = svc.delete_history("evict_0")
                assert result is True

                # DB 中应只剩 4 条
                assert svc.get_history_count() == 4
            finally:
                svc.close()
        finally:
            ts_module._MAX_HISTORY = original_max

    def test_delete_history_nonexistent_returns_false(self, svc_factory):
        """删除不存在的记录应返回 False"""
        svc, db_path = svc_factory("delete_nonexist")
        try:
            assert svc.delete_history("nonexistent_id") is False
        finally:
            svc.close()

    def test_delete_history_in_memory_record(self, svc_factory):
        """删除内存中存在的记录应同时从内存和 DB 删除"""
        svc, db_path = svc_factory("delete_inmem")
        try:
            svc.add_history({"id": "in_mem_1", "filename": "f1.jpg"})
            svc.add_history({"id": "in_mem_2", "filename": "f2.jpg"})

            result = svc.delete_history("in_mem_1")
            assert result is True

            # 内存和 DB 都不应再有该记录
            assert "in_mem_1" not in {h["id"] for h in svc._history}
            assert svc.get_history_count() == 1
        finally:
            svc.close()

    def test_batch_delete_mixed_memory_and_db_only(self, svc_factory):
        """批量删除混合内存中和 DB-only 的记录应返回正确数量"""
        import importlib
        ts_module = importlib.import_module("apps.web.api.services.task_service")
        original_max = ts_module._MAX_HISTORY
        ts_module._MAX_HISTORY = 3
        try:
            svc, db_path = svc_factory("batch_delete_mixed")
            try:
                # 添加 5 条，前 2 条（batch_0, batch_1）被内存淘汰
                for i in range(5):
                    svc.add_history({"id": f"batch_{i}", "filename": f"f{i}.jpg"})

                memory_ids = {h["id"] for h in svc._history}
                assert "batch_0" not in memory_ids  # DB only
                assert "batch_1" not in memory_ids  # DB only
                assert "batch_2" in memory_ids      # in memory
                assert svc.get_history_count() == 5

                # 批量删除：2 个 DB-only + 1 个内存中
                deleted = svc.batch_delete_history(["batch_0", "batch_1", "batch_2"])
                assert deleted == 3

                # DB 应只剩 2 条
                assert svc.get_history_count() == 2
            finally:
                svc.close()
        finally:
            ts_module._MAX_HISTORY = original_max

    def test_batch_delete_empty_list_returns_zero(self, svc_factory):
        """空列表批量删除应返回 0"""
        svc, db_path = svc_factory("batch_empty")
        try:
            assert svc.batch_delete_history([]) == 0
        finally:
            svc.close()

    def test_batch_delete_nonexistent_ids_returns_zero(self, svc_factory):
        """全部不存在的 ID 批量删除应返回 0"""
        svc, db_path = svc_factory("batch_nonexist")
        try:
            deleted = svc.batch_delete_history(["no_1", "no_2", "no_3"])
            assert deleted == 0
        finally:
            svc.close()