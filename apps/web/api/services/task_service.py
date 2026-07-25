"""
任务管理服务 - 管理异步 OCR 任务状态与处理历史

将原本分散在 main.py 中的全局变量集中管理：
  - task_store: 异步任务状态存储（内存中）
  - processing_history: 处理历史记录（内存 + SQLite 持久化）
"""
import uuid
import sqlite3
import atexit
import threading
from collections import OrderedDict, deque
from typing import Dict, List, Optional
from datetime import datetime
from threading import Lock

from apps.web.api.logger import setup_logger
from apps.web.api.config import settings

logger = setup_logger("TaskService")


# 模块级 DB_PATH，保持向后兼容（测试可能 monkeypatch 此变量）
DB_PATH = settings.get_output_path() / "processing_history.db"

# task_store 最大条数（超出时 LRU 淘汰）
_MAX_TASK_STORE = 200
# 历史记录内存缓存上限（deque maxlen，超出自动淘汰尾部；DB 保留全量）
_MAX_HISTORY = 200
# 任务完成后 image_data 自动清理延迟（秒）
_IMAGE_DATA_CLEANUP_DELAY = 300


def _get_db_path():
    """动态获取数据库路径（L23: 支持运行时 output_dir 变更）"""
    return settings.get_db_path()


def _init_db():
    """初始化 SQLite 数据库表

    启用 WAL（Write-Ahead Logging）模式以提升并发读写性能：
    - 读操作不阻塞写操作
    - 写操作不阻塞读操作
    - 适合高频读取、低频写入的场景
    """
    db_path = _get_db_path()
    db = sqlite3.connect(str(db_path), check_same_thread=False)
    # 启用 WAL 模式，提升并发性能
    db.execute("PRAGMA journal_mode=WAL")
    # 设置忙等待超时（毫秒），避免并发写入时立即报错
    db.execute("PRAGMA busy_timeout=5000")
    db.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id TEXT PRIMARY KEY,
            file_id TEXT,
            filename TEXT,
            timestamp TEXT,
            success INTEGER,
            processing_time REAL,
            images_count INTEGER,
            markdown_length INTEGER,
            report_dir TEXT,
            model TEXT,
            total_pages INTEGER
        )
    """)
    # 性能优化：为常用查询字段建立索引
    # idx_history_timestamp: 加速 ORDER BY timestamp DESC（历史记录加载、分页）
    # idx_history_file_id:   加速按 file_id 查询（任务关联历史记录）
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_history_timestamp "
        "ON history(timestamp DESC)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_history_file_id "
        "ON history(file_id)"
    )
    db.commit()
    return db


class TaskService:
    """任务与历史记录状态管理"""

    def __init__(self):
        self._lock = Lock()
        # S10: 使用 OrderedDict 实现 LRU 淘汰，限制最大条数
        self._task_store: "OrderedDict[str, dict]" = OrderedDict()
        # 性能优化：使用 deque(maxlen=...) 替代 list
        #   - appendleft() 为 O(1)，而 list.insert(0, item) 为 O(n)
        #   - maxlen 自动淘汰旧条目，无需手动 pop
        #   - 引用模块级 _MAX_HISTORY 常量，测试可通过 monkeypatch 调整
        self._history: "deque[dict]" = deque(maxlen=_MAX_HISTORY)
        self._max_history = _MAX_HISTORY
        self._db: Optional[sqlite3.Connection] = None
        # S10: image_data 延迟清理定时器
        self._cleanup_timers: Dict[str, threading.Timer] = {}
        # 并发轮询互斥：防止同一 task_id 被多个请求同时处理
        self._active_polls: set = set()
        self._init_history_from_db()

    # ---- 资源管理 ----

    def close(self):
        """显式关闭 SQLite 连接，释放文件句柄"""
        with self._lock:
            # 取消所有待执行的清理定时器
            for timer in self._cleanup_timers.values():
                timer.cancel()
            self._cleanup_timers.clear()

            if self._db is not None:
                try:
                    self._db.close()
                    # atexit 时日志流可能已关闭，用 print 替代 logger 避免报错
                    print("[TaskService] SQLite 连接已关闭", flush=True)
                except Exception as e:
                    print(f"[TaskService] 关闭 SQLite 连接时出错: {e}", flush=True)
                finally:
                    self._db = None

    # ---- 任务存储 ----

    def get_task(self, task_id: str) -> Optional[dict]:
        """S11: 返回字典的浅拷贝，防止外部修改内部状态"""
        with self._lock:
            task_info = self._task_store.get(task_id)
            if task_info is None:
                return None
            return dict(task_info)

    def set_task(self, task_id: str, data: dict):
        """S10: 设置任务并维护 LRU 淘汰"""
        with self._lock:
            self._task_store[task_id] = data
            self._task_store.move_to_end(task_id)
            # LRU 淘汰：超出上限时删除最旧的条目
            while len(self._task_store) > _MAX_TASK_STORE:
                old_task_id, old_data = self._task_store.popitem(last=False)
                # 清理被淘汰任务的 image_data 和定时器
                self._cancel_cleanup_timer(old_task_id)

    def update_task(self, task_id: str, **kwargs):
        """更新任务字段（S11: 在锁内操作副本后写回）"""
        with self._lock:
            if task_id in self._task_store:
                self._task_store[task_id].update(kwargs)
                self._task_store.move_to_end(task_id)

    def has_task(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._task_store

    def all_tasks(self) -> Dict[str, dict]:
        with self._lock:
            return dict(self._task_store)

    def remove_task(self, task_id: str):
        """显式移除任务"""
        with self._lock:
            self._task_store.pop(task_id, None)
            self._cancel_cleanup_timer(task_id)

    # ---- 并发轮询互斥 ----

    def try_acquire_poll(self, task_id: str) -> bool:
        """尝试获取任务的独占轮询权。

        防止同一 task_id 被多个并发请求同时处理（TOCTOU 竞态防护）。
        返回 True 表示获取成功，False 表示已有其他请求在处理。
        """
        with self._lock:
            if task_id in self._active_polls:
                return False
            self._active_polls.add(task_id)
            return True

    def release_poll(self, task_id: str):
        """释放任务的独占轮询权。"""
        with self._lock:
            self._active_polls.discard(task_id)

    # ---- image_data 延迟清理 (S10) ----

    def _cancel_cleanup_timer(self, task_id: str):
        """取消指定任务的 image_data 清理定时器（须在锁内调用）"""
        timer = self._cleanup_timers.pop(task_id, None)
        if timer is not None:
            timer.cancel()

    def schedule_image_data_cleanup(self, task_id: str, delay: float = _IMAGE_DATA_CLEANUP_DELAY):
        """S10: 任务完成后延迟清理 image_data，防止内存驻留

        在 delay 秒后自动移除 task_info 中的 image_data 大字段。
        """
        def _cleanup():
            with self._lock:
                self._cleanup_timers.pop(task_id, None)
                task_info = self._task_store.get(task_id)
                if task_info is not None:
                    task_info.pop("image_data", None)
                    logger.debug(f"image_data 已自动清理: task_id={task_id}")

        timer = threading.Timer(delay, _cleanup)
        timer.daemon = True
        # 在锁内取消已有定时器并插入新定时器，确保线程安全
        with self._lock:
            self._cancel_cleanup_timer(task_id)
            self._cleanup_timers[task_id] = timer
        timer.start()

    # ---- 处理历史 ----

    def _ensure_db(self) -> sqlite3.Connection:
        if self._db is None:
            self._db = _init_db()
        return self._db

    def _init_history_from_db(self):
        """从 SQLite 加载历史记录到内存"""
        try:
            db = self._ensure_db()
            rows = db.execute(
                "SELECT * FROM history ORDER BY timestamp DESC LIMIT ?",
                (self._max_history,)
            ).fetchall()
            for row in rows:
                self._history.append({
                    "id": row[0],
                    "file_id": row[1],
                    "filename": row[2],
                    "timestamp": row[3],
                    "success": bool(row[4]),
                    "processing_time": row[5] or 0,
                    "images_count": row[6] or 0,
                    "markdown_length": row[7] or 0,
                    "report_id": row[8],
                    "model": row[9],
                    "total_pages": row[10] or 0,
                })
            if self._history:
                logger.info(f"从数据库加载了 {len(self._history)} 条历史记录")
        except Exception as e:
            logger.warning(f"加载历史记录失败（将使用空历史）: {e}")

    def add_history(self, item: dict):
        """添加历史记录（内存 + 数据库）

        M03: 数据库操作也纳入锁保护范围，防止竞态条件。
        """
        with self._lock:
            item.setdefault("id", uuid.uuid4().hex[:16])
            # deque.appendleft 为 O(1)，且 maxlen 自动淘汰旧条目
            self._history.appendleft(item)

            # 持久化到 SQLite（M03: 在锁内执行）
            try:
                db = self._ensure_db()
                db.execute(
                    """INSERT OR REPLACE INTO history
                       (id, file_id, filename, timestamp, success,
                        processing_time, images_count, markdown_length,
                        report_dir, model, total_pages)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        item["id"],
                        item.get("file_id"),
                        item.get("filename", ""),
                        item.get("timestamp", datetime.now().isoformat()),
                        1 if item.get("success") else 0,
                        item.get("processing_time", 0),
                        item.get("images_count", 0),
                        item.get("markdown_length", 0),
                        str(item.get("report_id", "")),
                        item.get("model", settings.paddleocr_model),
                        item.get("total_pages", 0),
                    ),
                )
                db.commit()
            except Exception as e:
                logger.warning(f"持久化历史记录失败: {e}")

    def get_history(self, limit: int = 50, offset: int = 0) -> List[dict]:
        """获取历史记录（最多 limit 条，从 offset 开始）"""
        with self._lock:
            # deque 不支持切片，需先转为 list（maxlen=200，转换开销可忽略）
            return list(self._history)[offset:offset + limit]

    def get_history_count(self) -> int:
        """获取历史记录总数（以 DB 为准，避免内存 deque maxlen 截断后 count 不一致）"""
        with self._lock:
            try:
                db = self._ensure_db()
                row = db.execute("SELECT COUNT(*) FROM history").fetchone()
                return row[0] if row else 0
            except Exception as e:
                logger.warning(f"查询历史记录总数失败，回退到内存计数: {e}")
                return len(self._history)

    def get_history_with_count(self, limit: int = 50, offset: int = 0) -> tuple:
        """性能优化：一次加锁同时获取分页数据和总数，避免两次锁竞争。

        返回: (items, total)
        """
        with self._lock:
            items = list(self._history)[offset:offset + limit]
            # total 以 DB 为准（内存 deque 有 maxlen 截断）
            try:
                db = self._ensure_db()
                row = db.execute("SELECT COUNT(*) FROM history").fetchone()
                total = row[0] if row else len(self._history)
            except Exception as e:
                logger.warning(f"查询历史记录总数失败，回退到内存计数: {e}")
                total = len(self._history)
            return items, total

    def delete_history(self, history_id: str) -> bool:
        """删除指定历史记录（内存 + 数据库）

        M03: 数据库操作也纳入锁保护范围。
        修复：即使内存 deque 已淘汰该记录，仍执行 DB DELETE，避免数据孤岛。
        """
        with self._lock:
            # 从内存中删除（deque 需按索引删除，不能重新赋值列表推导式）
            found_idx = None
            for i, h in enumerate(self._history):
                if h.get("id") == history_id:
                    found_idx = i
                    break
            if found_idx is not None:
                del self._history[found_idx]

            # 从数据库中删除（M03: 在锁内执行）
            # 即使内存未命中也执行 DB DELETE，避免"内存已淘汰但 DB 仍在"的孤岛
            try:
                db = self._ensure_db()
                cursor = db.execute("DELETE FROM history WHERE id = ?", (history_id,))
                db.commit()
                # 以 DB 实际删除行数为准（内存命中但 DB 已删会返回 0）
                return cursor.rowcount > 0 or found_idx is not None
            except Exception as e:
                logger.warning(f"从数据库删除历史记录失败: {e}")
                return found_idx is not None

    def batch_delete_history(self, history_ids: list[str]) -> int:
        """批量删除历史记录，返回成功删除数量

        M09: 使用单条 SQL ``DELETE FROM history WHERE id IN (...)`` 批量删除。
        修复：即使内存 deque 已淘汰部分记录，仍执行 DB DELETE，避免数据孤岛。
        """
        if not history_ids:
            return 0

        with self._lock:
            # 从内存中删除（deque 需按索引删除，倒序删除避免索引错位）
            id_set = set(history_ids)
            indices_to_remove = [
                i for i, h in enumerate(self._history) if h.get("id") in id_set
            ]
            for i in reversed(indices_to_remove):
                del self._history[i]
            in_memory_deleted = len(indices_to_remove)

            # M09: 使用单条 SQL 批量删除（在锁内执行）
            # DB 删除以 cursor.rowcount 为准，覆盖内存已淘汰但 DB 仍在的记录
            try:
                db = self._ensure_db()
                placeholders = ",".join("?" * len(history_ids))
                cursor = db.execute(
                    f"DELETE FROM history WHERE id IN ({placeholders})",
                    history_ids,
                )
                db.commit()
                # DB 实际删除数（可能 ≥ 内存删除数，因内存已淘汰部分记录）
                db_deleted = cursor.rowcount
                return max(db_deleted, in_memory_deleted)
            except Exception as e:
                logger.warning(f"批量删除历史记录失败: {e}")

            return in_memory_deleted


# 全局单例
task_service = TaskService()

# 注册进程退出时的清理回调
atexit.register(task_service.close)
