"""The tiles that arrived: one missing is a hole, never the whole answer."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from geokachel.addressing import frame_of, rasters
from geokachel.geotiff import write_geotiff
from geokachel.net import FetchError
from geokachel.tile_cache import TileCache
from geokachel.tile_grid import TileLookup, TileProduct, TileSource, under


def _source(**overrides: object) -> TileSource:
    fields: dict[str, object] = dict(
        name="xx-dgm1", state="BY", product=TileProduct.DGM1, tile_km=1, fmt="GeoTIFF",
        licence="CC-BY-4.0", attribution="© Test", epsg=25832,
        _url=lambda e, n: f"https://tiles.test/{e}_{n}.tif", _name=lambda e, n: f"{e}_{n}")
    fields.update(overrides)
    return TileSource(**fields)  # type: ignore[arg-type]


def test_one_refused_tile_is_a_hole_and_not_a_failure(tmp_path: Path) -> None:
    """A refusal is a `FetchError`, which is neither an OSError nor a
    ValueError — and until 2026-09-21 one 404 took the other tiles with it."""
    written = tmp_path / "tile.tif"
    write_geotiff(written, np.ones((10, 10), dtype="float32"), west=0.0, north=10.0,
                  cell_m=1.0, epsg=25832)

    def get(url: str) -> bytes:
        if "691_5334" in url:
            raise FetchError(f"GET {url} refused: 404", status=404)
        return written.read_bytes()

    got = rasters(_source(), [(691, 5334), (692, 5334)], TileCache(tmp_path / "c", 10**9), get)

    assert list(got) == [(692, 5334)]


def test_a_list_that_cannot_be_had_is_no_tiles_rather_than_a_crash(tmp_path: Path) -> None:
    def refused(url: str) -> bytes:
        raise FetchError(f"GET {url} refused: 503", status=503)

    listed = _source(_url=None, _name=None, lookup=TileLookup(
        index_url="https://tiles.test/index.meta4",
        address=under("https://tiles.test/"), parse=lambda _data: {}))

    assert rasters(listed, [(691, 5334)], TileCache(tmp_path / "c", 10**9), refused) == {}


@pytest.mark.parametrize(("tile_km", "cell", "side"), [(1, 1.0, 1000), (2, 1.0, 2000),
                                                       (1, 0.2, 5000)])
def test_a_tiles_frame_is_the_whole_tile(tile_km: int, cell: float, side: int) -> None:
    west, north, cols, rows = frame_of(_source(tile_km=tile_km), (410, 5656), cell)

    assert (west, north, cols, rows) == (410_000.0, (5656 + tile_km) * 1000.0, side, side)
