"""
HistoryTabMixin - 处理历史记录标签页
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox,
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
    show_toast: Any

    def create_history_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)

        action_bar = QHBoxLayout()
        action_bar.addStretch()
        self.batch_del_btn = QPushButton("批量删除")
        self.batch_del_btn.setEnabled(False)
        self.batch_del_btn.setStyleSheet(
            "QPushButton { background: rgba(239,68,68,38); color: #f87171; border: 1px solid #ef4444; "
            "border-radius: 4px; padding: 5px 12px; font-size: 14px; font-weight: 500; }"
            "QPushButton:hover { background: rgba(239,68,68,76); }"
            "QPushButton:disabled { background: transparent; color: #555; border-color: #444; }"
        )
        self.batch_del_btn.clicked.connect(self.batch_delete_history)
        action_bar.addWidget(self.batch_del_btn)
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
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.history_table.setColumnWidth(3, 50)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        vhdr = self.history_table.verticalHeader()
        assert vhdr is not None
        vhdr.setDefaultSectionSize(36)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        # 使用 selectionModel().selectionChanged 替代 itemSelectionChanged
        # itemSelectionChanged 在 SelectRows + cellWidget 组合下不可靠
        sm = self.history_table.selectionModel()
        if sm is not None:
            sm.selectionChanged.connect(self._on_history_selection_changed)
        layout.addWidget(self.history_table)

        self.tab_widget.addTab(tab, "处理记录")

    def load_history(self):
        worker = ApiTask(self.api_base, "GET", "/api/history?limit=100")
        worker.finished.connect(self._on_history_loaded)
        worker.error.connect(lambda e: self._show_status(f"加载历史失败: {e}"))
        worker.start()

    def _on_history_loaded(self, data: dict):
        try:
            items = data.get("items", []) or []
            # 阻止填充期间触发 itemSelectionChanged 信号
            self.history_table.blockSignals(True)
            self.history_table.setRowCount(len(items))
            for i, item in enumerate(items):
                history_id = item.get('id', '')
                self.history_table.setItem(i, 0, QTableWidgetItem(f"#{history_id}"))
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
                btn_layout.setContentsMargins(6, 4, 6, 4)
                btn_layout.setSpacing(8)

                report_dir = item.get('report_dir', '')
                report_id = Path(report_dir).name if report_dir else ''
                if report_id:
                    view_btn = QPushButton("查看")
                    view_btn.setMinimumWidth(60)
                    view_btn.setStyleSheet(
                        "QPushButton { background: rgba(59,130,246,30); color: #60a5fa; border: 1px solid #3b82f6; "
                        "border-radius: 4px; padding: 4px 10px; font-size: 13px; font-weight: 500; }"
                        "QPushButton:hover { background: rgba(59,130,246,64); }"
                    )
                    view_btn.clicked.connect(lambda checked, rid=report_id: self.view_report_content(rid))
                    btn_layout.addWidget(view_btn)

                    dl_btn = QPushButton("下载")
                    dl_btn.setMinimumWidth(60)
                    dl_btn.setStyleSheet(
                        "QPushButton { background: rgba(6,182,212,30); color: #22d3ee; border: 1px solid #06b6d4; "
                        "border-radius: 4px; padding: 4px 10px; font-size: 13px; font-weight: 500; }"
                        "QPushButton:hover { background: rgba(6,182,212,64); }"
                    )
                    dl_btn.clicked.connect(lambda checked, rid=report_id: self.download_report(rid))
                    btn_layout.addWidget(dl_btn)

                del_btn = QPushButton("删除")
                del_btn.setMinimumWidth(60)
                del_btn.setStyleSheet(
                    "QPushButton { background: rgba(239,68,68,30); color: #f87171; border: 1px solid #ef4444; "
                    "border-radius: 4px; padding: 4px 10px; font-size: 13px; font-weight: 500; }"
                    "QPushButton:hover { background: rgba(239,68,68,64); }"
                )
                del_btn.clicked.connect(lambda checked, hid=history_id: self.delete_history(hid))
                btn_layout.addWidget(del_btn)

                self.history_table.setCellWidget(i, 6, btn_widget)
                self.history_table.setRowHeight(i, 75)
            # 恢复信号
            self.history_table.blockSignals(False)
        except Exception as e:
            self.history_table.blockSignals(False)
            import traceback
            print(f"[Claw] _on_history_loaded 异常: {e}", flush=True)
            traceback.print_exc()
        # 显式刷新批量删除按钮状态（确保与当前选择一致）
        self._on_history_selection_changed()

    def delete_history(self, history_id: str):
        reply = QMessageBox.question(
            self,  # type: ignore[arg-type]
            "确认删除",
            f"确认删除历史记录 #{history_id}？\n此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        worker = ApiTask(self.api_base, "DELETE", f"/api/history/{history_id}")
        worker.finished.connect(lambda d: (
            self.show_toast(f"记录 #{history_id} 已删除"),
            self.load_history()
        ))
        worker.error.connect(lambda e: self.show_toast(f"删除失败: {e}"))
        worker.start()

    def _on_history_selection_changed(self, *_args):
        """选中行变化时更新批量删除按钮状态"""
        try:
            sm = self.history_table.selectionModel()
            if sm is None:
                return
            count = len(sm.selectedRows())
            self.batch_del_btn.setEnabled(count > 0)
        except Exception:
            pass

    def batch_delete_history(self):
        sm = self.history_table.selectionModel()
        if sm is None:
            return
        selected_rows = sorted(set(index.row() for index in sm.selectedRows()))
        if not selected_rows:
            return

        history_ids = []
        for row in sorted(selected_rows):
            id_item = self.history_table.item(row, 0)
            if id_item:
                text = id_item.text()
                # 去掉前缀 #
                history_ids.append(text.lstrip('#'))

        reply = QMessageBox.question(
            self,  # type: ignore[arg-type]
            "确认批量删除",
            f"确认删除选中的 {len(history_ids)} 条历史记录？\n\n"
            + "\n".join(f"  - #{hid}" for hid in history_ids[:5])
            + (f"\n  ... 等 {len(history_ids)} 项" if len(history_ids) > 5 else "")
            + "\n\n此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        worker = ApiTask(self.api_base, "POST", "/api/history/batch-delete",
                         json_data={"ids": history_ids})
        worker.finished.connect(lambda d: (
            self.show_toast(d.get("message", f"已删除 {len(history_ids)} 条记录")),
            self.load_history()
        ))
        worker.error.connect(lambda e: self.show_toast(f"批量删除失败: {e}"))
        worker.start()
