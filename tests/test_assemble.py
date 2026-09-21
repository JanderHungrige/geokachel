"""Filling a window from tiles and from services — offline, with fakes that
answer the way the real ones were measured to.
"""
from __future__ import annotations

import re
import struct
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

from geokachel.assemble import (
    Fetching,
    Unavailable,
    coverage_url,
    frame_around,
    from_service,
    from_tiles,
)
from geokachel.geotiff import write_geotiff
from geokachel.net import FetchError
from geokachel.terrain_sources import TerrainSource
from geokachel.tile_cache import TileCache
from geokachel.tile_grid import TileProduct, TileSource
from geokachel.utm import to_latlon
from geokachel.window import SEA

CELL = 10.0            # ten-metre cells keep a kilometre tile at 100 x 100
E0, N0 = 691, 5334     # the tile south-west of the point
#: A point 30 m east and 70 m north of a corner that four tiles share.
LAT, LON = to_latlon(E0 * 1000 + 1030.0, N0 * 1000 + 1070.0, 32)


def _tif(tmp_path: Path, values: np.ndarray, west: float, north: float,
         cell: float = CELL) -> bytes:
    path = tmp_path / f"t{west:.0f}_{north:.0f}_{values.shape}.tif"
    write_geotiff(path, values, west=west, north=north, cell_m=cell, epsg=25832)
    return path.read_bytes()


def _source(**overrides: object) -> TileSource:
    fields: dict[str, object] = dict(
        name="xx-dgm1", state="BY", product=TileProduct.DGM1, tile_km=1, fmt="GeoTIFF",
        licence="CC-BY-4.0", attribution="© Test", epsg=25832, cell_m=CELL,
        _url=lambda e, n: f"https://tiles.test/{e}_{n}.tif", _name=lambda e, n: f"{e}_{n}")
    fields.update(overrides)
    return TileSource(**fields)  # type: ignore[arg-type]


def _tiles(tmp_path: Path, refuse: tuple[str, ...] = ()) -> Callable[[str], bytes]:
    """Every tile is one number: 100, plus ten per kilometre east, plus one
    per kilometre north of the south-west one."""
    def get(url: str) -> bytes:
        e, n = (int(x) for x in re.findall(r"(\d+)_(\d+)", url)[0])
        if any(part in url for part in refuse):
            raise FetchError(f"GET {url} refused: 404", status=404)
        value = 100 + (e - E0) * 10 + (n - N0)
        return _tif(tmp_path, np.full((100, 100), value, dtype="float32"),
                    e * 1000.0, (n + 1) * 1000.0)
    return get


def _how(tmp_path: Path, get: Callable[[str], bytes]) -> Fetching:
    return Fetching(TileCache(tmp_path / "cache", 10**9), get)


def test_a_window_across_four_tiles_is_pasted_from_all_four(tmp_path: Path) -> None:
    w = from_tiles(_source(), LAT, LON, 200.0, _how(tmp_path, _tiles(tmp_path)))

    corner_e, corner_n = (E0 + 1) * 1000.0, (N0 + 1) * 1000.0
    assert w.at(corner_e - 5, corner_n - 5) == 100          # south-west
    assert w.at(corner_e + 5, corner_n - 5) == 110          # south-east
    assert w.at(corner_e - 5, corner_n + 5) == 101          # north-west
    assert w.at(corner_e + 5, corner_n + 5) == 111          # north-east
    assert w.surveyed == 1.0
    assert (w.source, w.attribution, w.heights_above) == ("xx-dgm1", "© Test", SEA)


def test_a_refused_tile_is_a_hole_and_the_rest_still_arrives(tmp_path: Path) -> None:
    get = _tiles(tmp_path, refuse=(f"{E0 + 1}_{N0 + 1}",))

    w = from_tiles(_source(), LAT, LON, 200.0, _how(tmp_path, get))

    assert w.at((E0 + 1) * 1000.0 + 5, (N0 + 1) * 1000.0 + 5) is None
    assert w.at((E0 + 1) * 1000.0 - 5, (N0 + 1) * 1000.0 - 5) == 100
    assert 0.3 < w.surveyed < 0.6        # the north-east tile is most of this square


def test_nothing_arriving_says_why_and_what_to_run(tmp_path: Path) -> None:
    get = _tiles(tmp_path, refuse=("tiles.test",))

    with pytest.raises(Unavailable, match=r"404.*geokachel check xx-dgm1"):
        from_tiles(_source(), LAT, LON, 200.0, _how(tmp_path, get))


