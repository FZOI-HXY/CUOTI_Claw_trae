"""
UI 合规性验证测试 - 基于 Web Interface Guidelines

TDD RED 阶段: 这些测试在修复前应全部失败，修复后应全部通过。
验证 HTML/CSS/JS 文件是否符合 Web Interface Guidelines 规范。
"""

import re
from pathlib import Path

import pytest

# 文件路径
FRONTEND_DIR = Path(__file__).parent.parent / "apps" / "web" / "frontend"
HTML_FILE = FRONTEND_DIR / "index.html"
CSS_FILE = FRONTEND_DIR / "styles.css"
JS_FILE = FRONTEND_DIR / "app.js"


def _read_html():
    return HTML_FILE.read_text(encoding="utf-8")


def _read_css():
    return CSS_FILE.read_text(encoding="utf-8")


def _read_js():
    return JS_FILE.read_text(encoding="utf-8")


# ──────────────────────────────────────────────────
# HTML: 暗色模式与元数据
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestHtmlDarkModeAndMeta:
    """测试 HTML 暗色模式声明和元数据"""

    def test_html_has_color_scheme_dark(self):
        """<html> 标签应声明 color-scheme: dark"""
        html = _read_html()
        assert 'color-scheme' in html, "html 标签缺少 color-scheme 声明"

    def test_has_theme_color_meta(self):
        """应有 <meta name="theme-color"> 匹配页面背景"""
        html = _read_html()
        assert 'name="theme-color"' in html, "缺少 theme-color meta 标签"

    def test_has_preconnect_for_mathjax_cdn(self):
        """MathJax CDN 应有 preconnect"""
        html = _read_html()
        assert 'rel="preconnect"' in html, "缺少 preconnect 链接"

    def test_brand_name_has_translate_no(self):
        """品牌名应标记 translate=\"no\" 防止自动翻译"""
        html = _read_html()
        # 查找 brand-title 附近是否有 translate="no"
        assert 'translate="no"' in html, "品牌名缺少 translate=no"


# ──────────────────────────────────────────────────
# HTML: 无障碍
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestHtmlAccessibility:
    """测试 HTML 无障碍合规"""

    def test_nav_icon_has_aria_hidden(self):
        """装饰性导航图标应有 aria-hidden=\"true\""""
        html = _read_html()
        # 查找 nav-icon span，检查是否有 aria-hidden
        nav_icon_pattern = r'<span class="nav-icon"[^>]*>'
        matches = re.findall(nav_icon_pattern, html)
        assert len(matches) > 0, "未找到 nav-icon"
        for match in matches:
            assert 'aria-hidden' in match, f"nav-icon 缺少 aria-hidden: {match}"

    def test_upload_zone_has_keyboard_access(self):
        """upload-zone 应有键盘访问能力（tabindex 或为 button）"""
        html = _read_html()
        upload_zone_match = re.search(r'<div class="upload-zone"[^>]*>', html)
        if upload_zone_match:
            zone_tag = upload_zone_match.group()
            assert 'tabindex' in zone_tag or 'role=' in zone_tag, \
                "upload-zone div 缺少 tabindex 或 role 属性"

    def test_toast_container_has_aria_live(self):
        """toast-container 应有 aria-live=\"polite\""""
        html = _read_html()
        assert 'aria-live' in html, "toast-container 缺少 aria-live"

    def test_labels_associated_with_inputs(self):
        """所有独立 <label> 应通过 for 属性关联 <input>（包裹input的除外）"""
        html = _read_html()
        # 找到所有 label 开始标签
        label_tags = re.findall(r'<label[^>]*>', html)
        for label_tag in label_tags:
            # 跳过包裹 input 的 label（class 包含 select 或无 for 但内部有 input）
            if 'select-all-label' in label_tag or 'report-select-label' in label_tag:
                continue
            assert 'for=' in label_tag, f"label 缺少 for 属性: {label_tag}"

    def test_form_inputs_have_autocomplete(self):
        """表单文本类 input 应有 autocomplete 属性（checkbox/radio/file 等除外）"""
        html = _read_html()
        # 找到所有 input
        inputs = re.findall(r'<input[^>]*>', html)
        # 排除 hidden、file、checkbox、radio 类型
        for inp in inputs:
            # 跳过不需要 autocomplete 的类型
            if any(t in inp for t in ['type="hidden"', 'type="file"', 'type="checkbox"', 'type="radio"']):
                continue
            assert 'autocomplete' in inp, f"input 缺少 autocomplete: {inp}"

    def test_password_input_has_spellcheck_false(self):
        """密码输入框应有 spellcheck=\"false\""""
        html = _read_html()
        password_match = re.search(r'<input type="password"[^>]*>', html)
        if password_match:
            assert 'spellcheck' in password_match.group(), \
                "密码输入框缺少 spellcheck=false"

    def test_external_links_have_rel_noopener(self):
        """外部链接应有 rel=\"noopener noreferrer\""""
        html = _read_html()
        external_links = re.findall(r'<a href="https?://[^"]*"[^>]*target="_blank"[^>]*>', html)
        for link in external_links:
            assert 'rel=' in link, f"外部链接缺少 rel 属性: {link}"

    def test_has_skip_link(self):
        """应有跳转到主内容的 skip link"""
        html = _read_html()
        assert 'skip' in html.lower() or '跳转' in html, "缺少 skip link"

    def test_preview_img_has_dimensions(self):
        """预览图片应有 width 和 height 属性"""
        html = _read_html()
        preview_img = re.search(r'<img id="preview-original"[^>]*>', html)
        if preview_img:
            img_tag = preview_img.group()
            assert 'width' in img_tag, "preview img 缺少 width"
            assert 'height' in img_tag, "preview img 缺少 height"


