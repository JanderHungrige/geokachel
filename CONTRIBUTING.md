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
