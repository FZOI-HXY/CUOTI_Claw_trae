"""
测试: backend/markdown_generator.py - Markdown 文档生成器

覆盖:
  - 报告构建 (build_report)
  - 图片嵌入处理
  - 版式分析详情嵌入
  - 元信息头部生成
  - 输出目录管理
"""

import sys
import re
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))


@pytest.mark.unit
class TestMarkdownGeneratorInit:
    """测试初始化"""

    def test_init_creates_output_dir(self, temp_dir):
        """初始化时创建输出目录"""
        from markdown_generator import MarkdownGenerator
        out_dir = temp_dir / "test_output"
        assert not out_dir.exists()
        mg = MarkdownGenerator(output_dir=out_dir)
        assert out_dir.exists()
        assert out_dir.is_dir()

    def test_init_existing_dir(self, temp_dir):
        """已存在的目录不报错"""
        from markdown_generator import MarkdownGenerator
        out_dir = temp_dir / "existing"
        out_dir.mkdir()
        mg = MarkdownGenerator(output_dir=out_dir)
        assert out_dir.exists()


@pytest.mark.unit
class TestBuildReport:
    """测试报告构建"""

    def test_build_report_basic(self, temp_dir):
        """基本报告构建"""
        from markdown_generator import MarkdownGenerator
        mg = MarkdownGenerator(output_dir=temp_dir / "output")

        result = mg.build_report(
            original_filename="math_problem.jpg",
            markdown_text="# Test Title\n\nSome content.",
            images={},
            processing_time=5.0,
        )
        assert isinstance(result, str)
        assert "# 错题分析报告" in result
        assert "math_problem.jpg" in result

    def test_build_report_contains_metadata(self, temp_dir):
        """报告包含元信息"""
        from markdown_generator import MarkdownGenerator
        mg = MarkdownGenerator(output_dir=temp_dir / "output")

        result = mg.build_report(
            original_filename="physics_problem.png",
            markdown_text="## Physics\n\nContent here.",
            images={},
            processing_time=8.2,
        )
        assert "physics_problem.png" in result
        assert "Physics" in result
        assert "Content here" in result
        # 包含处理时间
        assert "8.2" in result or "处理耗时" in result or "processing" in result.lower()

    def test_build_report_with_layout_items(self, temp_dir):
        """包含版面分析详情"""
        from markdown_generator import MarkdownGenerator
        mg = MarkdownGenerator(output_dir=temp_dir / "output")

        layout_items = [
            {
                "blockType": "title",
                "region": {"x": 10, "y": 10, "width": 200, "height": 30},
                "contentPreview": "Chapter 1",
            },
            {
                "blockType": "text",
                "region": {"x": 10, "y": 50, "width": 300, "height": 100},
                "contentPreview": "The quick brown fox...",
            },
        ]

        result = mg.build_report(
            original_filename="test.jpg",
            markdown_text="# Report",
            images={},
            layout_items=layout_items,
            processing_time=2.0,
        )
        # 版面分析应该被包含
        assert "版面分析" in result or "Layout" in result or "blockType" in result.lower() or "title" in result.lower()

    def test_build_report_with_base64_images(self, temp_dir):
        """包含 base64 图片的处理"""
        from markdown_generator import MarkdownGenerator
        mg = MarkdownGenerator(output_dir=temp_dir / "output")

        # 生成一个有效的小型 base64 PNG
        import base64
        from PIL import Image
        from io import BytesIO
        img = Image.new("RGB", (10, 10), color=(255, 0, 0))
        buf = BytesIO()
        img.save(buf, format="PNG")
        img_b64 = base64.b64encode(buf.getvalue()).decode()

        images = {"img_0": f"data:image/png;base64,{img_b64}"}

        result = mg.build_report(
            original_filename="with_image.jpg",
            markdown_text="# Report with Image\n\n![img](img_0)",
            images=images,
            processing_time=3.0,
        )
        # 图片引用应该被替换为本地路径（而非 base64 data URI）
        assert "data:image" not in result

    def test_build_report_empty_markdown(self, temp_dir):
        """空 Markdown 文本不会崩溃"""
        from markdown_generator import MarkdownGenerator
        mg = MarkdownGenerator(output_dir=temp_dir / "output")

        result = mg.build_report(
            original_filename="empty.jpg",
            markdown_text="",
            images={},
            processing_time=0,
        )
        assert isinstance(result, str)
        assert len(result) > 0

    def test_build_report_returns_non_empty_string(self, temp_dir):
        """报告返回非空字符串"""
        from markdown_generator import MarkdownGenerator
        out_dir = temp_dir / "reports"
        mg = MarkdownGenerator(output_dir=out_dir)

        result = mg.build_report(
            original_filename="save_test.png",
            markdown_text="# Saved Report",
            images={},
            processing_time=1.5,
        )

        # build_report 返回完整的 Markdown 文本
        assert isinstance(result, str)
        assert len(result) > 0
        assert "# Saved Report" in result
        assert "save_test.png" in result


@pytest.mark.unit
class TestMarkdownGeneratorSpecialChars:
    """测试特殊字符处理"""

    def test_chinese_characters(self, temp_dir):
        """中文字符不乱码"""
        from markdown_generator import MarkdownGenerator
        mg = MarkdownGenerator(output_dir=temp_dir / "output")

        result = mg.build_report(
            original_filename="数学错题.png",
            markdown_text="# 数学错题\n\n已知函数 f(x)=x²，求 f'(x)。",
            images={},
            processing_time=2.0,
        )
        assert "数学错题" in result
        assert "函数" in result

    def test_latex_content(self, temp_dir):
        """LaTeX 公式保留"""
        from markdown_generator import MarkdownGenerator
        mg = MarkdownGenerator(output_dir=temp_dir / "output")

        result = mg.build_report(
            original_filename="latex.jpg",
            markdown_text="Formula: $$E = mc^2$$\nInline: $x^2 + y^2 = z^2$",
            images={},
            processing_time=1.0,
        )
        assert "mc^2" in result
        assert "z^2" in result

    def test_special_unicode(self, temp_dir):
        """特殊 Unicode 字符不丢失"""
        from markdown_generator import MarkdownGenerator
        mg = MarkdownGenerator(output_dir=temp_dir / "output")

        special = "\u03b1\u03b2\u03b3 \u2211 \u222b"  # Greek + sum + integral
        result = mg.build_report(
            original_filename="unicode.jpg",
            markdown_text=f"# Symbols\n\n{special}",
            images={},
            processing_time=1.0,
        )
        assert special in result


@pytest.mark.unit
class TestReportFilenameSanitization:
    """测试文件名清理"""

    def test_unsafe_filename_chars(self, temp_dir):
        """包含不安全字符的文件名"""
        from markdown_generator import MarkdownGenerator
        mg = MarkdownGenerator(output_dir=temp_dir / "output")

        result = mg.build_report(
            original_filename='test<>&":*?.png',
            markdown_text="# Clean Report",
            images={},
            processing_time=1.0,
        )
        # 不应崩溃，正常返回报告
        assert isinstance(result, str)
