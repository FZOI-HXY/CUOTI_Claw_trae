"""
测试: apps/web/api/services/config_service.py - 配置持久化服务

覆盖:
  - save_env_file 函数
  - ENV_KEY_MAPPING 字段映射
  - 空文件处理
  - 空 api_key 过滤
  - 布尔值转换
"""

from pathlib import Path

import pytest


@pytest.mark.unit
class TestConfigServiceSaveEnv:
    """测试 save_env_file 函数"""

    def test_save_empty_env_file(self, temp_dir):
        """保存到不存在的 .env 文件"""
        from apps.web.api.services.config_service import save_env_file

        env_path = temp_dir / ".env"
        assert not env_path.exists()

        config_data = {"paddleocr_api_key": "test_key_123"}
        result = save_env_file(config_data, env_path)

        assert result is True
        assert env_path.exists()
        content = env_path.read_text(encoding="utf-8")
        assert "PADDLEOCR_API_KEY=test_key_123" in content

    def test_update_existing_env_file(self, temp_dir):
        """更新已存在的 .env 文件"""
        from apps.web.api.services.config_service import save_env_file

        env_path = temp_dir / ".env"
        env_path.write_text(
            "HOST=0.0.0.0\n"
            "PORT=8500\n"
            "LOG_LEVEL=INFO\n",
            encoding="utf-8"
        )

        config_data = {"host": "127.0.0.1", "port": 9999}
        result = save_env_file(config_data, env_path)

        assert result is True
        content = env_path.read_text(encoding="utf-8")
        assert "HOST=127.0.0.1" in content
        assert "PORT=9999" in content
        assert "LOG_LEVEL=INFO" in content

    def test_append_new_key(self, temp_dir):
        """追加新的配置键"""
        from apps.web.api.services.config_service import save_env_file

        env_path = temp_dir / ".env"
        env_path.write_text("HOST=127.0.0.1\n", encoding="utf-8")

        config_data = {"paddleocr_api_url": "https://new-api.example.com"}
        save_env_file(config_data, env_path)

        content = env_path.read_text(encoding="utf-8")
        assert "HOST=127.0.0.1" in content
        assert "PADDLEOCR_API_URL=https://new-api.example.com" in content

    def test_skips_empty_api_key(self, temp_dir):
        """空的 api_key 不应被写入"""
        from apps.web.api.services.config_service import save_env_file

        env_path = temp_dir / ".env"
        env_path.write_text("PADDLEOCR_API_KEY=old_key\n", encoding="utf-8")

        config_data = {"paddleocr_api_key": ""}
        save_env_file(config_data, env_path)

        content = env_path.read_text(encoding="utf-8")
        assert "PADDLEOCR_API_KEY=old_key" in content

    def test_skips_empty_api_key_new_file(self, temp_dir):
        """空的 api_key 在新文件中也不应被写入"""
        from apps.web.api.services.config_service import save_env_file

        env_path = temp_dir / ".env"

        config_data = {"paddleocr_api_key": "", "host": "127.0.0.1"}
        save_env_file(config_data, env_path)

        content = env_path.read_text(encoding="utf-8")
        assert "HOST=127.0.0.1" in content
        assert "PADDLEOCR_API_KEY" not in content

    def test_boolean_value_lowercase(self, temp_dir):
        """布尔值应转换为小写字符串"""
        from apps.web.api.services.config_service import save_env_file

        env_path = temp_dir / ".env"

        config_data = {"debug": True, "use_chart_recognition": False}
        save_env_file(config_data, env_path)

        content = env_path.read_text(encoding="utf-8")
        assert "DEBUG=true" in content
        assert "USE_CHART_RECOGNITION=false" not in content

    def test_unknown_key_ignored(self, temp_dir):
        """不在映射中的键应被忽略"""
        from apps.web.api.services.config_service import save_env_file

        env_path = temp_dir / ".env"

        config_data = {
            "host": "127.0.0.1",
            "unknown_field": "value",
            "another_unknown": "test"
        }
        save_env_file(config_data, env_path)

        content = env_path.read_text(encoding="utf-8")
        assert "HOST=127.0.0.1" in content
        assert "unknown_field" not in content
        assert "another_unknown" not in content

    def test_commented_key_updated(self, temp_dir):
        """M04: 注释掉的键保持原样，新值追加到文件末尾"""
        from apps.web.api.services.config_service import save_env_file

        env_path = temp_dir / ".env"
        env_path.write_text(
            "# PADDLEOCR_API_KEY=old_key\n"
            "# PORT=8000\n",
            encoding="utf-8"
        )

        config_data = {"paddleocr_api_key": "new_key", "port": 8500}
        save_env_file(config_data, env_path)

        content = env_path.read_text(encoding="utf-8")
        # M04: 注释行保持原样（不被取消注释）
        assert "# PADDLEOCR_API_KEY=old_key" in content
        assert "# PORT=8000" in content
        # 新值作为未注释行追加到文件末尾
        assert "PADDLEOCR_API_KEY=new_key" in content
        assert "PORT=8500" in content

    def test_save_empty_config(self, temp_dir):
        """空配置字典不应改变文件"""
        from apps.web.api.services.config_service import save_env_file

        env_path = temp_dir / ".env"
        env_path.write_text("EXISTING=value\n", encoding="utf-8")

        config_data = {}
        save_env_file(config_data, env_path)

        content = env_path.read_text(encoding="utf-8")
        assert content == "EXISTING=value\n"

    def test_error_returns_false(self, temp_dir):
        """写入失败应返回 False"""
        from apps.web.api.services.config_service import save_env_file

        invalid_path = temp_dir / "nonexistent" / ".env"

        config_data = {"host": "127.0.0.1"}
        result = save_env_file(config_data, invalid_path)

        assert result is False