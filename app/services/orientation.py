"""Rotate MP4 presentation without decoding or re-encoding video frames."""

from __future__ import annotations

import struct
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO


def _boxes(file: BinaryIO, start: int, end: int) -> Iterator[tuple[bytes, int, int]]:
    position = start
    while position + 8 <= end:
        file.seek(position)
        header = file.read(8)
        size, kind = struct.unpack(">I4s", header)
        header_size = 8
        if size == 1:
            if position + 16 > end:
                raise ValueError("Invalid MP4 box")
            size = struct.unpack(">Q", file.read(8))[0]
            header_size = 16
        elif size == 0:
            size = end - position
        if size < header_size or position + size > end:
            raise ValueError("Invalid MP4 box")
        yield kind, position + header_size, position + size
        position += size
    if position != end:
        raise ValueError("Invalid MP4 box padding")


def _child(file: BinaryIO, start: int, end: int, name: bytes) -> tuple[int, int] | None:
    for kind, payload_start, box_end in _boxes(file, start, end):
        if kind == name:
            return payload_start, box_end
    return None


def _rotation_matrix(degrees: int, width: int, height: int) -> bytes:
    unit = 1 << 16
    if degrees == 90:
        values = (0, unit, 0, -unit, 0, 0, height * unit, 0, 1 << 30)
    elif degrees == 180:
        values = (-unit, 0, 0, 0, -unit, 0, width * unit, height * unit, 1 << 30)
    elif degrees == 270:
        values = (0, -unit, 0, unit, 0, 0, 0, width * unit, 1 << 30)
    else:
        raise ValueError("Invalid rotation")
    return struct.pack(">9i", *values)


def set_mp4_rotation(path: Path, degrees: int) -> None:
    """Set the video track's tkhd display matrix in an existing MP4 in place."""
    if degrees not in (90, 180, 270):
        raise ValueError("Invalid rotation")
    with path.open("r+b") as file:
        length = file.seek(0, 2)
        moov = _child(file, 0, length, b"moov")
        if moov is None:
            raise ValueError("MP4 has no movie header")
        for kind, track_start, track_end in _boxes(file, *moov):
            if kind != b"trak":
                continue
            media = _child(file, track_start, track_end, b"mdia")
            track_header = _child(file, track_start, track_end, b"tkhd")
            if media is None or track_header is None:
                continue
            handler = _child(file, *media, b"hdlr")
            if handler is None or handler[1] - handler[0] < 12:
                continue
            file.seek(handler[0] + 8)
            if file.read(4) != b"vide":
                continue
            header_start, header_end = track_header
            file.seek(header_start)
            version = file.read(1)
            if version not in (b"\x00", b"\x01"):
                raise ValueError("Unsupported MP4 track header")
            matrix_offset = header_start + (52 if version == b"\x01" else 40)
            if matrix_offset + 44 > header_end:
                raise ValueError("Incomplete MP4 track header")
            file.seek(matrix_offset + 36)
            width, height = struct.unpack(">II", file.read(8))
            width >>= 16
            height >>= 16
            if not (0 < width < 32768 and 0 < height < 32768):
                raise ValueError("Invalid MP4 video dimensions")
            file.seek(matrix_offset)
            file.write(_rotation_matrix(degrees, width, height))
            return
    raise ValueError("MP4 has no video track")
