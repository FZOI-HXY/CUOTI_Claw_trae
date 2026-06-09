"""
错题管理系统 - 独立桌面应用程序
完整复刻前端系统所有功能，不依赖浏览器

功能:
  1. 文件上传与队列管理（拖拽、文件夹、批量）
  2. 批量 OCR 处理（提交→轮询→结果）
  3. 报告管理（列表、查看、下载ZIP、删除）
  4. 处理历史记录
  5. 系统配置管理

技术栈: PyQt6 + httpx + markdown
API后端: 调用 FastAPI 后端 (需单独启动)
"""
import sys
import os
import json
import asyncio
import io
import base64
import tempfile
import zipfile
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QPushButton, QLabel, QLineEdit, QTextEdit,
    QFileDialog, QProgressBar, QTableWidget, QTableWidgetItem,
    QHeaderView, QSplitter, QFrame, QGroupBox, QFormLayout,
    QSpinBox, QComboBox, QMessageBox, QStatusBar, QMenuBar,
    QMenu, QListWidget, QListWidgetItem, QScrollArea, QGridLayout,
    QSizePolicy, QDialog, QDialogButtonBox,
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QSize, QUrl, QMimeData,
)
from PyQt6.QtGui import (
    QAction, QFont, QColor, QPalette, QPixmap, QImage,
    QPainter, QPen, QBrush, QDragEnterEvent, QDropEvent,
    QTextCursor, QTextCharFormat, QSyntaxHighlighter, QFontMetrics,
)
import httpx
import re

# SMB NAS 跨网段同步
from smb_sync import (
    SmbSyncService, SyncConfig, SyncDirection, SyncStatus,
    create_default_sync_service, SyncRecord,
)

# ============ 样式表 ============
DARK_STYLE = """
QMainWindow {
    background-color: #0a0e17;
}
QWidget {
    background-color: #0a0e17;
    color: #e8ecf1;
    font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
    font-size: 13px;
}
QTabWidget::pane {
    border: 1px solid rgba(255,255,255,0.06);
    background-color: #111827;
    border-radius: 8px;
}
QTabWidget::tab-bar { left: 8px; }
QTabBar::tab {
    background-color: transparent;
    color: #8b95a8;
    padding: 10px 20px;
    border: none;
    border-bottom: 2px solid transparent;
    font-weight: 500;
}
QTabBar::tab:selected {
    color: #f59e0b;
    border-bottom: 2px solid #f59e0b;
}
QTabBar::tab:hover { color: #e8ecf1; }
QPushButton {
    background-color: #1a2235;
    color: #e8ecf1;
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 6px;
    padding: 8px 18px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #1f2a40;
    border-color: #f59e0b;
}
QPushButton:pressed { background-color: #162032; }
QPushButton#primaryBtn {
    background-color: #f59e0b;
    color: #0a0e17;
    border: none;
}
QPushButton#primaryBtn:hover { background-color: #fbbf24; }
QPushButton#dangerBtn {
    background-color: #ef4444;
    color: #ffffff;
    border: none;
}
QPushButton#dangerBtn:hover { background-color: #dc2626; }
QPushButton#ghostBtn {
    background-color: transparent;
    border: 1px solid rgba(255,255,255,0.1);
}
QPushButton#ghostBtn:hover {
    background-color: rgba(255,255,255,0.05);
    border-color: rgba(255,255,255,0.2);
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #1a2235;
    color: #e8ecf1;
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 6px;
    padding: 8px 12px;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #f59e0b;
}
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background-color: #1a2235;
    color: #e8ecf1;
    selection-background-color: rgba(245,158,11,0.2);
}
QProgressBar {
    background-color: #1a2235;
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #f59e0b, stop:1 #fbbf24);
    border-radius: 4px;
}
QTableWidget {
    background-color: #111827;
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px;
    gridline-color: rgba(255,255,255,0.04);
}
QTableWidget::item {
    padding: 8px;
    border-bottom: 1px solid rgba(255,255,255,0.04);
}
QTableWidget::item:selected {
    background-color: rgba(245,158,11,0.15);
}
QHeaderView::section {
    background-color: #1a2235;
    color: #8b95a8;
    padding: 10px 12px;
    border: none;
    border-bottom: 1px solid rgba(255,255,255,0.06);
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
}
QTextEdit {
    background-color: #111827;
    color: #e8ecf1;
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px;
    padding: 12px;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 13px;
}
QScrollBar:vertical {
    background: transparent;
    width: 8px;
}
QScrollBar::handle:vertical {
    background: rgba(255,255,255,0.1);
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: rgba(255,255,255,0.2); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: transparent;
    height: 8px;
}
QScrollBar::handle:horizontal {
    background: rgba(255,255,255,0.1);
    border-radius: 4px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover { background: rgba(255,255,255,0.2); }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QGroupBox {
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 10px;
    margin-top: 16px;
    padding: 20px 16px 16px 16px;
    font-weight: 600;
    color: #e8ecf1;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 16px;
    padding: 0 8px;
}
QStatusBar {
    background-color: #0d1321;
    color: #8b95a8;
    border-top: 1px solid rgba(255,255,255,0.06);
}
QMenuBar {
    background-color: #0d1321;
    color: #e8ecf1;
    border-bottom: 1px solid rgba(255,255,255,0.06);
}
QMenuBar::item:selected { background-color: #1a2235; }
QMenu {
    background-color: #1a2235;
    color: #e8ecf1;
    border: 1px solid rgba(255,255,255,0.08);
}
QMenu::item:selected { background-color: rgba(245,158,11,0.2); }
QSplitter::handle {
    background-color: rgba(255,255,255,0.06);
    width: 1px;
}
QLabel#sectionTitle {
    font-size: 16px;
    font-weight: 700;
    color: #f59e0b;
    padding: 4px 0;
}
QLabel#statusLabel {
    color: #8b95a8;
    font-size: 11px;
}
QListWidget {
    background-color: #111827;
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px;
    outline: none;
}
QListWidget::item {
    padding: 10px 14px;
    border-bottom: 1px solid rgba(255,255,255,0.04);
}
QListWidget::item:selected {
    background-color: rgba(245,158,11,0.15);
}
QListWidget::item:hover {
    background-color: rgba(255,255,255,0.03);
}
QDialog {
    background-color: #111827;
}
"""


# ============ API 工作线程 ============

class ApiTask(QThread):
    """通用 API 异步调用线程"""
    finished = pyqtSignal(object)  # response data
    error = pyqtSignal(str)

    def __init__(self, api_base: str, method: str, endpoint: str, 
                 json_data: dict = None, files_data: dict = None, 
                 raw_response: bool = False):
        super().__init__()
        self.api_base = api_base
        self.method = method
        self.endpoint = endpoint
        self.json_data = json_data
        self.files_data = files_data
        self.raw_response = raw_response

    def run(self):
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


class UploadWorker(QThread):
    """文件上传工作线程"""
    finished = pyqtSignal(dict)  # {index, file_id, ...}
    error = pyqtSignal(int, str)  # index, error

    def __init__(self, api_base: str, file_path: str, index: int):
        super().__init__()
        self.api_base = api_base
        self.file_path = file_path
        self.index = index

    def run(self):
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


class SubmitWorker(QThread):
    """提交异步 OCR 任务工作线程"""
    finished = pyqtSignal(dict)
    error = pyqtSignal(int, str)

    def __init__(self, api_base: str, file_id: str, index: int):
        super().__init__()
        self.api_base = api_base
        self.file_id = file_id
        self.index = index

    def run(self):
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


class PollWorker(QThread):
    """轮询任务状态工作线程"""
    finished = pyqtSignal(list)  # [{index, data, error}]
    error = pyqtSignal(str)

    def __init__(self, api_base: str, tasks: List[Dict], index_map: Dict[str, int]):
        super().__init__()
        self.api_base = api_base
        self.tasks = tasks
        self.index_map = index_map

    def run(self):
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
                    import asyncio
                    return await asyncio.gather(*coros)
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(_do())
            loop.close()
            self.finished.emit(list(result))
        except Exception as e:
            self.error.emit(str(e))


# ============ 主窗口 ============