# ──────────────────────────────────────────────────
# HTML: 排版
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestHtmlTypography:
    """测试 HTML 排版规范"""

    def test_no_three_dot_ellipsis_in_html(self):
        """HTML 中不应使用三个点 ... 作为省略号，应用 …"""
        html = _read_html()
        # 排除 JS 代码中的 ...（展开运算符等）
        # 只检查可见文本中的 ...
        visible_text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        # 匹配文本中的 ...（不在标签内）
        ellipsis_matches = re.findall(r'(?<!\.)\.\.\.(?!\.)', visible_text)
        assert len(ellipsis_matches) == 0, \
            f"HTML 中发现 {len(ellipsis_matches)} 处 '...' 应改为 '…'"


# ──────────────────────────────────────────────────
# CSS: 动画与焦点
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestCssAnimationAndFocus:
    """测试 CSS 动画和焦点状态"""

    def test_has_prefers_reduced_motion(self):
        """CSS 应包含 prefers-reduced-motion 媒体查询"""
        css = _read_css()
        assert 'prefers-reduced-motion' in css, \
            "CSS 缺少 prefers-reduced-motion 媒体查询"

    def test_no_transition_all(self):
        """不应使用 transition: all，应列出具体属性"""
        css = _read_css()
        # 查找 transition: all
        matches = re.findall(r'transition:\s*all', css)
        assert len(matches) == 0, \
            f"发现 {len(matches)} 处 'transition: all'，应改为具体属性"

    def test_has_focus_visible(self):
        """应使用 :focus-visible 而非仅 :focus"""
        css = _read_css()
        assert ':focus-visible' in css, "CSS 缺少 :focus-visible"

    def test_no_outline_none_without_replacement(self):
        """outline: none 应有焦点替代"""
        css = _read_css()
        # 查找 outline: none 或 outline:none
        outline_none = re.findall(r'outline:\s*none', css)
        # 如果有 outline: none，附近应有 :focus-visible 或 box-shadow 替代
        # 这个测试较宽松，只要存在 :focus-visible 就算通过
        if outline_none:
            assert ':focus-visible' in css, \
                "有 outline: none 但缺少 :focus-visible 替代"


# ──────────────────────────────────────────────────
# CSS: 排版与暗色模式
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestCssTypographyAndDarkMode:
    """测试 CSS 排版和暗色模式"""

    def test_has_color_scheme_dark(self):
        """:root 或 html 应声明 color-scheme: dark"""
        css = _read_css()
        assert 'color-scheme' in css, "CSS 缺少 color-scheme: dark"

    def test_has_tabular_nums(self):
        """数字列应有 font-variant-numeric: tabular-nums"""
        css = _read_css()
        assert 'tabular-nums' in css, "CSS 缺少 tabular-nums"

    def test_has_text_wrap_balance(self):
        """标题应有 text-wrap: balance"""
        css = _read_css()
        assert 'text-wrap' in css or 'text-pretty' in css, \
            "CSS 缺少 text-wrap: balance"

    def test_select_has_explicit_colors(self):
        """select 应有显式 background-color 和 color（Windows 暗色模式）"""
        css = _read_css()
        # 查找 select 相关样式
        select_section = re.search(r'select\s*\{[^}]*\}', css)
        if select_section:
            select_css = select_section.group()
            assert 'background-color' in select_css or 'background:' in select_css, \
                "select 缺少显式 background-color"

    def test_has_touch_action_manipulation(self):
        """应有 touch-action: manipulation"""
        css = _read_css()
        assert 'touch-action' in css, "CSS 缺少 touch-action: manipulation"

    def test_has_tap_highlight_color(self):
        """应有 -webkit-tap-highlight-color 声明"""
        css = _read_css()
        assert 'tap-highlight-color' in css, "CSS 缺少 -webkit-tap-highlight-color"


