"""
错题管理系统 - PyQt6 桌面管理控制台
"""
import sys
import os
import json
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QPushButton, QLabel, QLineEdit, QTextEdit,
    QFileDialog, QProgressBar, QTableWidget, QTableWidgetItem,
    QHeaderView, QSplitter, QFrame, QGroupBox, QFormLayout,
    QSpinBox, QDoubleSpinBox, QCheckBox, QComboBox, QMessageBox,
    QStatusBar, QMenuBar, QMenu, QToolBar, QStyle, QSizePolicy,
    QScrollArea, QGridLayout,
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QSize, QUrl,
)
from PyQt6.QtGui import (
    QAction, QIcon, QFont, QColor, QPalette, QPixmap,
    QImage, QPainter, QPen, QBrush,
)
import httpx
from PIL import Image
import io
import base64


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
QTabWidget::tab-bar {
    left: 8px;
}
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
QTabBar::tab:hover {
    color: #e8ecf1;
}
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
QPushButton:pressed {
    background-color: #162032;
}
QPushButton#primaryBtn {
    background-color: #f59e0b;
    color: #0a0e17;
    border: none;
}
QPushButton#primaryBtn:hover {
    background-color: #fbbf24;
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
QComboBox::drop-down {
    border: none;
}
QComboBox QAbstractItemView {
    background-color: #1a2235;
    color: #e8ecf1;
    selection-background-color: rgba(245,158,11,0.2);
}
QProgressBar {
    background-color: #1a2235;
    border: none;
    border-radius: 4px;
    height: 6px;
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
QScrollBar::handle:vertical:hover {
    background: rgba(255,255,255,0.2);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
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
QMenuBar::item:selected {
    background-color: #1a2235;
}
QMenu {
    background-color: #1a2235;
    color: #e8ecf1;
    border: 1px solid rgba(255,255,255,0.08);
}
QMenu::item:selected {
    background-color: rgba(245,158,11,0.2);
}
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
"""


class ApiWorker(QThread):
    """API异步工作线程"""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(int, str)

    def __init__(self, api_base: str, file_path: str, parent=None):
        super().__init__(parent)
        self.api_base = api_base
        self.file_path = file_path

    def run(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self._process())
            loop.close()
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))

    async def _process(self):
        # 上传
        self.progress.emit(10, "上传文件中...")
        async with httpx.AsyncClient(timeout=120.0) as client:
            with open(self.file_path, "rb") as f:
                files = {"file": (Path(self.file_path).name, f)}
                upload_res = await client.post(f"{self.api_base}/api/upload", files=files)
                upload_res.raise_for_status()
                upload_data = upload_res.json()

            file_id = upload_data["file_id"]
            self.progress.emit(25, "提交PP-StructureV3任务中...")

            # 处理（PP-StructureV3 一步完成版面分析+OCR识别+表格/公式识别）
            self.progress.emit(40, "AI处理中...")
            self.progress.emit(60, "下载结果中...")
            process_res = await client.post(f"{self.api_base}/api/process/{file_id}")
            process_res.raise_for_status()
            process_data = process_res.json()

            self.progress.emit(85, "生成报告中...")
            self.progress.emit(100, "处理完成")

            return process_data


class ImageViewer(QLabel):
    """图片查看器"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 200)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: #0a0e17; border: 1px solid rgba(255,255,255,0.06); border-radius: 8px;")
        self.setText("暂无图片")

    def display_image(self, image_data: bytes):
        pixmap = QPixmap()
        pixmap.loadFromData(image_data)
        scaled = pixmap.scaled(
            self.width() - 20, self.height() - 20,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.setPixmap(scaled)


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()
        self.api_base = "http://127.0.0.1:8500"
        self.current_file_path: Optional[str] = None
        self.setup_ui()
        self.setup_menu()
        self.setup_statusbar()
        self.check_server_status()

        # 定时检查服务器状态
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.check_server_status)
        self.status_timer.start(15000)

    def setup_ui(self):
        self.setWindowTitle("Claw - 错题管理系统")
        self.setMinimumSize(1200, 750)
        self.setStyleSheet(DARK_STYLE)

        # 中央组件
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(16, 12, 16, 12)
        main_layout.setSpacing(12)

        # 标题栏
        title_layout = QHBoxLayout()
        title = QLabel("Claw 错题管理系统")
        title.setObjectName("sectionTitle")
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

        # 创建标签页
        self.create_process_tab()
        self.create_history_tab()
        self.create_reports_tab()
        self.create_config_tab()

    def create_process_tab(self):
        """处理标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(16)

        # 上传区域
        upload_group = QGroupBox("图片上传与处理")
        upload_layout = QVBoxLayout(upload_group)

        # 文件选择
        file_layout = QHBoxLayout()
        self.file_path_edit = QLineEdit()
        self.file_path_edit.setPlaceholderText("选择要处理的图片文件...")
        self.file_path_edit.setReadOnly(True)
        file_layout.addWidget(self.file_path_edit)

        browse_btn = QPushButton("选择文件")
        browse_btn.clicked.connect(self.browse_file)
        file_layout.addWidget(browse_btn)

        self.upload_btn = QPushButton("上传并处理")
        self.upload_btn.setObjectName("primaryBtn")
        self.upload_btn.clicked.connect(self.process_image)
        self.upload_btn.setEnabled(False)
        file_layout.addWidget(self.upload_btn)

        upload_layout.addLayout(file_layout)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        upload_layout.addWidget(self.progress_bar)

        self.progress_label = QLabel("")
        self.progress_label.setVisible(False)
        self.progress_label.setStyleSheet("color: #8b95a8; font-size: 12px;")
        upload_layout.addWidget(self.progress_label)

        layout.addWidget(upload_group)

        # 图片预览
        preview_splitter = QSplitter(Qt.Orientation.Horizontal)

        # 原始图片
        orig_container = QWidget()
        orig_layout = QVBoxLayout(orig_container)
        orig_layout.setContentsMargins(0, 0, 0, 0)
        orig_label = QLabel("原始图片")
        orig_label.setStyleSheet("font-weight: 600; color: #8b95a8; padding: 4px 0;")
        orig_layout.addWidget(orig_label)
        self.orig_viewer = ImageViewer()
        orig_layout.addWidget(self.orig_viewer)
        preview_splitter.addWidget(orig_container)

        # 版面分析图片
        layout_container = QWidget()
        layout_layout = QVBoxLayout(layout_container)
        layout_layout.setContentsMargins(0, 0, 0, 0)
        layout_label = QLabel("版面分析图片")
        layout_label.setStyleSheet("font-weight: 600; color: #8b95a8; padding: 4px 0;")
        layout_layout.addWidget(layout_label)
        self.layout_viewer = ImageViewer()
        layout_layout.addWidget(self.layout_viewer)
        preview_splitter.addWidget(layout_container)

        layout.addWidget(preview_splitter)

        # 结果文本
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setPlaceholderText("处理结果将在此显示...")
        self.result_text.setMaximumHeight(200)
        layout.addWidget(self.result_text)

        self.tab_widget.addTab(tab, "📤 上传处理")

    def create_history_tab(self):
        """历史记录标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # 操作栏
        action_layout = QHBoxLayout()
        action_layout.addStretch()
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.load_history)
        action_layout.addWidget(refresh_btn)
        layout.addLayout(action_layout)

        # 表格
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(6)
        self.history_table.setHorizontalHeaderLabels([
            "编号", "文件名", "时间", "状态", "耗时(s)", "识别页数"
        ])
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.history_table)

        self.tab_widget.addTab(tab, "📋 处理记录")

    def create_reports_tab(self):
        """报告中心标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        action_layout = QHBoxLayout()
        action_layout.addStretch()
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.load_reports)
        action_layout.addWidget(refresh_btn)
        layout.addLayout(action_layout)

        self.reports_table = QTableWidget()
        self.reports_table.setColumnCount(4)
        self.reports_table.setHorizontalHeaderLabels([
            "报告ID", "创建时间", "包含Markdown", "操作"
        ])
        self.reports_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.reports_table)

        self.tab_widget.addTab(tab, "📄 报告中心")

    def create_config_tab(self):
        """配置标签页"""
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(16)

        # API配置
        api_group = QGroupBox("PaddleOCR API 配置 (百度AI Studio PP-StructureV3)")
        api_form = QFormLayout(api_group)
        api_hint = QLabel("从 aistudio.baidu.com/paddleocr/task 获取 API_URL 和 TOKEN")
        api_hint.setStyleSheet("color: #8b95a8; font-size: 11px; margin-bottom: 8px;")
        api_form.addRow(api_hint)
        self.cfg_api_url = QLineEdit()
        self.cfg_api_url.setPlaceholderText("https://aistudio.baidu.com/paddleocr/api/xxx")
        self.cfg_api_key = QLineEdit()
        self.cfg_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.cfg_api_key.setPlaceholderText("请输入TOKEN")
        api_form.addRow("API 地址:", self.cfg_api_url)
        api_form.addRow("TOKEN:", self.cfg_api_key)
        api_btn_layout = QHBoxLayout()
        save_api_btn = QPushButton("保存API配置")
        save_api_btn.setObjectName("primaryBtn")
        save_api_btn.clicked.connect(self.save_api_config)
        api_btn_layout.addWidget(save_api_btn)
        test_btn = QPushButton("测试连接")
        test_btn.clicked.connect(self.test_connection)
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

        layout.addStretch()
        scroll.setWidget(container)
        self.tab_widget.addTab(scroll, "⚙️ 系统配置")

    def setup_menu(self):
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu("文件(&F)")
        open_action = QAction("打开图片...", self)
        open_action.triggered.connect(self.browse_file)
        file_menu.addAction(open_action)
        file_menu.addSeparator()
        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # 工具菜单
        tools_menu = menubar.addMenu("工具(&T)")
        refresh_action = QAction("刷新所有", self)
        refresh_action.triggered.connect(self.refresh_all)
        tools_menu.addAction(refresh_action)

        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")
        about_action = QAction("关于", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def setup_statusbar(self):
        self.statusBar().showMessage("就绪")

    # ============ 功能实现 ============

    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择图片文件", "",
            "图片文件 (*.jpg *.jpeg *.png *.bmp *.webp *.tiff);;所有文件 (*)"
        )
        if file_path:
            self.current_file_path = file_path
            self.file_path_edit.setText(file_path)
            self.upload_btn.setEnabled(True)

            # 显示预览
            with open(file_path, "rb") as f:
                self.orig_viewer.display_image(f.read())

    def process_image(self):
        if not self.current_file_path:
            QMessageBox.warning(self, "提示", "请先选择图片文件")
            return

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_label.setVisible(True)
        self.upload_btn.setEnabled(False)

        self.worker = ApiWorker(self.api_base, self.current_file_path)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_process_finished)
        self.worker.error.connect(self.on_process_error)
        self.worker.start()

    def on_progress(self, value: int, text: str):
        self.progress_bar.setValue(value)
        self.progress_label.setText(text)

    def on_process_finished(self, data: dict):
        self.upload_btn.setEnabled(True)

        if data.get("success"):
            self.result_text.setPlainText(
                f"处理成功！\n"
                f"耗时: {data.get('processing_time', 0)}秒\n"
                f"报告目录: {data.get('report_dir', 'N/A')}"
            )

            # 显示版面分析图片（如果有）
            if data.get("layout_image_base64"):
                img_data = base64.b64decode(data["layout_image_base64"])
                self.layout_viewer.display_image(img_data)

            QMessageBox.information(self, "处理完成", "图片处理成功！")
        else:
            self.result_text.setPlainText(f"处理失败: {data.get('error', '未知错误')}")
            QMessageBox.warning(self, "处理警告", data.get('error', '处理过程中出现问题'))

        self.load_history()

    def on_process_error(self, error: str):
        self.upload_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        self.result_text.setPlainText(f"错误: {error}")
        QMessageBox.critical(self, "处理失败", f"发生错误:\n{error}")

    async def _async_request(self, method: str, url: str, **kwargs):
        async with httpx.AsyncClient(timeout=30.0) as client:
            if method == "GET":
                resp = await client.get(url, **kwargs)
            elif method == "POST":
                resp = await client.post(url, **kwargs)
            elif method == "DELETE":
                resp = await client.delete(url, **kwargs)
            else:
                raise ValueError(f"不支持的方法: {method}")
            resp.raise_for_status()
            return resp.json()

    def _sync_request(self, method: str, endpoint: str, **kwargs):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                self._async_request(method, f"{self.api_base}{endpoint}", **kwargs)
            )
            return result
        finally:
            loop.close()

    def load_history(self):
        try:
            data = self._sync_request("GET", "/api/history?limit=100")
            items = data.get("items", [])
            self.history_table.setRowCount(len(items))
            for i, item in enumerate(items):
                self.history_table.setItem(i, 0, QTableWidgetItem(f"#{item.get('id', '')}"))
                self.history_table.setItem(i, 1, QTableWidgetItem(item.get('filename', '')))
                self.history_table.setItem(i, 2, QTableWidgetItem(item.get('timestamp', '')))
                status = "成功" if item.get('success') else "失败"
                status_item = QTableWidgetItem(status)
                status_item.setForeground(QColor("#10b981") if item.get('success') else QColor("#ef4444"))
                self.history_table.setItem(i, 3, status_item)
                self.history_table.setItem(i, 4, QTableWidgetItem(str(item.get('processing_time', 0))))
                self.history_table.setItem(i, 5, QTableWidgetItem(str(item.get('extracted_pages', 0))))
        except Exception as e:
            self.statusBar().showMessage(f"加载历史失败: {e}")

    def load_reports(self):
        try:
            data = self._sync_request("GET", "/api/reports?limit=100")
            reports = data.get("reports", [])
            self.reports_table.setRowCount(len(reports))
            for i, r in enumerate(reports):
                self.reports_table.setItem(i, 0, QTableWidgetItem(r.get('id', '')))
                self.reports_table.setItem(i, 1, QTableWidgetItem(r.get('created_time', '')))
                has_md = "是" if r.get('has_markdown') else "否"
                self.reports_table.setItem(i, 2, QTableWidgetItem(has_md))
                view_btn = QPushButton("查看")
                view_btn.clicked.connect(lambda checked, rid=r['id']: self.view_report(rid))
                self.reports_table.setCellWidget(i, 3, view_btn)
        except Exception as e:
            self.statusBar().showMessage(f"加载报告失败: {e}")

    def view_report(self, report_id: str):
        try:
            data = self._sync_request("GET", f"/api/report/{report_id}")
            self.result_text.setPlainText(data.get('content', ''))
            self.tab_widget.setCurrentIndex(0)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"加载报告失败: {e}")

    def save_api_config(self):
        try:
            self._sync_request("POST", "/api/config", json={
                "paddleocr_api_url": self.cfg_api_url.text(),
                "paddleocr_api_key": self.cfg_api_key.text(),
            })
            QMessageBox.information(self, "成功", "API配置已保存")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")

    def save_server_config(self):
        try:
            self._sync_request("POST", "/api/config", json={
                "host": self.cfg_host.text(),
                "port": self.cfg_port.value(),
                "max_upload_size_mb": self.cfg_max_size.value(),
            })
            QMessageBox.information(self, "成功", "服务器配置已保存（需重启服务生效）")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")

    def save_process_config(self):
        try:
            self._sync_request("POST", "/api/config", json={
                "log_level": self.cfg_log_level.currentText(),
            })
            QMessageBox.information(self, "成功", "处理参数已保存")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")

    def test_connection(self):
        try:
            data = self._sync_request("GET", "/api/health")
            if data.get("status") == "healthy":
                QMessageBox.information(self, "连接测试", "API服务连接正常")
            else:
                QMessageBox.warning(self, "连接测试", "API服务响应异常")
        except Exception as e:
            QMessageBox.critical(self, "连接测试", f"无法连接到API服务:\n{e}")

    def check_server_status(self):
        try:
            data = self._sync_request("GET", "/api/health")
            if data.get("status") == "healthy":
                self.server_status_label.setText("🟢 服务正常")
                self.server_status_label.setStyleSheet("color: #10b981; font-size: 11px;")
            else:
                self.server_status_label.setText("🟡 服务异常")
                self.server_status_label.setStyleSheet("color: #f59e0b; font-size: 11px;")
        except Exception:
            self.server_status_label.setText("🔴 连接断开")
            self.server_status_label.setStyleSheet("color: #ef4444; font-size: 11px;")

    def refresh_all(self):
        self.load_history()
        self.load_reports()
        self.statusBar().showMessage("已刷新", 2000)

    def show_about(self):
        QMessageBox.about(
            self, "关于 Claw",
            "<h2>Claw 错题管理系统 v1.0.0</h2>"
            "<p>基于PaddleOCR的智能错题识别与管理系统</p>"
            "<p>功能：图片上传、PP-StructureV3 文档结构化分析、报告生成</p>"
            "<hr>"
            "<p>技术栈：FastAPI + PyQt6 + PaddleOCR (PP-StructureV3)</p>"
        )


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Claw")
    app.setOrganizationName("ClawTeam")

    # 设置暗色主题
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#0a0e17"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e8ecf1"))
    app.setPalette(palette)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
