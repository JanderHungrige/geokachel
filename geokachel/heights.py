"""One call for a square of Germany — its ground, its surface, what stands on it.

    import geokachel as gk

    w = gk.ground(48.1374, 11.5755, state="BY")    # 200 m around Munich's Marienplatz
    w.height_at(48.1374, 11.5755)                   # metres above sea level
    w.attribution                                   # show this with the number

Everything the registry knows about a state — whether it runs a coverage
service or publishes tiles; whether those tiles are computed, listed in an
index or kept in a regional archive; whether they come as GeoTIFF, as a zip or
as a million lines of text; which UTM zone they are numbered in — is decided
here, so that a caller needs a point, a state and nothing else.

Before this, the documented way in was `url_for(east_km, north_km)`, and it
worked in one state of the six tried: Thüringen answers with a zip, three
states name their tiles in a list, and Nordrhein-Westfalen — the largest —
publishes its ground as a service and as no tiles at all.
"""
from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import numpy as np

from geokachel import net
from geokachel.assemble import Fetching, Get, Unavailable, from_service, from_tiles
from geokachel.remote_zip import Ranged, Sized
from geokachel.surface_sources import NORMALISED, SURFACE_SOURCES, SurfaceSource
from geokachel.terrain_sources import TERRAIN_SOURCES, TerrainSource
from geokachel.tile_cache import TileCache
from geokachel.tile_grid import TileProduct, TileSource
from geokachel.tile_sources import STATES, key_of, name_of, sources_for
from geokachel.window import GROUND, SEA, Window

#: How much the default cache may hold before the oldest tiles go.
DEFAULT_CACHE_BYTES = 2_000_000_000

#: Germany with a margin, for catching a swapped latitude and longitude — the
#: commonest way to ask for the wrong place.
_LAT, _LON = (47.0, 55.2), (5.5, 15.5)


def default_cache() -> TileCache:
    """Where tiles are kept between calls: `$GEOKACHEL_CACHE`, else a
    `geokachel` folder in the user's cache directory (`~/.cache`)."""
    root = os.environ.get("GEOKACHEL_CACHE")
    if not root:
        base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
        root = str(Path(base) / "geokachel")
    return TileCache(Path(root), DEFAULT_CACHE_BYTES)


def _state_key(state: str) -> str:
    """"BY", "by", "Bayern" or "DE-BY" — the last is ISO 3166-2, which is what
    OpenStreetMap's geocoder answers with whatever language it answers in."""
    named = state.strip()
    key = key_of(named[3:] if named.upper().startswith("DE-") else named)
    if key not in STATES:
        raise ValueError(f"{state!r} is not a Bundesland. Use its two-letter key or its "
                         f"name, e.g. 'BY' or 'Bayern'. Keys: {', '.join(sorted(STATES))}")
    return key


def _check_point(lat: float, lon: float) -> None:
    if _LAT[0] <= lat <= _LAT[1] and _LON[0] <= lon <= _LON[1]:
        return
    swapped = _LAT[0] <= lon <= _LAT[1] and _LON[0] <= lat <= _LON[1]
    raise ValueError(f"({lat}, {lon}) is not in Germany"
                     + ("; latitude and longitude look swapped (latitude comes first)"
                        if swapped else ""))


def _fetching(lat: float, lon: float, cache: TileCache | None, get: Get | None,
              sized: Sized | None, ranged: Ranged | None) -> Fetching:
    _check_point(lat, lon)
    return Fetching(cache if cache is not None else default_cache(),
                    get or net.get_bytes, sized, ranged)


def _tiles(key: str, product: TileProduct) -> TileSource | None:
    return next((s for s in sources_for(key) if s.product is product), None)


def ground_route(state: str) -> TerrainSource | TileSource | None:
    """Where a state's ground comes from: its coverage service where it runs
    one, else its tiles. Every Bundesland has one or the other."""
    key = _state_key(state)
    service = next((s for s in TERRAIN_SOURCES if key_of(s.state) == key), None)
    return service if service is not None else _tiles(key, TileProduct.DGM1)


def surface_route(state: str) -> SurfaceSource | TileSource | None:
    """Where a state's surface model comes from: the finer of its service and
    its tiles, or None — Schleswig-Holstein publishes none."""
    key = _state_key(state)
    service = next((s for s in SURFACE_SOURCES if key_of(s.state) == key), None)
    tiles = _tiles(key, TileProduct.DOM)
    if tiles is not None and (service is None or (tiles.cell_m or 1.0) < service.cell_m):
        return tiles
    return service


