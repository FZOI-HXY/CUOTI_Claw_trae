"""
SMB NAS 跨网段同步服务

在大内网跨网段环境中，利用 SMB 共享 NAS（192.168.0.79）作为数据中转节点。
不同网段的应用实例通过 NAS 可靠交换数据。

实现方案:
  - Windows net use 建立 SMB 认证会话
  - UNC 路径访问 NAS 文件系统
  - 指数退避断线重连
  - 本地离线缓存与延迟同步
  - 双向同步（推送 / 拉取）

NAS 连接信息:
  地址: 192.168.0.79
  共享: maker
  账号: maker
  密码: maker

NAS 标准目录结构:
  //192.168.0.79/maker/
  └── CLAW_CHANGE_RECORDS/
      ├── 01_changelogs/    # 变更日志
      ├── 02_releases/      # 版本发布
      ├── 03_snapshots/     # 代码快照
      ├── 04_configs_backup/# 配置备份
      ├── 05_patches/       # 补丁/热修复
      ├── 06_database/      # 数据库迁移
      ├── 07_logs/          # 日志归档
      ├── 08_shared_data/   # 跨网段共享数据（同步目标）
      │   ├── reports/      # 报告同步
      │   ├── history/      # 历史同步
      │   └── shared_config.json
      └── templates/        # 记录模板
  (详见 setup_nas_structure.py --verify)

依赖: 仅标准库 + subprocess（无额外 pip 包），可选 smbprotocol
"""
import os
import re
import io
import json
import time
import shutil
import zipfile
import hashlib
import threading
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Callable, Any
from dataclasses import dataclass, field
from enum import Enum


# ============ 数据类 ============

class SyncDirection(Enum):
    PUSH = "push"          # 本地 → NAS
    PULL = "pull"          # NAS → 本地
    BIDIRECTIONAL = "bidirectional"


