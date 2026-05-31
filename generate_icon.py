"""Generate a multi-size Windows .ico for the app and shortcuts."""

from __future__ import annotations

import struct
import sys
from pathlib import Path

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
BRAND_BLUE = (0x4D, 0x6B, 0xFE, 255)
BRAND_BLUE_DARK = (0x30, 0x30, 0x32, 255)
WHITE = (255, 255, 255, 255)


def _set_pixel(
    pixels: list[tuple[int, int, int, int]],
    size: int,
    x: int,
    y: int,
    color: tuple[int, int, int, int],
) -> None:
    if 0 <= x < size and 0 <= y < size:
        pixels[y * size + x] = color


def _draw_icon_rgba(size: int) -> list[tuple[int, int, int, int]]:
    pixels = [(0, 0, 0, 0)] * (size * size)
    center = (size - 1) / 2
    outer_radius = size * 0.46
    inner_radius = size * 0.40

    for y in range(size):
        for x in range(size):
            dx = x - center
            dy = y - center
            distance_sq = dx * dx + dy * dy
            if distance_sq <= outer_radius * outer_radius:
                pixels[y * size + x] = BRAND_BLUE_DARK
            if distance_sq <= inner_radius * inner_radius:
                pixels[y * size + x] = BRAND_BLUE

    stroke = max(1, size // 16)
    left = int(size * 0.30)
    top = int(size * 0.28)
    bottom = int(size * 0.72)
    right = int(size * 0.62)

    for y in range(top, bottom + 1):
        for s in range(stroke):
            _set_pixel(pixels, size, left + s, y, WHITE)
    for x in range(left, right + 1):
        for s in range(stroke):
            _set_pixel(pixels, size, x, top + s, WHITE)
            _set_pixel(pixels, size, x, bottom - s, WHITE)
    for y in range(top, bottom + 1):
        for s in range(stroke):
            _set_pixel(pixels, size, right - s, y, WHITE)

    return pixels


def _bitmap_payload(size: int, pixels: list[tuple[int, int, int, int]]) -> bytes:
    header = struct.pack(
        "<IIIHHIIIIII",
        40,
        size,
        size * 2,
        1,
        32,
        0,
        0,
        0,
        0,
        0,
        0,
    )

    xor_rows = bytearray()
    for y in range(size - 1, -1, -1):
        row = pixels[y * size : (y + 1) * size]
        for red, green, blue, alpha in row:
            xor_rows.extend((blue, green, red, alpha))
        padding = (4 - (size * 4) % 4) % 4
        xor_rows.extend(b"\x00" * padding)

    and_row_bytes = ((size + 31) // 32) * 4
    and_rows = b"\x00" * (and_row_bytes * size)
    return header + bytes(xor_rows) + and_rows


def _build_ico(images: list[tuple[int, bytes]]) -> bytes:
    count = len(images)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    entries = bytearray()
    blobs = bytearray()

    for size, payload in images:
        width = 0 if size >= 256 else size
        height = 0 if size >= 256 else size
        entries.extend(
            struct.pack(
                "<BBBBHHII",
                width,
                height,
                0,
                0,
                1,
                32,
                len(payload),
                offset,
            )
        )
        blobs.extend(payload)
        offset += len(payload)

    return header + bytes(entries) + bytes(blobs)


def generate_icon(output_path: Path, sizes: tuple[int, ...] = ICON_SIZES) -> None:
    """Write a Windows-compatible multi-size .ico file."""
    try:
        from PIL import Image, ImageDraw

        output_path.parent.mkdir(parents=True, exist_ok=True)
        images: list[Image.Image] = []
        for size in sizes:
            img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            margin = max(1, size // 16)
            draw.ellipse(
                [margin, margin, size - margin - 1, size - margin - 1],
                fill=(77, 107, 254, 255),
            )
            stroke = max(1, size // 16)
            left = int(size * 0.30)
            top = int(size * 0.28)
            bottom = int(size * 0.72)
            right = int(size * 0.62)
            draw.rectangle([left, top, left + stroke, bottom], fill=(255, 255, 255, 255))
            draw.rectangle([left, top, right, top + stroke], fill=(255, 255, 255, 255))
            draw.rectangle([left, bottom - stroke + 1, right, bottom], fill=(255, 255, 255, 255))
            draw.rectangle([right - stroke + 1, top, right, bottom], fill=(255, 255, 255, 255))
            images.append(img)
        images[0].save(
            str(output_path),
            format="ICO",
            sizes=[(image.width, image.height) for image in images],
            append_images=images[1:],
        )
        print(f"图标已生成 (PIL): {output_path}")
        return
    except ImportError:
        pass

    images = []
    for size in sizes:
        pixels = _draw_icon_rgba(size)
        images.append((size, _bitmap_payload(size, pixels)))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(_build_ico(images))
    print(f"图标已生成: {output_path} ({output_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    assets_dir = Path(__file__).resolve().parent / "assets"
    generate_icon(assets_dir / "app_icon.ico")
