"""Filling a window: cut out of a state's tiles, or asked of its service.

Two routes and one result. A **service** is asked for exactly the square and
placed by what its answer says about itself (`geotiff.georeference`). **Tiles**
are fetched one at a time — Bayern's 20 cm surface is a hundred megabytes a
tile once decoded — and each is pasted into the square where its own tags put
it, or its grid corner where it has none.

Checked on 2026-09-21 against a real tile from every GeoTIFF source, a zip's
four members included: all seventeen sat exactly on their grid corners at the
cell size the registry records. The tags are still read first, because they
are right by definition and the grid is only right by agreement.
"""
from __future__ import annotations

import hashlib
import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from geokachel.addressing import CELL_M, INSIDE, addressed, decode, tiles_across
from geokachel.geotiff import georeference
from geokachel.net import FetchError
from geokachel.remote_zip import Ranged, Sized
from geokachel.surface_sources import SurfaceSource
from geokachel.terrain_sources import TerrainSource
from geokachel.tiff import Raster, read_raster
from geokachel.tile_cache import TileCache
from geokachel.tile_grid import TileSource, corner_in
from geokachel.tile_sources import key_of, name_of
from geokachel.tile_zip import named
from geokachel.utm import to_utm
from geokachel.window import GROUND, SEA, Window

#: url -> its bytes.
Get = Callable[[str], bytes]

#: The largest square one call fetches, edge in metres. A kilometre either way
#: is up to nine tiles; more than that is a loop over smaller windows, with
#: pauses, and not one call that looks cheap.
MAX_SIZE_M = 2000.0
#: And the most cells a window may hold: 25 million float32 is 100 MB, which is
#: where Bayern's 20 cm surface stops, at a kilometre square.
MAX_CELLS = 25_000_000
#: Nothing in Germany is below the Dead Sea or above Everest. A number outside
#: this is a publisher's no-data marker, not a height.
PLAUSIBLE_M = (-500.0, 9000.0)

#: What can go wrong between asking and decoding: a refusal, a network error,
#: or bytes that are not what they claim — every reader's error is a ValueError.
TROUBLE = (FetchError, OSError, ValueError)


class Unavailable(RuntimeError):
    """Nothing could be had for this place: the state publishes nothing of the
    kind, nothing was surveyed there, or its portal did not answer."""


@dataclass(frozen=True)
class Fetching:
    """Where bytes come from and where they are kept, for one call."""

    cache: TileCache
    get: Get
    sized: Sized | None = None
    ranged: Ranged | None = None


def frame_around(east: float, north: float, size_m: float,
                 cell: float) -> tuple[float, float, int, int]:
    """A square on a source's own grid: west, north, columns, rows."""
    if not 0 < size_m <= MAX_SIZE_M:
        raise ValueError(f"size_m must be above 0 and at most {MAX_SIZE_M:.0f} metres, "
                         f"not {size_m}")
    half = size_m / 2
    west = math.floor((east - half) / cell) * cell
    top = math.ceil((north + half) / cell) * cell
    cols = math.ceil(round((east + half - west) / cell, 6))
    rows = math.ceil(round((top - (north - half)) / cell, 6))
    if cols * rows > MAX_CELLS:
        raise ValueError(f"{size_m:.0f} m at {cell} m cells is {cols * rows:,} cells, and one "
                         f"call returns at most {MAX_CELLS:,}. Ask for a smaller square.")
    return west, top, cols, rows


def _plausible(values: np.ndarray) -> np.ndarray:
    out = np.array(values, dtype="float32")
    low, high = PLAUSIBLE_M
    with np.errstate(invalid="ignore"):
        out[(out < low) | (out > high)] = np.nan
    return out


def _paste(values: np.ndarray, raster: Raster, west: float, north: float, cell: float,
           frame_west: float, frame_north: float) -> None:
    """Copy the part of a raster that falls inside the frame."""
    left = int(round((west - frame_west) / cell))
    up = int(round((frame_north - north) / cell))
    rows, cols = values.shape
    c0, r0 = max(0, -left), max(0, -up)
    c1, r1 = min(raster.width, cols - left), min(raster.height, rows - up)
    if c1 > c0 and r1 > r0:
        values[up + r0:up + r1, left + c0:left + c1] = raster.values[r0:r1, c0:c1]


def _pieces(source: TileSource, data: bytes, corner: tuple[int, int],
            cell: float) -> list[tuple[float, float, Raster]]:
    """Each raster in what arrived, with the north-west corner it belongs at."""
    bodies = ([(corner, data)] if not source.zipped else
              [(corner_in(name, corner), body)
               for name, body in named(data, want=INSIDE[source.fmt])])
    found: list[tuple[float, float, Raster]] = []
    for at, body in bodies:
        raster = decode(source, body, cell, at)
        grid_west, grid_north = at[0] * 1000.0, at[1] * 1000.0 + raster.height * cell
        tags = georeference(body) if source.fmt == "GeoTIFF" else None
        reach = source.tile_km * 1000.0
        trusted = (tags is not None and math.isclose(tags.cell_x, cell, rel_tol=1e-6)
                   and math.isclose(tags.cell_y, cell, rel_tol=1e-6)
                   and abs(tags.west - grid_west) <= reach
                   and abs(tags.north - grid_north) <= reach)
        if tags is not None and trusted:
            found.append((tags.west, tags.north, raster))
        else:
            found.append((grid_west, grid_north, raster))
    return found


