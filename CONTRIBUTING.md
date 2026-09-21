# Contributing

The most useful contribution is **a state that is missing, or a state that
moved** — and both follow one rule.

## An entry is a request that was answered

Never a portal page that says a thing exists. Before a source goes in the
registry, somebody has to have asked for a real tile and got real bytes back,
and the entry records which tile and how many bytes:

```python
TileSource(
    name="xx-dgm1", **terms("XX"), product=TileProduct.DGM1, tile_km=1,
    fmt="GeoTIFF",
    _url=lambda e, n: f"https://…/{e}_{n}.tif",
    _name=lambda e, n: f"{e}_{n}",
    vertical_step_m=0.01,
    probed_bytes=2_558_672,          # what came back
    probed_tile=(690, 5334),         # when asked for this square kilometre
)
```

`geokachel check xx-` then asks again, forever.

## A credit is a licence obligation

`attribution` is required and has no default, on purpose. Put the publisher's
**exact** wording in it, copied from their own terms page — not a tidied
version, not a translation. `dl-de/by-2-0` and `CC BY 4.0` both require the
named credit, and a height shown without it is a height used outside its
licence.

If a licence forbids this kind of use, or charges for it, the state gets **no
entry**, however a catalogue describes it. That judgement is made once here so
that nobody downstream has to make it.

## Three things that will surprise you

They surprised us, each measured rather than assumed:

- **A status code is not an answer.** One state's index lists tiles that 404;
  another answers a stale row with HTTP 200 and an HTML apology. `health.py`
  checks the bytes, not the status.
- **A tile is not always full.** Border tiles come short — 730,232 lines
  instead of a million — with holes inside a row, and several states emit no
  NoData marker at all: a cell nobody surveyed is simply an absent line. So
  values are placed by their own coordinates, never by counting.
- **Politeness is load-bearing.** Sixteen offices publish this at their own
  expense, with no quota and no contract. Keep the delay, keep the cap, and set
  `GEOKACHEL_USER_AGENT` to something with a contact in it.

## Open work

What does not work yet, or not well, with what is already known. Measured on
2026-09-21 unless it says otherwise. A finding is worth a pull request on its
own — a URL that answers, a licence page, a timing — even without the code.

### Baden-Württemberg's ground, in centimetres

`ground(..., state="BW")` asks LGL's INSPIRE coverage service
(`WCS_INSP_BW_Hoehe_Coverage_DGM1`, `EL.ElevationGridCoverage`). It answers in
**whole metres** (`vertical_step_m=1.0` in `terrain_sources.py`), and a box W
metres wide comes back as **W − 1 columns** stretched to fill it — for 200 and
201 m boxes, whole-metre and half-metre corners, either axis order and
`SCALEFACTOR=1`; `SCALESIZE` is refused. `assemble._squared` puts the answer
back onto square cells.

LGL publishes surface models as open tiles:
`https://opengeodata.lgl-bw.de/data/ndom1/ndom1_32_513_5404_2_bw.zip` (registered
as `bw-ndom1`) and `…/data/dom1/dom1_32_513_5404_2_bw.zip` (13 MB, not yet
registered) both answer. The same pattern for the ground,
`…/data/dgm1/dgm1_32_513_5404_2_bw.zip`, is a 404, and `/data/` refuses a
listing (403).

To do: find whether and where LGL publishes the DGM1 openly, and under which
licence. Then a `bw-dgm1` entry in `tile_entries.py` with its probed tile and
bytes, and `heights.ground_route` preferring tiles that are finer in height than
the state's service. Registering `bw-dom1` would give Baden-Württemberg a raw
surface model beside the normalised one.

### Schleswig-Holstein's surface

`surface_route("SH")` is `None`: the state's DGM1 (listed, as text grids) and
its LoD2 are open, and no open surface model was found when the registry was
built. To do: find one — tiles or a service — whose licence allows this use,
and add it with a probed request like every other entry.

### Bayern's 20 cm surface: decode only what a window needs

A `by-dom20` tile is a 51 MB GeoTIFF of 5000 × 5000 float32 cells, LZW without a
predictor, in **400 blocks of 256 × 256**. `tiff.read_raster` decodes all 400 —
about 17 seconds, on every call, cache or not — when a 200 m window (1000 × 1000
cells) touches at most 36 of them. `by-dgm1` is the same story at a smaller
scale: 500 strips of two rows each.

To do: let the reader take a pixel window and decode only the blocks or strips
that intersect it. `assemble.from_tiles` knows each tile's corner and the
window's edges, so it can pass that window down. `tiff.py` is already the
largest module; moving its strip and block assembly into a module of its own
first keeps it readable.

### Buildings and point clouds

`lod2_tiles_for()` answers in 13 states and `laser_tiles_for()` in 7: CityGML
and LAZ tiles that `addressed()` finds and `TileCache.file_for()` keeps on disk
(a laser tile can be 445 MB, so stream it from the file rather than holding the
bytes). Nothing in the package reads either yet.

To do: optional readers, behind an extra so that the core keeps its three
dependencies — each building's footprint, measured height and roof type from
LoD2 (`defusedxml` is already here), or a canopy or first-return surface from
LAZ with `laspy`.

### The GeoTIFF writer, against GDAL

`tests/test_geotiff.py` checks `write_geotiff` against the package's own reader,
and it was checked once by hand with `tifffile`. Nothing checks it against GDAL,
which is what QGIS and rasterio read with. To do: a CI job that installs
`rasterio` and asserts a written window's bounds, CRS (EPSG:25832 and 25833),
NaN no-data and Copyright tag, with `pytest.importorskip("rasterio")` so the
other jobs skip it.

### A source that moved

The weekly `sources` workflow asks every source and opens an issue when one
stops answering as its entry says. Mending it is the commonest contribution:
find the new address, ask it for a real tile, and record the answer — see
[An entry is a request that was answered](#an-entry-is-a-request-that-was-answered).

## Running it

```bash
pip install -e ".[dev]"
ruff check . && mypy geokachel && pytest -q
```

**No test may touch the network.** Archives, grids, indexes and malformed
headers are all built inside the tests. A suite that needs sixteen state
portals to be up fails on their maintenance window and teaches people to ignore
red. Whether the portals still serve what the registry claims is a separate,
weekly job that opens an issue instead of failing a build.

## Releasing

`pyproject.toml` version, then a tag:

```bash
git tag v0.2.0 && git push origin v0.2.0
```

Trusted Publishing does the rest — there is no token. A tag ending in `rc1`
goes to TestPyPI instead. A PyPI version can never be reused, even after
deletion, so the tag is the point of no return; CI refuses a tag that does not
match the version in `pyproject.toml`.

## Where this came from

Extracted from [NinaNatur](https://github.com/JanderHungrige/NinaNatur), a
garden-planning app that needed to know how much sun a flower bed gets. The
pre-extraction history, and the design notes behind most of these decisions,
are in that repository under `.mdd/docs/` — docs 102 to 110.
