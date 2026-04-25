from __future__ import annotations

import struct
import zlib
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_PUBLIC = _ROOT / "web" / "public"


def _paeth(left: int, up: int, up_left: int) -> int:
    estimate = left + up - up_left
    distance_left = abs(estimate - left)
    distance_up = abs(estimate - up)
    distance_up_left = abs(estimate - up_left)
    if distance_left <= distance_up and distance_left <= distance_up_left:
        return left
    if distance_up <= distance_up_left:
        return up
    return up_left


def _read_png_rgba(data: bytes) -> tuple[int, int, list[bytes]]:
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    offset = 8
    width = height = None
    compressed = bytearray()
    while offset < len(data):
        chunk_size = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_data = data[offset + 8 : offset + 8 + chunk_size]
        offset += 12 + chunk_size
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, *_ = struct.unpack(">IIBBBBB", chunk_data)
            assert bit_depth == 8
            assert color_type == 6
        elif chunk_type == b"IDAT":
            compressed.extend(chunk_data)
        elif chunk_type == b"IEND":
            break

    assert width is not None
    assert height is not None
    raw = zlib.decompress(bytes(compressed))
    stride = width * 4
    rows: list[bytes] = []
    previous = bytes(stride)
    cursor = 0
    for _ in range(height):
        filter_type = raw[cursor]
        cursor += 1
        scanline = raw[cursor : cursor + stride]
        cursor += stride
        row = bytearray(stride)
        for index, value in enumerate(scanline):
            left = row[index - 4] if index >= 4 else 0
            up = previous[index]
            up_left = previous[index - 4] if index >= 4 else 0
            if filter_type == 0:
                row[index] = value
            elif filter_type == 1:
                row[index] = (value + left) & 0xFF
            elif filter_type == 2:
                row[index] = (value + up) & 0xFF
            elif filter_type == 3:
                row[index] = (value + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                row[index] = (value + _paeth(left, up, up_left)) & 0xFF
            else:
                raise AssertionError(f"Unsupported PNG filter {filter_type}")
        previous = bytes(row)
        rows.append(previous)
    return width, height, rows


def _visible_padding(data: bytes, alpha_threshold: int = 128) -> tuple[int, int, int, int]:
    width, height, rows = _read_png_rgba(data)
    left = width
    top = height
    right = -1
    bottom = -1
    for y, row in enumerate(rows):
        for x in range(width):
            if row[x * 4 + 3] > alpha_threshold:
                left = min(left, x)
                top = min(top, y)
                right = max(right, x)
                bottom = max(bottom, y)
    assert right >= 0
    return left, top, width - right - 1, height - bottom - 1


def _assert_icon_safe_area(name: str, data: bytes, size: int) -> None:
    left, top, right, bottom = _visible_padding(data)
    minimum_side_padding = max(1, round(size * 0.04))
    minimum_vertical_padding = max(1, round(size * 0.05))
    assert left >= minimum_side_padding, (name, left)
    assert right >= minimum_side_padding, (name, right)
    assert top >= minimum_vertical_padding, (name, top)
    assert bottom >= minimum_vertical_padding, (name, bottom)


def test_png_favicons_keep_safe_area_around_artwork():
    for size in (16, 32, 48, 180, 512):
        path = _PUBLIC / f"cookdex-icon-{size}.png"
        _assert_icon_safe_area(path.name, path.read_bytes(), size)


def test_favicon_ico_embeds_safe_png_frames():
    data = (_PUBLIC / "favicon.ico").read_bytes()
    reserved, icon_type, count = struct.unpack("<HHH", data[:6])
    assert (reserved, icon_type) == (0, 1)
    sizes = set()
    for index in range(count):
        entry = data[6 + index * 16 : 22 + index * 16]
        width_byte, height_byte, _, _, _, _, image_size, image_offset = struct.unpack("<BBBBHHII", entry)
        size = width_byte or 256
        assert size == (height_byte or 256)
        png_data = data[image_offset : image_offset + image_size]
        _assert_icon_safe_area(f"favicon.ico:{size}", png_data, size)
        sizes.add(size)
    assert sizes == {16, 32, 48}
