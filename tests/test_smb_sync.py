"""
测试: standalone/smb_sync.py - SMB NAS 跨网段同步服务

覆盖:
  - SyncConfig 数据类
  - SyncDirection / SyncStatus 枚举
  - SyncRecord 数据类
  - LocalCache 本地缓存 (核心功能，不依赖 NAS)
  - SmbSyncService 初始化与状态管理
  - push_history / pull_history 模拟
  - 重连逻辑行为
  - create_default_sync_service 工厂函数

注意: 实际 SMB 网络操作会被 mock，只测试逻辑正确性。
"""

import os
import sys
import json
import threading
import time
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "standalone"))


# ──────────────────────────────────────────────────
# SyncConfig
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestSyncConfig:
    """测试 SyncConfig 数据类"""

    def test_default_values(self):
        """默认配置值"""
        from smb_sync import SyncConfig
        cfg = SyncConfig()
        assert cfg.host == "192.168.0.79"
        assert cfg.share == "maker"
        assert cfg.username == "maker"
        assert cfg.password == "maker"
        assert cfg.sync_root == "CLAW_CHANGE_RECORDS/08_shared_data"
        assert cfg.auto_sync is True
        assert cfg.sync_history is True
        assert cfg.sync_reports is True
        assert cfg.sync_interval_minutes == 5
        assert cfg.max_retries == 5
        assert cfg.retry_base_seconds == 2.0
        assert cfg.health_check_interval == 30
        assert cfg.cache_ttl_hours == 24
        assert cfg.mount_letter == ""

    def test_unc_path(self):
        """UNC 路径构造"""
        from smb_sync import SyncConfig
        cfg = SyncConfig(host="10.0.0.1", share="data")
        assert cfg.unc_path == r"\\10.0.0.1\data"

    def test_sync_unc_path(self):
        """同步根目录 UNC 路径"""
        from smb_sync import SyncConfig
        cfg = SyncConfig(host="192.168.0.79", share="maker",
                         sync_root="CLAW_CHANGE_RECORDS/08_shared_data")
        assert "192.168.0.79" in cfg.sync_unc_path
        assert "maker" in cfg.sync_unc_path
        assert "08_shared_data" in cfg.sync_unc_path

    def test_mount_unc_with_letter(self):
        """挂载路径：有盘符时返回盘符路径"""
        from smb_sync import SyncConfig
        cfg = SyncConfig(mount_letter="Z:")
        assert cfg.mount_unc == "Z:\\"

    def test_mount_unc_without_letter(self):
        """挂载路径：无盘符时返回 UNC"""
        from smb_sync import SyncConfig
        cfg = SyncConfig(host="192.168.0.79", share="maker")
        assert cfg.mount_unc == cfg.unc_path

    def test_to_dict_masks_password(self):
        """to_dict 会遮罩密码"""
        from smb_sync import SyncConfig
        cfg = SyncConfig(password="secret123")
        d = cfg.to_dict()
        assert d["password"] == "***"

    def test_custom_config(self):
        """自定义配置"""
        from smb_sync import SyncConfig
        cfg = SyncConfig(
            host="10.0.0.50",
            share="nas_share",
            username="admin",
            password="pass123",
            sync_root="data/reports",
            auto_sync=False,
            sync_interval_minutes=10,
            max_retries=3,
        )
        assert cfg.host == "10.0.0.50"
        assert cfg.share == "nas_share"
        assert cfg.sync_interval_minutes == 10
        assert cfg.max_retries == 3
        assert cfg.auto_sync is False


# ──────────────────────────────────────────────────
# SyncDirection / SyncStatus 枚举
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestSyncEnums:
    """测试同步相关枚举"""

    def test_sync_direction_values(self):
        """SyncDirection 枚举值"""
        from smb_sync import SyncDirection
        assert SyncDirection.PUSH.value == "push"
        assert SyncDirection.PULL.value == "pull"
        assert SyncDirection.BIDIRECTIONAL.value == "bidirectional"

    def test_sync_status_values(self):
        """SyncStatus 枚举值"""
        from smb_sync import SyncStatus
        assert SyncStatus.DISCONNECTED.value == "disconnected"
        assert SyncStatus.CONNECTING.value == "connecting"
        assert SyncStatus.CONNECTED.value == "connected"
        assert SyncStatus.SYNCING.value == "syncing"
        assert SyncStatus.ERROR.value == "error"


