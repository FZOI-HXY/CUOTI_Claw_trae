"""
Standalone 工具函数
- Markdown → HTML 渲染
- 文件大小格式化
"""
import re


def render_markdown_html(md: str) -> str:
    """将 Markdown 转换为基本 HTML（用于 QTextEdit 显示）"""
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
    html = md
    # 基本转换
    html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
    html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
    html = re.sub(r'`([^`]+)`', r'<code>\1</code>', html)
    html = re.sub(r'```json\n([\s\S]*?)```', r'<pre><code>\1</code></pre>', html)
    html = re.sub(r'^> (.+)$', r'<blockquote>\1</blockquote>', html, flags=re.MULTILINE)
    html = re.sub(r'^- (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
    html = re.sub(r'^---$', r'<hr>', html, flags=re.MULTILINE)
    # 表格行
    html = re.sub(
        r'^\|(.+)\|$',
        lambda m: '<tr>' + ''.join(
            f'<td>{c.strip()}</td>' for c in m.group(1).split('|')
            if c.strip() and '---' not in c
        ) + '</tr>',
        html, flags=re.MULTILINE
    )
    return f"<html><head>{css}</head><body>{html}</body></html>"


def format_size(bytes_val: int) -> str:
    """格式化文件大小"""
    if bytes_val < 1024:
        return f"{bytes_val} B"
    elif bytes_val < 1024 * 1024:
        return f"{bytes_val / 1024:.1f} KB"
    return f"{bytes_val / (1024 * 1024):.1f} MB"
