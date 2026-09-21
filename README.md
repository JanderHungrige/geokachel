# geokachel

**The height of any place in Germany — the ground, the roofs and trees on it,
and how tall they are — from the official survey of whichever of the sixteen
Bundesländer it is in, with the credit each licence requires.**

```bash
pip install geokachel
```

```python
import geokachel as gk

w = gk.ground(48.1374, 11.5755, state="BY")   # 200 m around Munich's Marienplatz
w.height_at(48.1374, 11.5755)                  # 515.8  (metres above sea level)
w.attribution                                  # 'Datenquelle: Bayerische Vermessungsverwaltung – …'
```

Germany's surveying offices measure the whole country from the air with lasers
and publish the result for free. They publish it sixteen different ways —
services and files, GeoTIFF and text, zips, lists, twelve-gigabyte archives,
two coordinate zones. geokachel reads all of them, so you only have to say
*where* and *which state*.

- [What it is for](#what-it-is-for)
- [What you need: a point and its Bundesland](#what-you-need-a-point-and-its-bundesland)
- [What you get back](#what-you-get-back)
- [Examples](#examples)
- [From the command line](#from-the-command-line)
- [All sixteen states](#all-sixteen-states)
- [UTM, and the numbers in a tile's name](#utm-and-the-numbers-in-a-tiles-name)
- [Going lower: the tiles themselves](#going-lower-the-tiles-themselves)
- [Accuracy, age and limits](#accuracy-age-and-limits)
- [Checking that it is all still there](#checking-that-it-is-all-still-there)
- [The credit, and being polite](#the-credit-and-being-polite)

## What it is for

Three questions, one function each:

| | function | answers | in |
|---|---|---|---|
| **Ground** (DGM) | `gk.ground()` | how high the bare earth is | metres above sea level |
| **Surface** (DOM) | `gk.surface()` | how high the top of everything is — roofs, tree crowns, and the ground where nothing stands | metres above sea level ¹ |
| **Objects** (nDOM) | `gk.object_heights()` | how tall what stands there is | metres above the ground |

¹ Three states publish their surface already relative to the ground; `w.heights_above` says which.

Things people use that for:

- **The height of a place** — a building plot, a garden, a summit, a well, a sensor.
- **Water** — is a house above the level of the last flood; which way does rain run off a plot.
- **Shade and sun** — how tall the neighbour's house and the oak to the south are, before
  planting a bed or putting panels on a roof.
- **Slope** — for drainage, a ramp, a vineyard, a path (see [Examples](#examples)).
- **Maps and models** — save a square as a GeoTIFF and it opens in the right place in QGIS;
  feed the array to a shadow, flood, noise or visibility model; print a hill in 3D.

## What you need: a point and its Bundesland

**1. The point, as latitude and longitude** in decimal degrees — the numbers
GPS, Google Maps and OpenStreetMap use. Latitude comes first; in Germany it is
between 47 and 55, and longitude between 6 and 15.

- **Google Maps:** right-click the place. The first line of the menu is
  `48.13740, 11.57550` — click it to copy.
- **OpenStreetMap** ([openstreetmap.org](https://www.openstreetmap.org)):
  right-click → *Show address*; the coordinates are at the top of the results.
- **From an address**, in code: OpenStreetMap's geocoder
  [Nominatim](https://nominatim.org) answers with the coordinates *and* the state.

  ```python
  import requests

  hit = requests.get(
      "https://nominatim.openstreetmap.org/search",
      params={"q": "Marienplatz 1, München", "format": "jsonv2", "addressdetails": 1, "limit": 1},
      headers={"User-Agent": "my-project/1.0 (me@example.org)"},  # required: say who you are
  ).json()[0]
  lat, lon = float(hit["lat"]), float(hit["lon"])        # 48.137499, 11.5747545
  state = hit["address"]["ISO3166-2-lvl4"]                # "DE-BY", which geokachel takes as it is
  w = gk.ground(lat, lon, state=state)
  ```

  Nominatim is a free public service: at most one request a second, and no bulk
  geocoding ([usage policy](https://operations.osmfoundation.org/policies/nominatim/)).

**2. The Bundesland the point is in**, as its two-letter key (`"BY"`), its name
(`"Bayern"`) or its ISO code (`"DE-BY"`). The keys are in the
[table below](#all-sixteen-states), or run `geokachel states`. The state is not
guessed from the coordinates, on purpose: each state's data stops at its
border, so a point near one needs you to say which side it is on — and a wrong
guess fetches nothing and looks like a bug.

**3. Optionally, how big a square**: `size_m=200` by default, centred on the
point, at most 2000 m. A bigger square is more to download, not a better answer.

## What you get back

A `Window`: a square of heights that knows where it is and whose it is.

```python
w = gk.ground(48.1374, 11.5755, state="BY")
```

| | | for Marienplatz |
|---|---|---|
| `w.values` | the heights, a NumPy `float32` array, north at the top — `values[0][0]` is the north-west corner | 201 × 201 |
| `w.height_at(lat, lon)` | the height at a point, or `None` outside the square or where nothing was measured | `515.8` |
| `w.cell_m` | the edge of one cell, in metres — 1 almost everywhere, 0.5 or 0.2 for some surfaces | `1.0` |
| `w.heights_above` | `"sea level"` or `"ground"` | `"sea level"` |
| `w.attribution`, `w.licence` | the credit to show with anything made from it, and the licence | `"Datenquelle: …"`, `"CC-BY-4.0"` |
| `w.surveyed` | the share of cells with a height, 0 to 1 — below 1 at a coast or a border | `1.0` |
| `w.west`, `w.north`, `w.east`, `w.south` | the square's edges, in metres of UTM (see [UTM](#utm-and-the-numbers-in-a-tiles-name)) | `691503.0`, `5334881.0`, … |
| `w.epsg`, `w.zone` | the coordinate system: 25832 is UTM zone 32, 25833 is zone 33 | `25832`, `32` |
| `w.source` | which dataset it came from | `"by-dgm1"` |
| `w.write_geotiff(path)` | saves it as a GeoTIFF, credit included, that any GIS puts in the right place | |

A cell with nothing measured in it — sea, a lake, a gap in a flight, the far
side of a state border — is `NaN`. Never zero, never a guess: use
`numpy.nanmax`, `nanmean` and friends. Heights are metres above
*Normalhöhennull*, the German sea level.

When nothing at all can be had — a portal down, a point outside the state you
named — the call raises `gk.Unavailable` with the reason and what to run to
check. A misspelt state or swapped coordinates raise `ValueError` before
anything is fetched.

Tiles are kept in `~/.cache/geokachel` (at most 2 GB; set `GEOKACHEL_CACHE` to
put them elsewhere), so a second call nearby costs nothing.

## Examples

```python
import numpy as np
import geokachel as gk

# How tall is Cologne Cathedral?
tall = gk.object_heights(50.9413, 6.9583, state="NW")
print(f"{np.nanmax(tall.values):.0f} m")           # 156 m (its towers are 157 m)
print(tall.attribution)                            # © Geobasis NRW

# Slope, in degrees: how much of a square is steeper than 10°
w = gk.ground(50.9757, 11.0233, state="TH")        # Erfurt, the Domberg
dy, dx = np.gradient(w.values, w.cell_m)
slope = np.degrees(np.arctan(np.hypot(dx, dy)))
print(f"{np.nanmean(slope > 10):.0%}")             # 16% (walls count: the steepest cell is 84°)

# How much of a 500 m square stands more than 20 m tall
w = gk.object_heights(53.5503, 9.9920, state="HH", size_m=500)   # Hamburg, the Rathaus
print(f"{np.mean(w.values > 20):.0%}")

# A map for QGIS: drag the file in, it lands in the right place
gk.surface(52.5163, 13.3777, state="BE", size_m=1000).write_geotiff("tiergarten.tif")
```

With matplotlib, the square and its credit:

```python
import matplotlib.pyplot as plt

w = gk.surface(51.0519, 13.7416, state="SN")        # Dresden, the Frauenkirche
plt.imshow(w.values, cmap="terrain", extent=(w.west, w.east, w.south, w.north))
plt.colorbar(label=f"metres above {w.heights_above}")
plt.figtext(0.01, 0.01, w.attribution, fontsize=7)
plt.show()
```

## From the command line

No Python needed:

```bash
geokachel states                                        # every state: its key, zone and data
geokachel ground 48.1374 11.5755 --state BY             # the height there, and whose it is
geokachel surface 48.1374 11.5755 --state BY --out marienplatz.tif
geokachel objects 50.9413 6.9583 --state NW --size 500  # how tall things are
```

```text
$ geokachel ground 48.1374 11.5755 --state BY --out marienplatz.tif
ground at 48.13740, 11.57550: 515.80 m above sea level
  lowest 511.40, highest 517.46 m above sea level
  201 x 201 cells of 1 m, 100% surveyed, UTM zone 32 (EPSG:25832), from by-dgm1
  credit (required): Datenquelle: Bayerische Vermessungsverwaltung – www.geodaten.bayern.de [CC-BY-4.0]
  saved marienplatz.tif
```

## All sixteen states

Generated from the registry (`geokachel states --markdown`), so it cannot drift
from the code. *Service* means the state answers for exactly the square asked
for; *tiles* means it publishes the country as files of one or two square
kilometres, which are fetched whole and kept.

<!-- states:start -->
| Key | Bundesland | UTM zone | Ground | Surface | Licence |
|---|---|---|---|---|---|
| BB | Brandenburg | 33 | 1 m service | 1 m service | dl-de/by-2-0 |
| BE | Berlin | 33 | 1 m service | 1 m service | dl-de/by-2-0 |
| BW | Baden-Württemberg | 32 | 1 m service | 1 m tiles, above ground | dl-de/by-2-0 |
| BY | Bayern | 32 | 1 m tiles | 0.2 m tiles | CC-BY-4.0 |
| HB | Bremen | 32 | 1 m tiles | 1 m tiles | CC-BY-4.0 |
| HE | Hessen | 32 | 1 m service | 1 m service | dl-de/zero-2-0 |
| HH | Hamburg | 32 | 1 m tiles | 1 m tiles | dl-de/by-2-0 |
| MV | Mecklenburg-Vorpommern | 33 | 1 m service | 1 m service, above ground | keine Bedingungen, Quellenvermerk verpflichtend |
| NI | Niedersachsen | 32 | 1 m service | 1 m service | CC-BY-4.0 |
| NW | Nordrhein-Westfalen | 32 | 1 m service | 0.5 m service, above ground | dl-de/zero-2-0 |
| RP | Rheinland-Pfalz | 32 | 1 m tiles | 1 m tiles | dl-de/by-2-0 |
| SH | Schleswig-Holstein | 32 | 1 m tiles | — | CC-BY-4.0 |
| SL | Saarland | 32 | 1 m tiles | 1 m tiles | dl-de/by-2-0 |
| SN | Sachsen | 33 | 1 m tiles | 1 m tiles | dl-de/by-2-0 |
| ST | Sachsen-Anhalt | 32 | 1 m service | 1 m service | dl-de/by-2-0 |
| TH | Thüringen | 32 | 1 m tiles | 1 m tiles | dl-de/by-2-0 |
<!-- states:end -->

Each state was asked through `ground()`, `surface()` and `object_heights()` at
a landmark of its own on 2026-09-21, and answered.

## UTM, and the numbers in a tile's name

You only need this for the lower-level functions; `ground()` and friends take
latitude and longitude and do the rest.

**UTM** (Universal Transverse Mercator) cuts the Earth into sixty strips, six
degrees of longitude wide, and flattens each onto its own grid **in metres**.
Germany lies in **zone 32** (6°–12° E) and **zone 33** (12°–18° E), and every
surveying office publishes in one of them — as *ETRS89 / UTM*, EPSG:25832 and
EPSG:25833.

A position is then two numbers:

- the **easting** — metres east of a line 500 km west of the zone's centre
  (9° E for zone 32);
- the **northing** — metres north of the equator.

Munich's Marienplatz is easting **691,603**, northing **5,334,780** in zone 32.
A tile is named after its south-west corner **in kilometres**, so the square
kilometre that holds Marienplatz is tile `691_5334`: 691 km east, 5,334 km
north of the equator. (5334 is not a postcode — Munich's run from 80331 to
81929. It is how far Munich is from the equator.)

```python
gk.to_utm(48.1374, 11.5755, 32)          # (691603.0…, 5334780.0…)
gk.to_latlon(691603.0, 5334780.0, 32)    # (48.1374…, 11.5755…)
```

**Which zone? The state decides, not the longitude.** Bayern numbers all of
itself in zone 32, although its east is past 12° E; Berlin, Brandenburg,
Mecklenburg-Vorpommern and Sachsen use zone 33 throughout. Munich in the wrong
zone is 245 km east and 5,337 km north — a tile that does not exist. The table
above gives each state's zone, and `ground()` uses it for you.

## Going lower: the tiles themselves

Underneath the front door is a registry of every source: its address scheme,
its format, its licence, and when it last answered. If you want a state's
files as they come — to keep, to feed another program, or for the products the
front door does not open (3D buildings as CityGML, laser point clouds as LAZ) —
this is the way in.

```python
from geokachel import ground_tiles_for, net, read_raster, to_utm

source = ground_tiles_for("BY")               # Bayern's 1 m ground, as tiles
east, north = to_utm(48.1374, 11.5755, 32)    # the zone from the table above
corner = source.corner_of(east, north)         # (691, 5334): the tile's south-west corner, in km
url = source.url_for(*corner)
# https://download1.bayernwolke.de/a/dgm/dgm1/691_5334.tif (paste it into a browser to download it)
raster = read_raster(net.get_bytes(url))       # 1000 × 1000 cells of one metre, NaN where unsurveyed
```

`url_for` only works where a tile's address is **computed** from its two
numbers, which is most states. Some are **listed** (Rheinland-Pfalz and
Schleswig-Holstein put the survey year in the name, so their own index is read
once) and some are **archived** (Hamburg, Bremen and Saarland publish whole
regions as one archive, and a tile is read out of it with HTTP range requests —
0.38 % of a 559 MB file, measured). `rasters()` handles all three:

```python
from geokachel import default_cache, ground_tiles_for, net, rasters

source = ground_tiles_for("RP")                # listed: url_for would refuse
tiles = rasters(source, [(447, 5538)], default_cache(), net.get_bytes)
tiles[(447, 5538)].values                      # Mainz, 1000 × 1000
```

Where a state publishes its ground as a coverage service rather than as tiles —
Nordrhein-Westfalen, Niedersachsen, Hessen and five others — `ground_tiles_for`
is `None`: `TERRAIN_SOURCES` and `SURFACE_SOURCES` describe the services, and
`ground()` asks them for you. `laser_tiles_for()` and `lod2_tiles_for()` give
the point clouds and the 3D buildings; `geokachel sources` lists everything.

## Accuracy, age and limits

- **About ±10–30 cm** in height on open ground, worse on steep slopes and under
  dense forest.
- **A survey is a snapshot.** Each state flies its country every few years, and
  a tile may be from any year since about 2010. A surface model shows the trees
  and houses of its flight: a house built since is missing, a tree has grown.
- **Baden-Württemberg's ground** comes from its coverage service in whole
  metres, one column short and stretched to fill the square. It is put back
  onto square one-metre cells, which moves no height by more than half a metre.
- **Schleswig-Holstein** publishes no surface model, so `surface()` and
  `object_heights()` raise `Unavailable` there. Its ground works.
- **A square is at most 2 km a side**, and 25 million cells (a kilometre of
  Bayern's 20 cm surface). For more, loop over squares.
- **Speed**: a service answers in about a second. Tiles are fetched whole
  (1–40 MB) the first time — a few seconds to half a minute — and read from
  the cache after that. Bayern's 20 cm surface takes about 15 seconds to decode.
- **Buildings (CityGML) and point clouds (LAZ)** are in the registry with their
  addresses, but not read by this package; use `lxml` or `laspy` on the files.

## Checking that it is all still there

States move their files. In the two days this registry was built, four of them
changed underneath it — one moved host, one still lists tiles that 404, one
carries dead share tokens, and one answers a stale row with **HTTP 200 and an
HTML apology**. So:

```bash
geokachel check              # every source, a few kB each, about two minutes
geokachel check sn- nw-      # only these
geokachel check --quiet      # only what is wrong; exit code 1 if anything is
```

A source passes only when the bytes are what it claims — a TIFF header, a
point-cloud signature, a CityGML root, numbers in a text grid, an archive that
still holds the square kilometre it held before. It is a command with an exit
code, for a weekly job, and deliberately not a test suite that goes red
whenever a state portal has a maintenance window.

## The credit, and being polite

**The credit is a licence obligation, not a caption.** `dl-de/by-2-0` and
`CC BY 4.0` require the publisher's named credit wherever the data, or anything
made from it, is shown. Every source carries it word for word, a window carries
it as `attribution`, a GeoTIFF carries it inside, and `geokachel credits BY NW`
prints it. Sources whose licence forbids this use are not in the registry at
all. See [NOTICE](https://github.com/JanderHungrige/geokachel/blob/main/NOTICE).

**These are public offices publishing at their own expense.** Each request
waits half a second after the last, answers are capped in size, and tiles are
cached. Before fetching anything in quantity, set `geokachel.net.USER_AGENT`
(or the `GEOKACHEL_USER_AGENT` environment variable) to something with your
own contact in it. Every function that fetches also takes a `get=` callable,
if you would rather fetch yourself.

**A gap is a gap.** No state borrows its neighbour's ground, and nothing
unsurveyed is filled in: it is `NaN`, and `w.surveyed` says how much of the
square that is.

## Installing

Python 3.11 or newer. Depends on `numpy`, `defusedxml` and `requests` only — no
GDAL, rasterio or pyproj: the GeoTIFF reader and writer and the UTM projection
are part of the package.

## Licence

MIT for the software — see [LICENSE](https://github.com/JanderHungrige/geokachel/blob/main/LICENSE)
and the [changelog](https://github.com/JanderHungrige/geokachel/blob/main/CHANGELOG.md).
The *data* is its publishers', under their own terms: read
[NOTICE](https://github.com/JanderHungrige/geokachel/blob/main/NOTICE) before
publishing anything made from it.

Not affiliated with any Landesvermessungsamt, the AdV, the BKG, ESA or
Copernicus; their names appear only inside the credits their licences require.
