"""
内嵌后端服务管理 — 为 standalone 桌面应用提供自包含的 FastAPI 后端

在后台线程启动 uvicorn，使 PyQt6 应用无需外部后端即可运行。
启动时自动设置数据目录和 .env 路径：
  - 打包后：所有数据与 Claw.exe 在同一目录（便携模式）
  - 开发模式：使用 %APPDATA%/Claw/ 目录
"""
import os
import sys
import shutil
import socket
import threading
import time
import urllib.request
import urllib.error

import uvicorn


# ---- PyInstaller 兼容性 ---- 

# 设置 socket 默认超时，防止 DNS 解析在 PyInstaller 中无限挂起
socket.setdefaulttimeout(10)

# Windows 下显式设置 asyncio 事件循环策略（避免 ProactorEventLoop 兼容问题）
if sys.platform == "win32":
    try:
        import asyncio as _asyncio
        _asyncio.set_event_loop_policy(_asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

def _get_project_root() -> str:
    """获取项目根目录（支持 PyInstaller 打包后的路径）"""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS  # type: ignore[reportAny]
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _get_data_dir() -> str:
    """获取数据目录，不存在则创建

    打包后 (frozen): Claw.exe 所在目录（便携模式，配置与程序同目录）
    开发模式: %APPDATA%/Claw/（避免污染源码目录）
    """
    if getattr(sys, 'frozen', False):
        data_dir = os.path.dirname(sys.executable)
    else:
        appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
        data_dir = os.path.join(appdata, "Claw")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def _setup_environment(data_dir: str):
    """在导入 backend 模块之前设置环境变量

    这些环境变量会在 Settings 初始化时被 pydantic-settings 读取，
    覆盖默认的相对路径，指向便携数据目录（exe 同级）或 AppData。
    """
    # .env 文件路径
    env_file = os.path.join(data_dir, ".env")
    if not os.environ.get("CLAW_ENV_FILE"):
        os.environ["CLAW_ENV_FILE"] = env_file

    # 数据根目录（config.py 中的 _resolve_path 会用到）
    if not os.environ.get("CLAW_DATA_DIR"):
        os.environ["CLAW_DATA_DIR"] = data_dir

    # PyInstaller 打包后 certifi 的 CA bundle 路径需要显式设置，
    # 否则 httpx 发起 HTTPS 请求时因找不到证书而挂起。
    if getattr(sys, 'frozen', False) and not os.environ.get("SSL_CERT_FILE"):
        try:
            import certifi
            os.environ["SSL_CERT_FILE"] = certifi.where()
        except Exception:
            pass  # certifi 模块可能不可用，让 httpx 自行处理（通常会失败）

    # 将项目根目录加入 sys.path，确保 backend 模块可被 import
    project_root = _get_project_root()
    if project_root not in sys.path:
        sys.path.insert(0, project_root)


def _ensure_env_file(data_dir: str):
    """确保 .env 文件存在，不存在则从模板复制或创建默认"""
    env_path = os.path.join(data_dir, ".env")
    if os.path.exists(env_path):
        return

    # 1. 尝试从 backend 目录复制已有 .env
    project_root = _get_project_root()
    template = os.path.join(project_root, "apps", "web", "api", ".env")
    if os.path.exists(template) and template != env_path:
        shutil.copy(template, env_path)
        return

    # 2. 创建默认 .env
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("# Claw 错题管理系统 配置文件\n")
        f.write("# 首次使用请在应用中配置 API Token（系统配置 → API Token）\n")
        f.write("# 从 https://aistudio.baidu.com/paddleocr/task 获取你的 API Token\n")
        f.write('PADDLEOCR_API_KEY=\n')
        f.write('PADDLEOCR_MODEL=PP-StructureV3\n')
        f.write('PADDLEOCR_API_URL=https://paddleocr.aistudio-app.com/api/v2/ocr/jobs\n')


# ---- 服务器生命周期 ----

_server: "uvicorn.Server | None" = None
_server_thread: "threading.Thread | None" = None
_server_lock = threading.Lock()  # 防止多线程竞态同时启动多个服务


def start_server(host: str = "127.0.0.1", port: int = 8500) -> bool:
    """启动内嵌后端服务器（线程安全）

    Args:
        host: 监听地址（默认 127.0.0.1，仅本机访问）
        port: 监听端口（默认 8500）

    Returns:
        True 表示服务器已就绪，False 表示启动超时
    """
    global _server, _server_thread

    # 快速路径：无锁检查（避免每次调用都竞争锁）
    if _server_thread is not None and _server_thread.is_alive():
        return True

    with _server_lock:
        # 二次检查：持有锁后再次确认（double-checked locking）
        if _server_thread is not None and _server_thread.is_alive():
            return True

        # 1. 设置环境
        data_dir = _get_data_dir()
        _setup_environment(data_dir)
        _ensure_env_file(data_dir)

        # 2. PyInstaller --windowed 模式下 sys.stdout/stderr 为 None，
        #    uvicorn 日志初始化会调用 .isatty()，导致 AttributeError。
        #    此处将 None 重定向到日志文件以兼容。
        if sys.stdout is None:
            sys.stdout = open(os.path.join(data_dir, "server_stdout.log"), "w")
        if sys.stderr is None:
            sys.stderr = open(os.path.join(data_dir, "server_stderr.log"), "w")

        # 3. 导入 FastAPI 应用（此时 Settings 会读取正确的 .env 路径）
        from apps.web.api.main import app  # noqa: E402 — 须在 _setup_environment 之后

        # 4. 创建并启动服务器
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="warning",
            access_log=False,
        )
        _server = uvicorn.Server(config)
        _server_thread = threading.Thread(target=_server.run, daemon=True)
        _server_thread.start()

    # 5. 等待就绪（在锁外执行，避免阻塞其他线程）
    health_url = f"http://{host}:{port}/api/health"
    return _wait_for_server(health_url, timeout=10)


def stop_server():
    """停止内嵌后端服务器"""
    global _server
    if _server:
        _server.should_exit = True


def is_running() -> bool:
    """检查服务器是否在运行"""
    return _server_thread is not None and _server_thread.is_alive()


# ---- 内部工具 ----

def _wait_for_server(url: str, timeout: int = 10) -> bool:
    """轮询 health endpoint 直到服务器响应"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=1) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.3)
    return False
