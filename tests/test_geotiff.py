"""Where a GeoTIFF says it sits, and a window written so a GIS agrees.

The writer was also read back with `tifffile` (an independent parser) on
2026-09-21: every tag, the UTF-8 credit, the geokeys and the pixels, NaN kept.
"""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest

from geokachel.geotiff import georeference, write_geotiff
from geokachel.tiff import _directory, read_raster
from tests.tiff_builders import _tiff

CREDIT = "Datenquelle: Bayerische Vermessungsverwaltung – www.geodaten.bayern.de (CC-BY-4.0)"


def _heights() -> np.ndarray:
    values = np.arange(12, dtype="float32").reshape(3, 4) + 500
    values[1, 2] = np.nan
    return values


def _written(tmp_path: Path, **extra: object) -> bytes:
    path = tmp_path / "w.tif"
    write_geotiff(path, _heights(), west=691000.0, north=5335000.0, cell_m=0.5,
                  epsg=25832, **extra)  # type: ignore[arg-type]
    return path.read_bytes()


def _patched(data: bytes, tag: int, *numbers: float) -> bytes:
    """The same file with one tag's doubles replaced."""
    field = _directory(data, "<")[tag]
    out = bytearray(data)
    struct.pack_into(f"<{len(numbers)}d", out, field.at, *numbers)
    return bytes(out)


def test_a_written_window_reads_back_with_its_heights_and_its_holes(tmp_path: Path) -> None:
    raster = read_raster(_written(tmp_path))

    assert (raster.width, raster.height) == (4, 3)
    np.testing.assert_array_equal(raster.values, _heights())


def test_a_written_window_says_where_it_is(tmp_path: Path) -> None:
    placed = georeference(_written(tmp_path))

    assert placed is not None
    assert (placed.west, placed.north, placed.cell_x, placed.cell_y) == (
        691000.0, 5335000.0, 0.5, 0.5)


def test_the_credit_travels_inside_the_file(tmp_path: Path) -> None:
    """A German credit is not ASCII; it is written as UTF-8, as GDAL does."""
    data = _written(tmp_path, credit=CREDIT + " · Thüringen", description="by-dgm1")
    fields = _directory(data, "<")

    def text(tag: int) -> str:
        field = fields[tag]
        return data[field.at:field.at + field.count].rstrip(b"\x00").decode("utf-8")

    assert text(33432) == CREDIT + " · Thüringen"
    assert text(270) == "by-dgm1"


def test_the_zone_is_written_as_the_state_publishes_it(tmp_path: Path) -> None:
    data = _written(tmp_path)
    field = _directory(data, "<")[34735]
    keys = struct.unpack_from("<16H", data, field.at)

    assert keys[12:] == (3072, 0, 1, 25832)


def test_a_tiepoint_on_another_pixel_still_finds_the_corner(tmp_path: Path) -> None:
    """A tiepoint may pin any pixel. Ten columns east and five rows south of
    the corner, at half-metre cells, is five metres east and 2.5 south."""
    data = _patched(_written(tmp_path), 33922,
                    10.0, 5.0, 0.0, 691005.0, 5334997.5, 0.0)

    placed = georeference(data)

    assert placed is not None
    assert (placed.west, placed.north) == (691000.0, 5335000.0)


def test_a_tiff_without_tags_says_nothing_rather_than_guessing() -> None:
    assert georeference(_tiff(np.zeros((4, 4), dtype="float32"))) is None


@pytest.mark.parametrize("scale", [(0.0, 1.0, 0.0), (1.0, -1.0, 0.0), (float("nan"), 1.0, 0.0)])
def test_a_cell_that_is_no_size_is_refused(tmp_path: Path,
                                           scale: tuple[float, float, float]) -> None:
    assert georeference(_patched(_written(tmp_path), 33550, *scale)) is None


def test_not_a_tiff_at_all_is_none() -> None:
    assert georeference(b"<ExceptionReport>no coverage</ExceptionReport>") is None


def test_a_multipart_answer_is_read_from_its_image(tmp_path: Path) -> None:
    """Sachsen-Anhalt wraps its coverage in multipart/related, GML first."""
    wrapped = (b"--wcs\r\nContent-Type: application/gml+xml\r\n\r\n<gml/>\r\n"
               b"--wcs\r\nContent-Type: image/tiff\r\n\r\n" + _written(tmp_path)
               + b"\r\n--wcs--\r\n")

    placed = georeference(wrapped)

    assert placed is not None and placed.west == 691000.0


@pytest.mark.parametrize("epsg", [4326, 3857, 31467])
def test_only_the_two_zones_german_data_uses_are_written(tmp_path: Path, epsg: int) -> None:
    with pytest.raises(ValueError, match="UTM"):
        write_geotiff(tmp_path / "x.tif", _heights(), west=0, north=0, cell_m=1, epsg=epsg)


def test_an_empty_raster_is_not_a_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        write_geotiff(tmp_path / "x.tif", np.zeros((0, 3), dtype="float32"),
                      west=0, north=0, cell_m=1, epsg=25832)
