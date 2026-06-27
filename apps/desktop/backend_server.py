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

    配置文件 (.env) 路径策略：
      - 打包模式：使用 exe 同级目录的 .env（便携模式）
      - 开发模式：使用源码目录 apps/web/api/.env（直接继承开发环境配置，
        修改源码 .env 立即生效，无需复制到 %APPDATA%）
    """
    # 数据根目录（config.py 中的 _resolve_path 会用到）
    # 数据库、上传文件等运行时数据仍存储在 data_dir
    if not os.environ.get("CLAW_DATA_DIR"):
        os.environ["CLAW_DATA_DIR"] = data_dir

    # .env 文件路径：开发模式用源码 .env，打包模式用 exe 同级 .env
    if not os.environ.get("CLAW_ENV_FILE"):
        if getattr(sys, 'frozen', False):
            # 打包模式：使用 exe 同级目录的 .env
            env_file = os.path.join(data_dir, ".env")
        else:
            # 开发模式：使用源码 .env，直接继承开发环境配置
            project_root = _get_project_root()
            env_file = os.path.join(project_root, "apps", "web", "api", ".env")
        os.environ["CLAW_ENV_FILE"] = env_file

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


def _read_env_key(env_path: str) -> str:
    """读取 .env 文件中的 PADDLEOCR_API_KEY 值"""
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("PADDLEOCR_API_KEY=") or line.startswith("paddleocr_api_key="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def _ensure_env_file(data_dir: str):
    """确保 .env 文件存在且有 API Key

    开发模式：直接使用源码 apps/web/api/.env，无需复制（_setup_environment 已设置路径）。
    frozen 模式下，如果 exe 同级 .env 不存在或 key 为空，
    会尝试从开发模式数据目录（%APPDATA%/Claw/.env）继承配置。
    """
    # 开发模式：.env 就是源码文件，无需复制或创建
    if not getattr(sys, 'frozen', False):
        project_root = _get_project_root()
        source_env = os.path.join(project_root, "apps", "web", "api", ".env")
        if os.path.exists(source_env):
            return  # 源码 .env 存在，直接使用
        # 源码 .env 不存在（异常情况），创建默认
        os.makedirs(os.path.dirname(source_env), exist_ok=True)
        with open(source_env, "w", encoding="utf-8") as f:
            f.write("# Claw 错题管理系统 配置文件\n")
            f.write('PADDLEOCR_API_URL=https://paddleocr.aistudio-app.com/api/v2/ocr/jobs\n')
            f.write('PADDLEOCR_API_KEY=\n')
            f.write('PADDLEOCR_MODEL=PP-OCRv5\n')
            f.write('HOST=127.0.0.1\n')
            f.write('PORT=8500\n')
            f.write('DEBUG=false\n')
        return

    # 以下为 frozen 模式逻辑
    env_path = os.path.join(data_dir, ".env")

    # .env 不存在 → 创建或从模板复制
    if not os.path.exists(env_path):
        # 1. 尝试从 _MEIPASS 内置模板复制
        project_root = _get_project_root()
        template = os.path.join(project_root, "apps", "web", "api", ".env")
        if os.path.exists(template) and template != env_path:
            shutil.copy(template, env_path)
            return

        # 2. 尝试从开发模式数据目录复制（frozen 模式继承开发配置）
        appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
        dev_env = os.path.join(appdata, "Claw", ".env")
        if os.path.exists(dev_env) and dev_env != env_path:
            shutil.copy(dev_env, env_path)
            print("[backend_server] 已从开发配置继承 .env", flush=True)
            return

        # 3. 创建默认 .env（key 为空，需用户手动配置）
        with open(env_path, "w", encoding="utf-8") as f:
            f.write("# Claw 错题管理系统 配置文件\n")
            f.write("# 首次使用请在应用中配置 API Token（系统配置 → API Token）\n")
            f.write("# 从 https://aistudio.baidu.com/paddleocr/task 获取你的 API Token\n")
            f.write('PADDLEOCR_API_KEY=\n')
            f.write('PADDLEOCR_MODEL=PP-StructureV3\n')
            f.write('PADDLEOCR_API_URL=https://paddleocr.aistudio-app.com/api/v2/ocr/jobs\n')
            f.write('HOST=127.0.0.1\n')
            f.write('PORT=8500\n')
            f.write('DEBUG=false\n')
        return

    # .env 存在 → 检查 API Key 是否为空
    existing_key = _read_env_key(env_path)
    if existing_key:
        return  # 已有 key，无需处理

    # key 为空 → 尝试从开发模式数据目录继承
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    dev_env = os.path.join(appdata, "Claw", ".env")
    if os.path.exists(dev_env) and dev_env != env_path:
        dev_key = _read_env_key(dev_env)
        if dev_key:
            shutil.copy(dev_env, env_path)
            print("[backend_server] 已从开发配置继承 API Key", flush=True)


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