class StandaloneApp(QMainWindow):
    """独立桌面应用程序主窗口"""

    def __init__(self):
        super().__init__()
        self.api_base = "http://127.0.0.1:8500"
        self.file_queue: List[Dict] = []           # [{path, name, size, status, file_id, task_id, result}]
        self.batch_results: List[Dict] = []        # 批量处理结果
        self.processing = False
        self.active_workers: List[QThread] = []

        # ---- NAS 同步服务 ----
        sync_cache_dir = Path(__file__).parent / "local_cache"
        self.sync_service = create_default_sync_service(cache_dir=str(sync_cache_dir))
        self.sync_service.set_on_status(self._on_nas_status_changed)
        self.sync_service.set_on_sync_complete(self._on_nas_sync_complete)

        # 加载持久化的 NAS 配置
        self._nas_config_file = Path(__file__).parent / "nas_config.json"
        self._load_nas_config()

        self.setup_ui()
        self.setup_menu()
        self.setup_statusbar()
        self.check_server_status()
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.check_server_status)
        self.status_timer.start(15000)

        # 尝试连接 NAS（延迟启动，避免阻塞 UI）
        QTimer.singleShot(2000, self._init_nas_connection)

    # ============ UI 搭建 ============

    def setup_ui(self):
        self.setWindowTitle("Claw - 错题管理系统")
        self.setMinimumSize(1280, 800)
        self.resize(1400, 880)
        self.setAcceptDrops(True)
        self.setStyleSheet(DARK_STYLE)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(16, 12, 16, 12)
        main_layout.setSpacing(12)

        # 标题栏
        title_layout = QHBoxLayout()
        title = QLabel("Claw 错题管理系统")
        title.setStyleSheet("font-size: 20px; font-weight: 700; color: #f59e0b;")
        title_layout.addWidget(title)
        title_layout.addStretch()
        self.server_status_label = QLabel("检查服务器状态...")
        self.server_status_label.setObjectName("statusLabel")
        title_layout.addWidget(self.server_status_label)
        main_layout.addLayout(title_layout)

        # 标签页
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        self.create_upload_tab()
        self.create_history_tab()
        self.create_reports_tab()
        self.create_config_tab()
        self.create_nas_sync_tab()
        self._populate_nas_config_ui()

    def create_upload_tab(self):
        """上传处理标签页 - 完整复刻前端功能"""
        tab = QWidget()
        tab.setAcceptDrops(True)
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)

        # ---- 上传区域 ----
        upload_group = QGroupBox("文件上传区")
        upload_layout = QVBoxLayout(upload_group)

        hint_bar = QHBoxLayout()
        upload_info = QLabel("拖拽文件/文件夹到此处，或使用下方按钮选择（右键选择文件夹）")
        upload_info.setStyleSheet("color: #8b95a8; font-size: 12px;")
        hint_bar.addWidget(upload_info)
        hint_bar.addStretch()
        upload_layout.addLayout(hint_bar)

        btn_bar = QHBoxLayout()
        self.btn_select_files = QPushButton("选择文件")
        self.btn_select_files.clicked.connect(self.select_files)
        btn_bar.addWidget(self.btn_select_files)

        self.btn_select_folder = QPushButton("选择文件夹")
        self.btn_select_folder.clicked.connect(self.select_folder)
        btn_bar.addWidget(self.btn_select_folder)

        btn_bar.addStretch()

        self.btn_clear_queue = QPushButton("清空队列")
        self.btn_clear_queue.setObjectName("ghostBtn")
        self.btn_clear_queue.clicked.connect(self.clear_queue)
        btn_bar.addWidget(self.btn_clear_queue)

        self.btn_process_all = QPushButton("全部处理")
        self.btn_process_all.setObjectName("primaryBtn")
        self.btn_process_all.clicked.connect(self.process_all_files)
        btn_bar.addWidget(self.btn_process_all)

        upload_layout.addLayout(btn_bar)

        # 文件列表
        self.file_list_widget = QListWidget()
        self.file_list_widget.setMinimumHeight(120)
        self.file_list_widget.setMaximumHeight(220)
        self.file_list_widget.setAlternatingRowColors(False)
        upload_layout.addWidget(self.file_list_widget)

        layout.addWidget(upload_group)

        # ---- 进度区域 ----
        progress_group = QGroupBox("处理进度")
        progress_layout = QVBoxLayout(progress_group)

        # 步骤指示器
        steps_layout = QHBoxLayout()
        self.step_labels = {}
        for step_key, step_name in [("upload", "上传文件"), ("analyze", "模型识别"), ("report", "生成报告")]:
            lbl = QLabel(f"● {step_name}")
            lbl.setStyleSheet("color: #4b5563; font-size: 12px; padding: 4px 12px;")
            steps_layout.addWidget(lbl)
            self.step_labels[step_key] = lbl
        steps_layout.addStretch()
        progress_layout.addLayout(steps_layout)

        self.progress_text = QLabel("等待处理...")
        self.progress_text.setStyleSheet("color: #e8ecf1; font-size: 14px; font-weight: 600;")
        progress_layout.addWidget(self.progress_text)

        self.progress_info = QLabel("")
        self.progress_info.setStyleSheet("color: #8b95a8; font-size: 12px;")
        progress_layout.addWidget(self.progress_info)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)

        layout.addWidget(progress_group)

        # ---- 结果面板 ----
        result_splitter = QSplitter(Qt.Orientation.Horizontal)

        # 结果统计
        stats_container = QWidget()
        stats_layout = QVBoxLayout(stats_container)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_header = QLabel("处理结果")
        stats_header.setStyleSheet("font-weight: 600; color: #f59e0b; font-size: 14px;")
        stats_layout.addWidget(stats_header)
        self.stats_grid = QGridLayout()
        stats_layout.addLayout(self.stats_grid)
        stats_layout.addStretch()
        result_splitter.addWidget(stats_container)

        # Markdown 预览
        md_container = QWidget()
        md_layout = QVBoxLayout(md_container)
        md_layout.setContentsMargins(0, 0, 0, 0)
        md_header_bar = QHBoxLayout()
        md_header = QLabel("Markdown 预览")
        md_header.setStyleSheet("font-weight: 600; color: #f59e0b; font-size: 14px;")
        md_header_bar.addWidget(md_header)
        md_header_bar.addStretch()
        self.btn_copy_md = QPushButton("复制内容")
        self.btn_copy_md.setObjectName("ghostBtn")
        self.btn_copy_md.setMaximumWidth(100)
        self.btn_copy_md.clicked.connect(self.copy_markdown)
        md_header_bar.addWidget(self.btn_copy_md)
        md_layout.addLayout(md_header_bar)
        self.markdown_view = QTextEdit()
        self.markdown_view.setReadOnly(True)
        self.markdown_view.setPlaceholderText("处理结果 Markdown 将在此显示...")
        md_layout.addWidget(self.markdown_view)
        result_splitter.addWidget(md_container)

        result_splitter.setSizes([200, 600])
        layout.addWidget(result_splitter, 1)

        self.tab_widget.addTab(tab, "上传处理")

    def create_history_tab(self):
        """处理历史记录标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)

        action_bar = QHBoxLayout()
        action_bar.addStretch()
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.load_history)
        action_bar.addWidget(refresh_btn)
        layout.addLayout(action_bar)

        self.history_table = QTableWidget()
        self.history_table.setColumnCount(7)
        self.history_table.setHorizontalHeaderLabels([
            "编号", "文件名", "时间", "状态", "耗时(s)", "图片数", "操作"
        ])
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        layout.addWidget(self.history_table)

        self.tab_widget.addTab(tab, "处理记录")

    def create_reports_tab(self):
        """报告中心标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)

        action_bar = QHBoxLayout()
        action_bar.addStretch()
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.load_reports)
        action_bar.addWidget(refresh_btn)
        layout.addLayout(action_bar)

        self.reports_table = QTableWidget()
        self.reports_table.setColumnCount(5)
        self.reports_table.setHorizontalHeaderLabels([
            "报告ID", "创建时间", "包含Markdown", "大小", "操作"
        ])
        self.reports_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.reports_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.reports_table)

        self.tab_widget.addTab(tab, "报告中心")

    def create_config_tab(self):
        """系统配置标签页"""
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(16)

        # API 配置
        api_group = QGroupBox("PaddleOCR API 配置")
        api_form = QFormLayout(api_group)
        api_hint = QLabel("从 aistudio.baidu.com/paddleocr/task 获取 API_URL 和 TOKEN")
        api_hint.setStyleSheet("color: #8b95a8; font-size: 11px;")
        api_form.addRow(api_hint)
        self.cfg_api_url = QLineEdit()
        self.cfg_api_key = QLineEdit()
        self.cfg_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.cfg_model = QComboBox()
        self.cfg_model.addItems(["PP-StructureV3", "PaddleOCR-VL-1.5", "PaddleOCR-VL", "PP-OCRv5"])
        api_form.addRow("API 地址:", self.cfg_api_url)
        api_form.addRow("TOKEN:", self.cfg_api_key)
        api_form.addRow("模型:", self.cfg_model)

        api_btn_layout = QHBoxLayout()
        save_api_btn = QPushButton("保存 API 配置")
        save_api_btn.setObjectName("primaryBtn")
        save_api_btn.clicked.connect(self.save_api_config)
        api_btn_layout.addWidget(save_api_btn)
        test_btn = QPushButton("测试连接")
        test_btn.clicked.connect(self.test_api_connection)
        api_btn_layout.addWidget(test_btn)
        api_btn_layout.addStretch()
        api_form.addRow("", api_btn_layout)
        layout.addWidget(api_group)

        # 服务器配置
        server_group = QGroupBox("服务器配置")
        server_form = QFormLayout(server_group)
        self.cfg_host = QLineEdit("0.0.0.0")
        self.cfg_port = QSpinBox()
        self.cfg_port.setRange(1, 65535)
        self.cfg_port.setValue(8500)
        self.cfg_max_size = QSpinBox()
        self.cfg_max_size.setRange(1, 500)
        self.cfg_max_size.setValue(50)
        self.cfg_max_size.setSuffix(" MB")
        server_form.addRow("监听地址:", self.cfg_host)
        server_form.addRow("监听端口:", self.cfg_port)
        server_form.addRow("最大上传:", self.cfg_max_size)

        save_server_btn = QPushButton("保存服务器配置")
        save_server_btn.setObjectName("primaryBtn")
        save_server_btn.clicked.connect(self.save_server_config)
        server_form.addRow("", save_server_btn)
        layout.addWidget(server_group)

        # 处理参数
        process_group = QGroupBox("处理参数")
        process_form = QFormLayout(process_group)
        self.cfg_log_level = QComboBox()
        self.cfg_log_level.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.cfg_log_level.setCurrentText("INFO")
        process_form.addRow("日志级别:", self.cfg_log_level)

        save_process_btn = QPushButton("保存处理参数")
        save_process_btn.setObjectName("primaryBtn")
        save_process_btn.clicked.connect(self.save_process_config)
        process_form.addRow("", save_process_btn)
        layout.addWidget(process_group)

        # NAS 同步配置
        nas_group = QGroupBox("NAS 跨网段同步配置")
        nas_form = QFormLayout(nas_group)
        nas_hint = QLabel("SMB NAS (192.168.0.79) 作为跨网段数据中转节点")
        nas_hint.setStyleSheet("color: #8b95a8; font-size: 11px;")
        nas_form.addRow(nas_hint)

        self.cfg_nas_host = QLineEdit("192.168.0.79")
        self.cfg_nas_share = QLineEdit("maker")
        self.cfg_nas_user = QLineEdit("maker")
        self.cfg_nas_pass = QLineEdit("maker")
        self.cfg_nas_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.cfg_nas_root = QLineEdit("CLAW_CHANGE_RECORDS/08_shared_data")

        nas_form.addRow("NAS 地址:", self.cfg_nas_host)
        nas_form.addRow("共享名:", self.cfg_nas_share)
        nas_form.addRow("账号:", self.cfg_nas_user)
        nas_form.addRow("密码:", self.cfg_nas_pass)
        nas_form.addRow("同步根目录:", self.cfg_nas_root)

        # 挂载盘符（可选）
        nas_mount_layout = QHBoxLayout()
        self.cfg_nas_mount = QLineEdit("")
        self.cfg_nas_mount.setPlaceholderText("如 Z: （留空则使用 UNC 路径）")
        self.cfg_nas_mount.setMaximumWidth(60)
        nas_mount_layout.addWidget(self.cfg_nas_mount)

        self.cfg_auto_sync = QComboBox()
        self.cfg_auto_sync.addItems(["启用", "禁用"])
        self.cfg_auto_sync.setCurrentText("启用")
        nas_mount_layout.addWidget(QLabel("自动同步:"))
        nas_mount_layout.addWidget(self.cfg_auto_sync)
        nas_mount_layout.addStretch()
        nas_form.addRow("挂载盘符/自动:", nas_mount_layout)

        nas_btn_layout = QHBoxLayout()
        save_nas_btn = QPushButton("保存 NAS 配置")
        save_nas_btn.setObjectName("primaryBtn")
        save_nas_btn.clicked.connect(self.save_nas_config)
        nas_btn_layout.addWidget(save_nas_btn)

        test_nas_btn = QPushButton("测试 NAS 连接")
        test_nas_btn.clicked.connect(self.test_nas_connection)
        nas_btn_layout.addWidget(test_nas_btn)

        reconnect_nas_btn = QPushButton("重连 NAS")
        reconnect_nas_btn.clicked.connect(self.reconnect_nas)
        nas_btn_layout.addWidget(reconnect_nas_btn)
        nas_btn_layout.addStretch()
        nas_form.addRow("", nas_btn_layout)
        layout.addWidget(nas_group)

        layout.addStretch()
        scroll.setWidget(container)
        self.tab_widget.addTab(scroll, "系统配置")

    def create_nas_sync_tab(self):
        """NAS 跨网段同步标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)

        # ---- 连接状态卡片 ----
        status_group = QGroupBox("NAS 连接状态")
        status_layout = QHBoxLayout(status_group)

        self.nas_status_indicator = QLabel("●")
        self.nas_status_indicator.setStyleSheet("font-size: 24px; color: #6b7280;")
        status_layout.addWidget(self.nas_status_indicator)

        status_text_layout = QVBoxLayout()
        self.nas_status_text = QLabel("未连接")
        self.nas_status_text.setStyleSheet("font-size: 15px; font-weight: 600; color: #8b95a8;")
        status_text_layout.addWidget(self.nas_status_text)
        self.nas_status_detail = QLabel("等待连接...")
        self.nas_status_detail.setStyleSheet("font-size: 11px; color: #6b7280;")
        status_text_layout.addWidget(self.nas_status_detail)
        status_layout.addLayout(status_text_layout)

        status_layout.addStretch()

        # 快速状态信息
        self.nas_info_pending = QLabel("缓存: 0")
        self.nas_info_pending.setStyleSheet("font-size: 11px; color: #8b95a8;")
        status_layout.addWidget(self.nas_info_pending)
        self.nas_info_last_sync = QLabel("上次同步: --")
        self.nas_info_last_sync.setStyleSheet("font-size: 11px; color: #8b95a8;")
        status_layout.addWidget(self.nas_info_last_sync)

        layout.addWidget(status_group)

        # ---- 同步操作按钮 ----
        action_group = QGroupBox("同步操作")
        action_layout = QHBoxLayout(action_group)

        self.btn_nas_push = QPushButton("推送报告 → NAS")
        self.btn_nas_push.setObjectName("primaryBtn")
        self.btn_nas_push.clicked.connect(self._nas_push_reports)
        action_layout.addWidget(self.btn_nas_push)

        self.btn_nas_pull = QPushButton("← 拉取报告")
        self.btn_nas_pull.setObjectName("primaryBtn")
        self.btn_nas_pull.clicked.connect(self._nas_pull_reports)
        action_layout.addWidget(self.btn_nas_pull)

        self.btn_nas_sync_all = QPushButton("双向同步")
        self.btn_nas_sync_all.clicked.connect(self._nas_sync_all)
        action_layout.addWidget(self.btn_nas_sync_all)

        self.btn_nas_push_history = QPushButton("推送历史")
        self.btn_nas_push_history.setObjectName("ghostBtn")
        self.btn_nas_push_history.clicked.connect(self._nas_push_history)
        action_layout.addWidget(self.btn_nas_push_history)

        self.btn_nas_pull_history = QPushButton("拉取历史")
        self.btn_nas_pull_history.setObjectName("ghostBtn")
        self.btn_nas_pull_history.clicked.connect(self._nas_pull_history)
        action_layout.addWidget(self.btn_nas_pull_history)

        action_layout.addStretch()
        layout.addWidget(action_group)

        # ---- 远程文件浏览器 ----
        browser_group = QGroupBox("NAS 远程文件浏览")
        browser_layout = QVBoxLayout(browser_group)

        browser_bar = QHBoxLayout()
        browser_bar.addWidget(QLabel("远程报告列表:"))
        browser_bar.addStretch()
        refresh_remote_btn = QPushButton("刷新")
        refresh_remote_btn.clicked.connect(self._refresh_nas_browser)
        browser_bar.addWidget(refresh_remote_btn)
        browser_layout.addLayout(browser_bar)

        self.nas_browser_table = QTableWidget()
        self.nas_browser_table.setColumnCount(3)
        self.nas_browser_table.setHorizontalHeaderLabels(["报告ID", "文件数", "操作"])
        self.nas_browser_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.nas_browser_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        browser_layout.addWidget(self.nas_browser_table)

        layout.addWidget(browser_group)

        # ---- 同步日志 ----
        log_group = QGroupBox("同步日志（最近 20 条）")
        log_layout = QVBoxLayout(log_group)
        self.nas_log_view = QTextEdit()
        self.nas_log_view.setReadOnly(True)
        self.nas_log_view.setMaximumHeight(180)
        self.nas_log_view.setPlaceholderText("同步操作日志将在此显示...")
        log_layout.addWidget(self.nas_log_view)

        log_btn_bar = QHBoxLayout()
        log_btn_bar.addStretch()
        clear_log_btn = QPushButton("清空日志")
        clear_log_btn.setObjectName("ghostBtn")
        clear_log_btn.clicked.connect(lambda: self.nas_log_view.clear())
        log_btn_bar.addWidget(clear_log_btn)
        log_layout.addLayout(log_btn_bar)
        layout.addWidget(log_group)

        self.tab_widget.addTab(tab, "NAS同步")

    # ============ NAS 同步回调与操作 ============

    def _on_nas_status_changed(self, status: SyncStatus, message: str):
        """NAS 状态变化回调（来自同步服务线程 → 主线程安全更新 UI）"""
        def _update():
            status_map = {
                SyncStatus.DISCONNECTED: ("#6b7280", "● 未连接"),
                SyncStatus.CONNECTING: ("#f59e0b", "⟳ 连接中"),
                SyncStatus.CONNECTED: ("#10b981", "● 已连接"),
                SyncStatus.SYNCING: ("#3b82f6", "⟳ 同步中"),
                SyncStatus.ERROR: ("#ef4444", "✕ 错误"),
            }
            color, prefix = status_map.get(status, ("#6b7280", ""))
            self.nas_status_indicator.setStyleSheet(f"font-size: 24px; color: {color};")
            self.nas_status_text.setText(prefix)
            self.nas_status_text.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {color};")
            self.nas_status_detail.setText(message)
            self._refresh_nas_status_info()

        # 确保在主线程执行
        if QApplication.instance():
            QTimer.singleShot(0, _update)

    def _on_nas_sync_complete(self, record: SyncRecord):
        """同步完成回调"""
        def _update():
            self._refresh_nas_status_info()
            self._append_sync_log(record)
            self._refresh_nas_browser()
        QTimer.singleShot(0, _update)

    def _refresh_nas_status_info(self):
        """刷新 NAS 状态信息栏"""
        status = self.sync_service.get_status()
        self.nas_info_pending.setText(f"缓存: {status.get('pending_cache', 0)}")
        last_sync = status.get("last_sync")
        if last_sync:
            try:
                dt = datetime.fromisoformat(last_sync)
                self.nas_info_last_sync.setText(f"上次同步: {dt.strftime('%H:%M:%S')}")
            except Exception:
                self.nas_info_last_sync.setText(f"上次同步: {last_sync[:19]}")
        else:
            self.nas_info_last_sync.setText("上次同步: --")

    def _append_sync_log(self, record: SyncRecord):
        """追加同步日志到日志视图"""
        timestamp = record.timestamp[:19] if record.timestamp else ""
        direction = {"push": "推送 ↑", "pull": "拉取 ↓", "bidirectional": "双向 ↔"}.get(
            record.direction, record.direction)
        line = f"[{timestamp}] {direction}: {record.files_synced} 成功, {record.files_failed} 失败"
        for detail in record.details[:5]:
            line += f"\n  {detail}"
        self.nas_log_view.append(line)
        self.nas_log_view.append("─" * 50)

        # 限制日志行数
        cursor = self.nas_log_view.textCursor()
        cursor.move(QTextCursor.MoveOperation.Start)
        lines = self.nas_log_view.toPlainText().split("\n")
        if len(lines) > 300:
            new_text = "\n".join(lines[-300:])
            self.nas_log_view.setPlainText(new_text)

    def _nas_push_reports(self):
        """手动推送报告到 NAS"""
        if not self.sync_service.is_connected():
            if not self.sync_service.connect():
                QMessageBox.warning(self, "NAS 不可用", "无法连接到 NAS，请检查网络和配置")
                return

        self.show_toast("正在推送报告到 NAS...")
        output_dir = Path(__file__).parent.parent / "output"
        record = self.sync_service.push_reports(local_output_dir=str(output_dir))
        self._on_nas_sync_complete(record)
        self._refresh_nas_browser()
        QMessageBox.information(self, "推送完成",
                                f"报告推送完成: {record.files_synced} 成功, {record.files_failed} 失败")

    def _nas_pull_reports(self):
        """手动从 NAS 拉取报告"""
        if not self.sync_service.is_connected():
            if not self.sync_service.connect():
                QMessageBox.warning(self, "NAS 不可用", "无法连接到 NAS")
                return

        self.show_toast("正在从 NAS 拉取报告...")
        output_dir = Path(__file__).parent.parent / "output"
        record = self.sync_service.pull_reports(local_output_dir=str(output_dir))
        self._on_nas_sync_complete(record)
        self.load_reports()
        QMessageBox.information(self, "拉取完成",
                                f"报告拉取完成: {record.files_synced} 成功, {record.files_failed} 失败")

    def _nas_sync_all(self):
        """全量双向同步"""
        if not self.sync_service.is_connected():
            if not self.sync_service.connect():
                QMessageBox.warning(self, "NAS 不可用", "无法连接到 NAS")
                return

        self.show_toast("正在执行双向同步...")
        output_dir = Path(__file__).parent.parent / "output"

        # 获取当前历史
        history_worker = ApiTask(self.api_base, "GET", "/api/history?limit=100")
        loop = asyncio.new_event_loop()

        def _do_sync():
            asyncio.set_event_loop(loop)
            try:
                async def _get():
                    async with httpx.AsyncClient(timeout=30) as client:
                        resp = await client.get(f"{self.api_base}/api/history?limit=100")
                        resp.raise_for_status()
                        return resp.json().get("items", [])
                items = loop.run_until_complete(_get())
                loop.close()
                record = self.sync_service.sync_all(
                    local_output_dir=str(output_dir),
                    history_items=items,
                    direction=SyncDirection.BIDIRECTIONAL,
                )
                QTimer.singleShot(0, lambda: (
                    self._on_nas_sync_complete(record),
                    self.load_reports(),
                    self.load_history(),
                    self._refresh_nas_browser(),
                ))
                QTimer.singleShot(0, lambda: QMessageBox.information(
                    self, "同步完成",
                    f"双向同步完成: {record.files_synced} 成功, {record.files_failed} 失败"))
            except Exception as e:
                loop.close()
                QTimer.singleShot(0, lambda: QMessageBox.warning(
                    self, "同步异常", f"同步过程中发生错误:\n{e}"))

        threading.Thread(target=_do_sync, daemon=True).start()

    def _nas_push_history(self):
        """手动推送处理历史"""
        if not self.sync_service.is_connected():
            if not self.sync_service.connect():
                QMessageBox.warning(self, "NAS 不可用", "无法连接到 NAS")
                return

        worker = ApiTask(self.api_base, "GET", "/api/history?limit=100")
        worker.finished.connect(lambda data: self._on_history_for_push(data))
        worker.error.connect(lambda e: self.show_toast(f"获取历史失败: {e}"))
        worker.start()

    def _on_history_for_push(self, data: dict):
        items = data.get("items", [])
        if not items:
            QMessageBox.information(self, "提示", "没有可推送的历史记录")
            return
        record = self.sync_service.push_history(items)
        self._on_nas_sync_complete(record)
        QMessageBox.information(self, "推送完成",
                                f"历史记录已推送: {len(items)} 条")

    def _nas_pull_history(self):
        """手动从 NAS 拉取处理历史"""
        if not self.sync_service.is_connected():
            if not self.sync_service.connect():
                QMessageBox.warning(self, "NAS 不可用", "无法连接到 NAS")
                return

        items = self.sync_service.pull_history()
        if not items:
            QMessageBox.information(self, "提示", "NAS 上没有历史记录")
            return

        # 合并到本地历史表（标记来源）
        self._show_pulled_history(items)
        QMessageBox.information(self, "拉取完成",
                                f"从 NAS 拉取了 {len(items)} 条历史记录")

    def _show_pulled_history(self, items: List[dict]):
        """显示从 NAS 拉取的历史记录"""
        self.history_table.setRowCount(len(items))
        for i, item in enumerate(items):
            # 标记来自 NAS
            source = item.get("_source", "")
            prefix = "[NAS] " if source == "nas" else ""
            self.history_table.setItem(i, 0, QTableWidgetItem(f"#{item.get('id', '')}"))
            fname = item.get("filename", "")
            self.history_table.setItem(i, 1, QTableWidgetItem(
                prefix + (fname[:35] + "..." if len(fname) > 35 else fname)))
            self.history_table.setItem(i, 2, QTableWidgetItem(
                item.get("timestamp", "")[:19]))
            status = "成功" if item.get("success") else "失败"
            sitem = QTableWidgetItem(status)
            sitem.setForeground(QColor("#10b981") if item.get("success") else QColor("#ef4444"))
            self.history_table.setItem(i, 3, sitem)
            self.history_table.setItem(i, 4, QTableWidgetItem(
                str(item.get("processing_time", 0))))
            self.history_table.setItem(i, 5, QTableWidgetItem(
                str(item.get("images_count", 0))))

    def _refresh_nas_browser(self):
        """刷新 NAS 远程文件浏览器"""
        self.nas_browser_table.setRowCount(0)
        if not self.sync_service.is_connected():
            return

        reports_dir = os.path.join(self.sync_service.config.sync_root, "reports")
        report_names = self.sync_service.list_remote_dir(reports_dir)
        self.nas_browser_table.setRowCount(len(report_names))

        for i, rid in enumerate(report_names):
            self.nas_browser_table.setItem(i, 0, QTableWidgetItem(rid))
            # 统计文件数
            remote_report_dir = os.path.join(reports_dir, rid)
            files = self.sync_service.list_remote_dir(remote_report_dir)
            self.nas_browser_table.setItem(i, 1, QTableWidgetItem(str(len(files))))
            # 操作按钮
            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(4, 2, 4, 2)
            btn_layout.setSpacing(4)

            pull_btn = QPushButton("拉取")
            pull_btn.setObjectName("ghostBtn")
            pull_btn.setMaximumWidth(60)
            pull_btn.clicked.connect(lambda checked, x=rid: self._nas_pull_single_report(x))
            btn_layout.addWidget(pull_btn)

            del_btn = QPushButton("删除")
            del_btn.setMaximumWidth(60)
            del_btn.setStyleSheet(
                "QPushButton { background: transparent; color: #ef4444; border: 1px solid #ef4444; "
                "border-radius: 4px; padding: 4px 8px; }"
                "QPushButton:hover { background: rgba(239,68,68,0.15); }"
            )
            del_btn.clicked.connect(lambda checked, x=rid: self._nas_delete_remote_report(x))
            btn_layout.addWidget(del_btn)

            self.nas_browser_table.setCellWidget(i, 2, btn_widget)

    def _nas_pull_single_report(self, report_id: str):
        """从 NAS 拉取单个报告"""
        if not self.sync_service.is_connected():
            return
        self.show_toast(f"正在从 NAS 拉取报告 {report_id}...")
        output_dir = Path(__file__).parent.parent / "output"

        # 单独下载该报告的所有文件
        remote_reports_dir = os.path.join(self.sync_service.config.sync_root, "reports", report_id)
        local_report_dir = output_dir / report_id
        local_report_dir.mkdir(parents=True, exist_ok=True)

        synced = 0
        failed = 0
        remote_files = self.sync_service.list_remote_dir(remote_reports_dir)
        for fname in remote_files:
            remote_file = os.path.join(remote_reports_dir, fname)
            local_file = local_report_dir / fname
            if self.sync_service.download_file(remote_file, str(local_file)):
                synced += 1
            else:
                failed += 1

        record = SyncRecord(
            timestamp=datetime.now().isoformat(),
            direction="pull",
            files_synced=synced,
            files_failed=failed,
            details=[f"拉取报告 {report_id}: {synced} 成功, {failed} 失败"],
        )
        self._on_nas_sync_complete(record)
        self.load_reports()
        self.show_toast(f"报告 {report_id} 已拉取 ({synced} 文件)")

    def _nas_delete_remote_report(self, report_id: str):
        """删除 NAS 上的远程报告"""
        reply = QMessageBox.question(
            self, "确认删除",
            f"确认删除 NAS 上的报告 {report_id}？\n此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        remote_report_dir = os.path.join(
            self.sync_service.config.sync_root, "reports", report_id)
        if self.sync_service.delete_remote(remote_report_dir):
            self.show_toast(f"NAS 报告 {report_id} 已删除")
            self._refresh_nas_browser()
        else:
            self.show_toast(f"删除 NAS 报告失败")

    def _init_nas_connection(self):
        """初始化 NAS 连接（后台线程）"""
        def _connect():
            if self.sync_service.connect():
                # 连接成功后启动健康监控
                self.sync_service.start_health_monitor()
        threading.Thread(target=_connect, daemon=True).start()

    # ============ NAS 配置管理 ============

    def _load_nas_config(self):
        """从持久化文件加载 NAS 配置"""
        if self._nas_config_file.exists():
            try:
                data = json.loads(self._nas_config_file.read_text(encoding="utf-8"))
                self.sync_service.config.host = data.get("host", "192.168.0.79")
                self.sync_service.config.share = data.get("share", "maker")
                self.sync_service.config.username = data.get("username", "maker")
                self.sync_service.config.password = data.get("password", "maker")
                self.sync_service.config.sync_root = data.get("sync_root", "CLAW_CHANGE_RECORDS/08_shared_data")
                self.sync_service.config.auto_sync = data.get("auto_sync", True)
                self.sync_service.config.mount_letter = data.get("mount_letter", "")
            except Exception:
                pass

    def _save_nas_config_to_file(self):
        """持久化 NAS 配置"""
        cfg = self.sync_service.config
        data = {
            "host": cfg.host,
            "share": cfg.share,
            "username": cfg.username,
            "password": cfg.password,
            "sync_root": cfg.sync_root,
            "auto_sync": cfg.auto_sync,
            "mount_letter": cfg.mount_letter,
        }
        self._nas_config_file.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                         encoding="utf-8")

    def _populate_nas_config_ui(self):
        """将已加载的 NAS 配置同步到 UI 字段"""
        cfg = self.sync_service.config
        self.cfg_nas_host.setText(cfg.host)
        self.cfg_nas_share.setText(cfg.share)
        self.cfg_nas_user.setText(cfg.username)
        self.cfg_nas_pass.setText(cfg.password)
        self.cfg_nas_root.setText(cfg.sync_root)
        self.cfg_auto_sync.setCurrentText("启用" if cfg.auto_sync else "禁用")
        self.cfg_nas_mount.setText(cfg.mount_letter)

    def save_nas_config(self):
        """保存 NAS 配置（从 UI 读取 → 应用到服务 → 持久化）"""
        self.sync_service.config.host = self.cfg_nas_host.text()
        self.sync_service.config.share = self.cfg_nas_share.text()
        self.sync_service.config.username = self.cfg_nas_user.text()
        self.sync_service.config.password = self.cfg_nas_pass.text()
        self.sync_service.config.sync_root = self.cfg_nas_root.text()
        self.sync_service.config.auto_sync = self.cfg_auto_sync.currentText() == "启用"
        self.sync_service.config.mount_letter = self.cfg_nas_mount.text().strip()
        self._save_nas_config_to_file()
        self.show_toast("NAS 配置已保存")

    def test_nas_connection(self):
        """测试 NAS 连接"""
        # 先应用当前 UI 配置
        self.sync_service.config.host = self.cfg_nas_host.text()
        self.sync_service.config.share = self.cfg_nas_share.text()
        self.sync_service.config.username = self.cfg_nas_user.text()
        self.sync_service.config.password = self.cfg_nas_pass.text()
        self.sync_service.config.mount_letter = self.cfg_nas_mount.text().strip()

        self.show_toast("正在测试 NAS 连接...")

        def _test():
            if self.sync_service.connect():
                QTimer.singleShot(0, lambda: QMessageBox.information(
                    self, "NAS 连接测试",
                    f"成功连接到 NAS\n地址: {self.sync_service.config.unc_path}"
                ))
            else:
                QTimer.singleShot(0, lambda: QMessageBox.warning(
                    self, "NAS 连接测试",
                    "无法连接到 NAS\n请检查:\n"
                    "1. 网络是否可达 (ping 192.168.0.79)\n"
                    "2. 账号密码是否正确\n"
                    "3. SMB 共享名是否正确"
                ))

        threading.Thread(target=_test, daemon=True).start()

    def reconnect_nas(self):
        """手动重连 NAS"""
        self.sync_service.disconnect()
        self._init_nas_connection()
        self.show_toast("正在重连 NAS...")

    def _auto_sync_after_process(self, output_dir: str):
        """处理完成后自动同步报告到 NAS（后台线程）"""
        try:
            record = self.sync_service.push_reports(local_output_dir=output_dir)
            QTimer.singleShot(0, lambda: self._on_nas_sync_complete(record))
        except Exception as e:
            QTimer.singleShot(0, lambda: self._append_sync_log(SyncRecord(
                timestamp=datetime.now().isoformat(),
                direction="push",
                files_synced=0, files_failed=1,
                details=[f"自动同步失败: {e}"],
            )))
        menubar = self.menuBar()
        file_menu = menubar.addMenu("文件(&F)")

        open_action = QAction("选择文件...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.select_files)
        file_menu.addAction(open_action)

        folder_action = QAction("选择文件夹...", self)
        folder_action.setShortcut("Ctrl+Shift+O")
        folder_action.triggered.connect(self.select_folder)
        file_menu.addAction(folder_action)

        file_menu.addSeparator()
        exit_action = QAction("退出", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        tools_menu = menubar.addMenu("工具(&T)")
        refresh_action = QAction("刷新全部", self)
        refresh_action.setShortcut("F5")
        refresh_action.triggered.connect(self.refresh_all)
        tools_menu.addAction(refresh_action)

        help_menu = menubar.addMenu("帮助(&H)")
        about_action = QAction("关于...", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def setup_statusbar(self):
        self.statusBar().showMessage("就绪 - 请连接后端服务后开始使用")

    # ============ 拖拽支持 ============

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        files_to_add = []
        for url in urls:
            path = url.toLocalFile()
            p = Path(path)
            if p.is_file():
                files_to_add.append(str(p))
            elif p.is_dir():
                for ext in ['.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff', '.tif']:
                    for f in p.rglob(f"*{ext}"):
                        files_to_add.append(str(f))
                    for f in p.rglob(f"*{ext.upper()}"):
                        files_to_add.append(str(f))
        if files_to_add:
            self.add_files_to_queue(files_to_add)

    # ============ 文件队列管理 ============

    def select_files(self):
        if self.processing:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择图片文件", "",
            "图片文件 (*.jpg *.jpeg *.png *.bmp *.webp *.tiff *.tif);;所有文件 (*)"
        )
        if paths:
            self.add_files_to_queue(list(paths))

    def select_folder(self):
        if self.processing:
            return
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if folder:
            p = Path(folder)
            files_to_add = []
            for ext in ['.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff', '.tif']:
                for f in p.rglob(f"*{ext}"):
                    files_to_add.append(str(f))
                for f in p.rglob(f"*{ext.upper()}"):
                    files_to_add.append(str(f))
            if files_to_add:
                self.add_files_to_queue(files_to_add)
            else:
                QMessageBox.information(self, "提示", "所选文件夹中没有支持的图片文件")

    def add_files_to_queue(self, paths: List[str]):
        """添加文件到队列"""
        ALLOWED_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff', '.tif'}
        MAX_SIZE = 50 * 1024 * 1024

        added = 0
        skipped = 0
        for path in paths:
            p = Path(path)
            if not p.is_file():
                continue
            ext = p.suffix.lower()
            if ext not in ALLOWED_EXTS:
                skipped += 1
                continue
            size = p.stat().st_size
            if size > MAX_SIZE:
                skipped += 1
                continue
            # 去重
            if any(q["path"] == str(p) for q in self.file_queue):
                skipped += 1
                continue
            self.file_queue.append({
                "path": str(p),
                "name": p.name,
                "size": size,
                "status": "pending",  # pending | uploading | uploading_done | processing | done | error
                "file_id": None,
                "task_id": None,
                "result": None,
                "error": None,
            })
            added += 1

        self.render_queue()
        if added > 0:
            self.show_toast(f"已添加 {added} 个文件" + 
                           (f" (跳过 {skipped} 个)" if skipped else ""))
        elif skipped > 0:
            self.show_toast(f"跳过了 {skipped} 个不支持的/重复的文件")

    def render_queue(self):
        """渲染文件队列列表"""
        self.file_list_widget.clear()
        for i, item in enumerate(self.file_queue):
            status_map = {
                "pending": ("⏳", "等待中"),
                "uploading": ("⬆", "上传中..."),
                "uploading_done": ("📤", "已上传"),
                "processing": ("⚙", "识别中..."),
                "done": ("✅", "完成"),
                "error": ("❌", "失败"),
            }
            icon, status_text = status_map.get(item["status"], ("", ""))
            size_text = self._format_size(item["size"])
            text = f"#{i+1}  [{icon}] {item['name']}  ({size_text})  -  {status_text}"
            if item.get("error"):
                text += f"  [{item['error'][:60]}]"
            
            list_item = QListWidgetItem(text)
            if item["status"] == "done":
                list_item.setForeground(QColor("#10b981"))
            elif item["status"] == "error":
                list_item.setForeground(QColor("#ef4444"))
            elif item["status"] in ("processing", "uploading"):
                list_item.setForeground(QColor("#f59e0b"))
            self.file_list_widget.addItem(list_item)

    def clear_queue(self):
        if self.processing:
            self.show_toast("处理中，无法清空队列")
            return
        self.file_queue.clear()
        self.batch_results.clear()
        self.render_queue()
        self.markdown_view.clear()
        self._clear_stats()
        self.progress_bar.setValue(0)
        self.progress_text.setText("等待处理...")
        self.progress_info.setText("")
        self._reset_steps()

    # ============ 批量处理流程 ============

    def process_all_files(self):
        """完整的批量处理流程：上传→提交→轮询→结果"""
        if self.processing:
            return
        if not self.file_queue:
            self.show_toast("请先添加文件")
            return
        pending = [q for q in self.file_queue if q["status"] == "pending"]
        if not pending:
            self.show_toast("所有文件已在处理中或已完成")
            return

        self.processing = True
        self.batch_results = []
        self.progress_bar.setValue(0)
        self._reset_steps()
        self._set_step_active("upload")

        total = len(self.file_queue)
        self._stage_upload_files(total)

    def _stage_upload_files(self, total: int):
        """阶段1：逐个上传文件"""
        self.progress_text.setText("批量上传中...")
        self.progress_info.setText(f"0/{total}")
        self.progress_bar.setValue(5)

        pending = [q for q in self.file_queue if q["status"] == "pending"]
        if not pending:
            self._stage_submit_tasks(total)
            return

        self._upload_index = 0
        self._upload_pending = pending
        self._upload_total = total
        self._upload_current_file()

    def _upload_current_file(self):
        if self._upload_index >= len(self._upload_pending):
            self._set_step_complete("upload")
            self._set_step_active("analyze")
            self._stage_submit_tasks(self._upload_total)
            return

        item = self._upload_pending[self._upload_index]
        item["status"] = "uploading"
        self.render_queue()

        idx = self.file_queue.index(item)
        worker = UploadWorker(self.api_base, item["path"], idx)
        worker.finished.connect(self._on_upload_done)
        worker.error.connect(self._on_upload_error)
        self.active_workers.append(worker)
        worker.finished.connect(lambda: self.active_workers.remove(worker))
        worker.start()

    def _on_upload_done(self, data: dict):
        idx = data.pop("_index")
        item = self.file_queue[idx]
        item["status"] = "uploading_done"
        item["file_id"] = data["file_id"]
        self.render_queue()

        self._upload_index += 1
        done = sum(1 for q in self.file_queue if q["status"] == "uploading_done")
        self.progress_info.setText(f"上传: {done}/{self._upload_total}")
        self.progress_bar.setValue(int(5 + done / max(self._upload_total, 1) * 15))
        self._upload_current_file()

    def _on_upload_error(self, idx: int, error: str):
        item = self.file_queue[idx]
        item["status"] = "error"
        item["error"] = f"上传失败: {error}"
        self.render_queue()

        self._upload_index += 1
        self._upload_current_file()

    def _stage_submit_tasks(self, total: int):
        """阶段2：并发提交所有异步任务"""
        upload_done = [q for q in self.file_queue if q["status"] == "uploading_done"]
        if not upload_done:
            self.show_toast("没有文件上传成功，无法继续")
            self.processing = False
            return

        self.progress_text.setText(f"提交 {len(upload_done)} 个任务...")
        self.progress_info.setText(f"提交中...")
        self.progress_bar.setValue(22)

        self._submit_pending = []
        self._submit_count = len(upload_done)
        self._submit_done_count = 0
        self._submit_total = total

        for item in upload_done:
            item["status"] = "processing"
            idx = self.file_queue.index(item)
            self._submit_pending.append(idx)
            worker = SubmitWorker(self.api_base, item["file_id"], idx)
            worker.finished.connect(self._on_submit_done)
            worker.error.connect(self._on_submit_error)
            self.active_workers.append(worker)
            worker.finished.connect(lambda w=worker: self._safe_remove_worker(w))

        self.render_queue()
        # 如果没有待提交项，直接进入轮询
        if not self._submit_pending:
            # 给一点时间让提交完成
            QTimer.singleShot(100, lambda: self._check_submit_done(total))

    def _on_submit_done(self, data: dict):
        idx = data.pop("_index")
        item = self.file_queue[idx]
        item["task_id"] = data.get("task_id")
        if not item["task_id"]:
            item["status"] = "error"
            item["error"] = "提交失败：未返回task_id"
        else:
            item["status"] = "processing"

        self._submit_done_count += 1
        if self._submit_done_count >= self._submit_count:
            self.progress_bar.setValue(25)
            self._set_step_complete("upload")
            self._set_step_active("analyze")
            self._start_polling(self._submit_total)

    def _on_submit_error(self, idx: int, error: str):
        item = self.file_queue[idx]
        item["status"] = "error"
        item["error"] = f"提交失败: {error}"
        self._submit_done_count += 1
        if self._submit_done_count >= self._submit_count:
            self._check_submit_done(self._submit_total)

    def _check_submit_done(self, total: int):
        processing = [q for q in self.file_queue if q["status"] == "processing" and q.get("task_id")]
        if not processing:
            self.show_toast("所有任务提交失败")
            self.processing = False
            self._show_batch_results()
            return
        self._set_step_complete("upload")
        self._set_step_active("analyze")
        self._start_polling(total)

    def _start_polling(self, total: int):
        """阶段3：轮询直到所有任务完成"""
        self._poll_total = total
        self._poll_count = 0
        self._max_polls = 120
        self.progress_text.setText("轮询任务状态...")
        self._do_poll()

    def _do_poll(self):
        processing = [q for q in self.file_queue 
                      if q["status"] == "processing" and q.get("task_id")]
        if not processing:
            self._finish_processing(self._poll_total)
            return

        self._poll_count += 1
        if self._poll_count > self._max_polls:
            for q in processing:
                q["status"] = "error"
                q["error"] = "轮询超时"
            self._finish_processing(self._poll_total)
            return

        tasks = []
        index_map = {}
        for item in processing:
            idx = self.file_queue.index(item)
            tasks.append({"task_id": item["task_id"], "index": idx})
            index_map[item["task_id"]] = idx

        worker = PollWorker(self.api_base, tasks, index_map)
        worker.finished.connect(self._on_poll_done)
        worker.error.connect(self._on_poll_error)
        self.active_workers.append(worker)
        worker.finished.connect(lambda w=worker: self._safe_remove_worker(w))
        worker.start()

    def _on_poll_done(self, results: list):
        for r in results:
            idx = r["index"]
            item = self.file_queue[idx]
            if "error" in r and r["error"]:
                continue  # 单次网络错误，继续轮询
            data = r.get("data", {})
            if not data:
                continue
            if data.get("completed"):
                if data.get("status") == "done":
                    item["status"] = "done"
                    item["result"] = data.get("result")
                else:
                    item["status"] = "error"
                    item["error"] = data.get("error", "处理失败")

        done = sum(1 for q in self.file_queue if q["status"] in ("done", "error"))
        processing = [q for q in self.file_queue if q["status"] == "processing"]
        
        pct = 25 + int((done / max(len(self.file_queue), 1)) * 65)
        self.progress_bar.setValue(pct)
        self.progress_info.setText(
            f"轮询中 {done}/{len(self.file_queue)} (第{self._poll_count}轮)"
        )
        self.progress_text.setText(f"处理中 {done}/{len(self.file_queue)}")
        self.render_queue()

        if processing:
            QTimer.singleShot(2000, self._do_poll)
        else:
            self._finish_processing(self._poll_total)

    def _on_poll_error(self, error: str):
        self.progress_info.setText(f"轮询错误: {error}，将继续...")
        QTimer.singleShot(2000, self._do_poll)

    def _finish_processing(self, total: int):
        """阶段4：汇总结果"""
        self._set_step_complete("analyze")
        self._set_step_active("report")

        self.progress_bar.setValue(100)
        self.progress_text.setText("生成报告中...")
        self.progress_info.setText(f"{total}/{total}")

        # 收集结果
        self.batch_results = []
        for item in self.file_queue:
            if item["status"] == "done":
                self.batch_results.append({
                    "name": item["name"],
                    "file_id": item["file_id"],
                    "success": True,
                    "processingTime": item["result"].get("processing_time", 0) if item["result"] else 0,
                    "imagesCount": item["result"].get("images_count", 0) if item["result"] else 0,
                    "mdLength": item["result"].get("markdown_text", "").__len__() if item["result"] else 0,
                    "reportDir": item["result"].get("report_dir", "") if item["result"] else "",
                    "layoutItems": item["result"].get("layout_items", []) if item["result"] else [],
                    "layoutItemsCount": item["result"].get("layout_items_count", 0) if item["result"] else 0,
                })
            elif item["status"] == "error":
                self.batch_results.append({
                    "name": item["name"],
                    "file_id": item["file_id"],
                    "success": False,
                    "error": item.get("error", "未知错误"),
                })

        self._set_step_complete("report")
        self.processing = False
        self.progress_text.setText("处理完成")
        self.progress_info.setText("全部完成")

        succeeded = sum(1 for r in self.batch_results if r["success"])
        if succeeded > 0:
            self.show_toast(f"全部完成: {succeeded} 个文件处理成功")
        else:
            self.show_toast(f"处理失败: 所有文件都失败了")

        self._show_batch_results()
        self.render_queue()
        self.load_history()

        # 自动预览第一个成功的结果
        for r in self.batch_results:
            if r["success"]:
                self._preview_first_result(r["file_id"])
                break

        # ---- 自动同步到 NAS ----
        if self.sync_service.config.auto_sync and self.sync_service.is_connected():
            output_dir = Path(__file__).parent.parent / "output"
            threading.Thread(
                target=lambda: self._auto_sync_after_process(str(output_dir)),
                daemon=True,
            ).start()

    def _preview_first_result(self, file_id: str):
        for item in self.file_queue:
            if item["file_id"] == file_id and item["result"]:
                md_text = item["result"].get("markdown_text", "")
                if md_text:
                    self.markdown_view.setHtml(self._render_markdown_html(md_text))
                break

    def _show_batch_results(self):
        """显示批量处理结果统计"""
        total = len(self.batch_results)
        succeeded = sum(1 for r in self.batch_results if r["success"])
        failed = total - succeeded
        total_time = sum(r.get("processingTime", 0) for r in self.batch_results if r["success"])

        # 清空并重建统计网格
        for i in reversed(range(self.stats_grid.count())):
            widget = self.stats_grid.itemAt(i)
            if widget and widget.widget():
                widget.widget().deleteLater()

        stats_data = [
            (str(total), "文件总数"),
            (str(succeeded), "成功"),
            (str(failed), "失败"),
            (f"{total_time:.1f}s", "总耗时"),
        ]
        for col, (val, label) in enumerate(stats_data):
            val_lbl = QLabel(val)
            val_lbl.setStyleSheet("font-size: 18px; font-weight: 700; color: #f59e0b;")
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_lbl = QLabel(label)
            lbl_lbl.setStyleSheet("font-size: 11px; color: #8b95a8;")
            lbl_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.stats_grid.addWidget(val_lbl, 0, col)
            self.stats_grid.addWidget(lbl_lbl, 1, col)

    def _clear_stats(self):
        for i in reversed(range(self.stats_grid.count())):
            widget = self.stats_grid.itemAt(i)
            if widget and widget.widget():
                widget.widget().deleteLater()

    # ============ Markdown 渲染 ============

    def _render_markdown_html(self, md: str) -> str:
        """将 Markdown 转换为基本 HTML"""
        css = """
        <style>
        body { font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif; color: #e8ecf1; 
               background: #111827; line-height: 1.8; padding: 10px; }
        h1 { color: #f59e0b; border-bottom: 2px solid rgba(245,158,11,0.3); padding-bottom: 8px; }
        h2 { color: #fbbf24; border-bottom: 1px solid rgba(245,158,11,0.2); padding-bottom: 6px; }
        h3 { color: #fcd34d; }
        strong { color: #f59e0b; }
        em { color: #fbbf24; }
        code { background: #1a2235; padding: 2px 6px; border-radius: 3px; 
               font-family: 'Consolas', monospace; color: #10b981; }
        pre { background: #1a2235; padding: 12px; border-radius: 8px; overflow-x: auto;
              border: 1px solid rgba(255,255,255,0.06); }
        pre code { background: transparent; padding: 0; color: #e8ecf1; }
        table { border-collapse: collapse; width: 100%; margin: 12px 0; }
        th, td { border: 1px solid rgba(255,255,255,0.1); padding: 8px 12px; text-align: left; }
        th { background: #1a2235; color: #f59e0b; font-weight: 600; }
        tr:nth-child(even) { background: rgba(255,255,255,0.02); }
        blockquote { border-left: 3px solid #f59e0b; padding-left: 16px; margin: 12px 0;
                     color: #8b95a8; }
        hr { border: none; border-top: 1px solid rgba(255,255,255,0.08); margin: 16px 0; }
        li { margin: 4px 0; }
        img { max-width: 100%; border-radius: 8px; margin: 8px 0; }
        </style>
        """
        html = md
        # 基本转换
        html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
        html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
        html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
        html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
        html = re.sub(r'`([^`]+)`', r'<code>\1</code>', html)
        html = re.sub(r'```json\n([\s\S]*?)```', r'<pre><code>\1</code></pre>', html)
        html = re.sub(r'^> (.+)$', r'<blockquote>\1</blockquote>', html, flags=re.MULTILINE)
        html = re.sub(r'^- (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
        html = re.sub(r'^---$', r'<hr>', html, flags=re.MULTILINE)
        # 表格行
        html = re.sub(
            r'^\|(.+)\|$',
            lambda m: '<tr>' + ''.join(
                f'<td>{c.strip()}</td>' for c in m.group(1).split('|') if c.strip() and '---' not in c
            ) + '</tr>',
            html, flags=re.MULTILINE
        )
        return f"<html><head>{css}</head><body>{html}</body></html>"

    def copy_markdown(self):
        """复制 Markdown 内容"""
        text = self.markdown_view.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.show_toast("已复制到剪贴板")

    # ============ 历史记录 ============

    def load_history(self):
        worker = ApiTask(self.api_base, "GET", "/api/history?limit=100")
        worker.finished.connect(self._on_history_loaded)
        worker.error.connect(lambda e: self.statusBar().showMessage(f"加载历史失败: {e}"))
        worker.start()

    def _on_history_loaded(self, data: dict):
        items = data.get("items", [])
        self.history_table.setRowCount(len(items))
        for i, item in enumerate(items):
            self.history_table.setItem(i, 0, QTableWidgetItem(f"#{item.get('id', '')}"))
            fname = item.get('filename', '')
            self.history_table.setItem(i, 1, QTableWidgetItem(
                fname[:40] + '...' if len(fname) > 40 else fname))
            self.history_table.setItem(i, 2, QTableWidgetItem(
                item.get('timestamp', '')[:19]))
            status = "成功" if item.get('success') else "失败"
            sitem = QTableWidgetItem(status)
            sitem.setForeground(QColor("#10b981") if item.get('success') else QColor("#ef4444"))
            self.history_table.setItem(i, 3, sitem)
            self.history_table.setItem(i, 4, QTableWidgetItem(
                str(item.get('processing_time', 0))))
            self.history_table.setItem(i, 5, QTableWidgetItem(
                str(item.get('images_count', 0))))

            # 操作按钮
            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(4, 2, 4, 2)
            btn_layout.setSpacing(4)

            report_dir = item.get('report_dir', '')
            report_id = Path(report_dir).name if report_dir else ''
            if report_id:
                view_btn = QPushButton("查看")
                view_btn.setObjectName("ghostBtn")
                view_btn.setMaximumWidth(60)
                view_btn.clicked.connect(lambda checked, rid=report_id: self.view_report_content(rid))
                btn_layout.addWidget(view_btn)

                dl_btn = QPushButton("下载")
                dl_btn.setObjectName("ghostBtn")
                dl_btn.setMaximumWidth(60)
                dl_btn.clicked.connect(lambda checked, rid=report_id: self.download_report(rid))
                btn_layout.addWidget(dl_btn)

            self.history_table.setCellWidget(i, 6, btn_widget)

    # ============ 报告管理 ============

    def load_reports(self):
        worker = ApiTask(self.api_base, "GET", "/api/reports?limit=100")
        worker.finished.connect(self._on_reports_loaded)
        worker.error.connect(lambda e: self.statusBar().showMessage(f"加载报告失败: {e}"))
        worker.start()

    def _on_reports_loaded(self, data: dict):
        reports = data.get("reports", [])
        self.reports_table.setRowCount(len(reports))
        for i, r in enumerate(reports):
            self.reports_table.setItem(i, 0, QTableWidgetItem(r.get('id', '')))
            created = r.get('created_time', '')
            self.reports_table.setItem(i, 1, QTableWidgetItem(
                created[:19] if created else ''))
            has_md = "是" if r.get('has_markdown') else "否"
            md_item = QTableWidgetItem(has_md)
            md_item.setForeground(QColor("#10b981") if r.get('has_markdown') else QColor("#8b95a8"))
            self.reports_table.setItem(i, 2, md_item)

            # 报告大小
            report_path = r.get('path', '')
            size_str = "-"
            if report_path:
                p = Path(report_path)
                if p.exists():
                    total_sz = sum(f.stat().st_size for f in p.rglob('*') if f.is_file())
                    size_str = self._format_size(total_sz)
            self.reports_table.setItem(i, 3, QTableWidgetItem(size_str))

            # 操作按钮
            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(4, 2, 4, 2)
            btn_layout.setSpacing(4)

            rid = r.get('id', '')
            view_btn = QPushButton("查看")
            view_btn.setObjectName("ghostBtn")
            view_btn.setMaximumWidth(60)
            view_btn.clicked.connect(lambda checked, x=rid: self.view_report_content(x))
            btn_layout.addWidget(view_btn)

            dl_btn = QPushButton("下载")
            dl_btn.setObjectName("ghostBtn")
            dl_btn.setMaximumWidth(60)
            dl_btn.clicked.connect(lambda checked, x=rid: self.download_report(x))
            btn_layout.addWidget(dl_btn)

            del_btn = QPushButton("删除")
            del_btn.setMaximumWidth(60)
            del_btn.setStyleSheet(
                "QPushButton { background: transparent; color: #ef4444; border: 1px solid #ef4444; "
                "border-radius: 4px; padding: 4px 8px; }"
                "QPushButton:hover { background: rgba(239,68,68,0.15); }"
            )
            del_btn.clicked.connect(lambda checked, x=rid: self.delete_report(x))
            btn_layout.addWidget(del_btn)

            self.reports_table.setCellWidget(i, 4, btn_widget)

    def view_report_content(self, report_id: str):
        """查看报告 Markdown 内容"""
        worker = ApiTask(self.api_base, "GET", f"/api/report/{report_id}")
        def _on_done(data):
            content = data.get("content", "")
            self.markdown_view.setHtml(self._render_markdown_html(content))
            self.tab_widget.setCurrentIndex(0)
            self.show_toast("报告已加载")
        worker.finished.connect(_on_done)
        worker.error.connect(lambda e: self.show_toast(f"加载报告失败: {e}"))
        worker.start()

    def download_report(self, report_id: str):
        """下载报告 ZIP"""
        save_path, _ = QFileDialog.getSaveFileName(
            self, "保存报告", f"report_{report_id}.zip",
            "ZIP 文件 (*.zip)"
        )
        if not save_path:
            return

        worker = ApiTask(self.api_base, "GET", f"/api/report/{report_id}/download", 
                         raw_response=True)
        def _on_done(data: bytes):
            try:
                with open(save_path, "wb") as f:
                    f.write(data)
                self.show_toast(f"报告已保存到: {save_path}")
            except Exception as e:
                self.show_toast(f"保存失败: {e}")
        worker.finished.connect(_on_done)
        worker.error.connect(lambda e: self.show_toast(f"下载失败: {e}"))
        worker.start()

    def delete_report(self, report_id: str):
        """删除报告"""
        reply = QMessageBox.question(
            self, "确认删除",
            f"确认删除报告 {report_id}？\n此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        worker = ApiTask(self.api_base, "DELETE", f"/api/report/{report_id}")
        worker.finished.connect(lambda d: (
            self.show_toast(f"报告 {report_id} 已删除"),
            self.load_reports()
        ))
        worker.error.connect(lambda e: self.show_toast(f"删除失败: {e}"))
        worker.start()

    # ============ 配置管理 ============

    def load_config(self):
        worker = ApiTask(self.api_base, "GET", "/api/config")
        worker.finished.connect(self._on_config_loaded)
        worker.error.connect(lambda e: self.statusBar().showMessage(f"加载配置失败: {e}"))
        worker.start()

    def _on_config_loaded(self, config: dict):
        self.cfg_api_url.setText(config.get("paddleocr_api_url", ""))
        if config.get("api_key_configured"):
            self.cfg_api_key.setPlaceholderText(config.get("api_key_prefix", "") + " (已配置)")
        model = config.get("paddleocr_model", "PP-StructureV3")
        idx = self.cfg_model.findText(model)
        if idx >= 0:
            self.cfg_model.setCurrentIndex(idx)
        self.cfg_host.setText(config.get("host", "0.0.0.0"))
        self.cfg_port.setValue(config.get("port", 8500))
        self.cfg_max_size.setValue(config.get("max_upload_size_mb", 50))
        idx = self.cfg_log_level.findText(config.get("log_level", "INFO"))
        if idx >= 0:
            self.cfg_log_level.setCurrentIndex(idx)

    def save_api_config(self):
        data = {
            "paddleocr_api_url": self.cfg_api_url.text(),
            "paddleocr_model": self.cfg_model.currentText(),
        }
        if self.cfg_api_key.text():
            data["paddleocr_api_key"] = self.cfg_api_key.text()
        worker = ApiTask(self.api_base, "POST", "/api/config", json_data=data)
        worker.finished.connect(lambda d: self.show_toast("API 配置已保存"))
        worker.error.connect(lambda e: self.show_toast(f"保存失败: {e}"))
        worker.start()

    def save_server_config(self):
        data = {
            "host": self.cfg_host.text(),
            "port": self.cfg_port.value(),
            "max_upload_size_mb": self.cfg_max_size.value(),
        }
        worker = ApiTask(self.api_base, "POST", "/api/config", json_data=data)
        worker.finished.connect(lambda d: self.show_toast("服务器配置已保存（需重启服务生效）"))
        worker.error.connect(lambda e: self.show_toast(f"保存失败: {e}"))
        worker.start()

    def save_process_config(self):
        data = {"log_level": self.cfg_log_level.currentText()}
        worker = ApiTask(self.api_base, "POST", "/api/config", json_data=data)
        worker.finished.connect(lambda d: self.show_toast("处理参数已保存"))
        worker.error.connect(lambda e: self.show_toast(f"保存失败: {e}"))
        worker.start()

    def test_api_connection(self):
        self.show_toast("正在测试连接...")
        worker = ApiTask(self.api_base, "GET", "/api/health")
        def _on_done(data):
            if data.get("status") == "healthy":
                QMessageBox.information(self, "连接测试", "API 服务连接正常")
            else:
                QMessageBox.warning(self, "连接测试", "API 服务响应异常")
        worker.finished.connect(_on_done)
        worker.error.connect(lambda e: QMessageBox.critical(
            self, "连接测试", f"无法连接到 API 服务:\n{e}"))
        worker.start()

    # ============ 服务器状态 ============

    def check_server_status(self):
        worker = ApiTask(self.api_base, "GET", "/api/health")
        def _on_done(data):
            if data.get("status") == "healthy":
                self.server_status_label.setText("🟢 服务正常")
                self.server_status_label.setStyleSheet("color: #10b981; font-size: 11px;")
            else:
                self.server_status_label.setText("🟡 服务异常")
                self.server_status_label.setStyleSheet("color: #f59e0b; font-size: 11px;")
        def _on_error(e):
            self.server_status_label.setText("🔴 连接断开")
            self.server_status_label.setStyleSheet("color: #ef4444; font-size: 11px;")
        worker.finished.connect(_on_done)
        worker.error.connect(_on_error)
        worker.start()

    # ============ 步骤指示器 ============

    def _reset_steps(self):
        for key, lbl in self.step_labels.items():
            lbl.setStyleSheet("color: #4b5563; font-size: 12px; padding: 4px 12px;")

    def _set_step_active(self, step_key: str):
        if step_key in self.step_labels:
            self.step_labels[step_key].setStyleSheet(
                "color: #f59e0b; font-size: 12px; padding: 4px 12px; font-weight: 600;")

    def _set_step_complete(self, step_key: str):
        if step_key in self.step_labels:
            orig_name = {"upload": "上传文件", "analyze": "模型识别", "report": "生成报告"}
            name = orig_name.get(step_key, "")
            self.step_labels[step_key].setText(f"✓ {name}")
            self.step_labels[step_key].setStyleSheet(
                "color: #10b981; font-size: 12px; padding: 4px 12px;")

    # ============ 工具函数 ============

    @staticmethod
    def _format_size(bytes_val: int) -> str:
        if bytes_val < 1024:
            return f"{bytes_val} B"
        elif bytes_val < 1024 * 1024:
            return f"{bytes_val / 1024:.1f} KB"
        return f"{bytes_val / (1024 * 1024):.1f} MB"

    def show_toast(self, message: str):
        self.statusBar().showMessage(message, 4000)

    def _safe_remove_worker(self, worker):
        if worker in self.active_workers:
            self.active_workers.remove(worker)

    def refresh_all(self):
        self.load_history()
        self.load_reports()
        if self.tab_widget.currentIndex() == 3:
            self.load_config()
        self._refresh_nas_status_info()
        self._refresh_nas_browser()
        self.show_toast("已刷新")

    def show_about(self):
        QMessageBox.about(
            self, "关于 Claw",
            "<h2>Claw 错题管理系统 v1.2.0</h2>"
            "<p>基于 PaddleOCR 的智能错题识别与管理系统</p>"
            "<p>独立桌面应用程序 - 不依赖前端浏览器</p><hr>"
            "<p>功能：拖拽/批量上传 → PP-StructureV3 文档结构化分析 → 报告自动生成</p>"
            "<p>技术栈：PyQt6 + httpx + PaddleOCR API</p><hr>"
            "<p>使用前提：请确保后端服务 (main.py) 已启动</p>"
        )

    # ============ 标签页切换事件 ============

    def tab_changed(self, index: int):
        if index == 1:
            self.load_history()
        elif index == 2:
            self.load_reports()
        elif index == 3:
            self.load_config()
        elif index == 4:
            self._refresh_nas_browser()
            self._refresh_nas_status_info()

    def closeEvent(self, event):
        # 停止 NAS 同步服务
        self.sync_service.stop_health_monitor()
        self.sync_service.disconnect()

        # 清理所有活跃线程
        for w in list(self.active_workers):
            if w.isRunning():
                w.quit()
                w.wait(1000)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Claw-Desktop")
    app.setOrganizationName("ClawTeam")

    # 暗色 Palette
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#0a0e17"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e8ecf1"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#111827"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#1a2235"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#1a2235"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#e8ecf1"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e8ecf1"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#1a2235"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e8ecf1"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#f59e0b"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#0a0e17"))
    app.setPalette(palette)

    window = StandaloneApp()
    # 连接标签页切换
    window.tab_widget.currentChanged.connect(window.tab_changed)
    window.show()

    # 启动时加载数据
    QTimer.singleShot(500, window.refresh_all)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
