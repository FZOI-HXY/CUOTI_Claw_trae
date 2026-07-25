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
        assert "# 文档分析报告" in result
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


@pytest.mark.unit
class TestImageDataResolution:
    """测试图片数据解析"""

    def test_resolve_base64_data_uri(self):
        """解析 base64 data URI"""
        import base64
        from apps.web.api.markdown_generator import MarkdownGenerator

        img_data = b"test image data"
        b64_str = base64.b64encode(img_data).decode()
        data_uri = f"data:image/png;base64,{b64_str}"

        result = MarkdownGenerator._resolve_image_data(data_uri)
        assert result == img_data

    def test_resolve_plain_base64(self):
        """解析纯 base64 字符串"""
        import base64
        from apps.web.api.markdown_generator import MarkdownGenerator

        img_data = b"test plain base64"
        b64_str = base64.b64encode(img_data).decode()

        result = MarkdownGenerator._resolve_image_data(b64_str)
        assert result == img_data

    def test_resolve_empty_string(self):
        """空字符串应返回 None"""
        from apps.web.api.markdown_generator import MarkdownGenerator

        result = MarkdownGenerator._resolve_image_data("")
        assert result is None

    def test_resolve_invalid_base64(self):
        """无效 base64 应返回 None"""
        from apps.web.api.markdown_generator import MarkdownGenerator

        result = MarkdownGenerator._resolve_image_data("not valid base64!!!")
        assert result is None


@pytest.mark.unit
class TestImagePathReplacement:
    """测试图片路径替换"""

    def test_replace_image_ref_simple(self):
        """替换简单的图片引用"""
        from apps.web.api.markdown_generator import MarkdownGenerator

        mg = MarkdownGenerator(output_dir=Path("/tmp"))
        images = {"img_0": "data:image/png;base64,test"}

        md = "# Report\n\n![Image](img_0)"
        result = mg._replace_image_refs(md, images)

        assert "imgs/img_0.png" in result
        assert "](img_0)" not in result

    def test_replace_image_ref_external_url(self):
        """外部 URL 不应被替换"""
        from apps.web.api.markdown_generator import MarkdownGenerator

        mg = MarkdownGenerator(output_dir=Path("/tmp"))
        images = {}

        md = "# Report\n\n![Image](https://example.com/img.png)"
        result = mg._replace_image_refs(md, images)

        assert "https://example.com/img.png" in result

    def test_replace_image_ref_data_uri(self):
        """data URI 不应被替换"""
        from apps.web.api.markdown_generator import MarkdownGenerator

        mg = MarkdownGenerator(output_dir=Path("/tmp"))
        images = {}

        md = '# Report\n\n![Image](data:image/png;base64,iVBORw0KGgo)'
        result = mg._replace_image_refs(md, images)

        assert "data:image/png;base64,iVBORw0KGgo" in result

    def test_replace_html_img_tag(self):
        """替换 HTML img 标签中的路径"""
        from apps.web.api.markdown_generator import MarkdownGenerator

        mg = MarkdownGenerator(output_dir=Path("/tmp"))
        images = {"chart_0": "data:image/png;base64,chart"}

        md = '<img src="chart_0" alt="Chart" />'
        result = mg._replace_image_refs(md, images)

        assert 'src="imgs/chart_0.png"' in result

    def test_replace_image_ref_with_imgs_prefix(self):
        """images dict 的 key 包含 imgs/ 前缀时，markdown 引用应被正确替换"""
        from apps.web.api.markdown_generator import MarkdownGenerator

        mg = MarkdownGenerator(output_dir=Path("/tmp"))
        images = {"imgs/img_in_footer_image_box_644_1161_686_1203.jpg": "data:image/png;base64,test"}

        md = "![](imgs/img_in_footer_image_box_644_1161_686_1203.jpg)"
        result = mg._replace_image_refs(md, images)

        assert "imgs/img_in_footer_image_box_644_1161_686_1203.jpg" in result
        assert "imgs/imgs_img_in_footer" not in result

    def test_replace_image_ref_with_img_prefix(self):
        """markdown 引用包含 img/ 前缀（无 s）时也应被正确替换"""
        from apps.web.api.markdown_generator import MarkdownGenerator

        mg = MarkdownGenerator(output_dir=Path("/tmp"))
        images = {"img_in_footer_image_box_644_1161_686_1203.jpg": "data:image/png;base64,test"}

        md = "![](img/img_in_footer_image_box_644_1161_686_1203.jpg)"
        result = mg._replace_image_refs(md, images)

        assert "imgs/img_in_footer_image_box_644_1161_686_1203.jpg" in result


