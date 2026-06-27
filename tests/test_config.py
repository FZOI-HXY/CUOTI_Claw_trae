"""
测试: backend/config.py - 系统配置模块

覆盖:
  - 默认值正确性
  - derived 属性 (路径构建)
  - 环境变量覆盖
"""

from pathlib import Path

import pytest

# 路径由 conftest.py 统一设置（apps/web/api），此处无需重复添加


@pytest.mark.unit
class TestSettingsDefaults:
    """测试默认值 — 使用 _env_file="" 避免读取用户 .env 配置"""

    def test_default_api_url(self):
        from config import Settings
        s = Settings(_env_file="")  # type: ignore[reportCallIssue]
        assert "paddleocr.aistudio-app.com" in s.paddleocr_api_url

    def test_default_model(self):
        from config import Settings
        s = Settings(_env_file="")  # type: ignore[reportCallIssue]
        assert s.paddleocr_model == "PaddleOCR-VL-1.6"

    def test_default_host_port(self):
        from config import Settings
        s = Settings(_env_file="")  # type: ignore[reportCallIssue]
        assert s.host == "127.0.0.1"
        assert s.port == 8500

    def test_default_max_upload(self):
        from config import Settings
        s = Settings(_env_file="")  # type: ignore[reportCallIssue]
        assert s.max_upload_size_mb == 50

    def test_default_log_level(self):
        from config import Settings
        s = Settings(_env_file="")  # type: ignore[reportCallIssue]
        assert s.log_level == "INFO"


@pytest.mark.unit
class TestSettingsPaths:
    def test_get_upload_path(self, temp_dir):
        from config import Settings
        s = Settings(upload_dir=str(temp_dir / "test_uploads"))
        p = s.get_upload_path()
        assert p.exists()
        assert p.is_dir()

    def test_get_output_path(self, temp_dir):
        from config import Settings
        s = Settings(output_dir=str(temp_dir / "test_output"))
        p = s.get_output_path()
        assert p.exists()

    def test_get_log_path(self, temp_dir):
        from config import Settings
        s = Settings(log_dir=str(temp_dir / "test_logs"))
        p = s.get_log_path()
        assert p.exists()


@pytest.mark.unit
class TestSettingsEnvOverride:
    def test_env_var_override_port(self, temp_env):
        temp_env["PORT"] = "9999"
        from config import Settings
        s = Settings(_env_file="")  # type: ignore[reportCallIssue]
        assert s.port == 9999

    def test_env_var_override_host(self, temp_env):
        temp_env["HOST"] = "127.0.0.1"
        from config import Settings
        s = Settings(_env_file="")  # type: ignore[reportCallIssue]
        assert s.host == "127.0.0.1"

    def test_env_var_override_log_level(self, temp_env):
        temp_env["LOG_LEVEL"] = "DEBUG"
        from config import Settings
        s = Settings(_env_file="")  # type: ignore[reportCallIssue]
        assert s.log_level == "DEBUG"


@pytest.mark.unit
class TestEnvFilePath:
    def test_env_file_path_is_path(self):
        from config import ENV_FILE_PATH
        assert isinstance(ENV_FILE_PATH, Path)

    def test_env_file_path_backend_dir(self):
        from config import ENV_FILE_PATH
        # ENV_FILE_PATH 现在通过自动发现确定，可能是源码目录、
        # %APPDATA%/Claw/ 或 exe 同级目录。只需验证它是有效的 .env 路径。
        assert ENV_FILE_PATH.name == ".env"
        assert ENV_FILE_PATH.parent.exists()