def test_a_tile_that_does_not_decode_is_not_kept(tmp_path: Path) -> None:
    """A portal's maintenance page, cached as a tile, would be the answer for
    that square kilometre from then on."""
    good = _tiles(tmp_path)
    bad_one = f"{E0}_{N0}.tif"

    def maintenance(url: str) -> bytes:
        return b"<html>Wartungsarbeiten</html>" if url.endswith(bad_one) else good(url)

    how = _how(tmp_path, maintenance)
    first = from_tiles(_source(), LAT, LON, 200.0, how)
    assert first.at(E0 * 1000.0 + 995, N0 * 1000.0 + 995) is None

    again = from_tiles(_source(), LAT, LON, 200.0, _how(tmp_path, good))
    assert again.at(E0 * 1000.0 + 995, N0 * 1000.0 + 995) == 100


def test_a_partial_tile_is_placed_by_its_own_tags(tmp_path: Path) -> None:
    """Forty rows surveyed at the north of a tile. Anchored at the tile's
    south-west corner it would sit 600 m too far south."""
    def north_strip(url: str) -> bytes:
        e, n = (int(x) for x in re.findall(r"(\d+)_(\d+)", url)[0])
        return _tif(tmp_path, np.full((40, 100), 7.0, dtype="float32"),
                    e * 1000.0, (n + 1) * 1000.0)

    w = from_tiles(_source(), LAT, LON, 200.0, _how(tmp_path, north_strip))

    assert w.at((E0 + 1) * 1000.0 - 5, (N0 + 1) * 1000.0 - 5) == 7.0
    assert w.at((E0 + 1) * 1000.0 - 5, (N0 + 1) * 1000.0 - 395) is None


def test_tags_that_put_a_tile_far_from_its_grid_corner_are_not_trusted(
        tmp_path: Path) -> None:
    """An easting with the zone written in front of it is 32,000 km out."""
    def prefixed(url: str) -> bytes:
        e, n = (int(x) for x in re.findall(r"(\d+)_(\d+)", url)[0])
        return _tif(tmp_path, np.full((100, 100), 5.0, dtype="float32"),
                    32_000_000.0 + e * 1000.0, (n + 1) * 1000.0)

    w = from_tiles(_source(), LAT, LON, 200.0, _how(tmp_path, prefixed))

    assert w.surveyed == 1.0


def test_a_publishers_no_data_marker_is_not_a_height(tmp_path: Path) -> None:
    def odd(url: str) -> bytes:
        e, n = (int(x) for x in re.findall(r"(\d+)_(\d+)", url)[0])
        values = np.full((100, 100), 3.4e38, dtype="float32")
        values[:, :50] = 250.0
        return _tif(tmp_path, values, e * 1000.0, (n + 1) * 1000.0)

    w = from_tiles(_source(), LAT, LON, 200.0, _how(tmp_path, odd))

    assert np.nanmax(w.values) == 250.0
    assert 0.0 < w.surveyed < 1.0


def test_a_window_is_cut_on_the_sources_own_grid() -> None:
    assert frame_around(691003.3, 5335007.7, 200.0, 1.0) == (690903.0, 5335108.0, 201, 201)
    assert frame_around(691000.0, 5335000.0, 200.0, 1.0) == (690900.0, 5335100.0, 200, 200)


@pytest.mark.parametrize(("size", "cell"), [(0.0, 1.0), (-5.0, 1.0), (2001.0, 1.0),
                                             (1500.0, 0.2)])
def test_a_square_too_large_for_one_call_is_refused(size: float, cell: float) -> None:
    with pytest.raises(ValueError, match="size_m|cells"):
        frame_around(691000.0, 5335000.0, size, cell)


# --- services ----------------------------------------------------------------

SERVICE = TerrainSource(
    state="Nordrhein-Westfalen", url="https://wcs.test/dgm", coverage="test_dgm",
    epsg=25832, axes=("x", "y"), cell_m=1.0, vertical_step_m=0.01,
    licence="dl-de/zero-2-0", attribution="© Test NRW")


def _answering(tmp_path: Path, *, short: int = 0, cell: float = 1.0,
               calls: list[str] | None = None) -> Callable[[str], bytes]:
    """A service that anchors its answer at the corner asked for — and, like
    Baden-Württemberg's, may answer a column short or at its own cell size."""
    def get(url: str) -> bytes:
        if calls is not None:
            calls.append(url)
        found = re.search(r"SUBSET=x\((\d+),(\d+)\)&SUBSET=y\((\d+),(\d+)\)", url)
        assert found, url
        w, e, s, n = (int(g) for g in found.groups())
        cols, rows = int((e - w) / cell) - short, int((n - s) / cell)
        return _tif(tmp_path, np.full((rows, cols), 80.0, dtype="float32"), w, n, cell)
    return get


