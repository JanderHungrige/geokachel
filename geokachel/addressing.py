"""Where a tile lives, and what comes out of it — the three ways.

Germany's sixteen surveying offices give a tile an address in three different
kinds of way, and this returns all three in one shape so that nothing above has
to know which it got:

- **computed** — the name is arithmetic on two UTM kilometre numbers, which is
  what most states do and what makes a tile's address a template and two
  integers rather than a lookup.
- **listed** — the name carries a survey year, so no arithmetic reaches it and
  the state's own index is read once. What is taken out of that index is a
  *file name*; the scheme, the host and the shape of the address stay ours.
- **archived** — the state publishes no tile at all, only a whole region of
  them, so one member is pulled out over HTTP range requests. A zip keeps its
  index at its end, which is what makes that possible: 0.38 % of a 559 MB file
  for one tile, measured.

What comes back is a `Raster` per grid corner, north-up, in the source's own
UTM, with NaN where nobody surveyed. Putting those on some other set of axes is
the caller's business.
"""
from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable

from geokachel.net import FetchError, get_range, size_of
from geokachel.remote_zip import Ranged, Sized, member_of, names_in
from geokachel.tiff import WHOLE_TILE_PIXELS, Raster, TiffError, read_raster
from geokachel.tile_cache import Fetch, TileCache
from geokachel.tile_grid import TileLookup, TileSource, corner_in
from geokachel.tile_index import SAFE_NAME
from geokachel.tile_zip import ArchiveError, named
from geokachel.xyz import Frame, read_grid

log = logging.getLogger(__name__)

#: How a tile's bytes are got, whichever of the three ways it is addressed.
Grab = Callable[[], bytes]

#: What a DGM1 tile's cell is, in metres. The product's name is its resolution.
CELL_M = 1.0


def tiles_across(east: float, north: float, source: TileSource,
                 reach_m: float) -> list[tuple[int, int]]:
    """Every tile a window of this reach touches, by south-west corner.

    A window lies inside one tile only when the point is far enough from every
    edge — for a 200 m window in a 1 km tile, 64 % of the time. The rest of the
    time it crosses a line, and a caller that fetched one tile would have a
    window with nothing in one corner of it.
    """
    step = source.tile_km
    first_e, first_n = source.corner_of(east - reach_m, north - reach_m)
    last_e, last_n = source.corner_of(east + reach_m, north + reach_m)
    return [(e, n)
            for e in range(first_e, last_e + 1, step)
            for n in range(first_n, last_n + 1, step)]


#: What the wanted member of an archive is called, per format. CityGML is
#: `.gml` in most states and `.xml` in Berlin and Schleswig-Holstein.
INSIDE: dict[str, tuple[str, ...]] = {
    "GeoTIFF": (".tif", ".tiff"),
    "CityGML": (".gml", ".xml"),
    "LAZ": (".laz", ".las"),
    "XYZ": (".xyz", ".txt", ".asc"),
}


def cache_key(source: TileSource, east_km: int, north_km: int) -> str:
    """Where this tile lives on the volume: what it is, never who asked."""
    suffix = {"GeoTIFF": "tif", "CityGML": "gml",
              "LAZ": "laz", "XYZ": "xyz"}.get(source.fmt, "bin")
    return (f"{source.state.lower()}/{source.product.value}/"
            f"{source.tile_name(east_km, north_km)}.{'zip' if source.zipped else suffix}")


def frame_of(source: TileSource, corner: tuple[int, int], cell_m: float) -> Frame:
    """The whole tile at this corner: its west and north edges, and its size.

    What a partly surveyed tile must be decoded into, so that it is placed as
    the tile it is rather than as the part of it that was surveyed.
    """
    east_km, north_km = corner
    side = int(round(source.tile_km * 1000 / cell_m))
    return (east_km * 1000.0, (north_km + source.tile_km) * 1000.0, side, side)


