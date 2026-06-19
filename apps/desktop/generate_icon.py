"""
应用图标生成器
使用 Pillow 生成一个简洁的错题管理应用图标
"""
import os
from PIL import Image, ImageDraw, ImageFont


def create_app_icon(output_path: str = "app_icon.ico", size: int = 256):
    """
    生成应用图标 — 书本 + 错号标记风格

    生成多个分辨率: 16, 24, 32, 48, 64, 128, 256
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 背景圆角矩形 — 深蓝主色
    margin = size // 20
    bg_color = (41, 98, 255)  # 品牌蓝
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=size // 6,
        fill=bg_color
    )

    # 书本图标 — 白色
    book_left = size * 0.25
    book_right = size * 0.75
    book_top = size * 0.30
    book_bottom = size * 0.78
    spine_x = size * 0.50

    book_color = (255, 255, 255)

    # 左页
    draw.polygon([
        (book_left, book_top),
        (spine_x, book_top + size * 0.06),
        (spine_x, book_bottom - size * 0.06),
        (book_left, book_bottom),
    ], fill=book_color)

    # 右页
    draw.polygon([
        (spine_x, book_top + size * 0.06),
        (book_right, book_top),
        (book_right, book_bottom),
        (spine_x, book_bottom - size * 0.06),
    ], fill=(230, 235, 245))

    # 中缝线
    draw.line(
        [(spine_x, book_top + size * 0.06), (spine_x, book_bottom - size * 0.06)],
        fill=(180, 190, 210),
        width=max(1, size // 128)
    )

    # 书本内页横线（左页）
    for i in range(3):
        y = book_top + size * 0.12 + i * size * 0.10
        draw.line(
            [(book_left + size * 0.06, y), (spine_x - size * 0.03, y)],
            fill=(180, 195, 220),
            width=max(1, size // 100)
        )

    # 书本内页横线（右页）
    for i in range(3):
        y = book_top + size * 0.12 + i * size * 0.10
        draw.line(
            [(spine_x + size * 0.03, y), (book_right - size * 0.06, y)],
            fill=(180, 195, 220),
            width=max(1, size // 100)
        )

    # 右上角 "X" 标记 — 红色圆形
    x_center = size * 0.72
    y_center = size * 0.28
    x_radius = size * 0.11

    draw.ellipse(
        [x_center - x_radius, y_center - x_radius,
         x_center + x_radius, y_center + x_radius],
        fill=(229, 57, 53)
    )

    # X 线条
    x_len = x_radius * 0.55
    x_width = max(2, size // 40)
    draw.line(
        [(x_center - x_len, y_center - x_len),
         (x_center + x_len, y_center + x_len)],
        fill=(255, 255, 255),
        width=x_width
    )
    draw.line(
        [(x_center + x_len, y_center - x_len),
         (x_center - x_len, y_center + x_len)],
        fill=(255, 255, 255),
        width=x_width
    )

    # 生成多分辨率 ICO
    # 注意：PIL 的 ICO 保存不能同时使用 sizes 和 append_images 参数，
    # 否则只会保存第一个尺寸。正确方式是用最大尺寸图像作为基础，
    # 通过 sizes 参数让 PIL 自动缩放到所有目标尺寸。
    sizes = [16, 24, 32, 48, 64, 128, 256]
    img.save(
        output_path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
    )

    print(f"[OK] Icon generated: {output_path}")
    return output_path


if __name__ == "__main__":
    create_app_icon(os.path.join(os.path.dirname(__file__), "app_icon.ico"))
