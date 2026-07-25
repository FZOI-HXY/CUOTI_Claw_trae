"""
回归测试缺口补充 (Round 5)

针对 F-001 安全修复中仍未被充分覆盖的核心路径：
  1. 业务 GET 端点在启用认证时强制要求 X-Claw-Token
  2. 合法的 X-Claw-Token 请求头可正常访问业务 GET 端点
  3. 图片端点通过 ?token= 查询参数回退认证

这些测试直接降低公网部署下未授权读取敏感业务数据的回归风险。
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

_backend_path = str(Path(__file__).parent.parent / "apps" / "web" / "api")
if _backend_path in sys.path:
    sys.path.remove(_backend_path)
sys.path.insert(0, _backend_path)


@pytest.mark.integration
class TestBusinessGetEndpointsRequireAuth:
    """F-001 修复：业务 GET 端点不再全局豁免，必须校验认证 token。

    此前认证中间件对 GET 请求全局放行，导致 /api/reports、/api/history 等
    返回敏感数据的端点可被未授权访问。修复后仅显式白名单端点免认证。
    """

    @pytest.fixture
    def auth_client(self, temp_dir, load_backend_app):
        """加载后端并启用本地认证，返回 (client, backend, token)。"""
        from apps.web.api.config import settings

        original_token = settings.claw_auth_token
        # 注意：load_backend_app 会重置 claw_auth_token 为空，因此必须在加载后设置 token
        backend = load_backend_app(temp_dir, "auth_business_get")
        token = "round5_test_token_12345"
        settings.claw_auth_token = token

        try:
            client = TestClient(backend.app)
            yield client, backend, token
        finally:
            settings.claw_auth_token = original_token

    @pytest.mark.parametrize("path", [
        "/api/config",
        "/api/history",
        "/api/reports",
        "/api/report/20250725_120000_abcdef12",
        "/api/report/20250725_120000_abcdef12/download",
        "/api/report/20250725_120000_abcdef12/image/chart.png",
        "/api/batch/batch_12345",
    ])
    def test_business_get_without_token_returns_401(self, auth_client, path):
        """未提供 token 时，业务 GET 端点应返回 401"""
        client, _, _ = auth_client
        resp = client.get(path)
        assert resp.status_code == 401, f"{path} 未提供 token 时应返回 401，实际 {resp.status_code}"
        body = resp.json()
        assert body.get("code") == "UNAUTHORIZED"
        assert "未授权" in body.get("error", "")

    @pytest.mark.parametrize("path", [
        "/api/config",
        "/api/history",
        "/api/reports",
    ])
    def test_business_get_with_valid_header_token_succeeds(self, auth_client, path):
        """提供正确的 X-Claw-Token 请求头，业务 GET 端点应可访问"""
        client, _, token = auth_client
        resp = client.get(path, headers={"X-Claw-Token": token})
        assert resp.status_code == 200, f"{path} 携带合法 token 时应返回 200，实际 {resp.status_code}"

    def test_report_get_with_valid_header_token_succeeds(self, auth_client, temp_dir):
        """提供正确的 X-Claw-Token，可读取报告详情与下载"""
        client, backend, token = auth_client

        report_id = "20250725_120000_abcdef12"
        report_dir = Path(backend.settings.get_output_path()) / report_id
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.md").write_text("# Test Report")

        resp = client.get(f"/api/report/{report_id}", headers={"X-Claw-Token": token})
        assert resp.status_code == 200

        resp = client.get(f"/api/report/{report_id}/download", headers={"X-Claw-Token": token})
        assert resp.status_code == 200
        assert resp.headers.get("content-type") == "application/zip"

    def test_report_image_with_query_token_fallback(self, auth_client, temp_dir):
        """图片端点无法携带自定义头，应支持 ?token= 查询参数回退"""
        client, backend, token = auth_client

        report_id = "20250725_120000_abcdef12"
        image_name = "imgs/chart.png"
        report_dir = Path(backend.settings.get_output_path()) / report_id
        image_path = report_dir / image_name
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake_png_data")

        # 无 token 应被拒绝
        resp = client.get(f"/api/report/{report_id}/image/{image_name}")
        assert resp.status_code == 401

        # ?token= 回退应被接受
        resp = client.get(f"/api/report/{report_id}/image/{image_name}?token={token}")
        assert resp.status_code == 200, f"图片端点 ?token= 回退应返回 200，实际 {resp.status_code}"
        assert resp.headers.get("content-type") == "image/png"

    def test_batch_get_with_valid_header_token_succeeds(self, auth_client):
        """提供正确的 X-Claw-Token，批量查询端点可正常访问"""
        client, backend, token = auth_client

        with patch.object(backend.paddle_service, "batch_get_results", new_callable=AsyncMock) as mock_batch:
            mock_batch.return_value = {"success": True, "results": []}
            resp = client.get("/api/batch/batch_12345", headers={"X-Claw-Token": token})
            assert resp.status_code == 200
            body = resp.json()
            assert body.get("success") is True
            assert body.get("count") == 0

    def test_invalid_token_rejected_for_business_get(self, auth_client):
        """错误的 token 无法通过认证中间件"""
        client, _, _ = auth_client
        resp = client.get("/api/history", headers={"X-Claw-Token": "wrong_token"})
        assert resp.status_code == 401


@pytest.mark.integration
class TestAuthMiddlewareHmacTimingSafe:
    """认证中间件使用 hmac.compare_digest 做时序安全比较。

    这些测试确保比较逻辑不会被简单字符串相等替换，降低 token 被逐字节爆破的风险。
    """

    def test_token_prefix_mismatch_rejected(self, temp_dir, load_backend_app):
        """前缀不同的 token 应被拒绝"""
        from apps.web.api.config import settings

        original_token = settings.claw_auth_token
        backend = load_backend_app(temp_dir, "auth_hmac_prefix")
        settings.claw_auth_token = "secret_token_value"
        try:
            client = TestClient(backend.app)

            resp = client.get("/api/history", headers={"X-Claw-Token": "secret_token_wrong"})
            assert resp.status_code == 401
        finally:
            settings.claw_auth_token = original_token

    def test_token_case_sensitive(self, temp_dir, load_backend_app):
        """token 比较应区分大小写"""
        from apps.web.api.config import settings

        original_token = settings.claw_auth_token
        backend = load_backend_app(temp_dir, "auth_hmac_case")
        settings.claw_auth_token = "SecretToken"
        try:
            client = TestClient(backend.app)

            resp = client.get("/api/history", headers={"X-Claw-Token": "secrettoken"})
            assert resp.status_code == 401
        finally:
            settings.claw_auth_token = original_token
