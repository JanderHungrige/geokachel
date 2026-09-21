"""The front door: a point and a state in, a placed and credited window out —
whichever of the sixteen ways the state publishes behind it."""
from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

from geokachel import heights
from geokachel.assemble import Unavailable
from geokachel.geotiff import write_geotiff
from geokachel.heights import (
    default_cache,
    ground,
    ground_route,
    object_heights,
    surface,
    surface_route,
)
from geokachel.surface_sources import NORMALISED, SurfaceSource
from geokachel.terrain_sources import TerrainSource
from geokachel.tile_cache import TileCache
from geokachel.tile_grid import TileSource
from geokachel.tile_sources import STATES
from geokachel.window import GROUND, SEA, Window

MUNICH, COLOGNE, KIEL = (48.1374, 11.5755), (50.9413, 6.9583), (54.3233, 10.1394)


def _cache(tmp_path: Path) -> TileCache:
    return TileCache(tmp_path / "cache", 10**10)


def _never(url: str) -> bytes:
    raise AssertionError(f"nothing should have been fetched: {url}")


def _tif(tmp_path: Path, values: np.ndarray, west: float, north: float, cell: float) -> bytes:
    path = tmp_path / f"{west:.0f}_{north:.0f}.tif"
    write_geotiff(path, values, west=west, north=north, cell_m=cell, epsg=25832)
    return path.read_bytes()


def _recording(tmp_path: Path, asked: list[str]) -> Callable[[str], bytes]:
    """Bayern's tiles by their grid name, or a service's box by its SUBSET."""
    def get(url: str) -> bytes:
        asked.append(url)
        box = re.search(r"SUBSET=x\((\d+),(\d+)\)&SUBSET=y\((\d+),(\d+)\)", url)
        if box:
            w, e, s, n = (int(g) for g in box.groups())
            return _tif(tmp_path, np.full((n - s, e - w), 60.0, dtype="float32"), w, n, 1.0)
        tile = re.search(r"/(\d+)_(\d+)\.tif$", url)
        assert tile, url
        east, north = (int(g) for g in tile.groups())
        return _tif(tmp_path, np.full((1000, 1000), 519.0, dtype="float32"),
                    east * 1000.0, (north + 1) * 1000.0, 1.0)
    return get


def test_every_bundesland_has_a_way_to_its_ground() -> None:
    assert [key for key in STATES if ground_route(key) is None] == []


def test_each_state_goes_the_way_that_was_measured() -> None:
    nrw_surface = surface_route("NW")
    assert isinstance(ground_route("NW"), TerrainSource)
    assert getattr(ground_route("BY"), "name", None) == "by-dgm1"
    assert getattr(surface_route("BY"), "name", None) == "by-dom20"
    # Tiles at one metre beat a service at five.
    assert getattr(surface_route("BW"), "name", None) == "bw-ndom1"
    assert isinstance(nrw_surface, SurfaceSource) and nrw_surface.kind == NORMALISED
    assert surface_route("SH") is None


def test_three_states_publish_their_surface_already_above_the_ground() -> None:
    def normalised(route: SurfaceSource | TileSource | None) -> bool:
        if isinstance(route, SurfaceSource):
            return route.kind == NORMALISED
        return route is not None and route.normalised

    assert sorted(k for k in STATES if normalised(surface_route(k))) == ["BW", "MV", "NW"]


@pytest.mark.parametrize("state", ["BY", "by", " BY ", "Bayern", "bayern", "DE-BY", "de-by"])
def test_a_state_is_known_by_its_key_or_its_name(state: str) -> None:
    assert getattr(ground_route(state), "name", None) == "by-dgm1"


def test_a_state_that_is_not_one_is_told_which_are() -> None:
    with pytest.raises(ValueError, match=r"'Bavaria' is not a Bundesland.*BW, BY, HB"):
        ground_route("Bavaria")


def test_a_swapped_latitude_and_longitude_are_caught_before_any_request(
        tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="swapped"):
        ground(MUNICH[1], MUNICH[0], state="BY", cache=_cache(tmp_path), get=_never)


def test_a_point_outside_germany_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not in Germany"):
        ground(40.7128, -74.0060, state="BY", cache=_cache(tmp_path), get=_never)


