"""
错题管理系统 - 独立桌面应用程序
完整复刻前端系统所有功能，内嵌后端服务，不依赖外部进程

功能:
  1. 文件上传与队列管理（拖拽、文件夹、批量）
  2. 批量 OCR 处理（提交→轮询→结果）
  3. 报告管理（列表、查看、下载ZIP、删除）
  4. 处理历史记录
  5. 系统配置管理

技术栈: PyQt6 + FastAPI (内嵌) + httpx + markdown
后端: 内嵌 FastAPI 服务，双击 .exe 即可使用，无需额外启动
API Token 已内置，开箱即用

模块结构:
  standalone/
    main.py          - 入口 + StandaloneApp 主窗口（继承所有 Mixin）
    style.py         - 暗色主题样式表 DARK_STYLE
    utils.py         - 工具函数 (render_markdown_html, format_size)
    workers/         - 异步 API 工作线程
    ui/              - UI Mixin 模块
      base_mixin.py    - 基础功能（菜单、状态栏、拖拽、步骤指示器）
      upload_mixin.py  - 上传处理标签页 + 批量处理流程
      history_mixin.py - 处理历史记录标签页
      reports_mixin.py - 报告中心标签页
      config_mixin.py  - 系统配置标签页
"""
import sys
from typing import List, Dict

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QMessageBox, QTabWidget,
)
from PyQt6.QtCore import QThread, QTimer
from PyQt6.QtGui import QPalette, QColor

# 内嵌后端服务
import backend_server

# Modular UI components
from apps.desktop.style import DARK_STYLE
from apps.desktop.ui import (
    AppBaseMixin,
    UploadTabMixin,
    HistoryTabMixin,
    ReportsTabMixin,
    ConfigTabMixin,
)


class StandaloneApp(
    AppBaseMixin,
    UploadTabMixin,
    HistoryTabMixin,
    ReportsTabMixin,
    ConfigTabMixin,
    QMainWindow,
):
    """独立桌面应用程序主窗口 - 通过 Mixin 组合所有功能"""

    def __init__(self):
        QMainWindow.__init__(self)
        self.api_base = "http://127.0.0.1:8500"
        self.file_queue: List[Dict] = []           # [{path, name, size, status, file_id, task_id, result}]
        self.batch_results: List[Dict] = []        # 批量处理结果
        self.processing = False
        self.active_workers: List[QThread] = []

        self.setup_ui()
        print("  [INIT] setup_menu...", flush=True)
        self.setup_menu()
        print("  [INIT] setup_statusbar...", flush=True)
        self.setup_statusbar()
        print("  [INIT] check_server_status...", flush=True)
        self.check_server_status()
        print("  [INIT] QTimer...", flush=True)
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.check_server_status)
        self.status_timer.start(15000)
        print("  [INIT] __init__ 完成", flush=True)

    # ============ UI 搭建 ============

    def setup_ui(self):
        print("  [UI] 设置窗口属性...", flush=True)
        self.setWindowTitle("Claw - 错题管理系统")
        self.setMinimumSize(1280, 800)
        self.resize(1400, 880)
        self.setAcceptDrops(True)

        print("  [UI] 应用样式表...", flush=True)
        self.setStyleSheet(DARK_STYLE)

        print("  [UI] 创建中央组件和布局...", flush=True)
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(16, 12, 16, 12)
        main_layout.setSpacing(12)

        # 标题栏
        print("  [UI] 标题栏...", flush=True)
        title_layout = QHBoxLayout()
        title = QLabel("Claw 错题管理系统")
        title.setStyleSheet("font-size: 20px; font-weight: 700; color: #f59e0b;")
        title_layout.addWidget(title)
        title_layout.addStretch()
        self.server_status_label = QLabel("检查服务器状态...")
        self.server_status_label.setObjectName("statusLabel")
        title_layout.addWidget(self.server_status_label)
        main_layout.addLayout(title_layout)

        # 标签页
        print("  [UI] 标签页容器...", flush=True)
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        print("  [UI] 创建上传标签页...", flush=True)
        self.create_upload_tab()
        print("  [UI] 创建历史标签页...", flush=True)
        self.create_history_tab()
        print("  [UI] 创建报告标签页...", flush=True)
        self.create_reports_tab()
        print("  [UI] 创建配置标签页...", flush=True)
        self.create_config_tab()
        print("  [UI] setup_ui 完成", flush=True)

    # ============ 清理 ============

    def closeEvent(self, event):
        # 关闭内嵌后端
        from apps.desktop import backend_server as bs
        if bs.is_running():
            print("[Claw] 正在停止后端服务...", flush=True)
            bs.stop_server()

        # 等待所有活跃线程结束
        from apps.desktop.workers.api_task import _SelfPreservingThread
        _SelfPreservingThread.wait_all(timeout_ms=2000)

        # 清理 active_workers 中剩余的线程
        for w in list(getattr(self, 'active_workers', [])):
            if w.isRunning():
                w.quit()
                w.wait(1000)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Claw-Desktop")
    app.setOrganizationName("ClawTeam")

    # --- 诊断：检查 Qt 插件路径 ---
    print(f"[Claw] Qt plugin path: {app.libraryPaths()}", flush=True)

    # --- 启动内嵌后端服务 ---
    print("[Claw] 正在启动内嵌后端服务...", flush=True)
    if not backend_server.start_server(host="127.0.0.1", port=8500):
        QMessageBox.critical(
            None, "启动失败",
            "内嵌后端服务启动超时，请检查以下可能原因：\n"
            "1. 端口 8500 被其他程序占用\n"
            "2. 缺少必要的依赖 (uvicorn, fastapi 等)\n"
            "3. 配置文件 .env 读写权限异常"
        )
        backend_server.stop_server()
        sys.exit(1)
    print("[Claw] 后端服务已就绪", flush=True)

    # 注册退出清理
    app.aboutToQuit.connect(backend_server.stop_server)

    # 暗色 Palette
    print("[Claw] 设置样式...", flush=True)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#0a0e17"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e8ecf1"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#111827"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#1a2235"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#1a2235"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#e8ecf1"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e8ecf1"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#1a2235"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e8ecf1"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#f59e0b"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#0a0e17"))
    app.setPalette(palette)

    print("[Claw] 创建主窗口...", flush=True)
    try:
        window = StandaloneApp()
        print("[Claw] 主窗口已创建", flush=True)
    except Exception as e:
        import traceback
        traceback.print_exc()
        QMessageBox.critical(None, "窗口错误", f"创建主窗口失败:\n{e}")
        backend_server.stop_server()
        sys.exit(1)

    # 连接标签页切换
    window.tab_widget.currentChanged.connect(window.tab_changed)
    print("[Claw] 显示窗口...", flush=True)
    window.show()

    # 启动时加载数据
    QTimer.singleShot(500, window.refresh_all)

    print("[Claw] 进入事件循环", flush=True)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