class SyncStatus(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    SYNCING = "syncing"
    ERROR = "error"


@dataclass
class SyncConfig:
    """NAS 同步配置"""
    host: str = "192.168.0.79"
    share: str = "maker"
    username: str = "maker"
    password: str = "maker"
    sync_root: str = "CLAW_CHANGE_RECORDS/08_shared_data"  # NAS 上的同步根目录
    auto_sync: bool = True                  # 处理完成后自动同步
    sync_history: bool = True               # 同步处理历史
    sync_reports: bool = True               # 同步报告数据
    sync_interval_minutes: int = 5          # 周期性同步间隔
    max_retries: int = 5                    # 最大重连次数
    retry_base_seconds: float = 2.0         # 重试退避基秒数
    health_check_interval: int = 30         # 健康检查间隔秒数
    cache_ttl_hours: int = 24               # 离线缓存有效期
    mount_letter: str = ""                  # 可选的挂载盘符，如 "Z:"

    @property
    def unc_path(self) -> str:
        """构建 UNC 路径"""
        return f"\\\\{self.host}\\{self.share}"

    @property
    def sync_unc_path(self) -> str:
        """NAS 上同步根目录的 UNC 路径"""
        # 将 sync_root 中的 / 替换为 \ 以兼容 Windows UNC 路径
        normalized_root = self.sync_root.replace("/", os.sep)
        return os.path.join(self.unc_path, normalized_root)

    @property
    def mount_unc(self) -> str:
        """挂载路径（盘符或 UNC）"""
        if self.mount_letter:
            return f"{self.mount_letter}\\"
        return self.unc_path

    def to_dict(self) -> dict:
        return {
            "host": self.host,
            "share": self.share,
            "username": self.username,
            "password": "***" if self.password else "",
            "sync_root": self.sync_root,
            "auto_sync": self.auto_sync,
            "sync_history": self.sync_history,
            "sync_reports": self.sync_reports,
            "sync_interval_minutes": self.sync_interval_minutes,
            "max_retries": self.max_retries,
            "retry_base_seconds": self.retry_base_seconds,
            "health_check_interval": self.health_check_interval,
            "cache_ttl_hours": self.cache_ttl_hours,
            "mount_letter": self.mount_letter,
        }


@dataclass
class SyncRecord:
    """单次同步记录"""
    timestamp: str
    direction: str
    files_synced: int
    files_failed: int
    details: List[str] = field(default_factory=list)


@dataclass
class CacheEntry:
    """离线缓存条目"""
    operation: str               # "push_reports" | "push_history" | "push_file"
    payload: dict
    created_at: str
    attempts: int = 0


# ============ 本地缓存 ============

class LocalCache:
    """离线模式本地缓存 —— 当 NAS 不可用时暂存待同步数据"""

    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.pending_file = self.cache_dir / "pending_sync.json"

    def add_pending(self, operation: str, payload: dict):
        """添加待同步操作到缓存队列"""
        entry = CacheEntry(
            operation=operation,
            payload=payload,
            created_at=datetime.now().isoformat(),
        )
        pending = self._load_pending()
        pending.append(entry)
        self._save_pending(pending)

    def get_pending(self) -> List[CacheEntry]:
        """获取所有待同步操作"""
        return self._load_pending()

    def remove_pending(self, entry: CacheEntry):
        """移除已完成的待同步操作"""
        pending = self._load_pending()
        pending = [e for e in pending
                   if e.created_at != entry.created_at or e.operation != entry.operation]
        self._save_pending(pending)

    def clear_pending(self):
        """清空待同步队列"""
        self._save_pending([])

    def has_pending(self) -> bool:
        return len(self._load_pending()) > 0

    def pending_count(self) -> int:
        return len(self._load_pending())

    def _load_pending(self) -> List[CacheEntry]:
        if self.pending_file.exists():
            try:
                data = json.loads(self.pending_file.read_text(encoding="utf-8"))
                return [CacheEntry(**item) for item in data]
            except Exception:
                pass
        return []

    def _save_pending(self, entries: List[CacheEntry]):
        data = [{"operation": e.operation, "payload": e.payload,
                 "created_at": e.created_at, "attempts": e.attempts} for e in entries]
        self.pending_file.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                     encoding="utf-8")


# ============ SMB 同步服务 ============

