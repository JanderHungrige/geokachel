"""The command line, for someone who wants a number or a file and not Python."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from geokachel import cli, cli_heights
from geokachel.assemble import Unavailable
from geokachel.geotiff import georeference
from geokachel.window import SEA, Window

WINDOW = Window(np.array([[519.25, 520.0], [np.nan, 518.5]], dtype="float32"),
                691600.0, 5334800.0, 100.0, 25832, "by-dgm1", "CC-BY-4.0",
                "Datenquelle: Bayerische Vermessungsverwaltung – www.geodaten.bayern.de", SEA)
#: The centre of that window's north-west cell.
LAT, LON = WINDOW.latlon_of(0, 0)


def _run(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", ["geokachel", *args])
    return cli.main()


def _answering(window: Window | Exception) -> tuple[object, str]:
    def fetch(*_a: object, **_k: object) -> Window:
        if isinstance(window, Exception):
            raise window
        return window
    return fetch, "the ground"


def test_every_state_has_a_row_and_one_has_no_surface() -> None:
    rows = cli_heights.state_rows()

    assert len(rows) == 16
    assert [row[0] for row in rows if row[4] == "—"] == ["SH"]
    assert ("BY", "Bayern", "32", "1 m tiles", "0.2 m tiles", "CC-BY-4.0") in rows


def test_the_height_comes_with_its_credit(monkeypatch: pytest.MonkeyPatch,
                                          capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setitem(cli_heights.JOBS, "ground", _answering(WINDOW))

    assert _run(monkeypatch, "ground", str(LAT), str(LON), "--state", "BY") == 0

    said = capsys.readouterr().out
    assert "519.25 m above sea level" in said
    assert "75% surveyed" in said and "EPSG:25832" in said
    assert "credit (required): Datenquelle: Bayerische Vermessungsverwaltung" in said


def test_out_writes_a_geotiff_a_gis_can_place(monkeypatch: pytest.MonkeyPatch,
                                              tmp_path: Path,
                                              capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setitem(cli_heights.JOBS, "ground", _answering(WINDOW))
    target = tmp_path / "marienplatz.tif"

    assert _run(monkeypatch, "ground", str(LAT), str(LON), "--state", "BY",
                "--out", str(target)) == 0

    placed = georeference(target.read_bytes())
    assert placed is not None and (placed.west, placed.north) == (691600.0, 5334800.0)
    assert f"saved {target}" in capsys.readouterr().out


@pytest.mark.parametrize("trouble", [Unavailable("by-dgm1: no heights"),
                                     ValueError("'Bavaria' is not a Bundesland")])
def test_trouble_is_one_line_and_a_failing_exit(monkeypatch: pytest.MonkeyPatch,
                                                capsys: pytest.CaptureFixture[str],
                                                trouble: Exception) -> None:
    monkeypatch.setitem(cli_heights.JOBS, "ground", _answering(trouble))

    assert _run(monkeypatch, "ground", str(LAT), str(LON), "--state", "BY") == 1

    assert capsys.readouterr().err.strip() == f"geokachel ground: {trouble}"


def test_credits_for_a_state_without_tiles_come_from_its_services(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Sachsen-Anhalt publishes no tile at all, and used to have no credit."""
    assert _run(monkeypatch, "credits", "ST") == 0

    assert capsys.readouterr().out.strip() == (
        "© GeoBasis-DE / LVermGeo LSA, dl-de/by-2-0  [dl-de/by-2-0]")


def test_credits_for_nothing_known_fail(monkeypatch: pytest.MonkeyPatch,
                                        capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(monkeypatch, "credits", "XX") == 1
    assert "no source matched" in capsys.readouterr().err
