"""Heights from the command line — a number or a file, without Python.

    geokachel states                                  # what each Bundesland publishes
    geokachel ground  48.1374 11.5755 --state BY      # the height there, and whose it is
    geokachel surface 48.1374 11.5755 --state BY --out marienplatz.tif
    geokachel objects 50.9413 6.9583 --state NW --size 500 --out dom.tif

The two numbers are latitude and longitude in decimal degrees — right-click a
place in Google Maps or OpenStreetMap and they are the first thing shown.
`--out` writes a GeoTIFF that QGIS, GDAL or any GIS puts in the right place on
its own, with the required credit inside it.
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from functools import partial

import numpy as np

from geokachel.assemble import MAX_SIZE_M, Unavailable
from geokachel.heights import ground, ground_route, object_heights, surface, surface_route
from geokachel.net import FetchError
from geokachel.surface_sources import NORMALISED, SurfaceSource
from geokachel.terrain_sources import TerrainSource
from geokachel.tile_grid import TileSource
from geokachel.tile_sources import STATES
from geokachel.window import Window

Route = TerrainSource | SurfaceSource | TileSource | None

JOBS: dict[str, tuple[Callable[..., Window], str]] = {
    "ground": (ground, "the bare ground, in metres above sea level (DGM)"),
    "surface": (surface, "the top of everything on it: roofs, tree crowns (DOM)"),
    "objects": (object_heights, "how tall buildings and trees are: surface minus ground"),
}


def _route(route: Route) -> str:
    if route is None:
        return "—"
    above = ((isinstance(route, SurfaceSource) and route.kind == NORMALISED)
             or (isinstance(route, TileSource) and route.normalised))
    how = "tiles" if isinstance(route, TileSource) else "service"
    cell = (route.cell_m or 1.0) if isinstance(route, TileSource) else route.cell_m
    return f"{cell:g} m {how}" + (", above ground" if above else "")


def state_rows() -> list[tuple[str, str, str, str, str, str]]:
    """Key, name, UTM zone, ground, surface and licence, for every state."""
    rows = []
    for key, name in sorted(STATES.items()):
        base, top = ground_route(key), surface_route(key)
        zone = "—" if base is None else ("32" if base.epsg == 25832 else "33")
        licences = dict.fromkeys(r.licence for r in (base, top) if r is not None)
        rows.append((key, name, zone, _route(base), _route(top), ", ".join(licences)))
    return rows


def markdown_table() -> str:
    """The table in the README, generated so it cannot drift from the code."""
    lines = ["| Key | Bundesland | UTM zone | Ground | Surface | Licence |",
             "|---|---|---|---|---|---|"]
    lines += ["| " + " | ".join(row) + " |" for row in state_rows()]
    return "\n".join(lines)


def _states(chosen: argparse.Namespace) -> int:
    if chosen.markdown:
        print(markdown_table())
        return 0
    print(f"{'key':4s}{'Bundesland':24s}{'zone':6s}{'ground':12s}{'surface':30s}licence")
    for key, name, zone, base, top, licence in state_rows():
        print(f"{key:4s}{name:24s}{zone:6s}{base:12s}{top:30s}{licence}")
    return 0


def _summary(w: Window, lat: float, lon: float, what: str) -> list[str]:
    here = w.height_at(lat, lon)
    unit = f"m above {w.heights_above}"
    lines = [f"{what} at {lat:.5f}, {lon:.5f}: "
             + (f"{here:.2f} {unit}" if here is not None else "not surveyed")]
    if w.surveyed > 0:
        lines.append(f"  lowest {np.nanmin(w.values):.2f}, highest "
                     f"{np.nanmax(w.values):.2f} {unit}")
    lines += [f"  {w.cols} x {w.rows} cells of {w.cell_m:g} m, {w.surveyed:.0%} surveyed, "
              f"UTM zone {w.zone} (EPSG:{w.epsg}), from {w.source}",
              f"  credit (required): {w.attribution} [{w.licence}]"]
    return lines


def _window_job(job: str, chosen: argparse.Namespace) -> int:
    fetch, _ = JOBS[job]
    try:
        w = fetch(chosen.lat, chosen.lon, state=chosen.state, size_m=chosen.size)
    except (ValueError, Unavailable, FetchError, OSError) as why:
        print(f"geokachel {job}: {why}", file=sys.stderr)
        return 1
    print("\n".join(_summary(w, chosen.lat, chosen.lon, job)))
    if chosen.out:
        print(f"  saved {w.write_geotiff(chosen.out)}")
    return 0


def add_commands(jobs: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """`states`, `ground`, `surface` and `objects`, on the main parser."""
    listed = jobs.add_parser("states", help="what each Bundesland publishes, and how")
    listed.add_argument("--markdown", action="store_true", help="as a Markdown table")
    listed.set_defaults(run=_states, quiet=False)
    for job, (_, words) in JOBS.items():
        how = (__doc__ or "").partition("\n")[2].strip("\n")
        asked = jobs.add_parser(job, help=words, description=f"{words.capitalize()}.\n\n{how}",
                                formatter_class=argparse.RawDescriptionHelpFormatter)
        asked.add_argument("lat", type=float, help="latitude in degrees, e.g. 48.1374")
        asked.add_argument("lon", type=float, help="longitude in degrees, e.g. 11.5755")
        asked.add_argument("--state", required=True,
                           help="the Bundesland, as BY or Bayern (list: geokachel states)")
        asked.add_argument("--size", type=float, default=200.0,
                           help=f"edge of the square in metres (default 200, at most "
                                f"{MAX_SIZE_M:.0f})")
        asked.add_argument("--out", help="also save the square as a GeoTIFF here")
        asked.set_defaults(run=partial(_window_job, job), quiet=False)


__all__ = ["add_commands", "markdown_table", "state_rows"]
