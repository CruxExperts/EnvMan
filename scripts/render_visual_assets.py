#!/usr/bin/env python3
"""Render the editable Envman social SVG as a metadata-tagged PNG."""

from __future__ import annotations

import argparse
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "assets" / "social-preview.svg"
DEFAULT_OUTPUT = ROOT / "docs" / "assets" / "social-preview.png"
WIDTH = 1280
HEIGHT = 640
COPYRIGHT = "Copyright © 2026 Crux Experts LLC"
SOURCE_URL = "https://www.cruxexperts.com/"
ASSET_RIGHTS = (
    "Private asset. Property of Crux Experts LLC. Use, reproduction, modification, "
    "distribution, or publication without prior written permission is prohibited."
)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def find_browser() -> str | None:
    """Find an installed Chrome or Chromium browser for headless SVG rendering."""
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        browser = shutil.which(name)
        if browser:
            return browser
    return None


def png_chunk(kind: bytes, data: bytes) -> bytes:
    """Encode one PNG chunk with its length and CRC."""
    checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def text_chunk(keyword: str, value: str) -> bytes:
    """Encode a standard Latin-1 PNG text field."""
    try:
        data = keyword.encode("latin-1") + b"\0" + value.encode("latin-1")
    except UnicodeEncodeError as exc:
        raise ValueError(f"PNG tEXt metadata must be Latin-1: {keyword}") from exc
    return png_chunk(b"tEXt", data)


def xmp_chunk() -> bytes:
    """Encode ownership fields in the common Adobe XMP PNG extension."""
    xml = (
        '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:title><rdf:Alt><rdf:li xml:lang="x-default">Envman | Set variables once. Load them in new shells.</rdf:li></rdf:Alt></dc:title>'
        f'<dc:creator><rdf:Seq><rdf:li>Crux Experts LLC</rdf:li></rdf:Seq></dc:creator>'
        f'<dc:source><rdf:Bag><rdf:li>{SOURCE_URL}</rdf:li></rdf:Bag></dc:source>'
        f'<dc:rights><rdf:Alt><rdf:li xml:lang="x-default">{COPYRIGHT}. {ASSET_RIGHTS}</rdf:li></rdf:Alt></dc:rights>'
        '</rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>'
    )
    payload = b"XML:com.adobe.xmp\0\0\0\0\0" + xml.encode("utf-8")
    return png_chunk(b"iTXt", payload)


def read_chunks(png_data: bytes) -> list[tuple[bytes, bytes]]:
    """Read a bounded PNG chunk sequence and reject truncated data."""
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


def add_metadata(png_data: bytes) -> bytes:
    """Add descriptive and rights metadata while retaining rendered PNG chunks."""
    chunks = read_chunks(png_data)
    width, height = struct.unpack(">II", chunks[0][1][:8])
    if (width, height) != (WIDTH, HEIGHT):
        raise ValueError(f"rendered dimensions were {width}x{height}, expected {WIDTH}x{HEIGHT}")

    metadata = [
        text_chunk("Title", "Envman | Set variables once. Load them in new shells."),
        text_chunk("Author", "Crux Experts LLC"),
        text_chunk("Source", SOURCE_URL),
        text_chunk("Copyright", COPYRIGHT),
        text_chunk("Rights", f"{COPYRIGHT}. {ASSET_RIGHTS}"),
        text_chunk("Description", "Synthetic Envman terminal catalog with sample values only."),
        xmp_chunk(),
    ]
    output = bytearray(PNG_SIGNATURE)
    for index, (kind, data) in enumerate(chunks):
        output.extend(png_chunk(kind, data))
        if index == 0:
            output.extend(b"".join(metadata))
    return bytes(output)


def render(output: Path) -> None:
    """Render the SVG at the social-image dimensions and preserve its metadata."""
    browser = find_browser()
    if browser is None:
        raise RuntimeError("Google Chrome or Chromium is required to render the social preview")
    if not SOURCE.is_file():
        raise FileNotFoundError(f"social preview SVG not found: {SOURCE}")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="envman-visual-assets-") as temp_name:
        temp = Path(temp_name)
        svg_url = SOURCE.as_uri()
        page = temp / "render.html"
        screenshot = temp / "social-preview.png"
        page.write_text(
            "<!doctype html><html><head><meta charset=\"utf-8\">"
            f"<style>html,body{{width:{WIDTH}px;height:{HEIGHT}px;margin:0;overflow:hidden}}"
            f"img{{display:block;width:{WIDTH}px;height:{HEIGHT}px}}</style></head>"
            f"<body><img src=\"{svg_url}\" width=\"{WIDTH}\" height=\"{HEIGHT}\" alt=\"\"></body></html>",
            encoding="utf-8",
        )
        command = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            f"--window-size={WIDTH},{HEIGHT}",
            f"--user-data-dir={temp / 'profile'}",
            f"--screenshot={screenshot}",
            page.as_uri(),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
        if result.returncode != 0 or not screenshot.is_file():
            details = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"headless SVG render failed: {details or 'browser produced no PNG'}")
        output.write_bytes(add_metadata(screenshot.read_bytes()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="PNG destination (default: docs/assets/social-preview.png)",
    )
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    try:
        render(output)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"render_visual_assets.py: {exc}", file=sys.stderr)
        return 1
    print(f"Rendered {output.resolve()} at {WIDTH}x{HEIGHT} with rights metadata.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
