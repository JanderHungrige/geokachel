"""The README is what PyPI shows a stranger, so parts of it are checked."""
from __future__ import annotations

import re
from pathlib import Path

from geokachel import cli_heights

README = (Path(__file__).parent.parent / "README.md").read_text()


def test_the_readme_table_is_the_one_the_code_generates() -> None:
    """`geokachel states --markdown` between the README's two markers: a new
    source or a changed licence fails here until the README says so too."""
    inside = README.split("<!-- states:start -->\n", 1)[1].split("\n<!-- states:end -->", 1)[0]

    assert inside == cli_heights.markdown_table()


def test_the_readme_links_work_on_pypi_too() -> None:
    """PyPI shows the README without the repository around it, so a relative
    link to NOTICE there is a 404 — the licence notice, of all things."""
    links = re.findall(r"\]\(([^)#][^)]*)\)", README)

    assert links and all(link.startswith("https://") for link in links), links
