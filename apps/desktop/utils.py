"""
Standalone 工具函数
- Markdown → HTML 渲染
- 文件大小格式化
"""
import re
from html import escape as _html_escape
from pathlib import Path


def _escape_text(text: str) -> str:
    """对纯文本进行 HTML 转义，防止 XSS。

    转义 & < > " ' 五个字符，防止恶意 HTML/JS 注入。
    """
    return _html_escape(text, quote=True)


def render_markdown_html(md: str, report_dir: str = "", api_base: str = "") -> str:
    """
    将 Markdown 转换为基本 HTML（用于 QTextEdit 显示）

    Args:
        md: Markdown 文本
        report_dir: 报告目录的绝对路径（用于将相对图片路径转为 file:// URL）
        api_base: API 基础地址（备用方案，通过 API 获取图片）
    """
    # 输入大小保护：拒绝超长文本，防止正则回溯爆炸
    MAX_MD_LENGTH = 5 * 1024 * 1024  # 5MB
    if len(md) > MAX_MD_LENGTH:
        return (
            "<html><body><p style='color:#f87171;'>"
            f"Markdown 文本过长 ({len(md) / 1024 / 1024:.1f}MB)，"
            "不进行渲染以避免性能问题。</p></body></html>"
        )

    css = """
    <style>
    body { font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif; color: #e8ecf1;
           background: #111827; line-height: 1.8; padding: 10px; }
    h1 { color: #f59e0b; border-bottom: 2px solid rgba(245,158,11,0.3); padding-bottom: 8px; }
    h2 { color: #fbbf24; border-bottom: 1px solid rgba(245,158,11,0.2); padding-bottom: 6px; }
    h3 { color: #fcd34d; }
    strong { color: #f59e0b; }
    em { color: #fbbf24; }
    code { background: #1a2235; padding: 2px 6px; border-radius: 3px;
           font-family: 'Consolas', monospace; color: #10b981; }
    pre { background: #1a2235; padding: 12px; border-radius: 8px; overflow-x: auto;
          border: 1px solid rgba(255,255,255,0.06); }
    pre code { background: transparent; padding: 0; color: #e8ecf1; }
    table { border-collapse: collapse; width: 100%; margin: 12px 0; }
    th, td { border: 1px solid rgba(255,255,255,0.1); padding: 8px 12px; text-align: left; }
    th { background: #1a2235; color: #f59e0b; font-weight: 600; }
    tr:nth-child(even) { background: rgba(255,255,255,0.02); }
    blockquote { border-left: 3px solid #f59e0b; padding-left: 16px; margin: 12px 0;
                 color: #8b95a8; }
    hr { border: none; border-top: 1px solid rgba(255,255,255,0.08); margin: 16px 0; }
    li { margin: 4px 0; }
    img { max-width: 100%; border-radius: 8px; margin: 8px 0; }
    </style>
    """

    # ---- 第一阶段：提取需要保护的块（代码块、图片），用占位符替换 ----
    placeholders: list[str] = []

    def _make_placeholder(html_content: str) -> str:
        """生成唯一占位符并保存对应的 HTML 内容"""
        idx = len(placeholders)
        placeholders.append(html_content)
        return f"\x00PH{idx}\x00"

    # 提取代码块 ```json ... ``` （内容不需要转义，保持原样展示）
    def _extract_codeblock(match):
        code = match.group(1)
        # 代码块内容做 HTML 转义（保留显示原样，但防止注入）
        return _make_placeholder(f"<pre><code>{_escape_text(code)}</code></pre>")
    md = re.sub(r'```json\n([\s\S]*?)```', _extract_codeblock, md)

    # 提取图片语法: ![alt](path) → 生成 <img> 标签（alt 和路径需转义）
    def _resolve_img(match):
        alt = _escape_text(match.group(1) or "image")
        img_path = match.group(2)
        # 跳过已有协议的 URL
        if img_path.startswith(("http://", "https://", "data:", "file://")):
            safe_src = _escape_text(img_path)
            return _make_placeholder(f'<img src="{safe_src}" alt="{alt}" width="34%" />')
        # 优先用 report_dir 解析为本地 file:// 路径
        if report_dir:
            full = (Path(report_dir) / img_path).resolve()
            if full.exists():
                # 用 as_uri() 生成跨平台兼容的 file:// URL（Windows 下自动转换反斜杠）
                safe_src = _escape_text(full.as_uri())
                return _make_placeholder(f'<img src="{safe_src}" alt="{alt}" width="34%" />')
        # 其次尝试通过 API 获取（需要 report_id）
        if api_base and report_dir:
            from pathlib import PurePath
            report_id = PurePath(report_dir).name
            api_url = f"{api_base.rstrip('/')}/api/report/{report_id}/image/{img_path}"
            safe_src = _escape_text(api_url)
            return _make_placeholder(f'<img src="{safe_src}" alt="{alt}" width="34%" />')
        # 都不行就保留原样，显示 alt 文本
        safe_path = _escape_text(img_path)
        return _make_placeholder(f'<div style="color:#f87171;padding:4px 0;">[图片: {alt} - {safe_path}]</div>')
    md = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', _resolve_img, md)

    # ---- 第二阶段：对剩余文本进行 HTML 转义 ----
    html = _escape_text(md)

    # ---- 第三阶段：Markdown 标记转换（此时文本已转义，安全） ----
    html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
    html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
    html = re.sub(r'`([^`]+)`', lambda m: f'<code>{_escape_text(m.group(1))}</code>', html)
    html = re.sub(r'^&gt; (.+)$', r'<blockquote>\1</blockquote>', html, flags=re.MULTILINE)
    html = re.sub(r'^- (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
    html = re.sub(r'^---$', r'<hr>', html, flags=re.MULTILINE)
    # 表格行（转义后 | 仍是 |，单元格内容已转义）
    html = re.sub(
        r'^\|(.+)\|$',
        lambda m: '<tr>' + ''.join(
            f'<td>{c.strip()}</td>' for c in m.group(1).split('|')
            if c.strip() and '---' not in c
        ) + '</tr>',
        html, flags=re.MULTILINE
    )

    # ---- 第四阶段：还原占位符（代码块、图片） ----
    def _restore_placeholder(match):
        idx = int(match.group(1))
        if 0 <= idx < len(placeholders):
            return placeholders[idx]
        return ""
    html = re.sub(r'\x00PH(\d+)\x00', _restore_placeholder, html)

    return f"<html><head>{css}</head><body>{html}</body></html>"


def format_size(bytes_val: int) -> str:
    """格式化文件大小"""
    if bytes_val < 1024:
        return f"{bytes_val} B"
    elif bytes_val < 1024 * 1024:
        return f"{bytes_val / 1024:.1f} KB"
    return f"{bytes_val / (1024 * 1024):.1f} MB"
