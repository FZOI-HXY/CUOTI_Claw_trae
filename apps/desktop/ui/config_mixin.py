"""
ConfigTabMixin - 系统配置标签页（可视化卡片布局）

功能：
  - PaddleOCR API 配置卡片（地址、模型、Token 状态、连接测试）
  - 服务器配置卡片（地址、端口、最大上传）
  - 系统参数卡片（日志级别、存储路径）
  - 实时状态指示器 + 可视化反馈
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING, Tuple

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit,
    QSpinBox, QComboBox, QFormLayout,
    QScrollArea, QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt

from apps.desktop.workers.api_task import ApiTask

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QTabWidget


class ConfigTabMixin:
    """系统配置标签页 Mixin —— 可视化卡片设计"""

    api_base: str
    tab_widget: QTabWidget
    server_status_label: QLabel

    # ── 配置控件 ──
    cfg_api_url: QLineEdit
    cfg_api_token: QLineEdit
    cfg_model: QComboBox
    cfg_host: QLineEdit
    cfg_port: QSpinBox
    cfg_max_size: QSpinBox
    cfg_log_level: QComboBox

    # ── 状态指示器 ──
    _api_status_badge: QLabel
    _api_test_result: QLabel
    _server_status_badge: QLabel
    _token_toggle_btn: QPushButton

    # 来自 AppBaseMixin
    _show_status: Any
    show_toast: Any

    # ═══════════════════════════════════════════════════════
    #  创建配置标签页
    # ═══════════════════════════════════════════════════════

    def create_config_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(20)
        layout.setContentsMargins(8, 8, 8, 8)

        layout.addWidget(self._build_api_card())
        layout.addWidget(self._build_server_card())
        layout.addWidget(self._build_system_card())
        layout.addStretch()

        scroll.setWidget(container)
        self.tab_widget.addTab(scroll, "⚙ 系统配置")

    # ═══════════════════════════════════════════════════════
    #  卡片构造器
    # ═══════════════════════════════════════════════════════

    def _build_api_card(self) -> QFrame:
        """PaddleOCR API 配置卡片"""
        card, cl = self._create_card_frame("configCard")

        # 标题行
        title_row = QHBoxLayout()
        self._card_title("API 服务配置", title_row)
        self._api_status_badge = self._badge("badgeWarning", "⚡ 未验证")
        title_row.addStretch()
        title_row.addWidget(self._api_status_badge)
        cl.addLayout(title_row)

        cl.addWidget(self._card_desc(
            "配置 PaddleOCR API 连接参数。Token 可从 PaddleOCR 官网获取，修改后点击保存立即生效。"
        ))

        # ── 表单 ──
        form = self._card_form()

        self.cfg_api_url = self._form_row(form, "API 地址:")
        self.cfg_api_url.setPlaceholderText("https://paddleocr.aistudio-app.com/api/v2/ocr/jobs")

        # Token 输入行（含显隐切换）
        token_row = QHBoxLayout()
        token_row.setSpacing(6)
        self.cfg_api_token = QLineEdit()
        self.cfg_api_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.cfg_api_token.setPlaceholderText("输入 PaddleOCR API Token")
        self.cfg_api_token.setToolTip("输入 PaddleOCR API Token，点击眼睛图标可切换显示/隐藏")
        token_row.addWidget(self.cfg_api_token)

        self._token_toggle_btn = QPushButton("👁")
        self._token_toggle_btn.setObjectName("ghostBtn")
        self._token_toggle_btn.setFixedWidth(36)
        self._token_toggle_btn.setToolTip("切换 Token 显示/隐藏")
        self._token_toggle_btn.clicked.connect(self._toggle_token_visibility)
        token_row.addWidget(self._token_toggle_btn)
        form.addRow("API Token:", token_row)

        self.cfg_model = QComboBox()
        self.cfg_model.addItems([
            "PaddleOCR-VL-1.6", "PaddleOCR-VL-1.5",
            "PP-StructureV3", "PP-OCRv6", "PP-OCRv5"
        ])
        self.cfg_model.setToolTip(
            "PaddleOCR-VL-1.6: 多模态大模型（推荐）\n"
            "PaddleOCR-VL-1.5: 多模态大模型\n"
            "PP-StructureV3: 文档结构化\n"
            "PP-OCRv6: 纯文字识别\n"
            "PP-OCRv5: 纯文字识别"
        )
        form.addRow("模型:", self.cfg_model)

        # 操作按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        test_btn = QPushButton("测试连接")
        test_btn.setObjectName("ghostBtn")
        test_btn.clicked.connect(self._test_api_connection_visual)
        test_btn.setToolTip("向 API 服务器发送探测请求，验证连接是否正常")
        btn_row.addWidget(test_btn)

        save_btn = QPushButton("保存并应用")
        save_btn.setObjectName("primaryBtn")
        save_btn.clicked.connect(self.save_api_config)
        save_btn.setToolTip("将当前 API 配置写入配置文件并立即生效")
        btn_row.addWidget(save_btn)

        btn_row.addStretch()

        self._api_test_result = QLabel("")
        self._api_test_result.setWordWrap(True)
        btn_row.addWidget(self._api_test_result)
        btn_row.addStretch()

        form.addRow("", btn_row)
        cl.addLayout(form)

        return card

    def _build_server_card(self) -> QFrame:
        """服务器配置卡片"""
        card, cl = self._create_card_frame("configCard")

        title_row = QHBoxLayout()
        self._card_title("🖥 本地服务器配置", title_row)
        self._server_status_badge = self._badge("badgeInfo", "端口: 8500")
        title_row.addStretch()
        title_row.addWidget(self._server_status_badge)
        cl.addLayout(title_row)

        cl.addWidget(self._card_desc(
            "内嵌后端服务的监听参数。修改后需重启应用才生效。"
        ))

        form = self._card_form()

        self.cfg_host = self._form_row(form, "监听地址:")
        self.cfg_host.setPlaceholderText("0.0.0.0")
        self.cfg_host.setToolTip("0.0.0.0 表示监听所有网络接口；127.0.0.1 仅本机访问")

        self.cfg_port = QSpinBox()
        self.cfg_port.setRange(1, 65535)
        self.cfg_port.setValue(8500)
        self.cfg_port.setToolTip("服务监听端口，默认 8500")
        form.addRow("监听端口:", self.cfg_port)

        self.cfg_max_size = QSpinBox()
        self.cfg_max_size.setRange(1, 500)
        self.cfg_max_size.setValue(50)
        self.cfg_max_size.setSuffix(" MB")
        self.cfg_max_size.setToolTip("单次上传文件的最大体积")
        form.addRow("最大上传:", self.cfg_max_size)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("保存服务器配置")
        save_btn.setObjectName("primaryBtn")
        save_btn.clicked.connect(self.save_server_config)
        save_btn.setToolTip("写入配置，需重启应用后生效")
        btn_row.addWidget(save_btn)
        btn_row.addStretch()
        form.addRow("", btn_row)
        cl.addLayout(form)

        return card

    def _build_system_card(self) -> QFrame:
        """系统参数卡片"""
        card, cl = self._create_card_frame("configCard")

        self._card_title("⚙ 系统运行参数", cl)

        cl.addWidget(self._card_desc(
            "日志级别和存储路径等运行参数，立即生效无需重启。"
        ))

        form = self._card_form()

        self.cfg_log_level = QComboBox()
        self.cfg_log_level.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.cfg_log_level.setCurrentText("INFO")
        self.cfg_log_level.setToolTip(
            "DEBUG: 详细诊断信息\nINFO: 常规运行日志\nWARNING: 仅警告以上\nERROR: 仅错误信息"
        )
        form.addRow("日志级别:", self.cfg_log_level)

        # 存储路径（只读展示）
        upload_label = QLabel("uploads/")
        upload_label.setStyleSheet("color: #6b7280; padding: 8px 0;")
        form.addRow("上传目录:", upload_label)

        output_label = QLabel("output/")
        output_label.setStyleSheet("color: #6b7280; padding: 8px 0;")
        form.addRow("输出目录:", output_label)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("保存运行参数")
        save_btn.setObjectName("primaryBtn")
        save_btn.clicked.connect(self.save_process_config)
        btn_row.addWidget(save_btn)
        btn_row.addStretch()
        form.addRow("", btn_row)
        cl.addLayout(form)

        return card

    # ═══════════════════════════════════════════════════════
    #  可视化辅助方法
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def _create_card_frame(obj_name: str) -> Tuple[QFrame, QVBoxLayout]:
        """创建配置卡片容器，返回 (卡片, 布局)"""
        card = QFrame()
        card.setObjectName(obj_name)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        return card, layout

    @staticmethod
    def _card_title(text: str, layout: QHBoxLayout | QVBoxLayout) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("cardTitle")
        layout.addWidget(lbl)
        return lbl

    @staticmethod
    def _card_desc(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("cardDesc")
        lbl.setWordWrap(True)
        return lbl

    @staticmethod
    def _badge(style: str, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName(style)
        return lbl

    @staticmethod
    def _card_form() -> QFormLayout:
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return form

    @staticmethod
    def _form_row(form: QFormLayout, label: str) -> QLineEdit:
        field = QLineEdit()
        form.addRow(label, field)
        return field

    def _toggle_token_visibility(self):
        """切换 Token 输入框的显示/隐藏模式"""
        if self.cfg_api_token.echoMode() == QLineEdit.EchoMode.Password:
            self.cfg_api_token.setEchoMode(QLineEdit.EchoMode.Normal)
            self._token_toggle_btn.setText("🙈")
        else:
            self.cfg_api_token.setEchoMode(QLineEdit.EchoMode.Password)
            self._token_toggle_btn.setText("👁")

    @staticmethod
    def _set_badge(badge: QLabel, style: str, text: str):
        badge.setObjectName(style)
        badge.setText(text)
        s = badge.style()
        if s is not None:
            s.unpolish(badge)
            s.polish(badge)

    # ═══════════════════════════════════════════════════════
    #  配置加载与保存
    # ═══════════════════════════════════════════════════════

    def load_config(self):
        worker = ApiTask(self.api_base, "GET", "/api/config")
        worker.finished.connect(self._on_config_loaded)
        worker.error.connect(lambda e: self._show_status(f"加载配置失败: {e}"))
        worker.start()

    def _on_config_loaded(self, config: dict):
        self.cfg_api_url.setText(config.get("paddleocr_api_url", ""))
        model = config.get("paddleocr_model", "PP-StructureV3")
        idx = self.cfg_model.findText(model)
        if idx >= 0:
            self.cfg_model.setCurrentIndex(idx)

        # 已配置 Token 仅显示占位提示，不暴露完整密钥
        if config.get("api_key_configured"):
            self.cfg_api_token.setPlaceholderText("(已配置，输入新值可替换)")
            self.cfg_api_token.clear()
        else:
            self.cfg_api_token.setPlaceholderText("请输入 API Token")
            self.cfg_api_token.clear()
        self.cfg_api_token.setEchoMode(QLineEdit.EchoMode.Password)
        self._token_toggle_btn.setText("👁")

        self.cfg_host.setText(config.get("host", "0.0.0.0"))
        self.cfg_port.setValue(config.get("port", 8500))
        self.cfg_max_size.setValue(config.get("max_upload_size_mb", 50))
        idx = self.cfg_log_level.findText(config.get("log_level", "INFO"))
        if idx >= 0:
            self.cfg_log_level.setCurrentIndex(idx)

        # 更新 Token 状态指示
        if config.get("api_key_configured"):
            prefix = config.get("api_key_prefix", "****")
            self._set_badge(self._api_status_badge, "badgeSuccess", f"✓ Token: {prefix}")
        else:
            self._set_badge(self._api_status_badge, "badgeError", "✗ Token 未配置")

        # 更新端口展示
        port_val = config.get("port", 8500)
        self._server_status_badge.setText(f"端口: {port_val}")

        self._show_status("配置加载完成")

    def save_api_config(self):
        """保存 API 配置（含 Token）"""
        token_input = self.cfg_api_token.text().strip()
        # 忽略占位符/掩码值，避免覆盖真实 Token
        if token_input in ("", "********", "your-paddleocr-api-token-here"):
            token_input = ""  # 空值会被后端跳过，不覆盖现有配置
        data = {
            "paddleocr_api_url": self.cfg_api_url.text().strip(),
            "paddleocr_api_key": token_input,
            "paddleocr_model": self.cfg_model.currentText(),
        }
        worker = ApiTask(self.api_base, "POST", "/api/config", json_data=data)
        worker.finished.connect(self._on_api_saved)
        worker.error.connect(lambda e: self._on_api_save_error(e))
        worker.start()

    def _on_api_saved(self, _data):
        self.show_toast("API 配置已保存并应用")
        # 重新加载配置以获取最新 Token 状态
        self.load_config()
        # 自动测试连接
        self._test_api_connection_visual()

    def _on_api_save_error(self, err: str):
        self._set_badge(self._api_status_badge, "badgeError", "✗ 保存失败")
        self.show_toast(f"保存失败: {err}")

    def save_server_config(self):
        data = {
            "host": self.cfg_host.text().strip(),
            "port": self.cfg_port.value(),
            "max_upload_size_mb": self.cfg_max_size.value(),
        }
        worker = ApiTask(self.api_base, "POST", "/api/config", json_data=data)
        worker.finished.connect(self._on_server_saved)
        worker.error.connect(lambda e: self.show_toast(f"保存失败: {e}"))
        worker.start()

    def _on_server_saved(self, _data):
        self.show_toast("服务器配置已保存（需重启服务生效）")
        self._server_status_badge.setText(f"端口: {self.cfg_port.value()}")

    def save_process_config(self):
        data = {"log_level": self.cfg_log_level.currentText()}
        worker = ApiTask(self.api_base, "POST", "/api/config", json_data=data)
        worker.finished.connect(lambda d: self.show_toast("运行参数已保存"))
        worker.error.connect(lambda e: self.show_toast(f"保存失败: {e}"))
        worker.start()

    # ═══════════════════════════════════════════════════════
    #  可视化连接测试
    # ═══════════════════════════════════════════════════════

    def _test_api_connection_visual(self):
        """测试 API 连接并在卡片内显示结果"""
        self._api_test_result.setText("⏳ 正在测试...")
        self._api_test_result.setObjectName("")
        self._api_test_result.style().unpolish(self._api_test_result)  # type: ignore[union-attr]
        self._api_test_result.style().polish(self._api_test_result)  # type: ignore[union-attr]
        self._set_badge(self._api_status_badge, "badgeWarning", "⏳ 测试中...")

        worker = ApiTask(self.api_base, "GET", "/api/health")
        worker.finished.connect(self._on_test_success)
        worker.error.connect(self._on_test_error)
        worker.start()

    def _on_test_success(self, data):
        if data.get("status") == "healthy":
            self._api_test_result.setText("✓ 服务连接正常")
            self._api_test_result.setObjectName("testResultSuccess")
            s = self._api_test_result.style()
            if s is not None:
                s.unpolish(self._api_test_result)
                s.polish(self._api_test_result)
            self._set_badge(self._api_status_badge, "badgeSuccess", "✓ API 可连接")
        else:
            self._on_test_error("响应异常")

    def _on_test_error(self, err: str):
        self._api_test_result.setText(f"✗ 连接失败: {err}")
        self._api_test_result.setObjectName("testResultError")
        s = self._api_test_result.style()
        if s is not None:
            s.unpolish(self._api_test_result)
            s.polish(self._api_test_result)
        self._set_badge(self._api_status_badge, "badgeError", "✗ 无法连接")

    # ═══════════════════════════════════════════════════════
    #  服务器状态检查（供外部定时调用）
    # ═══════════════════════════════════════════════════════

    _status_check_count = 0

    def check_server_status(self):
        # 窗口正在关闭，不再发起新请求
        if getattr(self, '_shutting_down', False):
            return

        ConfigTabMixin._status_check_count += 1
        cnt = ConfigTabMixin._status_check_count
        print(f"[Claw] DIAG: check_server_status #{cnt} 开始", flush=True)

        try:
            worker = ApiTask(self.api_base, "GET", "/api/health")
        except Exception as e:
            print(f"[Claw] DIAG: check_server_status #{cnt} ApiTask创建失败: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return

        def _on_done(data):
            if getattr(self, '_shutting_down', False):
                return
            try:
                if isinstance(data, dict) and data.get("status") == "healthy":
                    self.server_status_label.setText("🟢 服务正常")
                    self.server_status_label.setStyleSheet("color: #10b981; font-size: 11px;")
                else:
                    self.server_status_label.setText("🟡 服务异常")
                    self.server_status_label.setStyleSheet("color: #f59e0b; font-size: 11px;")
                print(f"[Claw] DIAG: check_server_status #{cnt} _on_done OK", flush=True)
            except Exception as _ex:
                print(f"[Claw] DIAG: check_server_status #{cnt} _on_done 异常: {_ex}", flush=True)
                import traceback
                traceback.print_exc()

        def _on_error(err_msg):
            if getattr(self, '_shutting_down', False):
                return
            try:
                self.server_status_label.setText("🔴 连接断开")
                self.server_status_label.setStyleSheet("color: #ef4444; font-size: 11px;")
                print(f"[Claw] DIAG: check_server_status #{cnt} _on_error: {err_msg}", flush=True)
            except Exception as _ex:
                print(f"[Claw] DIAG: check_server_status #{cnt} _on_error 异常: {_ex}", flush=True)
                import traceback
                traceback.print_exc()

        worker.finished.connect(_on_done)
        worker.error.connect(_on_error)
        worker.start()
        print(f"[Claw] DIAG: check_server_status #{cnt} worker已启动", flush=True)
