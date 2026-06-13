"""
ReportsTabMixin - 报告中心标签页
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog, QMessageBox,
)
from PyQt6.QtGui import QColor

from apps.desktop.workers.api_task import ApiTask

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QTabWidget, QTextEdit


class ReportsTabMixin:
    """报告中心标签页 Mixin"""

    api_base: str
    markdown_view: QTextEdit
    tab_widget: QTabWidget
    reports_table: QTableWidget

    # 来自 AppBaseMixin
    _show_status: Any
    _format_size: Any
    _render_markdown_html: Any
    show_toast: Any

    def create_reports_tab(self):
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
        hdr = self.reports_table.horizontalHeader()
        assert hdr is not None
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.reports_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.reports_table)

        self.tab_widget.addTab(tab, "报告中心")

    def load_reports(self):
        worker = ApiTask(self.api_base, "GET", "/api/reports?limit=100")
        worker.finished.connect(self._on_reports_loaded)
        worker.error.connect(lambda e: self._show_status(f"加载报告失败: {e}"))
        worker.start()

    def _on_reports_loaded(self, data: dict):
        reports = data.get("reports", []) or []
        self.reports_table.setRowCount(len(reports))
        for i, r in enumerate(reports):
            self.reports_table.setItem(i, 0, QTableWidgetItem(str(r.get('id', ''))))
            created = r.get('created_time', '')
            self.reports_table.setItem(i, 1, QTableWidgetItem(
                str(created)[:19] if created else ''))
            has_md = "是" if r.get('has_markdown') else "否"
            md_item = QTableWidgetItem(has_md)
            md_item.setForeground(QColor("#10b981") if r.get('has_markdown') else QColor("#8b95a8"))
            self.reports_table.setItem(i, 2, md_item)

            report_path = r.get('path', '')
            size_str = "-"
            if report_path:
                try:
                    p = Path(report_path)
                    if p.exists():
                        total_sz = sum(f.stat().st_size for f in p.rglob('*') if f.is_file())
                        size_str = self._format_size(total_sz)
                except Exception:
                    size_str = "-"
            self.reports_table.setItem(i, 3, QTableWidgetItem(size_str))

            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(4, 2, 4, 2)
            btn_layout.setSpacing(4)

            rid = r.get('id', '')
            view_btn = QPushButton("查看")
            view_btn.setMaximumWidth(70)
            view_btn.setStyleSheet(
                "QPushButton { background: rgba(59,130,246,0.12); color: #60a5fa; border: 1px solid #3b82f6; "
                "border-radius: 4px; padding: 4px 8px; font-size: 13px; font-weight: 500; }"
                "QPushButton:hover { background: rgba(59,130,246,0.25); }"
            )
            view_btn.clicked.connect(lambda checked, x=rid: self.view_report_content(x))
            btn_layout.addWidget(view_btn)

            dl_btn = QPushButton("下载")
            dl_btn.setMaximumWidth(70)
            dl_btn.setStyleSheet(
                "QPushButton { background: rgba(6,182,212,0.12); color: #22d3ee; border: 1px solid #06b6d4; "
                "border-radius: 4px; padding: 4px 8px; font-size: 13px; font-weight: 500; }"
                "QPushButton:hover { background: rgba(6,182,212,0.25); }"
            )
            dl_btn.clicked.connect(lambda checked, x=rid: self.download_report(x))
            btn_layout.addWidget(dl_btn)

            del_btn = QPushButton("删除")
            del_btn.setMaximumWidth(70)
            del_btn.setStyleSheet(
                "QPushButton { background: rgba(239,68,68,0.12); color: #f87171; border: 1px solid #ef4444; "
                "border-radius: 4px; padding: 4px 8px; font-size: 13px; font-weight: 500; }"
                "QPushButton:hover { background: rgba(239,68,68,0.25); }"
            )
            del_btn.clicked.connect(lambda checked, x=rid: self.delete_report(x))
            btn_layout.addWidget(del_btn)

            self.reports_table.setCellWidget(i, 4, btn_widget)

    def view_report_content(self, report_id: str):
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
        save_path, _ = QFileDialog.getSaveFileName(
            self,  # type: ignore[arg-type]
            "保存报告", f"report_{report_id}.zip",
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
            except Exception as ex:
                self.show_toast(f"保存失败: {ex}")
        worker.finished.connect(_on_done)
        worker.error.connect(lambda e: self.show_toast(f"下载失败: {e}"))
        worker.start()

    def delete_report(self, report_id: str):
        reply = QMessageBox.question(
            self,  # type: ignore[arg-type]
            "确认删除",
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
