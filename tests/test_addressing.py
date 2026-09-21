"""The tiles that arrived: one missing is a hole, never the whole answer."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import numpy as np
import pytest

from geokachel import addressing
from geokachel.addressing import addressed, frame_of, rasters
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


def _archive(*names: str) -> bytes:
    """A regional archive, as Saarland publishes one per district."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, b"a tile")
    return buffer.getvalue()


def test_an_archive_that_did_not_answer_is_asked_again_later(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A district whose archive missed one request used to stay missing until
    the program restarted. Now it is asked again once `RETRY_AFTER_S` has
    passed — and not before, so a portal that is down is not asked on every
    call — while the directory that did answer is never read twice."""
    west, east = "https://archive.test/west.zip", "https://archive.test/east.zip"
    archives = {west: _archive("dgm1_32_353_5455_1_sl.tif"),
                east: _archive("dgm1_32_360_5460_1_sl.tif")}
    down, asked, clock = {east}, [], [1000.0]
    monkeypatch.setattr(addressing, "_HELD", {})
    monkeypatch.setattr(addressing, "_FAILED_AT", {})
    monkeypatch.setattr(addressing, "_now", lambda: clock[0])

    def sized(url: str) -> int:
        asked.append(url)
        if url in down:
            raise FetchError(f"HEAD {url} refused: 503", status=503)
        return len(archives[url])

    def ranged(url: str, start: int, end: int) -> bytes:
        return archives[url][start:end + 1]

    def nothing(url: str) -> bytes:
        raise AssertionError(f"an archived state fetches no whole file: {url}")

    source = _source(_url=None, _name=None, archives=(west, east))

    def found() -> set[tuple[int, int]]:
        return {corner for corner, _key, _grab in addressed(
            source, [(353, 5455), (360, 5460)], TileCache(tmp_path / "c", 10**9), nothing,
            sized=sized, ranged=ranged)}

    assert found() == {(353, 5455)}                  # the east is down: a hole there
    down.clear()
    clock[0] += addressing.RETRY_AFTER_S - 1
    assert found() == {(353, 5455)}                  # and left alone for a while
    assert asked.count(east) == 1

    clock[0] += 1
    assert found() == {(353, 5455), (360, 5460)}     # asked again, and back
    assert (asked.count(west), asked.count(east)) == (1, 2)
