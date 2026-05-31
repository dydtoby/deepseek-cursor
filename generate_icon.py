"""生成应用图标。

如果没有 PIL/Pillow，则创建基于 PNG 的最小图标。
"""

from __future__ import annotations

import base64
import struct
import sys
from pathlib import Path

# 32x32 蓝色圆形图标的最小 PNG 数据（base64 编码）
# 这是一个极简的 DeepSeek 风格蓝色图标
_MINIMAL_ICON_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAtklEQVR4"
    "nO2WsQ3CMBBF/x0yAiMwAiMwAiMwAiMwAiMwAiMwAiNQskIFyYWiOE4s"
    "y1eePtl3vrv/PzlJUs4ZERGZOee8AZhtzT0i4rkAiDG+BkBEHJsAGGM8"
    "JskH8CWgCMDbJQhjrIExxjUgIs4JIMZ4Nsa4NkBEHAAaIYT3ZQBjjK0A"
    "F8YYWwDGGLMAXHLO/w+gtb4MgK2sA7e4tQS01g8A7jFGX4OYwey9N+f8"
    "CACM1toHQCl1PwJ4AXKKSGV0z5YIAAAAAElFTkSuQmCC"
)


def generate_icon(output_path: Path, size: int = 32) -> None:
    """生成 .ico 文件。"""
    try:
        from PIL import Image, ImageDraw

        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # 绘制一个蓝色圆形
        draw.ellipse([2, 2, size - 3, size - 3], fill=(30, 30, 50, 255))
        # 绘制 D 字母的简化表示（白色横线）
        draw.rectangle([size // 2 - 3, size // 3, size // 2 + 3, size * 2 // 3], fill=(255, 255, 255, 255))
        draw.rectangle([size // 3, size // 3, size // 2 + 3, size // 3 + 4], fill=(255, 255, 255, 255))
        draw.rectangle([size // 3, size * 2 // 3 - 4, size // 2 + 3, size * 2 // 3], fill=(255, 255, 255, 255))

        # 确保目录存在
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 保存为 .ico（包含多尺寸）
        img.save(str(output_path), format="ICO", sizes=[(32, 32), (16, 16)])
        print(f"图标已生成 (PIL): {output_path}")
        return
    except ImportError:
        pass

    # 回退方案：使用内嵌 PNG 创建最小 .ico
    try:
        png_data = base64.b64decode(_MINIMAL_ICON_PNG_B64)
    except Exception:
        print("无法解码内嵌图标数据", file=sys.stderr)
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 构建 .ico 文件格式
    # ICO header: reserved(2) + type(2) + count(2)
    ico_header = struct.pack("<HHH", 0, 1, 1)
    # Directory entry: width, height, colors, reserved, planes, bpp, size, offset
    offset = 6 + 16  # header + 1 entry
    entry = struct.pack(
        "<BBBBHHII",
        size if size < 256 else 0,  # width
        size if size < 256 else 0,  # height
        0,   # color palette
        0,   # reserved
        1,   # color planes
        32,  # bits per pixel
        len(png_data),  # image size
        offset,          # image offset
    )

    with open(output_path, "wb") as f:
        f.write(ico_header)
        f.write(entry)
        f.write(png_data)

    print(f"图标已生成 (回退): {output_path}")


if __name__ == "__main__":
    assets_dir = Path(__file__).resolve().parent / "assets"
    generate_icon(assets_dir / "app_icon.ico")