# ──────────────────────────────────────────────────
# SyncRecord
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestSyncRecord:
    """测试 SyncRecord 数据类"""

    def test_create_record(self):
        """创建同步记录"""
        from smb_sync import SyncRecord
        record = SyncRecord(
            timestamp="2026-06-09T12:00:00",
            direction="push",
            files_synced=10,
            files_failed=2,
            details=["report_001 synced", "report_002 failed: timeout"],
        )
        assert record.files_synced == 10
        assert record.files_failed == 2
        assert len(record.details) == 2

    def test_default_details(self):
        """默认 details 为空列表"""
        from smb_sync import SyncRecord
        record = SyncRecord(
            timestamp="2026-06-09T12:00:00",
            direction="pull",
            files_synced=0,
            files_failed=0,
        )
        assert record.details == []


# ──────────────────────────────────────────────────
# LocalCache
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestLocalCache:
    """测试 LocalCache 离线缓存 (不依赖网络)"""

    def test_init_creates_cache_dir(self, temp_dir):
        """初始化创建缓存目录"""
        from smb_sync import LocalCache
        cache_dir = temp_dir / "cache"
        cache = LocalCache(cache_dir)
        assert cache_dir.exists()

    def test_init_existing_dir(self, temp_dir):
        """已存在的目录不报错"""
        from smb_sync import LocalCache
        cache_dir = temp_dir / "existing_cache"
        cache_dir.mkdir()
        cache = LocalCache(cache_dir)

    def test_add_and_get_pending(self, temp_dir):
        """添加和获取待同步操作"""
        from smb_sync import LocalCache
        cache = LocalCache(temp_dir / "cache")

        cache.add_pending("push_reports", {"report_ids": ["rpt_1", "rpt_2"]})
        pending = cache.get_pending()
        assert len(pending) == 1
        assert pending[0].operation == "push_reports"
        assert pending[0].payload["report_ids"] == ["rpt_1", "rpt_2"]

    def test_has_pending(self, temp_dir):
        """检查是否有待同步数据"""
        from smb_sync import LocalCache
        cache = LocalCache(temp_dir / "cache")
        assert not cache.has_pending()
        cache.add_pending("push_history", {"items": []})
        assert cache.has_pending()

    def test_pending_count(self, temp_dir):
        """待同步计数"""
        from smb_sync import LocalCache
        cache = LocalCache(temp_dir / "cache")
        assert cache.pending_count() == 0
        cache.add_pending("push_reports", {})
        cache.add_pending("push_history", {})
        assert cache.pending_count() == 2

    def test_remove_pending(self, temp_dir):
        """移除指定的待同步操作"""
        from smb_sync import LocalCache, CacheEntry
        cache = LocalCache(temp_dir / "cache")
        cache.add_pending("push_reports", {"id": "1"})
        cache.add_pending("push_history", {"id": "2"})

        pending = cache.get_pending()
        cache.remove_pending(pending[0])
        remaining = cache.get_pending()
        assert len(remaining) == 1
        assert remaining[0].operation == "push_history"

    def test_clear_pending(self, temp_dir):
        """清空所有待同步"""
        from smb_sync import LocalCache
        cache = LocalCache(temp_dir / "cache")
        cache.add_pending("op1", {})
        cache.add_pending("op2", {})
        cache.clear_pending()
        assert not cache.has_pending()
        assert cache.pending_count() == 0

    def test_persistence_across_instances(self, temp_dir):
        """待同步数据持久化 (跨实例恢复)"""
        from smb_sync import LocalCache
        cache_dir = temp_dir / "cache"

        # 第一个实例
        cache1 = LocalCache(cache_dir)
        cache1.add_pending("push_reports", {"ids": ["A", "B"]})
        cache1.add_pending("push_config", {"key": "value"})

        # 第二个实例 (模拟重启)
        cache2 = LocalCache(cache_dir)
        pending = cache2.get_pending()
        assert len(pending) == 2
        operations = {p.operation for p in pending}
        assert "push_reports" in operations
        assert "push_config" in operations

    def test_multiple_operation_types(self, temp_dir):
        """多种操作类型的混合管理"""
        from smb_sync import LocalCache
        cache = LocalCache(temp_dir / "cache")

        cache.add_pending("push_reports", {"report_ids": ["rpt_1"]})
        cache.add_pending("push_history", {"history_items": []})
        cache.add_pending("push_config", {"config_data": {}})
        cache.add_pending("push_file", {"path": "/tmp/test.jpg"})

        assert cache.pending_count() == 4

    def test_cache_entry_created_at(self, temp_dir):
        """缓存条目包含创建时间"""
        from smb_sync import LocalCache
        cache = LocalCache(temp_dir / "cache")
        before = datetime.now().isoformat()
        cache.add_pending("test_op", {})
        pending = cache.get_pending()
        assert pending[0].created_at >= before


