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
import os
from pathlib import Path

# 确保项目根目录在 sys.path 中（支持从任意目录执行）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---- 关键：在任何 app 模块导入之前设置环境变量 ----
# apps.desktop.ui 等模块的导入链会触发 apps.web.api.config 的导入，
# 此时 Settings() 单例被创建。若 CLAW_ENV_FILE 未设置，会使用错误的 .env 路径，
# 导致 API Key 等配置无法加载。
if not os.environ.get("CLAW_ENV_FILE"):
    if getattr(sys, 'frozen', False):
        _data_dir = os.path.dirname(sys.executable)
    else:
        _appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
        _data_dir = os.path.join(_appdata, "Claw")
    os.makedirs(_data_dir, exist_ok=True)
    os.environ["CLAW_ENV_FILE"] = os.path.join(_data_dir, ".env")
    os.environ["CLAW_DATA_DIR"] = _data_dir

from typing import List, Dict

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QMessageBox, QTabWidget,
)
from PyQt6.QtCore import QThread, QTimer
from PyQt6.QtGui import QPalette, QColor, QIcon

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
        self._shutting_down = False  # 关闭标志，阻止关闭过程中创建新线程

        self.setup_ui()
        self.setup_menu()
        self.setup_statusbar()
        self.check_server_status()
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.check_server_status)
        self.status_timer.start(5000)  # 每 5 秒检查一次服务器状态

    # ============ UI 搭建 ============

    def setup_ui(self):
        self.setWindowTitle("Claw - 错题管理系统")
        self.setMinimumSize(1280, 800)
        self.resize(1400, 880)
        self.setAcceptDrops(True)

        self.setStyleSheet(DARK_STYLE)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(16, 12, 16, 12)
        main_layout.setSpacing(12)

        # 标题栏
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
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        self.create_upload_tab()
        self.create_history_tab()
        self.create_reports_tab()
        self.create_config_tab()

    # ============ 清理 ============

    def closeEvent(self, event):
        # 0. 标记关闭中，阻止后续代码创建新线程
        self._shutting_down = True

        # 1. 停止定时器，防止退出时产生新的工作线程
        if hasattr(self, 'status_timer') and self.status_timer.isActive():
            self.status_timer.stop()
            print("[Claw] 已停止服务器状态定时检查", flush=True)

        # 2. 关闭内嵌后端
        if backend_server.is_running():
            print("[Claw] 正在停止后端服务...", flush=True)
            backend_server.stop_server()

        # 3. 等待所有活跃线程结束
        from apps.desktop.workers.api_task import _SelfPreservingThread
        _SelfPreservingThread.wait_all(timeout_ms=2000)

        # 4. 清理 active_workers 中剩余的线程
        for w in list(getattr(self, 'active_workers', [])):
            if w.isRunning():
                w.quit()
                w.wait(1000)
        event.accept()
        QApplication.quit()


def main():
    # PyInstaller --noconsole 模式下 sys.stdout/stderr 为 None，重定向到空设备
    import os as _os
    if sys.stdout is None:
        sys.stdout = open(_os.devnull, 'w')
    if sys.stderr is None:
        sys.stderr = open(_os.devnull, 'w')

    # SIGSEGV handler for C-level crash stack traces
    import faulthandler, signal
    faulthandler.enable()
    # Windows does not support all POSIX signals; ignore failure
    try:
        faulthandler.register(signal.SIGSEGV)
    except AttributeError:
        pass

    # 抑制 Qt 内部 "Destroyed while thread is still running" 无害警告
    from PyQt6.QtCore import qInstallMessageHandler, QtMsgType
    def _qt_msg_handler(_msg_type: QtMsgType, _context, msg: str):
        # 吞掉 "Destroyed while thread" 无害警告
        if "Destroyed while thread" in msg:
            return
        # 致命错误也打印出来
        prefix = "[Qt-FATAL]" if _msg_type == QtMsgType.QtFatalMsg else "[Qt]"
        print(f"{prefix} {msg}", flush=True)
    qInstallMessageHandler(_qt_msg_handler)

    try:
        _do_main()
    except Exception as e:
        import traceback as _tb
        print(f"\n[Claw] ===== 程序异常退出 =====", flush=True)
        print(f"[Claw] 异常: {e}", flush=True)
        _tb.print_exc()
        try:
            backend_server.stop_server()
        except Exception:
            pass
        sys.exit(1)


def _get_icon_path() -> str:
    """获取应用图标路径（支持 frozen 和开发模式）"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后，图标通过 --add-data 打包到 _MEIPASS 根目录
        base = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
        return os.path.join(base, "app_icon.ico")
    # 开发模式：图标在 apps/desktop/ 目录
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_icon.ico")


def _do_main():
    # Windows: 设置 AppUserModelID，让任务栏显示自定义图标而非 Python 默认图标
    # 必须在 QApplication 创建之前调用
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "ClawTeam.Claw.Desktop.1.0"
            )
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("Claw-Desktop")
    app.setOrganizationName("ClawTeam")

    # 设置应用图标（影响任务栏、Alt+Tab、窗口标题栏）
    icon_path = _get_icon_path()
    if os.path.exists(icon_path):
        app_icon = QIcon(icon_path)
        app.setWindowIcon(app_icon)
    else:
        print(f"[Claw] 警告: 图标文件不存在: {icon_path}", flush=True)

    app.setQuitOnLastWindowClosed(False)

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
        # 设置窗口级图标（确保 Alt+Tab 和任务栏预览正确显示）
        if os.path.exists(icon_path):
            window.setWindowIcon(QIcon(icon_path))
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

    app.processEvents()

    # 启动时加载数据
    QTimer.singleShot(500, window.refresh_all)

    print("[Claw] 进入事件循环", flush=True)
    import time
    _t0 = time.monotonic()
    try:
        exit_code = app.exec()
        _elapsed = time.monotonic() - _t0
        print(f"[Claw] 事件循环退出，退出码: {exit_code}, 运行时间: {_elapsed:.2f}s", flush=True)
    except Exception as _exec_exc:
        import traceback as _tb
        print(f"[Claw] app.exec() 异常: {_exec_exc}", flush=True)
        _tb.print_exc()
        exit_code = 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
