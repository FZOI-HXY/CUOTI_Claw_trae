"""
测试: backend/logger.py - 日志模块
"""

import logging

import pytest

# 路径由 conftest.py 统一设置（apps/web/api），此处无需重复添加


@pytest.mark.unit
class TestSetupLogger:
    def test_returns_logger_instance(self):
        from logger import setup_logger
        logger = setup_logger("TestLogger1")
        assert isinstance(logger, logging.Logger)

    def test_logger_name_correct(self):
        from logger import setup_logger
        logger = setup_logger("MyCustomLogger")
        assert logger.name == "MyCustomLogger"

    def test_logger_has_handlers(self):
        from logger import setup_logger
        logger = setup_logger("TestLogger2")
        assert len(logger.handlers) > 0

    def test_same_name_reuses_logger(self):
        from logger import setup_logger
        logger_a = setup_logger("TestLogger_Dup")
        count_a = len(logger_a.handlers)
        logger_b = setup_logger("TestLogger_Dup")
        assert len(logger_b.handlers) == count_a
        assert logger_a is logger_b

    def test_different_names_different_loggers(self):
        from logger import setup_logger
        l1 = setup_logger("Logger_A")
        l2 = setup_logger("Logger_B")
        assert l1 is not l2


@pytest.mark.unit
class TestLoggerHandlers:
    def test_has_console_handler(self):
        from logger import setup_logger
        logger = setup_logger("TestLogger_H1")
        has_console = any(
            isinstance(h, logging.StreamHandler)
            for h in logger.handlers
        )
        assert has_console


@pytest.mark.unit
class TestLoggerWriting:
    def test_info_log(self):
        from logger import setup_logger
        logger = setup_logger("TestLogger_W1")
        logger.info("Test info")

    def test_warning_log(self):
        from logger import setup_logger
        logger = setup_logger("TestLogger_W2")
        logger.warning("Test warning")

    def test_error_log(self):
        from logger import setup_logger
        logger = setup_logger("TestLogger_W3")
        logger.error("Test error")

    def test_format_log(self):
        from logger import setup_logger
        logger = setup_logger("TestLogger_W4")
        logger.info("User %s uploaded %s", "admin", "test.jpg")


@pytest.mark.unit
class TestModuleLevelLogger:
    def test_module_logger_ok(self):
        from logger import logger
        assert isinstance(logger, logging.Logger)
        assert logger.name == "MistakeManager"