# ──────────────────────────────────────────────────
# SmbSyncService 初始化与状态管理
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestSmbSyncServiceInit:
    """测试 SmbSyncService 初始化"""

    def test_default_init(self, temp_dir):
        """默认初始化"""
        from smb_sync import SmbSyncService, SyncStatus
        svc = SmbSyncService(cache_dir=str(temp_dir / "cache"))
        assert svc.config.host == "192.168.0.79"
        assert svc._status == SyncStatus.DISCONNECTED
        assert svc._session_id is None

    def test_init_with_custom_config(self, temp_dir):
        """自定义配置初始化"""
        from smb_sync import SmbSyncService, SyncConfig
        cfg = SyncConfig(host="10.0.0.99", share="backup", username="root")
        svc = SmbSyncService(config=cfg, cache_dir=str(temp_dir / "cache"))
        assert svc.config.host == "10.0.0.99"
        assert svc.config.share == "backup"

    def test_get_status_disconnected(self, temp_dir):
        """初始状态为 DISCONNECTED"""
        from smb_sync import SmbSyncService
        svc = SmbSyncService(cache_dir=str(temp_dir / "cache"))
        # Mock _test_unc_readable 以确保初始状态是断开的
        svc._test_unc_readable = lambda: False
        status = svc.get_status()
        assert status["status"] == "disconnected"
        assert status["connected"] is False
        assert status["connect_failures"] == 0
        assert status["pending_cache"] == 0

    def test_get_status_has_recent_logs(self, temp_dir):
        """状态快照包含最近日志"""
        from smb_sync import SmbSyncService
        svc = SmbSyncService(cache_dir=str(temp_dir / "cache"))
        status = svc.get_status()
        assert "recent_logs" in status
        assert isinstance(status["recent_logs"], list)


# ──────────────────────────────────────────────────
# SmbSyncService 回调
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestSmbSyncServiceCallbacks:
    """测试回调机制"""

    def test_set_status_callback(self, temp_dir):
        """设置状态回调"""
        from smb_sync import SmbSyncService
        svc = SmbSyncService(cache_dir=str(temp_dir / "cache"))
        called = []

        def on_status(status, msg):
            called.append((status.value, msg))

        svc.set_on_status(on_status)
        svc._notify_status(svc._status, "test")
        assert len(called) == 1

    def test_set_sync_complete_callback(self, temp_dir):
        """设置同步完成回调"""
        from smb_sync import SmbSyncService, SyncRecord
        svc = SmbSyncService(cache_dir=str(temp_dir / "cache"))
        called = []

        def on_complete(record):
            called.append(record)

        svc.set_on_sync_complete(on_complete)

        record = SyncRecord(
            timestamp=datetime.now().isoformat(),
            direction="push",
            files_synced=5,
            files_failed=1,
        )
        # 直接调用回调
        svc._on_sync_complete(record)
        assert len(called) == 1
        assert called[0].files_synced == 5

    def test_callback_exception_handled(self, temp_dir):
        """回调异常不影响服务"""
        from smb_sync import SmbSyncService
        svc = SmbSyncService(cache_dir=str(temp_dir / "cache"))

        def bad_callback(status, msg):
            raise RuntimeError("Callback error")

        svc.set_on_status(bad_callback)
        # 不应抛出异常
        svc._notify_status(svc._status, "should not crash")


