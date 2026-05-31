"""Generate a multi-size Windows .ico from assets/logo.png."""

from __future__ import annotations

import struct
import sys
from pathlib import Path

ICON_SIZES = (128,)

BRAND_BG_COLOR = (30, 30, 35, 255)


def _extract_logo_mark(logo_path: Path) -> "Image.Image | None":
    """Extract the DeepSeek whale logo mark from the left side of the banner."""
    try:
        from PIL import Image
    except ImportError:
        return None

    img = Image.open(logo_path).convert("RGBA")
    w, h = img.size

    bbox = img.crop((0, 0, w // 3, h)).getbbox()
    if bbox is None:
        return None
    return img.crop(bbox)


def _draw_icon_rgba(size: int) -> list[tuple[int, int, int, int]]:
    """Fallback: draw a simple D-shaped icon when logo.png is unavailable."""
    pixels = [(0, 0, 0, 0)] * (size * size)
    center = (size - 1) / 2
    outer_r = size * 0.46
    inner_r = size * 0.40
    dark = (0x30, 0x30, 0x32, 255)
    blue = (0x4D, 0x6B, 0xFE, 255)
    white = (255, 255, 255, 255)

    for y in range(size):
        for x in range(size):
            dx = x - center
            dy = y - center
            d2 = dx * dx + dy * dy
            if d2 <= outer_r * outer_r:
                pixels[y * size + x] = dark
            if d2 <= inner_r * inner_r:
                pixels[y * size + x] = blue

    stroke = max(1, size // 16)
    left = int(size * 0.30)
    top = int(size * 0.28)
    bottom = int(size * 0.72)
    right = int(size * 0.62)

    for y in range(top, bottom + 1):
        for si in range(stroke):
            if 0 <= left + si < size:
                pixels[y * size + left + si] = white
            if 0 <= right - si < size:
                pixels[y * size + right - si] = white
    for x in range(left, right + 1):
        for si in range(stroke):
            if 0 <= top + si < size:
                pixels[(top + si) * size + x] = white
            if 0 <= bottom - si < size:
                pixels[(bottom - si) * size + x] = white
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


def generate_icon(
    output_path: Path,
    sizes: tuple[int, ...] = ICON_SIZES,
    logo_path: Path | None = None,
) -> None:
    """Write a Windows-compatible multi-size .ico file using logo.png style."""
    if logo_path is None:
        logo_path = Path(__file__).resolve().parent / "assets" / "logo.png"

    try:
        from PIL import Image

        output_path.parent.mkdir(parents=True, exist_ok=True)
        logo_mark = _extract_logo_mark(Path(logo_path))
        if logo_mark is None:
            raise FileNotFoundError("Cannot extract logo mark")

        images: list[Image.Image] = []
        for size in sizes:
            square = Image.new("RGBA", (size, size), BRAND_BG_COLOR)
            padding = max(1, size // 8)
            fit_size = size - padding * 2
            mark_w, mark_h = logo_mark.size
            scale = fit_size / max(mark_w, mark_h)
            new_w = int(mark_w * scale)
            new_h = int(mark_h * scale)
            resized = logo_mark.resize((new_w, new_h), Image.LANCZOS)
            offset_x = (size - new_w) // 2
            offset_y = (size - new_h) // 2
            square.paste(resized, (offset_x, offset_y), resized)
            images.append(square)

        images[0].save(
            str(output_path),
            format="ICO",
            sizes=[(img.width, img.height) for img in images],
            append_images=images[1:],
        )
        print(f"图标已生成 (logo.png): {output_path}")
        # Remove preview temp files
        for p in Path(__file__).resolve().parent.glob("assets/_logo_mark_*.png"):
            p.unlink(missing_ok=True)
        return
    except (ImportError, FileNotFoundError):
        pass

    # Fallback: draw programmatically when PIL or logo.png unavailable
    images = []
    for size in sizes:
        pixels = _draw_icon_rgba(size)
        images.append((size, _bitmap_payload(size, pixels)))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(_build_ico(images))
    print(f"图标已生成 (fallback): {output_path} ({output_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    assets_dir = Path(__file__).resolve().parent / "assets"
    generate_icon(assets_dir / "app_icon.ico")