@pytest.mark.unit
class TestSafeImageName:
    """测试安全图片文件名生成"""

    def test_safe_image_name_with_special_chars(self):
        """包含特殊字符的图片名应被清理"""
        from apps.web.api.markdown_generator import MarkdownGenerator

        result = MarkdownGenerator._safe_image_name("img<>&:*?.png")
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result
        assert "*" not in result
        assert "?" not in result
        assert result.endswith(".png")

    def test_safe_image_name_without_extension(self):
        """无扩展名的图片名应添加 .png"""
        from apps.web.api.markdown_generator import MarkdownGenerator

        result = MarkdownGenerator._safe_image_name("img_without_ext")
        assert result.endswith(".png")

    def test_safe_image_name_with_path_separator(self):
        """路径分隔符应被替换（保留子目录结构）"""
        from apps.web.api.markdown_generator import MarkdownGenerator

        result = MarkdownGenerator._safe_image_name("subdir/image.jpg")
        assert "/" not in result
        assert "\\" not in result
        assert result.endswith(".jpg")

    def test_safe_image_name_strips_imgs_prefix(self):
        """imgs/ 前缀应被剥离，避免 imgs_img_xxx 冗余文件名"""
        from apps.web.api.markdown_generator import MarkdownGenerator

        result = MarkdownGenerator._safe_image_name("imgs/img_in_footer_image_box_644_1161_686_1203.jpg")
        assert not result.startswith("imgs_")
        assert result == "img_in_footer_image_box_644_1161_686_1203.jpg"

    def test_safe_image_name_strips_img_prefix(self):
        """img/ 前缀应被剥离"""
        from apps.web.api.markdown_generator import MarkdownGenerator

        result = MarkdownGenerator._safe_image_name("img/chart_0.jpg")
        assert not result.startswith("img_")
        assert result == "chart_0.jpg"


@pytest.mark.unit
class TestEscapeMdTableCell:
    """测试 _escape_md_table_cell XSS 防护与格式保护"""

    @pytest.mark.parametrize("input_text,expected", [
        # 管道符转义
        ("a|b|c", "a\\|b\\|c"),
        # 换行符替换为空格
        ("line1\nline2", "line1 line2"),
        # 反引号转义为 HTML 实体
        ("code `rm -rf /` here", "code &#96;rm -rf /&#96; here"),
    ])
    def test_escapes_special_chars(self, input_text, expected):
        """管道符、换行符、反引号应被正确转义"""
        from apps.web.api.markdown_generator import MarkdownGenerator
        result = MarkdownGenerator._escape_md_table_cell(input_text)
        assert result == expected

    @pytest.mark.parametrize("payload", [
        "<script>alert(1)</script>",
        '<img src=x onerror=alert(1)>',
        '<img src=x onerror=alert(1)>|`code`',
    ])
    def test_escapes_html_tags(self, payload):
        """尖括号应被 HTML 实体转义，防止注入 HTML 标签"""
        from apps.web.api.markdown_generator import MarkdownGenerator
        result = MarkdownGenerator._escape_md_table_cell(payload)
        assert "<" not in result, f"未转义的 < 字符存在: {result}"
        assert ">" not in result, f"未转义的 > 字符存在: {result}"
        assert "&lt;" in result or "&gt;" in result

    @pytest.mark.parametrize("input_value,expected", [
        ("", ""),            # 空字符串返回空
        (None, ""),          # None 返回空
        (12345, "12345"),    # 非字符串先转字符串再转义
    ])
    def test_handles_empty_and_non_string(self, input_value, expected):
        """空字符串、None、非字符串输入应正确处理"""
        from apps.web.api.markdown_generator import MarkdownGenerator
        result = MarkdownGenerator._escape_md_table_cell(input_value)
        assert result == expected

    @pytest.mark.parametrize("layout_items,assertion_func", [
        # 恶意 type 字段转义
        ([{"type": "<script>alert('xss')</script>", "content_preview": "normal text"}],
         lambda result: ("<script>" not in result and "&lt;script&gt;" in result)),
        # 恶意 preview 转义
        ([{"type": "text", "content_preview": '<img src=x onerror=alert(1)>'}],
         lambda result: ("<img src=x onerror" not in result and "&lt;img" in result)),
        # 截断在转义前进行
        ([{"type": "text", "content_preview": "A" * 95 + "<b>" + "B" * 50}],
         lambda result: ("..." in result and "&lt" not in result.replace("&lt;", ""))),
    ])
    def test_build_report_escapes_malicious_layout(self, temp_dir, layout_items, assertion_func):
        """build_report 应转义 layout_items 中的恶意内容"""
        from apps.web.api.markdown_generator import MarkdownGenerator
        mg = MarkdownGenerator(output_dir=temp_dir / "output")

        result = mg.build_report(
            original_filename="test.jpg",
            markdown_text="# Report",
            images={},
            layout_items=layout_items,
            processing_time=1.0,
        )
        assert assertion_func(result), f"断言失败，result 片段: {result[:200]}"


