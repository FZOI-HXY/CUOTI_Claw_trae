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


@pytest.mark.unit
class TestModuleLevelLogger:
    def test_module_logger_ok(self):
        from logger import logger
        assert isinstance(logger, logging.Logger)
        assert logger.name == "MistakeManager"