def decode(source: TileSource, body: bytes, cell_m: float,
           corner: tuple[int, int] | None = None) -> Raster:
    """One tile's bytes as a raster, whichever way the state writes them.

    Several states publish a height grid as text rather than as an image. It
    decodes to the same north-up raster, so nothing downstream knows — and,
    given the tile's `corner`, to the *whole* tile even where only part of it
    was surveyed, because every caller places it by that corner.
    """
    if source.fmt == "XYZ":
        frame = frame_of(source, corner, cell_m) if corner is not None else None
        return read_grid(body, cell_m=cell_m, max_pixels=WHOLE_TILE_PIXELS, frame=frame)
    return read_raster(body, max_pixels=WHOLE_TILE_PIXELS)


def parts(source: TileSource, data: bytes, corner: tuple[int, int],
           cell_m: float) -> list[tuple[tuple[int, int], Raster]]:
    """The rasters in what arrived, each with the corner it belongs at."""
    if not source.zipped:
        return [(corner, decode(source, data, cell_m, corner))]
    placed = [(corner_in(name, corner), body)
              for name, body in named(data, want=INSIDE[source.fmt])]
    return [(at, decode(source, body, cell_m, at)) for at, body in placed]


#: A state's list of what it holds, parsed once per process. Rheinland-Pfalz's
#: ground is twelve megabytes of XML and twenty-one thousand names: a thing to
#: read once for a deployment, not once for a garden. The file itself is on the
#: volume under the same cap as the tiles.
_LISTINGS: dict[str, dict[tuple[int, int], str]] = {}


def _listing(lookup: TileLookup, cache: TileCache,
             fetch: Fetch) -> dict[tuple[int, int], str]:
    """Which tiles the state says it has, and what each is called."""
    if lookup.index_url not in _LISTINGS:
        leaf = lookup.index_url.rsplit("/", 1)[-1]
        key = f"index/{leaf if SAFE_NAME.match(leaf) else 'listing'}"
        _LISTINGS[lookup.index_url] = lookup.parse(cache.get(key, lookup.index_url, fetch))
    return _LISTINGS[lookup.index_url]


#: Which tiles each archive holds, read from its own directory once and kept
#: for the life of the process. Reading Saarland's six directories is eighteen
#: requests and two hundred kilobytes.
_HELD: dict[str, dict[tuple[int, int], tuple[str, str]]] = {}
#: When an archive last failed to answer. Until 2026-09-21 a failure was kept
#: like an answer, so a region whose archive missed one request stayed missing
#: until the program restarted — harmless on the command line, and a hole that
#: never closed in anything long-running.
_FAILED_AT: dict[str, float] = {}
#: How long an archive that did not answer is left alone before it is asked
#: again: a region missing for five minutes, rather than a public portal that
#: is down being asked on every call.
RETRY_AFTER_S = 300.0
#: The clock, under a name a test can replace.
_now: Callable[[], float] = time.monotonic


def _held(archives: tuple[str, ...], *, sized: Sized | None = None,
          ranged: Ranged | None = None) -> dict[tuple[int, int], tuple[str, str]]:
    """What each archive holds, from its own central directory.

    A state that publishes no tile publishes no list of tiles either — and does
    not need to, because a zip says what is in it and says so at its end.

    The two fetchers are arguments because this was the last place in the tile
    path that reached for `ingest.http` itself; everything else here is already
    handed what it should use. The defaults are resolved at the call so a test
    can still replace the module's own.
    """
    look, reach = sized or size_of, ranged or get_range
    found: dict[tuple[int, int], tuple[str, str]] = {}
    for url in archives:
        if url not in _HELD and _now() - _FAILED_AT.get(url, -math.inf) >= RETRY_AFTER_S:
            _read_directory(url, look, reach)
        found.update(_HELD.get(url, {}))
    return found