def ground(lat: float, lon: float, *, state: str, size_m: float = 200.0,
           cache: TileCache | None = None, get: Get | None = None,
           sized: Sized | None = None, ranged: Ranged | None = None) -> Window:
    """The bare ground around a point, in metres above sea level.

    `state` is the Bundesland the point is in, as `"BY"` or `"Bayern"`, and
    `size_m` the edge of the square, centred on the point (at most 2000).
    Every state publishes its ground; `Unavailable` means none of it could be
    had for this place today — a portal down, or a point outside the state.
    """
    how = _fetching(lat, lon, cache, get, sized, ranged)
    route = ground_route(state)
    if isinstance(route, TerrainSource):
        return from_service(route, "dgm", lat, lon, size_m, how, SEA)
    if route is None:
        raise Unavailable(f"{name_of(state)} publishes no ground this package can use")
    return from_tiles(route, lat, lon, size_m, how)


def surface(lat: float, lon: float, *, state: str, size_m: float = 200.0,
            cache: TileCache | None = None, get: Get | None = None,
            sized: Sized | None = None, ranged: Ranged | None = None) -> Window:
    """The top of everything standing on the ground — roofs, tree crowns, and
    the ground itself where nothing stands.

    Mostly metres above sea level; three states publish it already relative to
    the ground, and `Window.heights_above` says which. Where a state offers a
    service and tiles, the finer is used. Schleswig-Holstein publishes no
    surface model, and there this raises `Unavailable`.
    """
    how = _fetching(lat, lon, cache, get, sized, ranged)
    route = surface_route(state)
    if isinstance(route, SurfaceSource):
        above = GROUND if route.kind == NORMALISED else SEA
        return from_service(route, route.kind, lat, lon, size_m, how, above)
    if route is None:
        raise Unavailable(f"{name_of(state)} publishes no surface model this package can "
                          f"use; ground() works there")
    return from_tiles(route, lat, lon, size_m, how)


def object_heights(lat: float, lon: float, *, state: str, size_m: float = 200.0,
                   cache: TileCache | None = None, get: Get | None = None,
                   sized: Sized | None = None, ranged: Ranged | None = None) -> Window:
    """How tall whatever stands on the ground is: the surface minus the ground.

    Zero is bare ground; a house reads its height and a tree its crown's top.
    The subtraction is done once, and not at all for a surface model that is
    already relative to the ground — doing it twice would put every tree three
    hundred metres underground, a mistake this code has made before. Below
    zero is two surveys disagreeing, not a pit, and reads as zero on either
    route; `surface()` keeps a publisher's own numbers as they are.
    """
    top = surface(lat, lon, state=state, size_m=size_m, cache=cache, get=get,
                  sized=sized, ranged=ranged)
    if top.heights_above == GROUND:
        return replace(top, values=np.maximum(top.values, 0.0).astype("float32"))
    base = ground(lat, lon, state=state, size_m=size_m, cache=cache, get=get,
                  sized=sized, ranged=ranged)
    standing = np.maximum(top.values - _ground_under(top, base), 0.0).astype("float32")
    return Window(standing, top.west, top.north, top.cell_m, top.epsg,
                  f"{top.source} minus {base.source}",
                  " + ".join(dict.fromkeys((top.licence, base.licence))),
                  " · ".join(dict.fromkeys((top.attribution, base.attribution))), GROUND)


def _ground_under(top: Window, base: Window) -> np.ndarray:
    """For each surface cell, the ground cell under its centre.

    Both are on the same axes, but not always the same cells: Bayern's surface
    is 20 cm over a one-metre ground. A value below its own ground is two
    surveys disagreeing at an edge, not a pit, so the caller clips it to zero.
    """
    if base.epsg != top.epsg:
        raise Unavailable("the ground and the surface came in different UTM zones")
    ys = top.north - (np.arange(top.rows) + 0.5) * top.cell_m
    xs = top.west + (np.arange(top.cols) + 0.5) * top.cell_m
    rows = np.floor((base.north - ys) / base.cell_m).astype(np.intp)
    cols = np.floor((xs - base.west) / base.cell_m).astype(np.intp)
    row_ok, col_ok = (rows >= 0) & (rows < base.rows), (cols >= 0) & (cols < base.cols)
    under = np.full(top.values.shape, np.nan, dtype="float32")
    under[np.ix_(row_ok, col_ok)] = base.values[np.ix_(rows[row_ok], cols[col_ok])]
    return under


__all__ = [
    "DEFAULT_CACHE_BYTES",
    "default_cache",
    "ground",
    "ground_route",
    "object_heights",
    "surface",
    "surface_route",
]
