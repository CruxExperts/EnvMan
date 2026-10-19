#!/usr/bin/env python3
"""Compose and render the coordinated Envman brand assets with ownership metadata."""

from __future__ import annotations

import argparse
import base64
import html
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets"
SOURCE = ASSETS / "social-preview.svg"
DEFAULT_OUTPUT = ASSETS / "social-preview.png"
WIDTH, HEIGHT = 1280, 640
COPYRIGHT = "Copyright © 2026 Crux Experts LLC"
SOURCE_URL = "https://www.cruxexperts.com/"
ASSET_RIGHTS = (
    "Private asset. Property of Crux Experts LLC. Use, reproduction, modification, "
    "distribution, or publication without prior written permission is prohibited."
)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
EXPORTS = {
    "social-preview": (1280, 640),
    "github-banner": (1600, 640),
    "social-square": (1080, 1080),
    "brand-mark": (1024, 1024),
    "logo-light": (1120, 256),
    "logo-dark": (1120, 256),
    "favicon": (64, 64),
}


def find_browser() -> str | None:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        browser = shutil.which(name)
        if browser:
            return browser
    return None


def png_chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def text_chunk(keyword: str, value: str) -> bytes:
    return png_chunk(b"tEXt", keyword.encode("latin-1") + b"\0" + value.encode("latin-1"))


def xmp_chunk(title: str) -> bytes:
    xml = (
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f'<dc:title>{html.escape(title)}</dc:title>'
        '<dc:creator>Crux Experts LLC</dc:creator>'
        f'<dc:source>{SOURCE_URL}</dc:source>'
        f'<dc:rights>{COPYRIGHT}. {ASSET_RIGHTS}</dc:rights>'
        '</rdf:Description></rdf:RDF></x:xmpmeta>'
    )
    return png_chunk(b"iTXt", b"XML:com.adobe.xmp\0\0\0\0\0" + xml.encode("utf-8"))