class SmbSyncService:
    """
    SMB NAS 同步服务

    生命周期:
      1. connect()     — 建立 SMB 认证会话（net use）
      2. sync_*()      — 执行同步操作（通过 UNC 路径读写）
      3. disconnect()  — 关闭会话
      4. 内置健康监控线程，断线自动重连
    """

    # 信号回调类型
    StatusCallback = Callable[[SyncStatus, str], None]  # status, message

    def __init__(self, config: SyncConfig = None, cache_dir: str = None):
        self.config = config or SyncConfig()
        self._status = SyncStatus.DISCONNECTED
        self._session_id: Optional[str] = None
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._health_thread: Optional[threading.Thread] = None
        self._sync_thread: Optional[threading.Thread] = None
        self._on_status: Optional[SmbSyncService.StatusCallback] = None
        self._on_sync_complete: Optional[Callable[[SyncRecord], None]] = None
        self._connect_failures = 0
        self._last_connected: Optional[datetime] = None
        self._last_sync: Optional[datetime] = None
        self._sync_log: List[SyncRecord] = []

        # 本地缓存
        cache_path = Path(cache_dir) if cache_dir else Path(__file__).parent / "local_cache"
        self.cache = LocalCache(cache_path)

    # -------- 回调设置 --------
    def set_on_status(self, callback: StatusCallback):
        self._on_status = callback

    def set_on_sync_complete(self, callback: Callable[[SyncRecord], None]):
        self._on_sync_complete = callback

    def _notify_status(self, status: SyncStatus, message: str = ""):
        self._status = status
        if self._on_status:
            try:
                self._on_status(status, message)
            except Exception:
                pass

    # ============ 连接管理 ============

    def connect(self) -> bool:
        """建立 SMB 认证会话"""
        with self._lock:
            if self._status == SyncStatus.CONNECTED:
                return True

            self._notify_status(SyncStatus.CONNECTING, "正在连接 NAS...")

            # 先用快速检查
            if self._test_unc_readable():
                self._status = SyncStatus.CONNECTED
                self._last_connected = datetime.now()
                self._connect_failures = 0
                self._notify_status(SyncStatus.CONNECTED,
                                    f"NAS 已连接 ({self.config.unc_path})")
                return True

            # 创建新的 SMB 认证会话
            success = self._mount_smb()
            if success:
                self._status = SyncStatus.CONNECTED
                self._last_connected = datetime.now()
                self._connect_failures = 0
                self._notify_status(SyncStatus.CONNECTED,
                                    f"NAS 已连接 ({self.config.unc_path})")
            else:
                self._connect_failures += 1
                self._notify_status(SyncStatus.ERROR, "NAS 连接失败")
            return success

    def disconnect(self):
        """断开 SMB 会话"""
        with self._lock:
            self._unmount_smb()
            self._status = SyncStatus.DISCONNECTED
            self._notify_status(SyncStatus.DISCONNECTED, "NAS 已断开")

    def is_connected(self) -> bool:
        """检查当前连接状态"""
        return self._test_unc_readable()

    def health_check(self) -> bool:
        """单次健康检查"""
        connected = self._test_unc_readable()
        if connected:
            if self._status != SyncStatus.CONNECTED:
                self._status = SyncStatus.CONNECTED
                self._last_connected = datetime.now()
                self._connect_failures = 0
                self._notify_status(SyncStatus.CONNECTED, "NAS 连接已恢复")
            return True
        else:
            if self._status == SyncStatus.CONNECTED:
                auto_reconnect = self.config.auto_sync
                self._notify_status(
                    SyncStatus.DISCONNECTED if not auto_reconnect else SyncStatus.CONNECTING,
                    "NAS 连接断开" if not auto_reconnect else "NAS 连接断开，尝试重连..."
                )
                if auto_reconnect:
                    threading.Thread(target=self._reconnect_loop, daemon=True).start()
            return False

    # ============ SMB 挂载/卸载 ============

    def _mount_smb(self) -> bool:
        """挂载 SMB 共享（Windows net use）"""
        unc = self.config.unc_path

        # 如果指定了盘符，先断开旧连接
        if self.config.mount_letter:
            try:
                subprocess.run(
                    ["net", "use", self.config.mount_letter, "/delete", "/y"],
                    capture_output=True, timeout=10, check=False
                )
            except Exception:
                pass

        # 构建 net use 命令
        if self.config.mount_letter:
            cmd = [
                "net", "use", self.config.mount_letter,
                unc,
                f"/user:{self.config.username}",
                self.config.password,
                "/persistent:no",
            ]
        else:
            # 不指定盘符，仅建立认证会话
            cmd = [
                "net", "use", unc,
                f"/user:{self.config.username}",
                self.config.password,
                "/persistent:no",
            ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30, check=False,
                # 隐藏密码在日志中
            )
            stdout = result.stdout or ""
            stderr = result.stderr or ""

            if result.returncode == 0:
                self._session_id = datetime.now().isoformat()
                # 验证连接
                if self._test_unc_readable():
                    return True
                else:
                    print(f"[SMB] net use 成功但无法访问 UNC 路径: {unc}")
                    return False
            else:
                # 检查是否是已连接的提示（也算成功）
                combined = stdout + stderr
                if "已连接" in combined or "already" in combined.lower():
                    self._session_id = datetime.now().isoformat()
                    return self._test_unc_readable()

                # 提取友好的错误信息
                error_msg = stderr.strip() or stdout.strip()
                if "1219" in error_msg:
                    # 多次连接同一资源的冲突，先断开再重试
                    self._unmount_smb()
                    time.sleep(1)
                    return self._mount_smb_retry()
                print(f"[SMB] mount 失败: {error_msg[:200]}")
                return False

        except subprocess.TimeoutExpired:
            print("[SMB] net use 命令超时")
            return False
        except Exception as e:
            print(f"[SMB] net use 异常: {e}")
            return False

    def _mount_smb_retry(self) -> bool:
        """断开后重试挂载"""
        try:
            subprocess.run(
                ["net", "use", self.config.unc_path, "/delete", "/y"],
                capture_output=True, timeout=10, check=False
            )
        except Exception:
            pass
        time.sleep(2)
        return self._mount_smb()

    def _unmount_smb(self):
        """卸载 SMB 共享"""
        try:
            target = self.config.mount_letter if self.config.mount_letter else self.config.unc_path
            subprocess.run(
                ["net", "use", target, "/delete", "/y"],
                capture_output=True, timeout=10, check=False
            )
        except Exception:
            pass
        self._session_id = None

    def _test_unc_readable(self) -> bool:
        """
        测试 UNC 路径是否可访问（仅检查根目录存在性，不产生日志噪音）
        使用多种方式验证，提高准确率。
        """
        unc = self.config.unc_path
        try:
            # 方式1: Path.exists()
            p = Path(unc)
            if p.exists() and p.is_dir():
                return True
        except (OSError, PermissionError):
            pass
        except Exception:
            pass

        try:
            # 方式2: os.listdir()
            os.listdir(unc)
            return True
        except (FileNotFoundError, NotADirectoryError):
            pass  # UNC 可访问但根目录为空 或 路径不是目录
        except (OSError, PermissionError):
            return False
        except Exception:
            pass

        # 方式3: 检查同步根目录
        sync_unc = os.path.join(unc, self.config.sync_root)
        try:
            p = Path(sync_unc)
            if p.exists() and p.is_dir():
                return True
        except Exception:
            pass

        return False

    # ============ 重连逻辑 ============

    def _reconnect_loop(self):
        """指数退避重连循环（在后台线程中运行）"""
        for attempt in range(1, self.config.max_retries + 1):
            if self._stop_event.is_set():
                return
            if self._test_unc_readable():
                self._status = SyncStatus.CONNECTED
                self._last_connected = datetime.now()
                self._connect_failures = 0
                self._notify_status(SyncStatus.CONNECTED, "NAS 重连成功")
                # 重连后自动刷新待同步队列
                self._flush_pending_cache()
                return

            delay = self.config.retry_base_seconds * (2 ** (attempt - 1))
            delay = min(delay, 120)  # 最多等 2 分钟
            self._notify_status(SyncStatus.CONNECTING,
                                f"NAS 重连中 ({attempt}/{self.config.max_retries}), 下一次 {delay:.0f}s 后...")
            time.sleep(delay)

        self._notify_status(SyncStatus.ERROR,
                            f"NAS 重连失败（已尝试 {self.config.max_retries} 次）")

    def _flush_pending_cache(self):
        """连接恢复后刷新离线缓存中的待同步数据"""
        if not self.cache.has_pending():
            return
        pending = self.cache.get_pending()
        for entry in pending:
            try:
                if entry.operation == "push_reports":
                    self.push_reports(entry.payload.get("report_ids"))
                elif entry.operation == "push_history":
                    self.push_history(entry.payload.get("history_items"))
                elif entry.operation == "push_config":
                    self.push_config(entry.payload.get("config_data"))
                self.cache.remove_pending(entry)
            except Exception as e:
                print(f"[SMB] 刷新缓存失败 [{entry.operation}]: {e}")
                entry.attempts += 1
                if entry.attempts >= 3:
                    self.cache.remove_pending(entry)

    # ============ 基础文件操作 ============

    def _ensure_remote_dir(self, remote_rel_path: str) -> bool:
        """确保 NAS 上的目录存在"""
        full_path = os.path.join(self.config.unc_path, remote_rel_path)
        try:
            Path(full_path).mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            print(f"[SMB] 创建远程目录失败 {remote_rel_path}: {e}")
            return False

    def upload_file(self, local_path: str, remote_rel_path: str) -> bool:
        """上传单个文件到 NAS"""
        full_remote = os.path.join(self.config.unc_path, remote_rel_path)
        try:
            remote_dir = os.path.dirname(full_remote)
            Path(remote_dir).mkdir(parents=True, exist_ok=True)
            shutil.copy2(local_path, full_remote)
            # 校验
            if self._verify_copy(local_path, full_remote):
                return True
            return False
        except Exception as e:
            print(f"[SMB] 上传失败 {local_path} → {remote_rel_path}: {e}")
            return False

    def download_file(self, remote_rel_path: str, local_path: str) -> bool:
        """从 NAS 下载单个文件"""
        full_remote = os.path.join(self.config.unc_path, remote_rel_path)
        try:
            local_dir = os.path.dirname(local_path)
            Path(local_dir).mkdir(parents=True, exist_ok=True)
            shutil.copy2(full_remote, local_path)
            return Path(local_path).exists()
        except Exception as e:
            print(f"[SMB] 下载失败 {remote_rel_path} → {local_path}: {e}")
            return False

    def list_remote_dir(self, remote_rel_path: str) -> List[str]:
        """列出 NAS 上指定目录的内容（仅文件名）"""
        full_path = os.path.join(self.config.unc_path, remote_rel_path)
        try:
            return os.listdir(full_path)
        except FileNotFoundError:
            return []
        except Exception as e:
            print(f"[SMB] 列表目录失败 {remote_rel_path}: {e}")
            return []

    def delete_remote(self, remote_rel_path: str) -> bool:
        """删除 NAS 上的文件或目录"""
        full_path = os.path.join(self.config.unc_path, remote_rel_path)
        try:
            p = Path(full_path)
            if p.is_dir():
                shutil.rmtree(full_path)
            elif p.is_file():
                p.unlink()
            return True
        except Exception as e:
            print(f"[SMB] 删除失败 {remote_rel_path}: {e}")
            return False

    def remote_exists(self, remote_rel_path: str) -> bool:
        """检查 NAS 上路径是否存在"""
        full_path = os.path.join(self.config.unc_path, remote_rel_path)
        try:
            return Path(full_path).exists()
        except Exception:
            return False

    @staticmethod
    def _verify_copy(src: str, dst: str) -> bool:
        """通过文件大小校验拷贝完整性"""
        try:
            return Path(src).stat().st_size == Path(dst).stat().st_size
        except Exception:
            return False

    # ============ 报告同步 ============

    def push_reports(self, report_ids: List[str] = None,
                     local_output_dir: str = None) -> SyncRecord:
        """
        推送本地报告到 NAS

        Args:
            report_ids: 要推送的报告 ID 列表，None 表示全部
            local_output_dir: 本地 output 目录路径
        """
        details = []
        synced = 0
        failed = 0

        local_dir = Path(local_output_dir) if local_output_dir else Path("./output")
        if not local_dir.exists():
            return SyncRecord(
                timestamp=datetime.now().isoformat(),
                direction="push",
                files_synced=0, files_failed=0,
                details=["本地 output 目录不存在"]
            )

        # 确定要同步的报告
        if report_ids:
            targets = [(rid, local_dir / rid) for rid in report_ids
                       if (local_dir / rid).exists()]
        else:
            targets = [(d.name, d) for d in sorted(local_dir.iterdir(), reverse=True)
                       if d.is_dir()]

        remote_reports_dir = os.path.join(self.config.sync_root, "reports")

        for report_id, report_path in targets:
            try:
                remote_report_dir = os.path.join(remote_reports_dir, report_id)

                # 清空远程目录再重新上传（确保一致性）
                if self.remote_exists(remote_report_dir):
                    self.delete_remote(remote_report_dir)

                self._ensure_remote_dir(remote_report_dir)

                # 上传报告中的所有文件
                for file_path in report_path.iterdir():
                    if file_path.is_file():
                        remote_file = os.path.join(remote_report_dir, file_path.name)
                        if self.upload_file(str(file_path), remote_file):
                            synced += 1
                        else:
                            failed += 1
                            details.append(f"上传失败: {file_path.name}")

                details.append(f"✓ 报告 {report_id} 已同步")

            except Exception as e:
                failed += 1
                details.append(f"✗ 报告 {report_id} 同步失败: {e}")

        record = SyncRecord(
            timestamp=datetime.now().isoformat(),
            direction="push",
            files_synced=synced,
            files_failed=failed,
            details=details,
        )
        self._sync_log.append(record)
        self._last_sync = datetime.now()

        if self._on_sync_complete:
            self._on_sync_complete(record)
        return record

    def pull_reports(self, local_output_dir: str = None) -> SyncRecord:
        """
        从 NAS 拉取报告到本地

        只拉取本地不存在或 NAS 更新的报告
        """
        details = []
        synced = 0
        failed = 0

        local_dir = Path(local_output_dir) if local_output_dir else Path("./output")
        local_dir.mkdir(parents=True, exist_ok=True)

        remote_reports_dir = os.path.join(self.config.sync_root, "reports")
        report_names = self.list_remote_dir(remote_reports_dir)

        for report_id in report_names:
            try:
                remote_report_dir = os.path.join(remote_reports_dir, report_id)
                local_report_dir = local_dir / report_id

                # 检查本地是否已有且更新
                if local_report_dir.exists():
                    remote_md = os.path.join(remote_report_dir, "report.md")
                    local_md = local_report_dir / "report.md"
                    if local_md.exists() and self.remote_exists(remote_md):
                        try:
                            remote_mtime = Path(remote_md).stat().st_mtime
                            local_mtime = local_md.stat().st_mtime
                            if local_mtime >= remote_mtime:
                                details.append(f"- 报告 {report_id} 已是最新")
                                continue
                        except Exception:
                            pass

                # 下载报告
                remote_files = self.list_remote_dir(remote_report_dir)
                for fname in remote_files:
                    remote_file = os.path.join(remote_report_dir, fname)
                    local_file = local_report_dir / fname
                    local_report_dir.mkdir(parents=True, exist_ok=True)
                    if self.download_file(remote_file, str(local_file)):
                        synced += 1
                    else:
                        failed += 1
                        details.append(f"下载失败: {fname}")

                details.append(f"✓ 报告 {report_id} 已拉取")

            except Exception as e:
                failed += 1
                details.append(f"✗ 报告 {report_id} 拉取失败: {e}")

        record = SyncRecord(
            timestamp=datetime.now().isoformat(),
            direction="pull",
            files_synced=synced,
            files_failed=failed,
            details=details,
        )
        self._sync_log.append(record)
        self._last_sync = datetime.now()

        if self._on_sync_complete:
            self._on_sync_complete(record)
        return record

    # ============ 历史记录同步 ============

    def push_history(self, history_items: List[dict]) -> SyncRecord:
        """推送处理历史到 NAS"""
        remote_history_path = os.path.join(
            self.config.sync_root, "history", f"history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )

        try:
            self._ensure_remote_dir(os.path.join(self.config.sync_root, "history"))
            full_remote = os.path.join(self.config.unc_path, remote_history_path)

            with open(full_remote, "w", encoding="utf-8") as f:
                json.dump({
                    "timestamp": datetime.now().isoformat(),
                    "source": "desktop_app",
                    "items": history_items,
                }, f, ensure_ascii=False, indent=2)

            record = SyncRecord(
                timestamp=datetime.now().isoformat(),
                direction="push",
                files_synced=1, files_failed=0,
                details=[f"✓ 处理历史已推送 ({len(history_items)} 条)"],
            )
        except Exception as e:
            record = SyncRecord(
                timestamp=datetime.now().isoformat(),
                direction="push",
                files_synced=0, files_failed=1,
                details=[f"✗ 历史推送失败: {e}"],
            )

        self._sync_log.append(record)
        self._last_sync = datetime.now()
        if self._on_sync_complete:
            self._on_sync_complete(record)
        return record

    def pull_history(self) -> List[dict]:
        """从 NAS 拉取所有处理历史"""
        remote_history_dir = os.path.join(self.config.sync_root, "history")
        all_items = []

        try:
            history_files = self.list_remote_dir(remote_history_dir)
            for fname in sorted(history_files, reverse=True):
                if not fname.endswith(".json"):
                    continue
                remote_file = os.path.join(remote_history_dir, fname)
                full_remote = os.path.join(self.config.unc_path, remote_file)
                try:
                    data = json.loads(Path(full_remote).read_text(encoding="utf-8"))
                    items = data.get("items", [])
                    for item in items:
                        item["_source"] = "nas"
                    all_items.extend(items)
                except Exception as e:
                    print(f"[SMB] 读取历史文件失败 {fname}: {e}")

        except Exception as e:
            print(f"[SMB] 拉取历史失败: {e}")

        return all_items

    # ============ 配置同步 ============

    def push_config(self, config_data: dict) -> SyncRecord:
        """推送配置到 NAS"""
        remote_config_path = os.path.join(self.config.sync_root, "shared_config.json")
        try:
            self._ensure_remote_dir(self.config.sync_root)
            full_remote = os.path.join(self.config.unc_path, remote_config_path)

            with open(full_remote, "w", encoding="utf-8") as f:
                json.dump({
                    "updated_at": datetime.now().isoformat(),
                    "config": config_data,
                }, f, ensure_ascii=False, indent=2)

            record = SyncRecord(
                timestamp=datetime.now().isoformat(),
                direction="push",
                files_synced=1, files_failed=0,
                details=["✓ 配置已共享到 NAS"],
            )
        except Exception as e:
            record = SyncRecord(
                timestamp=datetime.now().isoformat(),
                direction="push",
                files_synced=0, files_failed=1,
                details=[f"✗ 配置推送失败: {e}"],
            )

        self._sync_log.append(record)
        return record

    def pull_config(self) -> Optional[dict]:
        """从 NAS 拉取共享配置"""
        remote_config_path = os.path.join(self.config.sync_root, "shared_config.json")
        full_remote = os.path.join(self.config.unc_path, remote_config_path)
        try:
            if Path(full_remote).exists():
                data = json.loads(Path(full_remote).read_text(encoding="utf-8"))
                return data.get("config")
        except Exception as e:
            print(f"[SMB] 拉取配置失败: {e}")
        return None

    # ============ 全量同步 ============

    def sync_all(self, local_output_dir: str = None,
                 history_items: List[dict] = None,
                 config_data: dict = None,
                 direction: SyncDirection = SyncDirection.BIDIRECTIONAL) -> SyncRecord:
        """
        全量双向同步

        根据配置自动执行推送 + 拉取
        """
        if not self.is_connected():
            # 离线模式：缓存到本地
            self._notify_status(SyncStatus.DISCONNECTED, "NAS 不可用，数据已缓存到本地")
            if history_items and self.config.sync_history:
                self.cache.add_pending("push_history", {"history_items": history_items})
            return SyncRecord(
                timestamp=datetime.now().isoformat(),
                direction=direction.value,
                files_synced=0, files_failed=0,
                details=["NAS 不可用，数据已缓存到本地"]
            )

        self._notify_status(SyncStatus.SYNCING, "正在同步...")

        all_details = []
        total_synced = 0
        total_failed = 0

        try:
            # 推送
            if direction in (SyncDirection.PUSH, SyncDirection.BIDIRECTIONAL):
                if self.config.sync_reports:
                    record = self.push_reports(local_output_dir=local_output_dir)
                    total_synced += record.files_synced
                    total_failed += record.files_failed
                    all_details.extend(record.details)

                if self.config.sync_history and history_items:
                    record = self.push_history(history_items)
                    total_synced += record.files_synced
                    total_failed += record.files_failed
                    all_details.extend(record.details)

                if config_data:
                    record = self.push_config(config_data)
                    total_synced += record.files_synced
                    total_failed += record.files_failed
                    all_details.extend(record.details)

            # 拉取
            if direction in (SyncDirection.PULL, SyncDirection.BIDIRECTIONAL):
                if self.config.sync_reports:
                    record = self.pull_reports(local_output_dir=local_output_dir)
                    total_synced += record.files_synced
                    total_failed += record.files_failed
                    all_details.extend(record.details)

            self._notify_status(SyncStatus.CONNECTED,
                                f"同步完成: {total_synced} 成功, {total_failed} 失败")

        except Exception as e:
            self._notify_status(SyncStatus.ERROR, f"同步异常: {e}")
            all_details.append(f"✗ 同步异常: {e}")
            total_failed += 1

        record = SyncRecord(
            timestamp=datetime.now().isoformat(),
            direction=direction.value,
            files_synced=total_synced,
            files_failed=total_failed,
            details=all_details,
        )
        return record

    # ============ 后台线程 ============

    def start_health_monitor(self):
        """启动后台健康监控线程"""
        if self._health_thread and self._health_thread.is_alive():
            return
        self._stop_event.clear()
        self._health_thread = threading.Thread(target=self._health_monitor_loop, daemon=True)
        self._health_thread.start()

    def stop_health_monitor(self):
        """停止后台线程"""
        self._stop_event.set()
        if self._health_thread:
            self._health_thread.join(timeout=5)

    def _health_monitor_loop(self):
        """健康监控循环"""
        while not self._stop_event.is_set():
            self._stop_event.wait(self.config.health_check_interval)
            if not self._stop_event.is_set():
                try:
                    self.health_check()
                except Exception:
                    pass

    def start_periodic_sync(self, local_output_dir: str,
                            get_history: Callable[[], List[dict]] = None):
        """启动周期性同步线程"""
        if self._sync_thread and self._sync_thread.is_alive():
            return
        self._sync_thread = threading.Thread(
            target=self._periodic_sync_loop,
            args=(local_output_dir, get_history),
            daemon=True,
        )
        self._sync_thread.start()

    def _periodic_sync_loop(self, local_output_dir: str,
                            get_history: Callable[[], List[dict]] = None):
        """周期性同步循环"""
        while not self._stop_event.is_set():
            self._stop_event.wait(self.config.sync_interval_minutes * 60)
            if not self._stop_event.is_set() and self.is_connected():
                try:
                    history_items = get_history() if get_history else None
                    self.sync_all(
                        local_output_dir=local_output_dir,
                        history_items=history_items,
                    )
                except Exception as e:
                    print(f"[SMB] 周期性同步异常: {e}")

    # ============ 状态查询 ============

    def get_status(self) -> dict:
        """获取当前同步状态快照"""
        return {
            "status": self._status.value,
            "connected": self.is_connected(),
            "last_connected": self._last_connected.isoformat() if self._last_connected else None,
            "last_sync": self._last_sync.isoformat() if self._last_sync else None,
            "connect_failures": self._connect_failures,
            "pending_cache": self.cache.pending_count(),
            "recent_logs": [
                {"timestamp": r.timestamp, "direction": r.direction,
                 "synced": r.files_synced, "failed": r.files_failed}
                for r in self._sync_log[-10:]
            ],
        }


# ============ 导出便捷函数 ============

def create_default_sync_service(cache_dir: str = None) -> SmbSyncService:
    """
    使用默认配置创建同步服务实例
    NAS: 192.168.0.79, 共享: maker, 账号: maker, 密码: maker
    """
    config = SyncConfig(
        host="192.168.0.79",
        share="maker",
        username="maker",
        password="maker",
        sync_root="CLAW_CHANGE_RECORDS/08_shared_data",
        auto_sync=True,
        sync_reports=True,
        sync_history=True,
    )
    return SmbSyncService(config=config, cache_dir=cache_dir)