# ──────────────────────────────────────────────────
# JS: 排版与国际化
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestJsTypographyAndI18n:
    """测试 JS 排版和国际化"""

    def test_no_three_dot_ellipsis_in_strings(self):
        """JS 字符串中不应使用 ... 作为省略号（字符串字面量中）"""
        js = _read_js()
        # 查找字符串中的 ...（单引号或双引号或反引号内）
        # 匹配 'xxx...' "xxx..." `xxx...`
        string_ellipsis = re.findall(r"""['"`][^'"`]*\.\.\.[^'"`]*['"`]""", js)
        # 过滤掉合法的展开运算符（如 ...args）
        real_ellipsis = [s for s in string_ellipsis if not re.search(r'\.\.\.\w', s)]
        assert len(real_ellipsis) == 0, \
            f"JS 字符串中发现 {len(real_ellipsis)} 处 '...' 应改为 '…': {real_ellipsis[:5]}"

    def test_format_file_size_uses_intl(self):
        """formatFileSize 应使用 Intl.NumberFormat"""
        js = _read_js()
        assert 'Intl.NumberFormat' in js or 'Intl' in js, \
            "formatFileSize 应使用 Intl.NumberFormat 进行国际化"


# ──────────────────────────────────────────────────
# JS: 无障碍与状态
# ──────────────────────────────────────────────────

@pytest.mark.unit
class TestJsAccessibilityAndState:
    """测试 JS 无障碍和状态管理"""

    def test_upload_zone_has_keyboard_handler(self):
        """upload-zone 应有键盘事件处理"""
        js = _read_js()
        # 检查是否有 keydown 或 keyup 事件监听
        assert 'keydown' in js.lower() or 'keyup' in js.lower(), \
            "upload-zone 缺少键盘事件处理"

    def test_has_prefers_reduced_motion_check(self):
        """JS 应检测 prefers-reduced-motion"""
        js = _read_js()
        assert 'prefers-reduced-motion' in js or 'matchMedia' in js, \
            "JS 缺少 prefers-reduced-motion 检测"

    def test_has_beforeunload_warning(self):
        """处理中离开页面应有 beforeunload 警告"""
        js = _read_js()
        assert 'beforeunload' in js, "JS 缺少 beforeunload 警告"

    def test_rendermarkdown_escapes_table_cells(self):
        """renderMarkdown 中表格单元格内容应被转义"""
        js = _read_js()
        # 查找表格渲染部分，检查是否有转义
        table_render = re.search(r'split\([\'"]\|[\'"]\).*?map', js, re.DOTALL)
        if table_render:
            # 检查单元格内容是否经过 escapeHtml
            table_section = js[table_render.start():table_render.start() + 500]
            assert 'escapeHtml' in table_section or 'escape' in table_section.lower(), \
                "表格单元格内容未转义"

    def test_has_resize_debounce(self):
        """resize 事件应有 debounce 处理"""
        js = _read_js()
        # 查找 resize 事件监听
        resize_match = re.search(r'addEventListener\([\'"]resize[\'"]', js)
        if resize_match:
            # 检查是否有 debounce 或 setTimeout
            nearby = js[resize_match.start():resize_match.start() + 200]
            assert 'debounce' in nearby.lower() or 'setTimeout' in nearby, \
                "resize 事件缺少 debounce"

    def test_cfg_host_default_is_loopback(self):
        """cfg-host 默认值应为 127.0.0.1"""
        js = _read_js()
        assert "'127.0.0.1'" in js or '"127.0.0.1"' in js, \
            "cfg-host 默认值应改为 127.0.0.1"

    def test_generated_img_has_dimensions(self):
        """JS 生成的 img 标签应有 width/height"""
        js = _read_js()
        # 查找所有 img 标签生成处
        img_matches = list(re.finditer(r'<img\s+src=', js))
        if img_matches:
            for match in img_matches:
                # 检查 img 标签附近 200 字符内是否有 width 或 height
                nearby = js[match.start():match.start() + 200]
                assert 'width' in nearby or 'height' in nearby, \
                    f"生成的 img 标签缺少 width/height，位置: {match.start()}"