# ──────────────────────────────────────────────────
# SmbSyncService push_history / pull_history 模拟
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestSmbSyncServiceHistory:
    """测试历史记录同步 (mock 文件操作)"""

    def test_push_history_mocked(self, temp_dir):
        """推送历史记录 (mock)"""
        from smb_sync import SmbSyncService, SyncConfig
        cfg = SyncConfig(host="192.168.0.79", share="maker")
        svc = SmbSyncService(config=cfg, cache_dir=str(temp_dir / "cache"))

        # Mock 文件系统操作
        with patch.object(svc, "_ensure_remote_dir", return_value=True), \
             patch("builtins.open", MagicMock()):
            record = svc.push_history([
                {"id": 1, "filename": "test.jpg", "success": True},
                {"id": 2, "filename": "test2.png", "success": False},
            ])
            assert record.files_synced == 1
            assert record.files_failed == 0
            assert record.direction == "push"

    def test_push_history_empty(self, temp_dir):
        """推送空历史记录"""
        from smb_sync import SmbSyncService, SyncConfig
        cfg = SyncConfig()
        svc = SmbSyncService(config=cfg, cache_dir=str(temp_dir / "cache"))

        with patch.object(svc, "_ensure_remote_dir", return_value=True), \
             patch("builtins.open", MagicMock()):
            record = svc.push_history([])
            assert record.files_synced == 1  # 空列表仍然写入文件
            assert record.direction == "push"

    def test_push_history_exception(self, temp_dir):
        """推送历史记录异常处理"""
        from smb_sync import SmbSyncService, SyncConfig
        cfg = SyncConfig()
        svc = SmbSyncService(config=cfg, cache_dir=str(temp_dir / "cache"))

        # 模拟写入异常
        with patch.object(svc, "_ensure_remote_dir", side_effect=Exception("NAS gone")):
            record = svc.push_history([{"id": 1}])
            assert record.files_synced == 0
            assert record.files_failed == 1
            assert any("NAS gone" in d for d in record.details)

    def test_pull_history_with_mocked_files(self, temp_dir):
        """拉取历史记录 (mock)"""
        from smb_sync import SmbSyncService, SyncConfig, SyncRecord
        cfg = SyncConfig()
        svc = SmbSyncService(config=cfg, cache_dir=str(temp_dir / "cache"))

        # Mock list_remote_dir 返回 JSON 文件列表
        history_data = {
            "timestamp": datetime.now().isoformat(),
            "source": "desktop_app",
            "items": [
                {"id": 1, "filename": "remote.jpg", "success": True},
            ],
        }
        history_json = json.dumps(history_data, ensure_ascii=False)

        with patch.object(svc, "list_remote_dir", return_value=["history_20260609.json"]), \
             patch.object(Path, "read_text", return_value=history_json), \
             patch.object(Path, "exists", return_value=True):
            items = svc.pull_history()
            assert len(items) == 1
            assert items[0]["filename"] == "remote.jpg"
            assert items[0]["_source"] == "nas"

    def test_pull_history_empty_nas(self, temp_dir):
        """NAS 上无历史记录时返回空列表"""
        from smb_sync import SmbSyncService, SyncConfig
        cfg = SyncConfig()
        svc = SmbSyncService(config=cfg, cache_dir=str(temp_dir / "cache"))

        with patch.object(svc, "list_remote_dir", return_value=[]):
            items = svc.pull_history()
            assert items == []


# ──────────────────────────────────────────────────
# SmbSyncService 连接与重连逻辑
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestSmbSyncServiceConnection:
    """测试连接逻辑 (全部 mock 网络)"""

    def test_connect_success_mocked(self, temp_dir):
        """连接成功 (mock)"""
        from smb_sync import SmbSyncService, SyncStatus
        svc = SmbSyncService(cache_dir=str(temp_dir / "cache"))

        with patch.object(svc, "_test_unc_readable", return_value=True):
            result = svc.connect()
            assert result is True

    def test_connect_mount_needed_mocked(self, temp_dir):
        """需要挂载的连接 (mock)"""
        from smb_sync import SmbSyncService
        svc = SmbSyncService(cache_dir=str(temp_dir / "cache"))

        with patch.object(svc, "_test_unc_readable", side_effect=[False, True]), \
             patch.object(svc, "_mount_smb", return_value=True):
            result = svc.connect()
            assert result is True

    def test_connect_failure_mocked(self, temp_dir):
        """连接失败 (mock)"""
        from smb_sync import SmbSyncService
        svc = SmbSyncService(cache_dir=str(temp_dir / "cache"))

        with patch.object(svc, "_test_unc_readable", return_value=False), \
             patch.object(svc, "_mount_smb", return_value=False):
            result = svc.connect()
            assert result is False
            assert svc._connect_failures == 1

    def test_is_connected_delegates(self, temp_dir):
        """is_connected 委托给 _test_unc_readable"""
        from smb_sync import SmbSyncService
        svc = SmbSyncService(cache_dir=str(temp_dir / "cache"))

        with patch.object(svc, "_test_unc_readable", return_value=True):
            assert svc.is_connected() is True

        with patch.object(svc, "_test_unc_readable", return_value=False):
            assert svc.is_connected() is False

    def test_disconnect(self, temp_dir):
        """断开连接"""
        from smb_sync import SmbSyncService, SyncStatus
        svc = SmbSyncService(cache_dir=str(temp_dir / "cache"))
        svc.disconnect()
        assert svc._status == SyncStatus.DISCONNECTED
        assert svc._session_id is None

    def test_health_check_becomes_healthy(self, temp_dir):
        """健康检查恢复连接"""
        from smb_sync import SmbSyncService, SyncStatus
        svc = SmbSyncService(cache_dir=str(temp_dir / "cache"))

        # 初始断开
        svc._status = SyncStatus.DISCONNECTED
        with patch.object(svc, "_test_unc_readable", return_value=True):
            result = svc.health_check()
            assert result is True
            assert svc._status == SyncStatus.CONNECTED

    def test_health_check_becomes_unhealthy(self, temp_dir):
        """健康检查发现断开"""
        from smb_sync import SmbSyncService, SyncStatus
        svc = SmbSyncService(cache_dir=str(temp_dir / "cache"))

        svc._status = SyncStatus.CONNECTED
        svc.config.auto_sync = False

        with patch.object(svc, "_test_unc_readable", return_value=False):
            result = svc.health_check()
            assert result is False
            assert svc._status == SyncStatus.DISCONNECTED

    def test_start_stop_health_monitor(self, temp_dir):
        """启动和停止健康监控线程"""
        from smb_sync import SmbSyncService
        svc = SmbSyncService(cache_dir=str(temp_dir / "cache"))

        # Mock health_check 避免实际网络调用
        with patch.object(svc, "health_check", return_value=True):
            svc.start_health_monitor()
            assert svc._health_thread is not None
            assert svc._health_thread.is_alive()
            svc.stop_health_monitor()

            # 等待线程结束
            svc._health_thread.join(timeout=3)
            assert not svc._health_thread.is_alive()