def read_chunks(png_data: bytes) -> list[tuple[bytes, bytes]]:
    """Reject incomplete or corrupted renderer output before attaching metadata."""
    if not png_data.startswith(PNG_SIGNATURE):
        raise ValueError("renderer output is not a PNG image")
    chunks: list[tuple[bytes, bytes]] = []
    offset = len(PNG_SIGNATURE)
    while offset < len(png_data):
        if offset + 12 > len(png_data):
            raise ValueError("renderer produced a truncated PNG chunk header")
        length = struct.unpack_from(">I", png_data, offset)[0]
        end = offset + 12 + length
        if end > len(png_data):
            raise ValueError("renderer produced a truncated PNG chunk")
        kind = png_data[offset + 4 : offset + 8]
        data = png_data[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack_from(">I", png_data, offset + 8 + length)[0]
        if zlib.crc32(kind + data) & 0xFFFFFFFF != expected_crc:
            raise ValueError(f"renderer produced a PNG chunk with a bad CRC: {kind!r}")
        chunks.append((kind, data))
        offset = end
        if kind == b"IEND":
            if offset != len(png_data):
                raise ValueError("renderer produced trailing bytes after PNG IEND")
            break
    if not chunks or chunks[0][0] != b"IHDR" or chunks[-1][0] != b"IEND":
        raise ValueError("renderer produced an incomplete PNG image")
    return chunks


def add_metadata(
    png_data: bytes, width: int = WIDTH, height: int = HEIGHT,
    title: str = "Envman | Your environment, in order.",
) -> bytes:
    chunks = read_chunks(png_data)
    actual = struct.unpack(">II", chunks[0][1][:8])
    if actual != (width, height):
        raise ValueError(f"rendered dimensions were {actual}, expected {(width, height)}")
    metadata = [
        text_chunk("Title", title),
        text_chunk("Author", "Crux Experts LLC"),
        text_chunk("Source", SOURCE_URL),
        text_chunk("Copyright", COPYRIGHT),
        text_chunk("Rights", f"{COPYRIGHT}. {ASSET_RIGHTS}"),
        text_chunk("Description", "Original Envman brand asset; synthetic artwork, no user data."),
        xmp_chunk(title),
    ]
    output = bytearray(PNG_SIGNATURE)
    for index, (kind, data) in enumerate(chunks):
        output.extend(png_chunk(kind, data))
        if index == 0:
            output.extend(b"".join(metadata))
    return bytes(output)


def svg_document(width: int, height: int, title: str, description: str, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:dc="http://purl.org/dc/elements/1.1/" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">\n'
        f'  <title id="title">{html.escape(title)}</title>\n'
        f'  <desc id="desc">{html.escape(description)}</desc>\n'
        '  <metadata>\n'
        f'    <dc:title>{html.escape(title)}</dc:title>\n'
        '    <dc:creator>Crux Experts LLC</dc:creator>\n'
        f'    <dc:source>{SOURCE_URL}</dc:source>\n'
        f'    <dc:rights>{COPYRIGHT}. {ASSET_RIGHTS}</dc:rights>\n'
        '  </metadata>\n'
        f'{body}\n</svg>\n'
    )


def mark(x: int = 0, y: int = 0, size: int = 64) -> str:
    return (
        f'<svg x="{x}" y="{y}" width="{size}" height="{size}" viewBox="0 0 64 64">'
        '<rect x="1" y="1" width="62" height="62" rx="14" fill="#0c3036" '
        'stroke="#386067" stroke-width="1"/>'
        '<path d="M23 17h-8v30h8M41 17h8v30h-8" fill="none" stroke="#b8e5da" stroke-width="4"/>'
        '<path d="M26 27h12M26 37h12" fill="none" stroke="#e4f49b" stroke-width="4"/>'
        '</svg>'
    )


def text(x: int, y: int, size: int, value: str, color: str = "#f0f3ed", weight: int = 400, spacing: float = 0) -> str:
    return (
        f'<text x="{x}" y="{y}" fill="{color}" font-family="Arial, Helvetica, sans-serif" '
        f'font-size="{size}" font-weight="{weight}" letter-spacing="{spacing}">'
        f'{html.escape(value)}</text>'
    )


def compose_sources() -> None:
    """Keep every campaign format and compact mark on one visual system."""
    artwork = base64.b64encode((ASSETS / "brand-artwork.webp").read_bytes()).decode("ascii")
    image = f'data:image/webp;base64,{artwork}'
    for name, (width, height) in EXPORTS.items():
        if name in ("brand-mark", "favicon"):
            body = mark(size=64)
            source_width, source_height = 64, 64
            description = "A mineral-teal square with pale brackets and a restrained lime equals sign."
        elif name.startswith("logo-"):
            color = "#f0f3ed" if name == "logo-dark" else "#102d32"
            body = mark(8, 8, 112) + text(148, 88, 76, "envman", color, 600, -3)
            source_width, source_height = 560, 128
            description = "Envman wordmark and bracketed-equals symbol on a transparent background."
        elif name == "social-square":
            body = (
                '<rect width="1080" height="1080" fill="#020f12"/>'
                f'<image href="{image}" x="-530" y="290" width="1440" height="960"/>'
                '<defs><linearGradient id="fade" x2="0" y2="1">'
                '<stop stop-color="#020f12"/><stop offset="1" stop-color="#020f12" stop-opacity="0"/>'
                '</linearGradient></defs><rect y="290" width="1080" height="160" fill="url(#fade)"/>'
                '<defs><linearGradient id="edge">'
                '<stop stop-color="#020f12" stop-opacity="0"/>'
                '<stop offset=".4" stop-color="#020f12"/></linearGradient></defs>'
                '<rect x="830" y="450" width="250" height="630" fill="url(#edge)"/>'
                + mark(76, 70, 64) + text(160, 117, 54, "envman", weight=600, spacing=-2)
                + text(76, 245, 70, "Your environment,", weight=500, spacing=-2)
                + text(76, 328, 70, "in order.", weight=500, spacing=-2)
                + text(78, 389, 25, "Set variables once. Load them in new shells.", "#a8bcbc")
                + text(78, 1040, 20, "CruxExperts / EnvMan", "#a8bcbc")
            )
            source_width, source_height = width, height
            description = "Envman square campaign artwork with a sculpted teal bracket-equals emblem."
        else:
            banner = name == "github-banner"
            body = (
                f'<rect width="{width}" height="{height}" fill="#020f12"/>'
                f'<image href="{image}" x="{320 if banner else 0}" y="-107" '
                'width="1280" height="853.333333"/>'
                + (
                    '<defs><linearGradient id="blend">'
                    '<stop offset=".45" stop-color="#020f12"/>'
                    '<stop offset="1" stop-color="#020f12" stop-opacity="0"/>'
                    '</linearGradient></defs><rect width="700" height="640" fill="url(#blend)"/>'
                    if banner else ""
                )
                + mark(76, 66, 56) + text(148, 108, 44, "envman", weight=600, spacing=-1.5)
                + text(76, 252, 58 if banner else 54, "Your environment,", weight=500, spacing=-1.8)
                + text(76, 322, 58 if banner else 54, "in order.", weight=500, spacing=-1.8)
                + '<rect x="78" y="362" width="36" height="3" rx="1.5" fill="#d4eaa0"/>'
                + text(76, 416, 23, "Set variables once.", "#b3c5c4")
                + text(76, 449, 23, "Load them in new shells.", "#b3c5c4")
                + text(76, 570, 15, "LOCAL-FIRST  /  TERMINAL UI + CLI", "#8ca6a8", spacing=1.6)
            )
            source_width, source_height = width, height
            description = "Envman editorial brand card with a sculpted teal bracket-equals emblem and clear product promise."
        title = "Envman" if name.startswith(("logo-", "brand-", "favicon")) else "Envman | Your environment, in order."
        (ASSETS / f"{name}.svg").write_text(
            svg_document(source_width, source_height, title, description, body), encoding="utf-8"
        )


def render(output: Path, source: Path = SOURCE, width: int = WIDTH, height: int = HEIGHT) -> None:
    """Rasterize a self-contained SVG headlessly without disabling the sandbox."""
    browser = find_browser()
    if browser is None:
        raise RuntimeError("Google Chrome or Chromium is required to render the visual assets")
    if not source.is_file():
        raise FileNotFoundError(f"visual source not found: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="envman-visual-assets-") as temp_name:
        temp = Path(temp_name)
        page = temp / "render.html"
        screenshot = temp / "render.png"
        page.write_text(
            '<!doctype html><html><head><meta charset="utf-8">'
            f'<style>html,body{{width:{width}px;height:{height}px;margin:0;overflow:hidden;background:transparent}}'
            f'img{{display:block;width:{width}px;height:{height}px}}</style></head>'
            f'<body><img src="{source.as_uri()}" width="{width}" height="{height}" alt=""></body></html>',
            encoding="utf-8",
        )
        command = [
            browser, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
            "--default-background-color=00000000", "--force-device-scale-factor=1",
            "--run-all-compositor-stages-before-draw", "--virtual-time-budget=2000",
            f"--window-size={width},{height}", f"--user-data-dir={temp / 'profile'}",
            f"--screenshot={screenshot}", page.as_uri(),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
        if result.returncode != 0 or not screenshot.is_file():
            details = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"headless SVG render failed: {details or 'browser produced no PNG'}")
        output.write_bytes(add_metadata(screenshot.read_bytes(), width, height, f"Envman | {source.stem}"))

def package_assets() -> Path:
    """Deliver a portable, versioned pack using repository-relative paths."""
    output = ASSETS / "envman-brand-assets-v1.0.0.zip"
    paths = [ASSETS / "README.md", ASSETS / "asset-manifest.json", ASSETS / "brand-artwork.webp"]
    paths += [ASSETS / f"{name}.{suffix}" for name in EXPORTS for suffix in ("svg", "png")]
    paths += [ASSETS / "terminal-preview.svg", ASSETS / "terminal-preview-mobile.svg", Path(__file__)]
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.comment = f"{COPYRIGHT}. {SOURCE_URL} {ASSET_RIGHTS}".encode("utf-8")
        for path in paths:
            archive.write(path, path.relative_to(ROOT))
    return output



def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Social PNG destination")
    parser.add_argument("--all", action="store_true", help="Recompose SVG sources and render every brand format")
    args = parser.parse_args()
    try:
        if args.all:
            compose_sources()
            for name, (width, height) in EXPORTS.items():
                output = ASSETS / f"{name}.png"
                render(output, ASSETS / f"{name}.svg", width, height)
                print(f"Rendered {output.resolve()} at {width}x{height} with rights metadata.")
            print(f"Packaged {package_assets().resolve()}")
        else:
            output = args.output if args.output.is_absolute() else ROOT / args.output
            render(output)
            print(f"Rendered {output.resolve()} at {WIDTH}x{HEIGHT} with rights metadata.")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"render_visual_assets.py: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