def test_a_service_is_asked_for_whole_metres(tmp_path: Path) -> None:
    calls: list[str] = []
    from_service(SERVICE, "dgm", LAT, LON, 200.0,
                 _how(tmp_path, _answering(tmp_path, calls=calls)), SEA)

    assert re.search(r"SUBSET=x\(\d+,\d+\)&SUBSET=y\(\d+,\d+\)&FORMAT=image/tiff$", calls[0])
    assert calls[0].startswith("https://wcs.test/dgm?SERVICE=WCS&VERSION=2.0.1")
    assert coverage_url(SERVICE, (1, 2, 3, 4)).count("SUBSET") == 2


def test_an_answer_is_placed_by_what_it_says_not_by_what_was_asked(tmp_path: Path) -> None:
    w = from_service(SERVICE, "dgm", LAT, LON, 200.0,
                     _how(tmp_path, _answering(tmp_path, short=1, cell=5.12)), SEA)

    assert w.cell_m == 5.12
    assert w.cols == int(201 / 5.12) - 1
    assert (w.source, w.attribution) == ("nw-dgm-wcs", "© Test NRW")


def test_an_answer_stretched_in_one_axis_is_put_back_on_square_cells(
        tmp_path: Path) -> None:
    """Baden-Württemberg's way: one column short, each 1.005 m wide. Every
    square cell takes the value of the stretched cell its centre falls in."""
    def stretched(url: str) -> bytes:
        found = re.search(r"SUBSET=x\((\d+),(\d+)\)&SUBSET=y\((\d+),(\d+)\)", url)
        assert found
        w, e, s, n = (int(g) for g in found.groups())
        columns = np.arange(e - w - 1, dtype="float32")        # each column says which
        path = tmp_path / "stretched.tif"
        write_geotiff(path, np.tile(columns, (n - s, 1)), west=w, north=n,
                      cell_m=1.0, epsg=25832)
        data = bytearray(path.read_bytes())
        at = data.index(struct.pack("<3d", 1.0, 1.0, 0.0))
        struct.pack_into("<d", data, at, (e - w) / (e - w - 1))
        return bytes(data)

    w = from_service(SERVICE, "dgm", LAT, LON, 200.0, _how(tmp_path, stretched), SEA)

    assert w.cell_m == 1.0 and w.cols == w.rows
    first, last = w.values[0][0], w.values[0][-1]
    assert (first, last) == (0.0, w.cols - 2)                 # one column is used twice
    assert np.all(np.diff(w.values[0]) >= 0)
    stretch = w.cols / (w.cols - 1)
    moved = np.abs((np.arange(w.cols) + 0.5) - (w.values[0].astype(float) + 0.5) * stretch)
    assert moved.max() <= 0.5 * stretch + 1e-6               # never more than half a cell


def test_a_second_call_for_the_same_square_asks_nobody(tmp_path: Path) -> None:
    calls: list[str] = []
    how = _how(tmp_path, _answering(tmp_path, calls=calls))
    for _ in range(2):
        from_service(SERVICE, "dgm", LAT, LON, 200.0, how, SEA)

    assert len(calls) == 1


def test_an_error_page_is_unavailable_and_is_not_kept(tmp_path: Path) -> None:
    def refusing(url: str) -> bytes:
        return b"<ows:ExceptionReport>InvalidSubsetting</ows:ExceptionReport>"

    with pytest.raises(Unavailable, match="nw-dgm-wcs"):
        from_service(SERVICE, "dgm", LAT, LON, 200.0, _how(tmp_path, refusing), SEA)

    w = from_service(SERVICE, "dgm", LAT, LON, 200.0,
                     _how(tmp_path, _answering(tmp_path)), SEA)
    assert w.surveyed == 1.0


def test_an_answer_with_nothing_surveyed_in_it_is_unavailable(tmp_path: Path) -> None:
    """What a service says for a point outside its state: a square of nothing."""
    def empty(url: str) -> bytes:
        return _tif(tmp_path, np.full((5, 5), -9999.0, dtype="float32"), 0.0, 5.0)

    with pytest.raises(Unavailable, match="nothing surveyed.*Nordrhein-Westfalen"):
        from_service(SERVICE, "dgm", LAT, LON, 200.0, _how(tmp_path, empty), SEA)
