"""
AppBaseMixin - 主窗口基础功能
包含: 菜单栏, 状态栏, 拖拽支持, 步骤指示器, 公共工具方法
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Dict, Any, TYPE_CHECKING

from PyQt6.QtWidgets import (
    QMessageBox, QStatusBar, QMenuBar, QMenu,
)
from PyQt6.QtGui import QAction, QDragEnterEvent, QDropEvent

from apps.desktop.utils import render_markdown_html, format_size

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QTabWidget, QLabel


class AppBaseMixin:
    """
    基础 Mixin：提供菜单、状态栏、拖拽、步骤指示器等通用功能。
    被 StandaloneApp 多重继承使用。
    """

    # ---- 类型标注（实际属性由 StandaloneApp / 其他 Mixin 设置） ----
    api_base: str
    file_queue: List[Dict]
    processing: bool
    tab_widget: QTabWidget

    # 来自 StandaloneApp
    active_workers: list

    # 来自 upload_mixin
    step_labels: Dict[str, QLabel]
    add_files_to_queue: Any
    select_files: Any
    select_folder: Any

    # 来自 history_mixin
    load_history: Any

    # 来自 reports_mixin
    load_reports: Any

    # 来自 config_mixin
    load_config: Any

    # ============ 菜单栏 ============

    def setup_menu(self):
        menubar: QMenuBar = self.menuBar()  # type: ignore[attr-defined]
        assert menubar is not None
        file_menu: QMenu = menubar.addMenu("文件(&F)")  # type: ignore[assignment]
        assert file_menu is not None

        open_action = QAction("选择文件...", self)  # type: ignore[arg-type]
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.select_files)  # type: ignore[arg-type]
        file_menu.addAction(open_action)

        folder_action = QAction("选择文件夹...", self)  # type: ignore[arg-type]
        folder_action.setShortcut("Ctrl+Shift+O")
        folder_action.triggered.connect(self.select_folder)  # type: ignore[arg-type]
        file_menu.addAction(folder_action)

        file_menu.addSeparator()
        exit_action = QAction("退出", self)  # type: ignore[arg-type]
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)  # type: ignore[arg-type]
        file_menu.addAction(exit_action)

        tools_menu: QMenu = menubar.addMenu("工具(&T)")  # type: ignore[assignment]
        assert tools_menu is not None
        refresh_action = QAction("刷新全部", self)  # type: ignore[arg-type]
        refresh_action.setShortcut("F5")
        refresh_action.triggered.connect(self.refresh_all)
        tools_menu.addAction(refresh_action)

        help_menu: QMenu = menubar.addMenu("帮助(&H)")  # type: ignore[assignment]
        assert help_menu is not None
        about_action = QAction("关于...", self)  # type: ignore[arg-type]
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    # ============ 状态栏 ============

    def setup_statusbar(self):
        sb: QStatusBar = self.statusBar()  # type: ignore[attr-defined]
        assert sb is not None
        sb.showMessage("就绪 - API Token 已内置，可直接使用")

    # ============ 拖拽支持 ============

    def dragEnterEvent(self, event: QDragEnterEvent):
        md = event.mimeData()
        if md is not None and md.hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        md = event.mimeData()
        if md is None:
            return
        urls = md.urls()
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

    # ============ 步骤指示器 ============

    def _reset_steps(self):
        for lbl in self.step_labels.values():
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
    def _render_markdown_html(md: str, report_dir: str = "") -> str:
        return render_markdown_html(md, report_dir=report_dir, api_base="")

    @staticmethod
    def _format_size(bytes_val: int) -> str:
        return format_size(bytes_val)

    def show_toast(self, message: str):
        self._show_status(message, 4000)

    def _show_status(self, message: str, timeout: int = 0):
        sb = self.statusBar()  # type: ignore[attr-defined]
        if sb is not None:
            if timeout > 0:
                sb.showMessage(message, timeout)
            else:
                sb.showMessage(message)

    def _safe_remove_worker(self, worker):
        if worker in self.active_workers:
            self.active_workers.remove(worker)

    def refresh_all(self):
        if getattr(self, '_shutting_down', False):
            return
        try:
            self.load_history()
            self.load_reports()
            if self.tab_widget.currentIndex() == 3:
                self.load_config()
            self.show_toast("已刷新")
        except Exception as e:
            print(f"[Claw] refresh_all 异常: {e}", flush=True)
            import traceback
            traceback.print_exc()

    def show_about(self):
        QMessageBox.about(
            self,  # type: ignore[arg-type]
            "关于 Claw",
            "<h2>Claw 错题管理系统 v1.3.0</h2>"
            "<p>基于 PaddleOCR 的智能错题识别与管理系统</p>"
            "<p>独立桌面应用程序 - API Token 已内置，开箱即用</p><hr>"
            "<p>功能：拖拽/批量上传 → PaddleOCR-VL 文档结构化分析 → 报告自动生成</p>"
            "<p>技术栈：PyQt6 + httpx + PaddleOCR API</p>"
        )

    # ============ 标签页切换 ============

    def tab_changed(self, index: int):
        if getattr(self, '_shutting_down', False):
            return
        try:
            if index == 1:
                self.load_history()
            elif index == 2:
                self.load_reports()
            elif index == 3:
                self.load_config()
        except Exception as e:
            print(f"[Claw] tab_changed({index}) 异常: {e}", flush=True)
            import traceback
            traceback.print_exc()
