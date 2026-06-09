#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Claw 错题管理系统 — PyInstaller 打包构建脚本

功能:
  1. 自动检查依赖环境 (PyInstaller, PyQt6, httpx, Pillow)
  2. 自动生成应用图标 (无 .ico 文件时)
  3. 配置 PyInstaller 打包参数
  4. 执行打包并输出单文件可执行程序
  5. 验证构建产物

输出:
  dist/Claw.exe          — 独立可执行文件 (无需 Python 环境)
  dist/Claw_build.log    — 构建日志

用法:
  python build.py                    # 默认打包
  python build.py --no-icon          # 不生成图标
  python build.py --console          # 带控制台窗口 (调试用)
  python build.py --clean            # 清理旧构建后重新打包
"""

import sys
import shutil
import subprocess
import argparse
import time
import platform
from pathlib import Path
from datetime import datetime


# ============================================================
# 配置区
# ============================================================

# 项目根目录 (此脚本所在目录)
PROJECT_DIR = Path(__file__).resolve().parent

# 入口文件 (相对于 PROJECT_DIR)
ENTRY_SCRIPT = "main.py"

# 自动包含的 Python 模块 (相对于 PROJECT_DIR)
PY_MODULES = [
    "smb_sync.py",
]

# 需要作为数据文件打包的路径 (相对 PROJECT_DIR)
DATA_FILES: list[tuple[str, str]] = [
    # ("local_cache", "local_cache"),  # 离线缓存目录
]

# 输出设置
OUTPUT_DIR = PROJECT_DIR / "dist"
BUILD_DIR = PROJECT_DIR / "build"
WORK_DIR = BUILD_DIR / "pyinstaller_work"
APP_NAME = "Claw"
ICON_FILE = PROJECT_DIR / "app_icon.ico"
VERSION_FILE = PROJECT_DIR / "version_info.txt"

# ============================================================
# PyInstaller 配置
# ============================================================

# PyQt6 需要显式导入的隐藏模块
PYQT6_HIDDEN_IMPORTS = [
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "PyQt6.QtNetwork",
    "PyQt6.sip",
]

# 必须收集完整子模块的包 (含二进制插件)
COLLECT_SUBMODULES = [
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
]

# 排除的不必要标准库模块 (减小体积)
EXCLUDE_MODULES = [
    "tkinter",
    "turtle",
    "turtledemo",
    "test",
    "unittest",
    "pydoc",
    "idlelib",
    "venv",
    "ensurepip",
    "distutils",
    "setuptools",
    "pkg_resources",
    "site",
    "lib2to3",
    "xmlrpc",
    "multiprocessing",
    "concurrent.futures.process",
    "curses",
    "dbm",
    "sqlite3",
    "sqlalchemy",
    "numpy",
    "scipy",
    "pandas",
    "matplotlib",
    "IPython",
    "jupyter",
    "notebook",
    "tornado",
    "flask",
    "django",
    "jinja2",
    "markupsafe",
    "werkzeug",
    "click",
    "itsdangerous",
    "bcrypt",
    "cryptography",
    "paramiko",
    "boto3",
    "botocore",
    "redis",
    "celery",
    "kafka",
    "grpc",
    "protobuf",
    "lxml",
    "beautifulsoup4",
    "scrapy",
    "pygame",
    "cffi",
    "ctypes",
    "asyncio",
    "aiohttp",
    "websockets",
    "uvicorn",
    "fastapi",
    "starlette",
    "pydantic",
]


# ============================================================
# 工具函数
# ============================================================

def log(msg: str, level: str = "INFO"):
    """带时间戳的日志输出"""
    ts = datetime.now().strftime("%H:%M:%S")
    prefix = {"INFO": "[*]", "OK": "[+]", "WARN": "[!]", "ERR": "[-]"}.get(level, "[*]")
    print(f"{ts} {prefix} {msg}")


def check_python():
    """检查 Python 版本"""
    ver = sys.version_info
    if ver.major < 3 or (ver.major == 3 and ver.minor < 8):
        log("Python 3.8+ 以上版本", "ERR")
        sys.exit(1)
    log(f"Python {ver.major}.{ver.minor}.{ver.micro} ({platform.architecture()[0]})")


def check_pyinstaller():
    """检查 PyInstaller 是否已安装"""
    try:
        import PyInstaller  # noqa: F401
        ver = PyInstaller.__version__
        log(f"PyInstaller {ver}")
        return True
    except ImportError:
        log("PyInstaller 未安装，正在安装...", "WARN")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "pyinstaller>=6.0.0"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            log(f"安装失败: {result.stderr.strip()}", "ERR")
            return False
        log("PyInstaller 安装完成")
        return True


def check_dependencies():
    """检查所有必需依赖"""
    deps = {
        "PyQt6": "PyQt6",
        "httpx": "httpx",
        "PIL": "Pillow",
    }
    missing: list[str] = []
    for import_name, pip_name in deps.items():
        try:
            __import__(import_name)
            log(f"{pip_name} OK")
        except ImportError:
            log(f"{pip_name} 未安装", "WARN")
            missing.append(pip_name)

    if missing:
        log(f"缺少依赖: {', '.join(missing)}", "ERR")
        log("请运行: pip install -r requirements.txt", "INFO")
        return False
    return True


def find_upx() -> str | None:
    """自动查找 UPX 可执行文件"""
    paths = [
        Path(r"C:\upx"),
        Path(r"C:\Program Files\upx"),
        PROJECT_DIR.parent / "upx",
    ]
    for p in paths:
        upx_exe = p / "upx.exe"
        if upx_exe.is_file():
            log(f"UPX found: {upx_exe}")
            return str(p)
    log("UPX 未找到，将跳过压缩 (可下载 https://upx.github.io/)", "WARN")
    return None


def clean_build():
    """清理旧的构建产物"""
    dirs_to_clean = [OUTPUT_DIR, WORK_DIR, PROJECT_DIR / "__pycache__"]
    for d in dirs_to_clean:
        if Path(d).exists():
            log(f"清理: {d}")
            shutil.rmtree(d, ignore_errors=True)

    # 清理 .spec 文件 (保留自定义 spec 除外)
    for spec_file in PROJECT_DIR.glob("*.spec"):
        if spec_file.name != "Claw.spec":
            spec_file.unlink()
            log(f"清理: {spec_file}")


def generate_icon():
    """生成应用图标"""
    if ICON_FILE.exists():
        log(f"图标已存在: {ICON_FILE}")
        return True

    log("图标文件不存在，正在生成...", "WARN")
    try:
        # 使用显式相对导入，避免隐式相对导入警告
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "generate_icon", str(PROJECT_DIR / "generate_icon.py")
        )
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.create_app_icon(str(ICON_FILE))  # type: ignore[reportAny]
        return True
    except Exception as e:
        log(f"图标生成失败: {e}，将使用默认图标", "WARN")
        return False


def get_pyinstaller_args(windowed: bool = True) -> list[str]:
    """
    构建 PyInstaller 命令行参数

    Args:
        windowed: True = 无控制台窗口, False = 带控制台 (调试用)
    """
    args: list[str] = []

    # === 基本设置 ===
    args.extend([str(ENTRY_SCRIPT)])

    # 显式声明隐藏导入 (确保模块被打包)
    # 注意: smb_sync.py 会被 main.py 的 import 自动检测，这里用 hidden-import 加固
    for mod in PY_MODULES:
        mod_name = mod.replace(".py", "")
        args.extend(["--hidden-import", mod_name])

    # === 输出设置 ===
    args.extend(["--name", APP_NAME])
    args.extend(["--distpath", str(OUTPUT_DIR)])
    args.extend(["--workpath", str(WORK_DIR)])
    args.extend(["--specpath", str(BUILD_DIR)])
    args.append("--noconfirm")

    # === 打包模式 ===
    args.append("--onefile")
    if windowed:
        args.append("--windowed")
    else:
        args.append("--console")

    # === 图标和版本信息 ===
    if ICON_FILE.exists():
        args.extend(["--icon", str(ICON_FILE)])
    if VERSION_FILE.exists():
        args.extend(["--version-file", str(VERSION_FILE)])

    # === 数据文件 ===
    for src, dst in DATA_FILES:
        sep = ";" if sys.platform == "win32" else ":"
        args.extend(["--add-data", f"{src}{sep}{dst}"])

    # === 隐藏导入 ===
    for mod in PYQT6_HIDDEN_IMPORTS:
        args.extend(["--hidden-import", mod])

    # === 收集子模块 (确保 Qt 平台插件被包含) ===
    for pkg in COLLECT_SUBMODULES:
        args.extend(["--collect-submodules", pkg])

    # === 收集 Qt 二进制文件 ===
    qt_binaries = [
        "PyQt6.QtCore",   # Qt6Core.dll 等
        "PyQt6.QtGui",    # Qt6Gui.dll, 平台插件
        "PyQt6.QtWidgets",# Qt6Widgets.dll, 样式插件
    ]
    for binary in qt_binaries:
        args.extend(["--collect-binaries", binary])

    # === 排除不需要的模块 ===
    for mod in EXCLUDE_MODULES:
        args.extend(["--exclude-module", mod])

    # === UPX 压缩 ===
    upx_path = find_upx()
    if upx_path:
        args.extend(["--upx-dir", upx_path])

    # === 优化 ===
    args.append("--clean")         # 清理 PyInstaller 缓存
    args.append("--noconfirm")     # 不询问覆盖
    if not windowed:
        args.append("--debug=noarchive")  # 调试模式不压缩

    return args


def run_pyinstaller(args: list[str]) -> bool:
    """执行 PyInstaller 打包"""
    cmd = [sys.executable, "-m", "PyInstaller"] + args
    log(f"执行: pyinstaller {' '.join(args[:10])}...")
    log(f"完整命令已写入日志")

    # 确保输出目录存在
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log_file = OUTPUT_DIR / f"{APP_NAME}_build.log"

    try:
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("=" * 60 + "\n")  # type: ignore[reportUnusedCallResult]
            f.write(f"Claw Build Log - {datetime.now().isoformat()}\n")  # type: ignore[reportUnusedCallResult]
            f.write(f"Command: {' '.join(cmd)}\n")  # type: ignore[reportUnusedCallResult]
            f.write("=" * 60 + "\n\n")  # type: ignore[reportUnusedCallResult]

            process = subprocess.Popen(
                cmd,
                cwd=str(PROJECT_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            stdout = process.stdout
            if stdout:
                for line in stdout:
                    stripped = line.rstrip()
                    print(f"  {stripped}")
                    f.write(line)  # type: ignore[reportUnusedCallResult]

            process.wait()

            if process.returncode == 0:
                log(f"构建日志: {log_file}")
                return True
            else:
                log(f"PyInstaller 返回码: {process.returncode}", "ERR")
                log(f"查看日志: {log_file}", "INFO")
                return False

    except Exception as e:
        log(f"构建异常: {e}", "ERR")
        return False


def verify_output() -> bool:
    """验证构建产物"""
    exe_path = OUTPUT_DIR / f"{APP_NAME}.exe"

    if not exe_path.is_file():
        log(f"输出文件不存在: {exe_path}", "ERR")
        return False

    size_mb = exe_path.stat().st_size / (1024 * 1024)
    log(f"输出文件: {exe_path}", "OK")
    log(f"文件大小: {size_mb:.1f} MB", "OK")

    # 检查 Windows 版本信息
    try:
        info = subprocess.run(
            ["powershell", "-Command",
             f"(Get-Item '{exe_path}').VersionInfo"],
            capture_output=True, text=True, timeout=10
        )
        if info.returncode == 0 and info.stdout.strip():
            log("版本信息已嵌入")
    except Exception:
        pass

    return True


def print_summary(success: bool, start_time: float):
    """打印构建摘要"""
    elapsed = time.time() - start_time
    print()
    print("=" * 55)
    print(f"  {'[OK] Build SUCCESS' if success else '[FAIL] Build FAILED'}")
    print(f"  Time: {elapsed:.1f}s")
    print(f"  Output: {OUTPUT_DIR / f'{APP_NAME}.exe'}")
    if success:
        size_mb = (OUTPUT_DIR / f"{APP_NAME}.exe").stat().st_size / (1024 * 1024)
        print(f"  Size: {size_mb:.1f} MB")
    print("=" * 55)


# ============================================================
# 主流程
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Claw 应用打包工具 (PyInstaller)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python build.py                    # 标准打包 (单文件, 无控制台)
  python build.py --clean            # 清理后重新打包
  python build.py --console          # 打包并保留控制台 (调试)
  python build.py --no-icon          # 跳过图标生成
        """
    )
    parser.add_argument("--console", action="store_true",  # type: ignore[reportUnusedCallResult]
                        help="保留控制台窗口 (调试用)")
    parser.add_argument("--clean", action="store_true",  # type: ignore[reportUnusedCallResult]
                        help="打包前清理旧构建产物")
    parser.add_argument("--no-icon", action="store_true",  # type: ignore[reportUnusedCallResult]
                        help="不生成图标")
    args: argparse.Namespace = parser.parse_args()

    start_time: float = time.time()

    print()
    log("=" * 50)
    log("Claw 应用打包工具")
    log(f"项目目录: {PROJECT_DIR}")
    log("=" * 50)
    print()

    # 1. 环境检查
    log("--- 环境检查 ---")
    check_python()
    if not check_pyinstaller():
        sys.exit(1)
    if not check_dependencies():
        sys.exit(1)
    print()

    # 2. 清理旧构建
    if args.clean:  # type: ignore[reportAny]
        log("--- 清理旧构建 ---")
        clean_build()
        print()

    # 3. 生成图标
    if not args.no_icon:  # type: ignore[reportAny]
        log("--- 图标处理 ---")
        generate_icon()
        print()

    # 4. 构建参数
    log("--- 打包配置 ---")
    build_args: list[str] = get_pyinstaller_args(windowed=not args.console)  # type: ignore[reportAny]

    # 打印参数摘要
    mode = "windowed (无控制台)" if not args.console else "console (调试)"  # type: ignore[reportAny]
    log(f"模式: {mode}")
    log(f"图标: {'有' if ICON_FILE.exists() else '无'}")
    log(f"版本: {'有' if VERSION_FILE.exists() else '无'}")
    print()

    # 5. 执行打包
    log("--- 开始打包 ---")
    success = run_pyinstaller(build_args)
    print()

    # 6. 验证
    if success:
        log("--- 验证产物 ---")
        success = verify_output()
        print()

    # 7. 摘要
    print_summary(success, start_time)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