@pytest.mark.unit
class TestValidateImageUrl:
    """测试 _validate_image_url 的 SSRF 防护"""

    def test_validate_image_url_accepts_valid_https(self):
        """应接受有效的 https URL"""
        from apps.web.api.markdown_generator import _validate_image_url

        _validate_image_url("https://example.com/image.png")
        _validate_image_url("https://cdn.example.com/path/to/image.jpg")

    def test_validate_image_url_accepts_valid_http(self):
        """应接受有效的 http URL"""
        from apps.web.api.markdown_generator import _validate_image_url

        _validate_image_url("http://example.com/image.png")

    def test_validate_image_url_rejects_localhost(self):
        """应拒绝 localhost URL"""
        from apps.web.api.markdown_generator import _validate_image_url

        with pytest.raises(ValueError) as exc_info:
            _validate_image_url("https://localhost/image.png")
        assert "localhost" in str(exc_info.value)

        with pytest.raises(ValueError) as exc_info:
            _validate_image_url("http://localhost:8080/image.png")
        assert "localhost" in str(exc_info.value)

    def test_validate_image_url_rejects_internal_ip(self):
        """应拒绝内网 IP"""
        from apps.web.api.markdown_generator import _validate_image_url

        internal_ips = [
            "https://127.0.0.1/image.png",
            "https://192.168.1.1/image.png",
            "https://10.0.0.1/image.png",
            "https://172.16.0.1/image.png",
            "https://0.0.0.0/image.png",
            "https://[::1]/image.png",
        ]

        for url in internal_ips:
            with pytest.raises(ValueError) as exc_info:
                _validate_image_url(url)
            assert "内网" in str(exc_info.value) or "localhost" in str(exc_info.value), f"应拒绝: {url}"

    def test_validate_image_url_rejects_domain_resolving_to_internal(self):
        """应拒绝解析到内网 IP 的域名（防 DNS 重绑定）"""
        from apps.web.api.markdown_generator import _validate_image_url
        from unittest.mock import patch
        import socket

        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.side_effect = [
                [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.168.1.100", 0))],
                socket.gaierror,
            ]
            with pytest.raises(ValueError) as exc_info:
                _validate_image_url("https://evil-ssrf.example.com/image.png")
            assert "内网" in str(exc_info.value)

    def test_validate_image_url_rejects_invalid_protocol(self):
        """应拒绝无效协议"""
        from apps.web.api.markdown_generator import _validate_image_url

        invalid_protocols = [
            "ftp://example.com/image.png",
            "file:///etc/passwd",
            "data:image/png;base64,test",
            "//example.com/image.png",
            "example.com/image.png",
        ]

        for url in invalid_protocols:
            with pytest.raises(ValueError) as exc_info:
                _validate_image_url(url)
            assert "协议" in str(exc_info.value), f"应拒绝: {url}"

    def test_validate_image_url_rejects_empty_host(self):
        """应拒绝空主机名"""
        from apps.web.api.markdown_generator import _validate_image_url

        with pytest.raises(ValueError) as exc_info:
            _validate_image_url("https:///image.png")
        assert "主机名" in str(exc_info.value)

    def test_validate_image_url_rejects_invalid_url(self):
        """应拒绝无法解析的 URL"""
        from apps.web.api.markdown_generator import _validate_image_url

        with pytest.raises(ValueError):
            _validate_image_url("https://[invalid-url/image.png")

    def test_validate_image_url_rejects_ipv6_local(self):
        """应拒绝 IPv6 本地地址"""
        from apps.web.api.markdown_generator import _validate_image_url

        local_ipv6_urls = [
            "https://[::1]/image.png",
            "https://[fc00::1]/image.png",
            "https://[fe80::1]/image.png",
        ]

        for url in local_ipv6_urls:
            with pytest.raises(ValueError) as exc_info:
                _validate_image_url(url)
            assert "内网" in str(exc_info.value) or "localhost" in str(exc_info.value), f"应拒绝: {url}"

    def test_validate_image_url_accepts_ipv6_public(self):
        """应接受 IPv6 公网地址"""
        from apps.web.api.markdown_generator import _validate_image_url

        _validate_image_url("https://[2606:2800:220:1:248:1893:25c8:1946]/image.png")

    def test_validate_image_url_dns_resolution_failure(self):
        """DNS 解析失败时，_is_internal_ip 返回 False，URL 校验通过"""
        from apps.web.api.markdown_generator import _validate_image_url
        from unittest.mock import patch
        import socket

        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.side_effect = socket.gaierror
            _validate_image_url("https://non-existent-domain-xyz123.com/image.png")

    def test_validate_image_url_rejects_domain_resolving_to_ipv6_local(self):
        """应拒绝解析到 IPv6 本地地址的域名"""
        from apps.web.api.markdown_generator import _validate_image_url
        from unittest.mock import patch
        import socket

        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.side_effect = [
                socket.gaierror,
                [(socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("fc00::1", 0, 0, 0))],
            ]
            with pytest.raises(ValueError) as exc_info:
                _validate_image_url("https://evil-ipv6-local.example.com/image.png")
            assert "内网" in str(exc_info.value)
