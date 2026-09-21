"""What `ground()` and `surface()` hand back: a square of heights that knows
where it is and whose it is.

A tile is a state's unit, and nobody's garden, field or roof is one. A window
is the caller's unit — a square around the point they asked about, cut out of
however many tiles or whatever service the state offers, on one grid, with the
credit its licence requires attached rather than left for later.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from geokachel.geotiff import write_geotiff
from geokachel.utm import to_latlon, to_utm

#: What a window's heights are measured from.
SEA, GROUND = "sea level", "ground"


@dataclass(frozen=True)
class Window:
    """A square of ground, north-up, in the metres of a UTM zone.

    `values[0][0]` is the north-west cell and `values[-1][-1]` the south-east.
    NaN is ground nobody surveyed — sea, a border, a gap in a flight — never a
    guess and never zero.
    """

    #: Heights in metres, as float32, shape (rows, cols).
    values: np.ndarray
    #: Easting of the west edge and northing of the north edge, in metres.
    west: float
    north: float
    #: Edge of one cell in metres: 1.0 for most ground, down to 0.2.
    cell_m: float
    #: 25832 for UTM zone 32 north, 25833 for zone 33 — ETRS89 in both. The
    #: state decides, not the longitude: all of Bayern is numbered in zone 32.
    epsg: int
    #: Which registry entry produced this, e.g. `by-dgm1` or `nw-dgm-wcs`.
    source: str
    licence: str
    #: The credit the licence requires, in the publisher's words. Show it
    #: wherever anything derived from these numbers is shown.
    attribution: str
    #: `"sea level"` for ground and most surface models; `"ground"` for a
    #: surface model already normalised to the ground, and for object heights.
    heights_above: str

    @property
    def rows(self) -> int:
        return int(self.values.shape[0])

    @property
    def cols(self) -> int:
        return int(self.values.shape[1])

    @property
    def east(self) -> float:
        return self.west + self.cols * self.cell_m

    @property
    def south(self) -> float:
        return self.north - self.rows * self.cell_m

    @property
    def zone(self) -> int:
        return 32 if self.epsg == 25832 else 33

    @property
    def surveyed(self) -> float:
        """The share of cells with a height, 0 to 1. Below 1 is a coast, a
        border, or a tile the state's portal did not hand over today."""
        return float(np.isfinite(self.values).mean()) if self.values.size else 0.0

    def centre_of(self, row: int, col: int) -> tuple[float, float]:
        """The easting and northing of a cell's centre."""
        return (self.west + (col + 0.5) * self.cell_m,
                self.north - (row + 0.5) * self.cell_m)

    def at(self, easting: float, northing: float) -> float | None:
        """The height at a UTM point in this window's zone, or None."""
        col = math.floor((easting - self.west) / self.cell_m)
        row = math.floor((self.north - northing) / self.cell_m)
        if not (0 <= row < self.rows and 0 <= col < self.cols):
            return None
        value = float(self.values[row][col])
        return None if math.isnan(value) else value

    def height_at(self, lat: float, lon: float) -> float | None:
        """The height at a latitude and longitude, or None outside the window
        or where nobody surveyed."""
        easting, northing = to_utm(lat, lon, self.zone)
        return self.at(easting, northing)

    def latlon_of(self, row: int, col: int) -> tuple[float, float]:
        """A cell's centre as latitude and longitude."""
        return to_latlon(*self.centre_of(row, col), self.zone)

    def write_geotiff(self, path: str | os.PathLike[str]) -> Path:
        """Save as a GeoTIFF that QGIS, GDAL or any GIS places on the map.

        The credit goes inside, as the file's Copyright tag — still show it
        wherever a map or a number made from this file is shown."""
        return write_geotiff(path, self.values, west=self.west, north=self.north,
                             cell_m=self.cell_m, epsg=self.epsg,
                             credit=f"{self.attribution} ({self.licence})",
                             description=f"{self.source}: metres above {self.heights_above}")


__all__ = ["GROUND", "SEA", "Window"]