def from_tiles(source: TileSource, lat: float, lon: float, size_m: float,
               how: Fetching) -> Window:
    """A window cut out of a state's tiles, one tile in memory at a time."""
    east, north = to_utm(lat, lon, 32 if source.epsg == 25832 else 33)
    cell = source.cell_m or CELL_M
    west, top, cols, rows = frame_around(east, north, size_m, cell)
    values = np.full((rows, cols), np.nan, dtype="float32")
    trouble: list[str] = []
    for corner in tiles_across(east, north, source, size_m / 2 + cell):
        try:
            wanted = addressed(source, [corner], how.cache, how.get,
                               sized=how.sized, ranged=how.ranged)
        except TROUBLE as why:
            trouble.append(f"its list of tiles: {why}")
            continue
        for at, key, grab in wanted:
            try:
                pieces = _pieces(source, how.cache.fetched(key, grab), at, cell)
            except TROUBLE as why:
                trouble.append(f"tile {at[0]}_{at[1]}: {why}")
                # A file that does not decode is not kept: the next call asks again.
                how.cache.path_for(key).unlink(missing_ok=True)
                continue
            for tile_west, tile_north, raster in pieces:
                _paste(values, raster, tile_west, tile_north, cell, west, top)
    window = Window(_plausible(values), west, top, cell, source.epsg, source.name,
                    source.licence, source.attribution,
                    GROUND if source.normalised else SEA)
    return _surveyed(window, source.name, source.state, lat, lon, trouble)


def coverage_url(service: TerrainSource | SurfaceSource,
                 box: tuple[int, int, int, int]) -> str:
    """A WCS 2.0.1 request for a west, south, east, north box in whole metres.

    Whole metres because, measured against all sixteen services, that is what
    makes every one of them anchor its answer at the corner asked for."""
    west, south, east, north = box
    x, y = service.axes
    return (f"{service.url}?SERVICE=WCS&VERSION=2.0.1&REQUEST=GetCoverage"
            f"&COVERAGEID={service.coverage}&SUBSET={x}({west},{east})"
            f"&SUBSET={y}({south},{north})&FORMAT=image/tiff")


def from_service(service: TerrainSource | SurfaceSource, kind: str, lat: float, lon: float,
                 size_m: float, how: Fetching, above: str) -> Window:
    """A window asked of a coverage service, placed by its own answer."""
    east, north = to_utm(lat, lon, 32 if service.epsg == 25832 else 33)
    frame_around(east, north, size_m, service.cell_m)          # the size guards
    half = size_m / 2
    box = (math.floor(east - half), math.floor(north - half),
           math.ceil(east + half), math.ceil(north + half))
    url = coverage_url(service, box)
    state = key_of(service.state).lower()
    name = f"{state}-{kind}-wcs"
    key = f"{state}/wcs/{kind}-{hashlib.sha256(url.encode()).hexdigest()[:24]}.tif"
    decoded: list[Raster] = []

    def grab() -> bytes:
        data = how.get(url)
        # Decoded before it is kept: a service's error page cached as a
        # raster would be served again on every call after.
        decoded.append(read_raster(data, max_pixels=MAX_CELLS))
        return data

    try:
        data = how.cache.fetched(key, grab)
        raster = decoded[0] if decoded else read_raster(data, max_pixels=MAX_CELLS)
    except TROUBLE as why:
        raise Unavailable(f"{name}: the service did not answer with heights for "
                          f"({lat}, {lon}): {why}") from why
    placed = georeference(data)
    if placed is None:
        values, west, top, cell = raster.values, float(box[0]), float(box[3]), service.cell_m
    else:
        values, cell = _squared(raster.values, placed.cell_x, placed.cell_y)
        west, top = placed.west, placed.north
    window = Window(_plausible(values), west, top, cell, service.epsg, name,
                    service.licence, service.attribution, above)
    return _surveyed(window, name, service.state, lat, lon, [])


def _squared(values: np.ndarray, cell_x: float, cell_y: float) -> tuple[np.ndarray, float]:
    """An answer on square cells, and their size.

    Baden-Württemberg's terrain service answers W - 1 columns for a box W
    metres wide, each stretched to fill it: 199 columns of 1.005 m for 200 m,
    whatever the box's size, offset or axis order, and it refuses `SCALESIZE`
    (measured 2026-09-21). Put back onto the finer of the two cell sizes by
    nearest neighbour, each cell takes the value its centre falls in, so no
    height moves by more than half a cell.
    """
    if math.isclose(cell_x, cell_y, rel_tol=1e-6):
        return values, cell_x
    cell = min(cell_x, cell_y)
    rows, cols = values.shape
    wanted_rows, wanted_cols = round(rows * cell_y / cell), round(cols * cell_x / cell)
    from_rows = np.minimum(((np.arange(wanted_rows) + 0.5) * cell / cell_y).astype(np.intp),
                           rows - 1)
    from_cols = np.minimum(((np.arange(wanted_cols) + 0.5) * cell / cell_x).astype(np.intp),
                           cols - 1)
    return values[np.ix_(from_rows, from_cols)], cell


def _surveyed(window: Window, name: str, state: str, lat: float, lon: float,
              trouble: list[str]) -> Window:
    """The window, or a clear reason there are no heights in it at all."""
    if window.surveyed > 0:
        return window
    why = "; ".join(trouble[:3]) if trouble else "nothing surveyed in this square"
    raise Unavailable(f"{name}: no heights around ({lat}, {lon}) — {why}. Is the point in "
                      f"{name_of(key_of(state))}? If it is, `geokachel check {name}` says "
                      f"whether the state's portal is answering.")


__all__ = [
    "MAX_CELLS",
    "MAX_SIZE_M",
    "PLAUSIBLE_M",
    "Fetching",
    "Get",
    "Unavailable",
    "coverage_url",
    "frame_around",
    "from_service",
    "from_tiles",
]
