"""
HistoryTabMixin - 处理历史记录标签页
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView,
)
from PyQt6.QtGui import QColor

from apps.desktop.workers.api_task import ApiTask

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QTabWidget, QTextEdit


class HistoryTabMixin:
    """处理历史记录标签页 Mixin"""

    api_base: str
    markdown_view: QTextEdit
    tab_widget: QTabWidget
    history_table: QTableWidget

    # 来自 AppBaseMixin
    _show_status: Any

    # 来自 reports_mixin
    view_report_content: Any
    download_report: Any

    def create_history_tab(self):
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
        header = self.history_table.horizontalHeader()
        assert header is not None
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        layout.addWidget(self.history_table)

        self.tab_widget.addTab(tab, "处理记录")

    def load_history(self):
        worker = ApiTask(self.api_base, "GET", "/api/history?limit=100")
        worker.finished.connect(self._on_history_loaded)
        worker.error.connect(lambda e: self._show_status(f"加载历史失败: {e}"))
        worker.start()

    def _on_history_loaded(self, data: dict):
        items = data.get("items", []) or []
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
