"""
ReportsTabMixin - 报告中心标签页
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog, QMessageBox, QCheckBox,
)
from PyQt6.QtCore import QTimer, Qt
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
        # 用内部集合追踪选中的 report_id，不依赖 cellWidget/selectionModel 查询
        self._selected_report_ids: set[str] = set()
        self._all_report_ids: list[str] = []

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)

        action_bar = QHBoxLayout()
        action_bar.addStretch()
        # 全选/取消全选
        self.report_select_all_cb = QCheckBox("全选")
        self.report_select_all_cb.setStyleSheet("color: #9ca3af; font-size: 13px;")
        self.report_select_all_cb.stateChanged.connect(self._on_report_select_all_changed)
        action_bar.addWidget(self.report_select_all_cb)
        self.report_batch_del_btn = QPushButton("批量删除")
        self.report_batch_del_btn.setEnabled(False)
        self.report_batch_del_btn.setStyleSheet(
            "QPushButton { background: rgba(239,68,68,0.15); color: #f87171; border: 1px solid #ef4444; "
            "border-radius: 4px; padding: 5px 12px; font-size: 14px; font-weight: 500; }"
            "QPushButton:hover { background: rgba(239,68,68,0.3); }"
            "QPushButton:disabled { background: transparent; color: #555; border-color: #444; }"
        )
        self.report_batch_del_btn.clicked.connect(self.batch_delete_reports)
        action_bar.addWidget(self.report_batch_del_btn)
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.load_reports)
        action_bar.addWidget(refresh_btn)
        layout.addLayout(action_bar)

        self.reports_table = QTableWidget()
        self.reports_table.setCornerButtonEnabled(False)
        self.reports_table.setColumnCount(6)  # +1 checkbox 列
        self.reports_table.setHorizontalHeaderLabels([
            "", "报告ID", "创建时间", "包含Markdown", "大小", "操作"
        ])
        hdr = self.reports_table.horizontalHeader()
        assert hdr is not None
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.reports_table.setColumnWidth(0, 36)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.reports_table.setColumnWidth(3, 90)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        vhdr = self.reports_table.verticalHeader()
        assert vhdr is not None
        vhdr.setDefaultSectionSize(36)
        # 用 itemChanged 处理 checkbox 列变化（不依赖 selectionModel）
        self.reports_table.itemChanged.connect(self._on_report_item_changed)
        layout.addWidget(self.reports_table)

        # 隐藏表格左上角默认的白色全选按钮（corner button）
        from PyQt6.QtWidgets import QAbstractButton
        corner_btn = self.reports_table.findChild(QAbstractButton)
        if corner_btn is not None:
            corner_btn.hide()

        self.tab_widget.addTab(tab, "报告中心")

    def load_reports(self):
        worker = ApiTask(self.api_base, "GET", "/api/reports?limit=100")
        worker.finished.connect(self._on_reports_loaded)
        worker.error.connect(lambda e: self._show_status(f"加载报告失败: {e}"))
        worker.start()

    def _on_reports_loaded(self, data: dict):
        reports = data.get("reports", []) or []
        # 重置选中状态
        self._selected_report_ids.clear()
        self._all_report_ids.clear()

        self.reports_table.blockSignals(True)
        self.reports_table.setRowCount(len(reports))
        for i, r in enumerate(reports):
            rid = r.get('id', '')
            self._all_report_ids.append(rid)

            # 列 0: 选择 checkbox（QTableWidgetItem + CheckState，可靠于 cellWidget QCheckBox）
            cb_item = QTableWidgetItem()
            cb_item.setFlags(cb_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            cb_item.setCheckState(Qt.CheckState.Unchecked)
            cb_item.setData(Qt.ItemDataRole.UserRole, rid)
            self.reports_table.setItem(i, 0, cb_item)

            # 列 1-4: 数据列
            self.reports_table.setItem(i, 1, QTableWidgetItem(str(rid)))
            created = r.get('created_time', '')
            self.reports_table.setItem(i, 2, QTableWidgetItem(
                str(created)[:19] if created else ''))
            has_md = "是" if r.get('has_markdown') else "否"
            md_item = QTableWidgetItem(has_md)
            md_item.setForeground(QColor("#10b981") if r.get('has_markdown') else QColor("#8b95a8"))
            self.reports_table.setItem(i, 3, md_item)

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
            self.reports_table.setItem(i, 4, QTableWidgetItem(size_str))

            # 列 5: 操作按钮
            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(6, 4, 6, 4)
            btn_layout.setSpacing(8)

            view_btn = QPushButton("查看")
            view_btn.setMinimumWidth(60)
            view_btn.setStyleSheet(
                "QPushButton { background: rgba(59,130,246,0.12); color: #60a5fa; border: 1px solid #3b82f6; "
                "border-radius: 4px; padding: 4px 10px; font-size: 13px; font-weight: 500; }"
                "QPushButton:hover { background: rgba(59,130,246,0.25); }"
            )
            view_btn.clicked.connect(lambda checked, x=rid: self.view_report_content(x))
            btn_layout.addWidget(view_btn)

            dl_btn = QPushButton("下载")
            dl_btn.setMinimumWidth(60)
            dl_btn.setStyleSheet(
                "QPushButton { background: rgba(6,182,212,0.12); color: #22d3ee; border: 1px solid #06b6d4; "
                "border-radius: 4px; padding: 4px 10px; font-size: 13px; font-weight: 500; }"
                "QPushButton:hover { background: rgba(6,182,212,0.25); }"
            )
            dl_btn.clicked.connect(lambda checked, x=rid: self.download_report(x))
            btn_layout.addWidget(dl_btn)

            del_btn = QPushButton("删除")
            del_btn.setMinimumWidth(60)
            del_btn.setStyleSheet(
                "QPushButton { background: rgba(239,68,68,0.12); color: #f87171; border: 1px solid #ef4444; "
                "border-radius: 4px; padding: 4px 10px; font-size: 13px; font-weight: 500; }"
                "QPushButton:hover { background: rgba(239,68,68,0.25); }"
            )
            del_btn.clicked.connect(lambda checked, x=rid: self.delete_report(x))
            btn_layout.addWidget(del_btn)

            self.reports_table.setCellWidget(i, 5, btn_widget)
            self.reports_table.setRowHeight(i, 75)

        self.reports_table.blockSignals(False)

        # 重置全选状态并刷新按钮
        self.report_select_all_cb.blockSignals(True)
        self.report_select_all_cb.setChecked(False)
        self.report_select_all_cb.blockSignals(False)
        self._refresh_report_batch_del_state()

    def view_report_content(self, report_id: str):
        worker = ApiTask(self.api_base, "GET", f"/api/report/{report_id}")
        def _on_done(data):
            content = data.get("content", "")
            report_dir = data.get("path", "")
            self.markdown_view.setHtml(self._render_markdown_html(content, report_dir=report_dir))
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

    # ═══════════════════════════════════════════════════════
    #  选择状态管理（基于内部集合，不依赖 cellWidget/selectionModel 查询）
    # ═══════════════════════════════════════════════════════

    def _on_report_item_changed(self, item: QTableWidgetItem):
        """checkbox 列 (col 0) 的 checkState 变化时更新内部集合"""
        if item.column() != 0:
            return
        rid = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(rid, str):
            return
        is_checked = item.checkState() == Qt.CheckState.Checked
        if is_checked:
            self._selected_report_ids.add(rid)
        else:
            self._selected_report_ids.discard(rid)
        self._refresh_report_batch_del_state()

    def _refresh_report_batch_del_state(self):
        """根据内部集合更新批量删除按钮 + 全选 checkbox 状态"""
        count = len(self._selected_report_ids)
        total = len(self._all_report_ids)
        has = count > 0
        self.report_batch_del_btn.setEnabled(has)
        self.report_batch_del_btn.setText(f"批量删除 ({count})" if has else "批量删除")

        self.report_select_all_cb.blockSignals(True)
        if total == 0:
            self.report_select_all_cb.setChecked(False)
        elif count == total:
            self.report_select_all_cb.setChecked(True)
        elif count > 0:
            self.report_select_all_cb.setTristate(True)
            self.report_select_all_cb.setCheckState(Qt.CheckState.PartiallyChecked)
        else:
            self.report_select_all_cb.setChecked(False)
        self.report_select_all_cb.blockSignals(False)

    def _on_report_select_all_changed(self, state: int):
        """全选 checkbox 变化：同步所有行 checkbox + 更新内部集合"""
        checked = (state == Qt.CheckState.Checked.value)
        if checked:
            self._selected_report_ids = set(self._all_report_ids)
        else:
            self._selected_report_ids.clear()
        self.reports_table.blockSignals(True)
        for i in range(self.reports_table.rowCount()):
            item = self.reports_table.item(i, 0)
            if item is not None:
                item.setCheckState(
                    Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
                )
        self.reports_table.blockSignals(False)
        self._refresh_report_batch_del_state()

    def batch_delete_reports(self):
        if not self._selected_report_ids:
            self.show_toast("请先勾选要删除的报告")
            return

        report_ids = sorted(self._selected_report_ids)

        reply = QMessageBox.question(
            self,  # type: ignore[arg-type]
            "确认批量删除",
            f"确认删除选中的 {len(report_ids)} 个报告？\n\n"
            + "\n".join(f"  - {rid}" for rid in report_ids[:5])
            + (f"\n  ... 等 {len(report_ids)} 项" if len(report_ids) > 5 else "")
            + "\n\n此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        for rid in report_ids:
            worker = ApiTask(self.api_base, "DELETE", f"/api/report/{rid}")
            worker.error.connect(
                lambda e, r=rid: self.show_toast(f"删除报告 {r} 失败: {e}")
            )
            worker.start()

        self.show_toast(f"正在删除 {len(report_ids)} 个报告...")
        # 延迟刷新列表
        QTimer.singleShot(1000, self.load_reports)