def _read_directory(url: str, look: Sized, reach: Ranged) -> None:
    """One archive's directory into `_HELD`, or the time it failed into
    `_FAILED_AT`. One region's archive missing is that region without ground,
    not the state without ground."""
    try:
        inside = names_in(url, size=look, ranged=reach)
    except (FetchError, OSError, ValueError) as trouble:
        _FAILED_AT[url] = _now()
        log.warning("an archive did not answer; that region stays unknown for now",
                    extra={"archive": url, "why": type(trouble).__name__})
        return
    held: dict[tuple[int, int], tuple[str, str]] = {}
    for name in inside:
        leaf = name.rsplit("/", 1)[-1]
        corner = corner_in(leaf, (0, 0))
        if corner != (0, 0) and SAFE_NAME.match(leaf):
            held[corner] = (url, name)
    _HELD[url] = held
    _FAILED_AT.pop(url, None)


def addressed(source: TileSource, corners: list[tuple[int, int]], cache: TileCache,
              fetch: Fetch, *, sized: Sized | None = None,
              ranged: Ranged | None = None) -> list[tuple[tuple[int, int], str, Grab]]:
    """Each tile's corner, the key to keep it under, and how to get it.

    Three ways a tile has an address, and every caller sees one shape. Nearly
    every state computes it from the grid. Two write a flight year into the
    name, so it is the registry's own folder plus a name their list gave us —
    never a URL out of that list. Three publish no tile at all, so it is a
    member read out of a whole-region archive over ranges (doc 103).
    """
    if source.archives:
        held = _held(source.archives, sized=sized, ranged=ranged)
        return [(corner, f"{source.state.lower()}/{source.product.value}/"
                         f"{held[corner][1].rsplit('/', 1)[-1]}",
                 _from_archive(held[corner], sized, ranged))
                for corner in corners if corner in held]
    if source.lookup is not None:
        names = _listing(source.lookup, cache, fetch)
        address = source.lookup.address
        return [(corner, f"{source.state.lower()}/{source.product.value}/{names[corner]}",
                 _from_url(address(names[corner], corner), fetch))
                for corner in corners if corner in names]
    return [(corner, cache_key(source, *corner),
             _from_url(source.url_for(*corner), fetch)) for corner in corners]


def _from_url(url: str, fetch: Fetch) -> Grab:
    return lambda: fetch(url)


def _from_archive(where: tuple[str, str], sized: Sized | None = None,
                  ranged: Ranged | None = None) -> Grab:
    url, name = where
    look, reach = sized or size_of, ranged or get_range
    return lambda: member_of(url, name, size=look, ranged=reach)


def rasters(source: TileSource, corners: list[tuple[int, int]], cache: TileCache,
            fetch: Fetch, cell_m: float = CELL_M, *, sized: Sized | None = None,
            ranged: Ranged | None = None) -> dict[tuple[int, int], Raster]:
    """The tiles that arrived. One missing is a hole, not a failure: a state's
    portal short of a tile is not a reason for a garden to have no ground.

    `sized` and `ranged` are only asked of a state that publishes no tile at
    all and has one read out of a regional archive; the defaults are the
    polite ones in `geokachel.net`.
    """
    got: dict[tuple[int, int], Raster] = {}
    try:
        wanted = addressed(source, corners, cache, fetch, sized=sized, ranged=ranged)
    except (FetchError, OSError, ValueError) as trouble:
        log.warning("a state's tile list could not be read; no ground from it",
                    extra={"source": source.name, "why": type(trouble).__name__})
        return got
    for corner, key, grab in wanted:
        try:
            got.update(parts(source, cache.fetched(key, grab), corner, cell_m))
        # A refusal is a FetchError, which is neither of the others: without
        # it one 404 took every other tile of the window down with it.
        except (FetchError, OSError, ValueError, TiffError, ArchiveError) as trouble:
            log.warning("a tile did not arrive; that ground stays unknown",
                        extra={"source": source.name, "tile": f"{corner[0]}_{corner[1]}",
                               "why": type(trouble).__name__})
    return got

__all__ = [
    "CELL_M",
    "Grab",
    "INSIDE",
    "addressed",
    "cache_key",
    "decode",
    "frame_of",
    "parts",
    "rasters",
    "tiles_across",
]
