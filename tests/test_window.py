"""A window answers for its own cells, in metres and in degrees."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from geokachel.geotiff import georeference
from geokachel.tiff import read_raster
from geokachel.window import GROUND, SEA, Window


def _window(**overrides: object) -> Window:
    values = np.array([[10, 11, 12], [20, np.nan, 22]], dtype="float32")
    fields: dict[str, object] = dict(
        values=values, west=691000.0, north=5335000.0, cell_m=2.0, epsg=25832,
        source="by-dgm1", licence="CC-BY-4.0", attribution="© Test", heights_above=SEA)
    fields.update(overrides)
    return Window(**fields)  # type: ignore[arg-type]


def test_its_edges_follow_from_its_corner_and_its_cells() -> None:
    w = _window()

    assert (w.rows, w.cols) == (2, 3)
    assert (w.east, w.south) == (691006.0, 5334996.0)
    assert w.zone == 32
    assert _window(epsg=25833).zone == 33


@pytest.mark.parametrize(("east", "north", "height"), [
    (691000.0, 5335000.0, 10.0),      # the north-west corner belongs to the first cell
    (691001.9, 5334998.1, 10.0),
    (691002.0, 5335000.0, 11.0),      # a west edge belongs to the cell east of it
    (691005.9, 5334996.1, 22.0),
])
def test_a_point_reads_the_cell_it_falls_in(east: float, north: float, height: float) -> None:
    assert _window().at(east, north) == height


@pytest.mark.parametrize(("east", "north"), [
    (690999.9, 5334999.0), (691006.0, 5334999.0),     # west of it, and its east edge
    (691001.0, 5335000.1), (691001.0, 5334996.0),     # north of it, and its south edge
])
def test_outside_is_none(east: float, north: float) -> None:
    assert _window().at(east, north) is None


def test_unsurveyed_is_none_and_never_zero() -> None:
    assert _window().at(691003.0, 5334997.0) is None


def test_a_cell_found_by_latitude_and_longitude_is_the_same_cell() -> None:
    w = _window()
    for row in range(w.rows):
        for col in range(w.cols):
            lat, lon = w.latlon_of(row, col)
            expected = w.values[row][col]
            got = w.height_at(lat, lon)
            assert (got is None) if np.isnan(expected) else got == expected


def test_it_says_how_much_of_it_was_surveyed() -> None:
    assert _window().surveyed == pytest.approx(5 / 6)
    assert _window(values=np.full((2, 2), np.nan, dtype="float32")).surveyed == 0.0


def test_saved_it_is_placed_labelled_and_credited(tmp_path: Path) -> None:
    w = _window(heights_above=GROUND, attribution="© GeoBasis-DE / LGB")
    data = w.write_geotiff(tmp_path / "w.tif").read_bytes()

    placed = georeference(data)
    assert placed is not None and (placed.west, placed.north, placed.cell_x) == (
        691000.0, 5335000.0, 2.0)
    np.testing.assert_array_equal(read_raster(data).values, w.values)
    assert "© GeoBasis-DE / LGB (CC-BY-4.0)".encode() in data
    assert b"by-dgm1: metres above ground" in data
