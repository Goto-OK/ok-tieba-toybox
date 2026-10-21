"""Render assets/app.svg to a multi-size ICO.

The SVG is the editable master.  On Windows Microsoft Edge is used as the
SVG rasterizer so the vector source, not a pre-baked PNG, drives the icon.
If Edge is unavailable we fall back to Pillow text rendering.
"""

from __future__ import annotations

import io
import os
import struct
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "assets" / "app.svg"
ICO = ROOT / "assets" / "app.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)
EDGE_PATHS = (
    Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
)


def _edge() -> Path | None:
    for path in EDGE_PATHS:
        if path.is_file():
            return path
    return None


def _render_edge(edge: Path, size: int = 512) -> Image.Image | None:
    try:
        svg = SVG.read_text(encoding="utf-8")
        svg = svg.replace('width="256" height="256"', f'width="{size}" height="{size}"', 1)
        with tempfile.TemporaryDirectory(prefix="tieba-icon-") as folder:
            source = Path(folder) / "app.svg"
            target = Path(folder) / "app.png"
            source.write_text(svg, encoding="utf-8")
            profile = Path(folder) / "edge-profile"
            command = [
                str(edge),
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--hide-scrollbars",
                "--default-background-color=00000000",
                "--force-device-scale-factor=1",
                f"--window-size={size},{size}",
                f"--user-data-dir={profile}",
                f"--screenshot={target}",
                source.as_uri(),
            ]
            subprocess.run(command, check=True, timeout=60, capture_output=True)
            if not target.is_file():
                return None
            image = Image.open(target).convert("RGBA")
            if image.size != (size, size):
                image = image.resize((size, size), Image.Resampling.LANCZOS)
            return image
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _render_fallback(size: int = 512) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=int(size * 0.19), fill=(31, 78, 121, 255))
    font = ImageFont.truetype("C:/Windows/Fonts/msyhbd.ttc", int(size * 0.82))
    draw.text((size / 2, size / 2 + size * 0.02), "贴", font=font, fill="white", anchor="mm")
    return image


def _sharpen_small(image: Image.Image) -> Image.Image:
    """Quantize 16–48px frames so the CJK strokes stay hard at taskbar size."""
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue
            if r > 150 and g > 150 and b > 150:
                pixels[x, y] = (255, 255, 255, 255)
            else:
                pixels[x, y] = (31, 78, 121, 255)
    return image


def _write_ico(frames: list[Image.Image]) -> None:
    """Write exact PNG-compressed frames; Pillow's ICO saver would re-resize them."""
    images = []
    for frame in frames:
        buffer = io.BytesIO()
        frame.save(buffer, format="PNG")
        images.append(buffer.getvalue())
    count = len(images)
    offset = 6 + count * 16
    entries = []
    for frame, payload in zip(frames, images):
        width = 0 if frame.width >= 256 else frame.width
        height = 0 if frame.height >= 256 else frame.height
        entries.append(
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
        offset += len(payload)
    ICO.write_bytes(struct.pack("<HHH", 0, 1, count) + b"".join(entries) + b"".join(images))


def main() -> None:
    edge = _edge()
    master = _render_edge(edge) if edge else None
    if master is None:
        master = _render_fallback()
    frames = []
    for size in SIZES:
        frame = master.resize((size, size), Image.Resampling.LANCZOS)
        if size <= 48:
            frame = _sharpen_small(frame)
        frames.append(frame)
    _write_ico(frames)
    print(f"icon: {ICO} ({len(frames)} sizes)")


if __name__ == "__main__":
    main()
