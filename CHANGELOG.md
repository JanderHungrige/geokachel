# Changelog

## 0.2.1 — not yet released

### Fixed

- A regional archive (Saarland, Hamburg, Bremen) that did not answer once was
  remembered as empty, so its region stayed missing until the program
  restarted. Only answers are remembered now; an archive that failed is asked
  again after five minutes (`addressing.RETRY_AFTER_S`).

## 0.2.0 — 2026-09-21

A front door: a point and a Bundesland in, heights out, in every state.

### Added

- **`ground()`, `surface()` and `object_heights()`** take a latitude, a
  longitude and the state, and return a `Window` — heights around the point,
  placed, with the credit its licence requires. They work in all sixteen
  states (`surface` in fifteen: Schleswig-Holstein publishes none), whichever
  way the state publishes: a coverage service, computed tiles, tiles named in a
  list, tiles inside regional archives, zips, GeoTIFF or text, UTM zone 32 or 33.
  Each was asked live at a landmark of its own state on 2026-09-21.
- **`Window`**: the heights as a NumPy array, `height_at(lat, lon)`, `at()`,
  `latlon_of()`, `surveyed`, and `write_geotiff()`.
- **GeoTIFF writing** with the coordinate system, NaN as no-data and the credit
  in the file's Copyright tag, so QGIS or GDAL place it and show whose it is.
  `georeference()` reads where a GeoTIFF says it sits.
- **Command line:** `geokachel states`, `ground`, `surface` and `objects`,
  with `--out` for a GeoTIFF.
- `ground_route()` and `surface_route()` say where a state's data comes from;
  `default_cache()` keeps tiles in `~/.cache/geokachel` (2 GB, or
  `$GEOKACHEL_CACHE`).
- `state=` takes `"BY"`, `"Bayern"` or `"DE-BY"` — the last is what
  OpenStreetMap's geocoder answers with.
- `rasters()` takes `sized=` and `ranged=` like `addressed()`.

### Fixed

- A text-grid tile surveyed only in part was placed by where its data happened
  to start, not by its tile: Bremerhaven's surface came out 821–844 m too far
  west. Such tiles are now decoded into their own frame.
- One refused tile — a 404 is a `FetchError`, which is not an `OSError` —
  aborted `rasters()` for every other tile of the call, instead of leaving a
  hole as documented.
- `geokachel credits` only knew tile sources, so a state that publishes only
  services (Sachsen-Anhalt) had no credit to print.

### Changed

- `geokachel check` names a service the way a window names its source —
  `nw-dgm-wcs`, `nw-ndom-wcs` — instead of `terrain: Nordrhein-Westfalen`, so
  the command an error suggests checks exactly what failed.
- The README is rewritten around the new calls: what goes in and where to find
  it, what comes out, UTM, and all sixteen states.

### Measured

- Every GeoTIFF tile source's tiles sit exactly on their grid corners (one
  tile each, a zip's four members included).
- Baden-Württemberg's terrain service answers a box W metres wide with W − 1
  columns stretched to fill it, whatever the box. Its answers are put back onto
  square cells by nearest neighbour.

## 0.1.0 — 2026-09-20

First release: the registry of sixteen states' tiles and services, the three
kinds of tile address, the GeoTIFF, text-grid and zip readers, and
`geokachel check`.