# ──────────────────────────────────────────────────
# create_default_sync_service 工厂
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestCreateDefaultSyncService:
    """测试工厂函数"""

    def test_creates_valid_service(self, temp_dir):
        """创建有效的服务实例"""
        from smb_sync import create_default_sync_service, SmbSyncService
        svc = create_default_sync_service(cache_dir=str(temp_dir / "cache"))
        assert isinstance(svc, SmbSyncService)
        assert svc.config.host == "192.168.0.79"
        assert svc.config.share == "maker"
        assert svc.config.auto_sync is True
        assert svc.config.sync_reports is True
        assert svc.config.sync_history is True

    def test_default_sync_root(self, temp_dir):
        """默认同步根目录"""
        from smb_sync import create_default_sync_service
        svc = create_default_sync_service(cache_dir=str(temp_dir / "cache"))
        assert "08_shared_data" in svc.config.sync_root

    def test_has_local_cache(self, temp_dir):
        """包含本地缓存"""
        from smb_sync import create_default_sync_service
        svc = create_default_sync_service(cache_dir=str(temp_dir / "cache"))
        assert svc.cache is not None
        assert not svc.cache.has_pending()


# ──────────────────────────────────────────────────
# sync_all 全量同步逻辑
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestSyncAll:
    """测试 sync_all 全量同步"""

    def test_sync_all_offline_fallback(self, temp_dir):
        """NAS 不可用时回退到离线缓存"""
        from smb_sync import SmbSyncService, SyncDirection
        svc = SmbSyncService(cache_dir=str(temp_dir / "cache"))

        with patch.object(svc, "is_connected", return_value=False):
            record = svc.sync_all(
                local_output_dir=str(temp_dir / "output"),
                history_items=[{"id": 1}],
                direction=SyncDirection.BIDIRECTIONAL,
            )
            assert record.files_synced == 0
            assert record.files_failed == 0
            assert "缓存" in record.details[0] or "不可用" in record.details[0]

    def test_sync_all_push_direction(self, temp_dir):
        """测试推送方向同步 (mock)"""
        from smb_sync import SmbSyncService, SyncDirection
        svc = SmbSyncService(cache_dir=str(temp_dir / "cache"))

        with patch.object(svc, "is_connected", return_value=True), \
             patch.object(svc, "push_reports", return_value=MagicMock(
                 files_synced=3, files_failed=1, details=["ok"]
             )), \
             patch.object(svc, "push_history", return_value=MagicMock(
                 files_synced=1, files_failed=0, details=["ok"]
             )):
            record = svc.sync_all(
                local_output_dir=str(temp_dir / "output"),
                history_items=[{"id": 1}],
                direction=SyncDirection.PUSH,
            )
            assert record.files_synced >= 3
