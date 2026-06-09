"""
ConfigTabMixin - 系统配置标签页
包含: API配置, 服务器配置, 处理参数
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit,
    QSpinBox, QComboBox, QMessageBox, QFormLayout,
    QGroupBox, QScrollArea,
)

from standalone.workers.api_task import ApiTask

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QTabWidget


class ConfigTabMixin:
    """系统配置标签页 Mixin"""

    api_base: str
    tab_widget: QTabWidget
    server_status_label: QLabel

    # 配置控件（由 create_config_tab 创建）
    cfg_api_url: QLineEdit
    cfg_api_key: QLineEdit
    cfg_model: QComboBox
    cfg_host: QLineEdit
    cfg_port: QSpinBox
    cfg_max_size: QSpinBox
    cfg_log_level: QComboBox

    # 来自 AppBaseMixin
    _show_status: Any
    show_toast: Any

    def create_config_tab(self):
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

        layout.addStretch()
        scroll.setWidget(container)
        self.tab_widget.addTab(scroll, "系统配置")

    # ============ 配置加载与保存 ============

    def load_config(self):
        worker = ApiTask(self.api_base, "GET", "/api/config")
        worker.finished.connect(self._on_config_loaded)
        worker.error.connect(lambda e: self._show_status(f"加载配置失败: {e}"))
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
                QMessageBox.information(self, "连接测试", "API 服务连接正常")  # type: ignore[arg-type]
            else:
                QMessageBox.warning(self, "连接测试", "API 服务响应异常")  # type: ignore[arg-type]
        worker.finished.connect(_on_done)
        worker.error.connect(lambda e: QMessageBox.critical(
            self, "连接测试", f"无法连接到 API 服务:\n{e}"))  # type: ignore[arg-type]
        worker.start()

    def check_server_status(self):
        worker = ApiTask(self.api_base, "GET", "/api/health")
        def _on_done(data):
            if data.get("status") == "healthy":
                self.server_status_label.setText("🟢 服务正常")
                self.server_status_label.setStyleSheet("color: #10b981; font-size: 11px;")
            else:
                self.server_status_label.setText("🟡 服务异常")
                self.server_status_label.setStyleSheet("color: #f59e0b; font-size: 11px;")
        def _on_error(_):
            self.server_status_label.setText("🔴 连接断开")
            self.server_status_label.setStyleSheet("color: #ef4444; font-size: 11px;")
        worker.finished.connect(_on_done)
        worker.error.connect(_on_error)
        worker.start()
