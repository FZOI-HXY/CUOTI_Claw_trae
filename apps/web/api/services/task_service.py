"""
任务管理服务 - 管理异步 OCR 任务状态与处理历史

将原本分散在 main.py 中的全局变量集中管理：
  - task_store: 异步任务状态存储（内存中）
  - processing_history: 处理历史记录（内存 + SQLite 持久化）
"""
import uuid
import sqlite3
from typing import Dict, List, Optional
from datetime import datetime
from threading import Lock

from apps.web.api.logger import setup_logger
from apps.web.api.config import settings

logger = setup_logger("TaskService")


DB_PATH = settings.get_output_path() / "processing_history.db"


def _init_db():
    """初始化 SQLite 数据库表"""
    db = sqlite3.connect(str(DB_PATH), check_same_thread=False)
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
    db.commit()
    return db


class TaskService:
    """任务与历史记录状态管理"""

    def __init__(self):
        self._lock = Lock()
        self._task_store: Dict[str, dict] = {}
        self._history: List[dict] = []
        self._max_history = 200
        self._db: Optional[sqlite3.Connection] = None
        self._init_history_from_db()

    # ---- 任务存储 ----

    def get_task(self, task_id: str) -> Optional[dict]:
        return self._task_store.get(task_id)

    def set_task(self, task_id: str, data: dict):
        self._task_store[task_id] = data

    def update_task(self, task_id: str, **kwargs):
        if task_id in self._task_store:
            self._task_store[task_id].update(kwargs)

    def has_task(self, task_id: str) -> bool:
        return task_id in self._task_store

    def all_tasks(self) -> Dict[str, dict]:
        return dict(self._task_store)

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
                    "report_dir": row[8],
                    "model": row[9],
                    "total_pages": row[10] or 0,
                })
            if self._history:
                logger.info(f"从数据库加载了 {len(self._history)} 条历史记录")
        except Exception as e:
            logger.warning(f"加载历史记录失败（将使用空历史）: {e}")

    def add_history(self, item: dict):
        """添加历史记录（内存 + 数据库）"""
        with self._lock:
            item.setdefault("id", uuid.uuid4().hex[:8])
            self._history.insert(0, item)
            if len(self._history) > self._max_history:
                self._history.pop()

        # 持久化到 SQLite
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
                    str(item.get("report_dir", "")),
                    item.get("model", settings.paddleocr_model),
                    item.get("total_pages", 0),
                ),
            )
            db.commit()
        except Exception as e:
            logger.warning(f"持久化历史记录失败: {e}")

    def get_history(self, limit: int = 50) -> List[dict]:
        """获取历史记录（最多 limit 条）"""
        return self._history[:limit]

    def get_history_count(self) -> int:
        return len(self._history)


# 全局单例
task_service = TaskService()
