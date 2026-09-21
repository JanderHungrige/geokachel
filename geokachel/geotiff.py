"""The *geo* in GeoTIFF: where a raster sits, read and written.

`tiff.py` decodes pixels and deliberately knows nothing about the ground they
cover. That was enough while every raster was a tile, because a tile's grid
number says where it is. A coverage service's answer says so only in its own
tags — and those tags turn out to matter.

Measured against all sixteen state coverage services on 2026-09-21, asking
each for the same whole-metre box:

- every one anchored its answer **exactly** at the requested corner — so the
  corner is not the problem;
- but Baden-Württemberg's terrain came back **219 columns wide, not 220**, and
  its surface model's cells are **5.12 m**, not the 5.0 its registry entry
  records. Placing either by the size that was asked for, or by the registry's
  cell, smears the data by up to five metres across the window.

So an answer is placed by what it says about itself: its tiepoint (which raster
pixel sits at which easting and northing) and its pixel scale (how big a cell
is). And a window handed back to a caller is written with the same two tags
plus its coordinate system, so QGIS, GDAL or anything else puts it on the map
without being told.
"""
from __future__ import annotations

import math
import os
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from geokachel.tiff import TiffError, _directory, _unwrap

#: GeoTIFF tags. The TIFF 6.0 ones are in `tiff.py`.
_PIXEL_SCALE, _TIEPOINT, _GEOKEYS, _GDAL_NODATA = 33550, 33922, 34735, 42113
_DOUBLE = 12


@dataclass(frozen=True)
class Placement:
    """Where a raster's north-west corner is, and how large its cells are."""

    west: float
    north: float
    cell_x: float
    cell_y: float


def _doubles(data: bytes, end: str, field: object, needed: int) -> tuple[float, ...] | None:
    kind, count, at = (getattr(field, name, None) for name in ("kind", "count", "at"))
    if kind != _DOUBLE or not isinstance(count, int) or not isinstance(at, int):
        return None
    if count < needed or at < 0 or at + count * 8 > len(data):
        return None
    return struct.unpack_from(f"{end}{count}d", data, at)


def georeference(data: bytes) -> Placement | None:
    """Where a GeoTIFF says it sits, or None if it does not say.

    Read from its own tiepoint and pixel scale. None — never a guess — for a
    TIFF without them, a malformed one, or one whose numbers make no sense.
    """
    data = _unwrap(data)
    if data[:2] not in (b"II", b"MM"):
        return None
    end = "<" if data[:2] == b"II" else ">"
    try:
        fields = _directory(data, end)
    except (TiffError, struct.error, IndexError, ValueError):
        return None
    scale = _doubles(data, end, fields.get(_PIXEL_SCALE), 2)
    tie = _doubles(data, end, fields.get(_TIEPOINT), 6)
    if scale is None or tie is None:
        return None
    cell_x, cell_y = scale[0], scale[1]
    # A tiepoint says raster pixel (i, j) sits at model point (x, y). The
    # corner is then i cells west and j cells north of that point.
    i, j, x, y = tie[0], tie[1], tie[3], tie[4]
    numbers = (cell_x, cell_y, i, j, x, y)
    if not all(math.isfinite(n) for n in numbers) or cell_x <= 0 or cell_y <= 0:
        return None
    return Placement(west=x - i * cell_x, north=y + j * cell_y, cell_x=cell_x, cell_y=cell_y)


_ASCII, _SHORT, _LONG = 2, 3, 4
_DESCRIPTION, _COPYRIGHT = 270, 33432


def _text(value: str) -> bytes:
    """A TIFF string: NUL-terminated, UTF-8 as GDAL writes it — the credits
    are German, and "Thüringen" is not ASCII."""
    return value.replace("\x00", " ").encode("utf-8") + b"\x00"


def write_geotiff(path: str | os.PathLike[str], values: np.ndarray, *, west: float,
                  north: float, cell_m: float, epsg: int, credit: str = "",
                  description: str = "") -> Path:
    """A single-band float32 GeoTIFF of a north-up raster, placed and labelled.

    Uncompressed and in one strip: large, but readable by anything that reads
    GeoTIFF at all, and a window is at most a few tens of megabytes. NaN is
    declared as the no-data value, so unsurveyed ground is shown as a hole
    rather than as zero metres above the sea. `credit` goes into the file's
    Copyright tag, which `gdalinfo` and QGIS show, so it travels with the data.
    """
    if values.ndim != 2 or values.size == 0:
        raise ValueError("a GeoTIFF needs a non-empty two-dimensional raster")
    if epsg not in (25832, 25833):
        raise ValueError(f"EPSG:{epsg} is not one of the two UTM zones German data uses")
    rows, cols = values.shape
    pixels = np.ascontiguousarray(values, dtype="<f4").tobytes()
    keys = struct.pack("<16H",
                       1, 1, 0, 3,                # key directory 1.1.0, three keys
                       1024, 0, 1, 1,             # model type: projected
                       1025, 0, 1, 1,             # raster type: pixel is area
                       3072, 0, 1, epsg)          # projected CRS: ETRS89 / UTM
    # tag -> (type, count, value): an int for a single number, bytes otherwise.
    fields: dict[int, tuple[int, int, int | bytes]] = {
        256: (_LONG, 1, cols), 257: (_LONG, 1, rows), 258: (_SHORT, 1, 32),
        259: (_SHORT, 1, 1), 262: (_SHORT, 1, 1), 273: (_LONG, 1, 0),
        277: (_SHORT, 1, 1), 278: (_LONG, 1, rows), 279: (_LONG, 1, len(pixels)),
        284: (_SHORT, 1, 1), 339: (_SHORT, 1, 3),
        _PIXEL_SCALE: (_DOUBLE, 3, struct.pack("<3d", cell_m, cell_m, 0.0)),
        _TIEPOINT: (_DOUBLE, 6, struct.pack("<6d", 0.0, 0.0, 0.0, west, north, 0.0)),
        _GEOKEYS: (_SHORT, 16, keys),
        _GDAL_NODATA: (_ASCII, 4, _text("nan")),
    }
    for tag, words in ((_DESCRIPTION, description), (_COPYRIGHT, credit)):
        if words:
            blob = _text(words)
            fields[tag] = (_ASCII, len(blob), blob)
    return _laid_out(Path(path), pixels, fields)


def _laid_out(target: Path, pixels: bytes,
              fields: dict[int, tuple[int, int, int | bytes]]) -> Path:
    """Header, pixels, the values too long for their entries, then the
    directory — its entries in tag order and every offset even, as TIFF asks."""
    tail = bytearray()
    at_values = 8 + len(pixels)
    entries = []
    for tag in sorted(fields):
        kind, count, value = fields[tag]
        if tag == 273:
            value = 8                              # the pixels follow the header
        if isinstance(value, int):
            packed = (struct.pack("<HH", value, 0) if kind == _SHORT
                      else struct.pack("<I", value))
        elif len(value) <= 4:
            packed = value.ljust(4, b"\x00")
        else:
            packed = struct.pack("<I", at_values + len(tail))
            tail += value + (b"\x00" if len(value) % 2 else b"")
        entries.append(struct.pack("<HHI", tag, kind, count) + packed)
    at_ifd = at_values + len(tail)
    ifd = struct.pack("<H", len(entries)) + b"".join(entries) + struct.pack("<I", 0)
    target.write_bytes(b"II*\x00" + struct.pack("<I", at_ifd) + pixels + bytes(tail) + ifd)
    return target


__all__ = ["Placement", "georeference", "write_geotiff"]
