"""
HistoryTabMixin - 处理历史记录标签页
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QCheckBox,
)
from PyQt6.QtGui import QColor
from PyQt6.QtCore import Qt

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
        # 用内部集合追踪选中的 history_id，不依赖 cellWidget 状态查询
        self._selected_ids: set[str] = set()
        self._all_history_ids: list[str] = []  # 按表格行顺序存储
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)

        action_bar = QHBoxLayout()
        action_bar.addStretch()
        # 全选/取消全选
        self.history_select_all_cb = QCheckBox("全选")
        self.history_select_all_cb.setStyleSheet("color: #9ca3af; font-size: 13px;")
        self.history_select_all_cb.stateChanged.connect(self._on_select_all_changed)
        action_bar.addWidget(self.history_select_all_cb)
        self.history_batch_del_btn = QPushButton("批量删除")
        self.history_batch_del_btn.setEnabled(False)
        self.history_batch_del_btn.setStyleSheet(
            "QPushButton { background: rgba(239,68,68,38); color: #f87171; border: 1px solid #ef4444; "
            "border-radius: 4px; padding: 5px 12px; font-size: 14px; font-weight: 500; }"
            "QPushButton:hover { background: rgba(239,68,68,76); }"
            "QPushButton:disabled { background: transparent; color: #555; border-color: #444; }"
        )
        self.history_batch_del_btn.clicked.connect(self.batch_delete_history)
        action_bar.addWidget(self.history_batch_del_btn)
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.load_history)
        action_bar.addWidget(refresh_btn)
        layout.addLayout(action_bar)

        self.history_table = QTableWidget()
        self.history_table.setCornerButtonEnabled(False)
        self.history_table.setColumnCount(8)  # +1 checkbox 列
        self.history_table.setHorizontalHeaderLabels([
            "", "编号", "文件名", "时间", "状态", "耗时(s)", "图片数", "操作"
        ])
        header = self.history_table.horizontalHeader()
        assert header is not None
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.history_table.setColumnWidth(0, 36)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.history_table.setColumnWidth(4, 50)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        vhdr = self.history_table.verticalHeader()
        assert vhdr is not None
        vhdr.setDefaultSectionSize(36)
        # 不再依赖行选择模式，改用 checkbox 列控制批量操作
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)

        # 暗色样式
        self.history_table.setStyleSheet(
            "QTableWidget {"
            "  gridline-color: #2d3748;"
            "  background: #111827; color: #e8ecf1;"
            "  border: 1px solid #2d3748; border-radius: 4px;"
            "}"
            "QTableWidget::section {"
            "  background: #1a2235; color: #9ca3af; padding: 6px 8px;"
            "  border: none; border-bottom: 1px solid #2d3748;"
            "  border-right: 1px solid #2d3748; font-weight: 600;"
            "}"
            "QTableCornerButton::section {"
            "  background: #1a2235; color: #9ca3af;"
            "  border: 1px solid #2d3748; border-top-left-radius: 3px;"
            "}"
        )
        # 用 itemChanged 处理 checkbox 列变化（比 cellWidget QCheckBox 可靠得多）
        self.history_table.itemChanged.connect(self._on_table_item_changed)
        layout.addWidget(self.history_table)

        # 隐藏表格左上角默认的白色全选按钮（corner button）
        from PyQt6.QtWidgets import QAbstractButton
        corner_btn = self.history_table.findChild(QAbstractButton)
        if corner_btn is not None:
            corner_btn.hide()

        self.tab_widget.addTab(tab, "处理记录")

    def load_history(self):
        worker = ApiTask(self.api_base, "GET", "/api/history?limit=100")
        worker.finished.connect(self._on_history_loaded)
        worker.error.connect(lambda e: self._show_status(f"加载历史失败: {e}"))
        worker.start()

    # ═══════════════════════════════════════════════════════
    #  选择状态管理（基于内部集合，不依赖 cellWidget 查询）
    # ═══════════════════════════════════════════════════════

    def _toggle_row_selection(self, history_id: str, checked: bool):
        """单行 checkbox 变化时更新内部选中集合"""
        if checked:
            self._selected_ids.add(history_id)
        else:
            self._selected_ids.discard(history_id)
        self._refresh_batch_del_state()

    def _refresh_batch_del_state(self):
        """根据内部集合更新批量删除按钮 + 全选 checkbox 状态"""
        count = len(self._selected_ids)
        total = len(self._all_history_ids)
        has = count > 0
        self.history_batch_del_btn.setEnabled(has)
        self.history_batch_del_btn.setText(f"批量删除 ({count})" if has else "批量删除")

        # 同步全选 checkbox（不触发信号）
        self.history_select_all_cb.blockSignals(True)
        if total == 0:
            self.history_select_all_cb.setChecked(False)
        elif count == total:
            self.history_select_all_cb.setChecked(True)
        elif count > 0:
            self.history_select_all_cb.setTristate(True)
            self.history_select_all_cb.setCheckState(Qt.CheckState.PartiallyChecked)
        else:
            self.history_select_all_cb.setChecked(False)
        self.history_select_all_cb.blockSignals(False)

    def _on_select_all_changed(self, state: int):
        """全选 checkbox 变化：同步所有行 checkbox + 更新内部集合"""
        checked = (state == Qt.CheckState.Checked.value)
        if checked:
            self._selected_ids = set(self._all_history_ids)
        else:
            self._selected_ids.clear()
        # 通过 QTableWidgetItem.CheckState 同步每个行 checkbox（不触发 itemChanged）
        self.history_table.blockSignals(True)
        for i in range(self.history_table.rowCount()):
            item = self.history_table.item(i, 0)
            if item is not None:
                item.setCheckState(
                    Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
                )
        self.history_table.blockSignals(False)
        self._refresh_batch_del_state()

    def _on_table_item_changed(self, item: QTableWidgetItem):
        """checkbox 列 (col 0) 的 checkState 变化时更新内部集合"""
        if item.column() != 0:
            return
        history_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(history_id, str):
            return
        is_checked = item.checkState() == Qt.CheckState.Checked
        self._toggle_row_selection(history_id, is_checked)

    def _on_history_loaded(self, data: dict):
        try:
            items = data.get("items", []) or []
            # 重置选中状态
            self._selected_ids.clear()
            self._all_history_ids.clear()

            self.history_table.blockSignals(True)
            self.history_table.setRowCount(len(items))
            for i, item in enumerate(items):
                history_id = item.get('id', '')
                self._all_history_ids.append(history_id)

                # 列 0: 选择 checkbox（用 QTableWidgetItem + CheckState，比 cellWidget QCheckBox 可靠）
                cb_item = QTableWidgetItem()
                cb_item.setFlags(cb_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                cb_item.setCheckState(Qt.CheckState.Unchecked)
                cb_item.setData(Qt.ItemDataRole.UserRole, history_id)
                self.history_table.setItem(i, 0, cb_item)

                # 列 1-5: 数据列
                self.history_table.setItem(i, 1, QTableWidgetItem(f"#{history_id}"))
                fname = item.get('filename', '')
                self.history_table.setItem(i, 2, QTableWidgetItem(
                    fname[:40] + '...' if len(fname) > 40 else fname))
                self.history_table.setItem(i, 3, QTableWidgetItem(
                    item.get('timestamp', '')[:19]))
                status = "成功" if item.get('success') else "失败"
                sitem = QTableWidgetItem(status)
                sitem.setForeground(QColor("#10b981") if item.get('success') else QColor("#ef4444"))
                self.history_table.setItem(i, 4, sitem)
                self.history_table.setItem(i, 5, QTableWidgetItem(
                    str(item.get('processing_time', 0))))
                self.history_table.setItem(i, 6, QTableWidgetItem(
                    str(item.get('images_count', 0))))

                # 列 7: 操作按钮
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

                self.history_table.setCellWidget(i, 7, btn_widget)
                self.history_table.setRowHeight(i, 75)

            self.history_table.blockSignals(False)
        except Exception as e:
            self.history_table.blockSignals(False)
            import traceback
            print(f"[Claw] _on_history_loaded 异常: {e}", flush=True)
            traceback.print_exc()

        # 重置全选状态并刷新按钮
        self.history_select_all_cb.blockSignals(True)
        self.history_select_all_cb.setChecked(False)
        self.history_select_all_cb.blockSignals(False)
        self._refresh_batch_del_state()

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

    def batch_delete_history(self):
        if not self._selected_ids:
            self.show_toast("请先勾选要删除的记录")
            return

        history_ids = sorted(self._selected_ids)

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
