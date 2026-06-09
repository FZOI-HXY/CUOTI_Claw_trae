"""
NasTabMixin - NAS 跨网段同步标签页
包含: NAS连接状态, 同步操作, 远程文件浏览, 同步日志, NAS配置管理
"""
from __future__ import annotations

import os
import json
import threading
from pathlib import Path
from datetime import datetime
from typing import List, Any, TYPE_CHECKING

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QApplication, QGroupBox,
    QTextEdit,
)
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QColor, QTextCursor

from smb_sync import (
    SmbSyncService, SyncDirection, SyncStatus, SyncRecord,
)
from standalone.workers.api_task import ApiTask

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QTabWidget, QLineEdit, QComboBox


class NasTabMixin:
    """NAS 跨网段同步标签页 Mixin"""

    api_base: str
    tab_widget: QTabWidget
    sync_service: SmbSyncService
    file_queue: List
    history_table: QTableWidget

    # NAS 配置控件（由 main.py 创建）
    _nas_config_file: Path
    cfg_nas_host: QLineEdit
    cfg_nas_share: QLineEdit
    cfg_nas_user: QLineEdit
    cfg_nas_pass: QLineEdit
    cfg_nas_root: QLineEdit
    cfg_auto_sync: QComboBox
    cfg_nas_mount: QLineEdit

    # NAS UI 控件
    nas_status_indicator: QLabel
    nas_status_text: QLabel
    nas_status_detail: QLabel
    nas_info_pending: QLabel
    nas_info_last_sync: QLabel
    nas_browser_table: QTableWidget
    nas_log_view: QTextEdit
    btn_nas_push: QPushButton
    btn_nas_pull: QPushButton
    btn_nas_sync_all: QPushButton
    btn_nas_push_history: QPushButton
    btn_nas_pull_history: QPushButton

    # 来自 AppBaseMixin
    show_toast: Any

    # 来自 reports_mixin
    load_reports: Any

    # 来自 history_mixin
    load_history: Any

    def create_nas_sync_tab(self):
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
        hdr2 = self.nas_browser_table.horizontalHeader()
        assert hdr2 is not None
        hdr2.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
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

    # ============ NAS 回调函数 ============

    def _on_nas_status_changed(self, status: SyncStatus, message: str):
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

        if QApplication.instance():
            QTimer.singleShot(0, _update)

    def _on_nas_sync_complete(self, record: SyncRecord):
        def _update():
            self._refresh_nas_status_info()
            self._append_sync_log(record)
            self._refresh_nas_browser()
        QTimer.singleShot(0, _update)

    def _refresh_nas_status_info(self):
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
        timestamp = record.timestamp[:19] if record.timestamp else ""
        direction = {"push": "推送 ↑", "pull": "拉取 ↓", "bidirectional": "双向 ↔"}.get(
            record.direction, record.direction)
        line = f"[{timestamp}] {direction}: {record.files_synced} 成功, {record.files_failed} 失败"
        for detail in record.details[:5]:
            line += f"\n  {detail}"
        self.nas_log_view.append(line)
        self.nas_log_view.append("─" * 50)

        cursor = self.nas_log_view.textCursor()
        if cursor is not None:
            cursor.movePosition(QTextCursor.MoveOperation.Start)
        lines = self.nas_log_view.toPlainText().split("\n")
        if len(lines) > 300:
            new_text = "\n".join(lines[-300:])
            self.nas_log_view.setPlainText(new_text)

    # ============ NAS 同步操作 ============

    def _nas_push_reports(self):
        if not self.sync_service.is_connected():
            if not self.sync_service.connect():
                QMessageBox.warning(self, "NAS 不可用", "无法连接到 NAS，请检查网络和配置")  # type: ignore[arg-type]
                return

        self.show_toast("正在推送报告到 NAS...")
        output_dir = Path(__file__).parent.parent / "output"
        record = self.sync_service.push_reports(local_output_dir=str(output_dir))
        self._on_nas_sync_complete(record)
        self._refresh_nas_browser()
        QMessageBox.information(self, "推送完成",  # type: ignore[arg-type]
                                f"报告推送完成: {record.files_synced} 成功, {record.files_failed} 失败")

    def _nas_pull_reports(self):
        if not self.sync_service.is_connected():
            if not self.sync_service.connect():
                QMessageBox.warning(self, "NAS 不可用", "无法连接到 NAS")  # type: ignore[arg-type]
                return

        self.show_toast("正在从 NAS 拉取报告...")
        output_dir = Path(__file__).parent.parent / "output"
        record = self.sync_service.pull_reports(local_output_dir=str(output_dir))
        self._on_nas_sync_complete(record)
        self.load_reports()
        QMessageBox.information(self, "拉取完成",  # type: ignore[arg-type]
                                f"报告拉取完成: {record.files_synced} 成功, {record.files_failed} 失败")

    def _nas_sync_all(self):
        if not self.sync_service.is_connected():
            if not self.sync_service.connect():
                QMessageBox.warning(self, "NAS 不可用", "无法连接到 NAS")  # type: ignore[arg-type]
                return

        self.show_toast("正在执行双向同步...")
        output_dir = Path(__file__).parent.parent / "output"

        import asyncio
        import httpx
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
                    self, "同步完成",  # type: ignore[arg-type]
                    f"双向同步完成: {record.files_synced} 成功, {record.files_failed} 失败"))
            except Exception as e:
                loop.close()
                QTimer.singleShot(0, lambda: QMessageBox.warning(
                    self, "同步异常", f"同步过程中发生错误:\n{e}"))  # type: ignore[arg-type]

        threading.Thread(target=_do_sync, daemon=True).start()

    def _nas_push_history(self):
        if not self.sync_service.is_connected():
            if not self.sync_service.connect():
                QMessageBox.warning(self, "NAS 不可用", "无法连接到 NAS")  # type: ignore[arg-type]
                return

        worker = ApiTask(self.api_base, "GET", "/api/history?limit=100")
        worker.finished.connect(lambda data: self._on_history_for_push(data))
        worker.error.connect(lambda e: self.show_toast(f"获取历史失败: {e}"))
        worker.start()

    def _on_history_for_push(self, data: dict):
        items = data.get("items", [])
        if not items:
            QMessageBox.information(self, "提示", "没有可推送的历史记录")  # type: ignore[arg-type]
            return
        record = self.sync_service.push_history(items)
        self._on_nas_sync_complete(record)
        QMessageBox.information(self, "推送完成",  # type: ignore[arg-type]
                                f"历史记录已推送: {len(items)} 条")

    def _nas_pull_history(self):
        if not self.sync_service.is_connected():
            if not self.sync_service.connect():
                QMessageBox.warning(self, "NAS 不可用", "无法连接到 NAS")  # type: ignore[arg-type]
                return

        items = self.sync_service.pull_history()
        if not items:
            QMessageBox.information(self, "提示", "NAS 上没有历史记录")  # type: ignore[arg-type]
            return

        self._show_pulled_history(items)
        QMessageBox.information(self, "拉取完成",  # type: ignore[arg-type]
                                f"从 NAS 拉取了 {len(items)} 条历史记录")

    def _show_pulled_history(self, items: List[dict]):
        self.history_table.setRowCount(len(items))
        for i, item in enumerate(items):
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

    # ============ NAS 远程文件浏览 ============

    def _refresh_nas_browser(self):
        self.nas_browser_table.setRowCount(0)
        if not self.sync_service.is_connected():
            return

        reports_dir = os.path.join(self.sync_service.config.sync_root, "reports")
        report_names = self.sync_service.list_remote_dir(reports_dir)
        self.nas_browser_table.setRowCount(len(report_names))

        for i, rid in enumerate(report_names):
            self.nas_browser_table.setItem(i, 0, QTableWidgetItem(rid))
            remote_report_dir = os.path.join(reports_dir, rid)
            files = self.sync_service.list_remote_dir(remote_report_dir)
            self.nas_browser_table.setItem(i, 1, QTableWidgetItem(str(len(files))))

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
        if not self.sync_service.is_connected():
            return
        self.show_toast(f"正在从 NAS 拉取报告 {report_id}...")
        output_dir = Path(__file__).parent.parent / "output"

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
        reply = QMessageBox.question(
            self,  # type: ignore[arg-type]
            "确认删除",
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
            self.show_toast("删除 NAS 报告失败")

    # ============ NAS 连接初始化 ============

    def _init_nas_connection(self):
        def _connect():
            if self.sync_service.connect():
                self.sync_service.start_health_monitor()
        threading.Thread(target=_connect, daemon=True).start()

    def _auto_sync_after_process(self, output_dir: str):
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

    # ============ NAS 配置管理 ============

    def _load_nas_config(self):
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
        cfg = self.sync_service.config
        self.cfg_nas_host.setText(cfg.host)
        self.cfg_nas_share.setText(cfg.share)
        self.cfg_nas_user.setText(cfg.username)
        self.cfg_nas_pass.setText(cfg.password)
        self.cfg_nas_root.setText(cfg.sync_root)
        self.cfg_auto_sync.setCurrentText("启用" if cfg.auto_sync else "禁用")
        self.cfg_nas_mount.setText(cfg.mount_letter)

    def save_nas_config(self):
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
        self.sync_service.config.host = self.cfg_nas_host.text()
        self.sync_service.config.share = self.cfg_nas_share.text()
        self.sync_service.config.username = self.cfg_nas_user.text()
        self.sync_service.config.password = self.cfg_nas_pass.text()
        self.sync_service.config.mount_letter = self.cfg_nas_mount.text().strip()

        self.show_toast("正在测试 NAS 连接...")

        def _test():
            if self.sync_service.connect():
                QTimer.singleShot(0, lambda: QMessageBox.information(
                    self, "NAS 连接测试",  # type: ignore[arg-type]
                    f"成功连接到 NAS\n地址: {self.sync_service.config.unc_path}"
                ))
            else:
                QTimer.singleShot(0, lambda: QMessageBox.warning(
                    self, "NAS 连接测试",  # type: ignore[arg-type]
                    "无法连接到 NAS\n请检查:\n"
                    "1. 网络是否可达 (ping 192.168.0.79)\n"
                    "2. 账号密码是否正确\n"
                    "3. SMB 共享名是否正确"
                ))

        threading.Thread(target=_test, daemon=True).start()

    def reconnect_nas(self):
        self.sync_service.disconnect()
        self._init_nas_connection()
        self.show_toast("正在重连 NAS...")
