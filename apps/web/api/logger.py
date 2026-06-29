"""
错题管理系统 - 日志模块
"""
import logging
import sys
from logging.handlers import RotatingFileHandler
from apps.web.api.config import settings


def setup_logger(name: str) -> logging.Logger:
    """配置并返回日志记录器"""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

    if logger.handlers:
        return logger

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if settings.debug else logging.INFO)
    console_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S"
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # 文件处理器
    log_path = settings.get_log_path()
    file_handler = RotatingFileHandler(
        log_path / "app.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        settings.log_format,
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # 错误日志单独文件
    error_handler = RotatingFileHandler(
        log_path / "error.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(file_formatter)
    logger.addHandler(error_handler)

    return logger


def update_log_level(level: str) -> None:
    """L24: 动态更新所有已注册 logger 的日志级别

    在运行时通过 API 修改 log_level 后调用此函数，使新级别立即生效。
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    # 更新 root logger 及所有子 logger
    root = logging.getLogger()
    root.setLevel(numeric_level)
    for name in list(root.manager.loggerDict.keys()):
        lg = logging.getLogger(name)
        lg.setLevel(numeric_level)


# 应用主日志
logger = setup_logger("MistakeManager")