def test_ground_in_bayern_comes_from_its_tiles(tmp_path: Path) -> None:
    asked: list[str] = []
    w = ground(*MUNICH, state="BY", cache=_cache(tmp_path), get=_recording(tmp_path, asked))

    assert asked and all(u.startswith("https://download1.bayernwolke.de/") for u in asked)
    assert (w.source, w.epsg, w.cell_m, w.heights_above) == ("by-dgm1", 25832, 1.0, SEA)
    assert w.height_at(*MUNICH) == 519.0
    assert "Bayerische Vermessungsverwaltung" in w.attribution


def test_ground_in_nordrhein_westfalen_is_asked_of_its_service(tmp_path: Path) -> None:
    asked: list[str] = []
    w = ground(*COLOGNE, state="NW", cache=_cache(tmp_path), get=_recording(tmp_path, asked))

    assert len(asked) == 1 and asked[0].startswith("https://www.wcs.nrw.de/geobasis/wcs_nw_dgm?")
    assert (w.source, w.heights_above) == ("nw-dgm-wcs", SEA)
    assert w.height_at(*COLOGNE) == 60.0


def test_a_normalised_surface_says_it_is_above_the_ground(tmp_path: Path) -> None:
    w = surface(*COLOGNE, state="NW", cache=_cache(tmp_path),
                get=_recording(tmp_path, []))

    assert (w.source, w.heights_above) == ("nw-ndom-wcs", GROUND)


def test_no_surface_model_says_so_and_what_does_work(tmp_path: Path) -> None:
    with pytest.raises(Unavailable, match=r"Schleswig-Holstein.*ground\(\) works"):
        surface(*KIEL, state="SH", cache=_cache(tmp_path), get=_never)


def _window(values: list[list[float]] | np.ndarray, cell: float, source: str,
            above: str = SEA) -> Window:
    return Window(np.asarray(values, dtype="float32"), 0.0, 2.0, cell, 25832, source,
                  "CC-BY-4.0", "© Test", above)


def test_object_heights_are_the_surface_less_the_ground_under_each_cell(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Twenty-centimetre surface cells over one-metre ground, as in Bayern."""
    top_values = np.full((10, 10), 520.0, dtype="float32")
    top_values[0, 0] = 499.0              # below its own ground: an edge, not a pit
    top_values[5, 5] = np.nan
    top = _window(top_values, 0.2, "by-dom20")
    base = _window([[500.0, 501.0], [502.0, 503.0]], 1.0, "by-dgm1")
    monkeypatch.setattr(heights, "surface", lambda *_a, **_k: top)
    monkeypatch.setattr(heights, "ground", lambda *_a, **_k: base)

    w = object_heights(*MUNICH, state="BY")

    assert (w.values[1, 1], w.values[1, 8], w.values[8, 1], w.values[8, 8]) == (20, 19, 18, 17)
    assert w.values[0, 0] == 0.0
    assert np.isnan(w.values[5, 5])
    assert (w.source, w.attribution, w.heights_above) == (
        "by-dom20 minus by-dgm1", "© Test", GROUND)


def test_a_surface_already_above_the_ground_is_not_subtracted_again(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Nordrhein-Westfalen's own nDOM goes down to -5.7 m around the cathedral.
    `surface()` keeps that; object heights read it as bare ground."""
    ndom = _window([[12.0, -5.7, np.nan]], 0.5, "nw-ndom-wcs", GROUND)
    monkeypatch.setattr(heights, "surface", lambda *_a, **_k: ndom)
    monkeypatch.setattr(heights, "ground", lambda *_a, **_k: pytest.fail("asked for ground"))

    w = object_heights(*COLOGNE, state="NW")

    np.testing.assert_array_equal(w.values, [[12.0, 0.0, np.nan]])
    assert (w.source, w.heights_above, w.cell_m) == ("nw-ndom-wcs", GROUND, 0.5)


def test_the_cache_goes_where_it_is_told(monkeypatch: pytest.MonkeyPatch,
                                         tmp_path: Path) -> None:
    monkeypatch.setenv("GEOKACHEL_CACHE", str(tmp_path / "here"))
    assert default_cache().root == tmp_path / "here"

    monkeypatch.delenv("GEOKACHEL_CACHE")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert default_cache().root == tmp_path / "xdg" / "geokachel"
