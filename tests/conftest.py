"""
Claw 错题管理系统 - Pytest 全局配置与 Fixtures

使用方法:
    pytest tests/ -v --tb=short
    pytest tests/ -v --tb=short --html=reports/test_report.html --self-contained-html
"""

import os
import sys
import json
import uuid
import shutil
import tempfile
import threading
from pathlib import Path
from datetime import datetime
from io import BytesIO
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

# 将项目根目录加入 Python 路径 (backend 优先于 standalone，避免 main 模块冲突)
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "standalone"))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))


# ──────────────────────────────────────────────────
# 基础 Fixtures
# ──────────────────────────────────────────────────

@pytest.fixture(scope="session")
def project_root():
    """返回项目根目录"""
    return PROJECT_ROOT


@pytest.fixture(scope="function")
def temp_dir():
    """创建临时目录，测试后自动清理"""
    tmp = Path(tempfile.mkdtemp(prefix="claw_test_"))
    yield tmp
    try:
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception:
        pass


@pytest.fixture(scope="function")
def temp_env():
    """临时修改环境变量，测试后恢复"""
    old = os.environ.copy()
    yield os.environ
    os.environ.clear()
    os.environ.update(old)


# ──────────────────────────────────────────────────
# 测试图片生成 Fixtures
# ──────────────────────────────────────────────────

def create_test_image(size_kb: int = 20) -> bytes:
    """生成一个有效的 JPEG 测试图片 (纯内存)"""
    from PIL import Image
    img = Image.new("RGB", (400, 300), color=(200, 180, 160))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


@pytest.fixture(scope="function")
def sample_image_bytes():
    """生成测试图片字节数据"""
    return create_test_image()


@pytest.fixture(scope="function")
def sample_image_file(temp_dir):
    """生成测试图片文件并返回路径"""
    data = create_test_image()
    filepath = temp_dir / "test_sample.jpg"
    filepath.write_bytes(data)
    return filepath


# ──────────────────────────────────────────────────
# Mock PaddleOCR API 响应
# ──────────────────────────────────────────────────

@pytest.fixture
def mock_ocr_submit_response():
    """模拟 PaddleOCR 提交任务的响应"""
    job_id = uuid.uuid4().hex[:16]
    return {
        "errCode": 0,
        "errMsg": "",
        "data": {"jobId": job_id},
    }


@pytest.fixture
def mock_ocr_poll_response():
    """模拟 PaddleOCR 轮询结果 - 已完成"""
    return {
        "errCode": 0,
        "errMsg": "",
        "data": {
            "jobId": "test_job_123",
            "state": "done",
            "resultUrl": {
                "jsonUrl": "https://example.com/result/test_job_123.jsonl"
            },
        },
    }


@pytest.fixture
def mock_ocr_jsonl_response():
    """模拟 JSONL 结构化识别结果"""
    return json.dumps(json.dumps({
        "result": {
            "layoutParsingResults": [{
                "markdown": {
                    "text": "# 错题分析报告\n\n## 题目\n已知三角形 ABC，AB=3，BC=4，AC=5，求角度 A。\n\n## 解答\n由余弦定理：\n$$\\cos A = \\frac{AB^2 + AC^2 - BC^2}{2 \\cdot AB \\cdot AC} = \\frac{9+25-16}{30} = \\frac{3}{5}$$\n\n$$A = \\arccos(0.6) \\approx 53.13^\\circ$$",
                    "images": {},
                },
                "layoutImageInfo": {
                    "imageBase64": "",
                },
                "parsingInfoList": [
                    {"blockType": "title", "region": {}, "contentPreview": "错题分析报告"},
                    {"blockType": "text", "region": {}, "contentPreview": "已知三角形 ABC..."},
                ],
            }],
        },
    }))


@pytest.fixture
def mock_ocr_result_jsonl():
    """模拟简化的识别结果 JSONL"""
    return json.dumps(json.dumps({
        "result": {
            "layoutParsingResults": [{
                "markdown": {
                    "text": "# Test Report\n\nSimple content.",
                    "images": {},
                },
                "layoutImageInfo": {"imageBase64": ""},
                "parsingInfoList": [
                    {"blockType": "title", "region": {}, "contentPreview": "Test Report"},
                ],
            }],
        },
    }))


# ──────────────────────────────────────────────────
# Mock FastAPI Test Client + Mock 外部 HTTP
# ──────────────────────────────────────────────────

@pytest.fixture(scope="function")
def mock_httpx_client():
    """Mock httpx.AsyncClient，返回预设的 OCR API 响应"""
    mock_client = AsyncMock()
    mock_post = AsyncMock()
    mock_get = AsyncMock()

    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    # 默认 POST 返回
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={
        "errCode": 0,
        "data": {"jobId": "mock_job_12345678"},
    })
    mock_client.post.return_value = mock_response

    # 默认 GET 返回 (轮询完成)
    mock_get_response = MagicMock()
    mock_get_response.raise_for_status = MagicMock()
    mock_get_response.json = MagicMock(return_value={
        "errCode": 0,
        "data": {
            "state": "done",
            "resultUrl": {"jsonUrl": "https://mock.example.com/result.jsonl"},
        },
    })
    mock_client.get.return_value = mock_get_response

    return mock_client


# ──────────────────────────────────────────────────
# 测试数据 Fixtures
# ──────────────────────────────────────────────────

@pytest.fixture
def sample_markdown_text():
    """示例 Markdown 文本"""
    return (
        "# 数学错题分析\n\n"
        "## 题目\n"
        "已知函数 f(x)=x²+2x+1，求 f(3) 的值。\n\n"
        "## 错解\n"
        "f(3) = 9 + 6 + 1 = **16**\n\n"
        "## 正解\n"
        "f(3) = 3² + 2×3 + 1 = 9 + 6 + 1 = 16\n\n"
        "## 错误类型\n"
        "- 计算错误\n"
        "- 概念混淆\n\n"
        "## 知识点\n"
        "二次函数求值"
    )


@pytest.fixture
def sample_history_items():
    """示例处理历史"""
    return [
        {
            "id": 1,
            "filename": "math_problem.jpg",
            "timestamp": datetime.now().isoformat(),
            "success": True,
            "processing_time": 12.5,
            "images_count": 7,
            "report_dir": "output/rpt_abc123",
            "file_id": "abc123",
        },
        {
            "id": 2,
            "filename": "physics_problem.png",
            "timestamp": datetime.now().isoformat(),
            "success": False,
            "processing_time": 0,
            "images_count": 0,
            "report_dir": "",
            "file_id": "def456",
            "error": "OCR recognition timeout",
        },
    ]


@pytest.fixture
def sample_report_data():
    """示例报告数据"""
    return [
        {
            "id": "rpt_abc123",
            "created_time": datetime.now().isoformat(),
            "has_markdown": True,
            "path": "output/rpt_abc123",
        },
        {
            "id": "rpt_def456",
            "created_time": datetime.now().isoformat(),
            "has_markdown": False,
            "path": "",
        },
    ]


# ──────────────────────────────────────────────────
# 全局 pytest 配置
# ──────────────────────────────────────────────────

# 自定义标记注册
def pytest_configure(config):
    config.addinivalue_line("markers", "unit: 标记为单元测试")
    config.addinivalue_line("markers", "integration: 标记为集成测试")
    config.addinivalue_line("markers", "slow: 标记为耗时测试")
    config.addinivalue_line("markers", "smb: 标记为需要 SMB/NAS 的测试")
