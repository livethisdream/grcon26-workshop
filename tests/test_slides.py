"""The deck's structure, checked the way every other artifact here is.

`slides/check_deck.py` is the real check -- it is also runnable on its own,
because someone editing the deck should not have to know pytest exists. This
wires it into the suite so a frame that loses its title, or a present block
that grows past what a room can read, fails on the same run as everything
else.

What it cannot check is layout: whether a frame fits one screen in present
mode is a question for a browser, and the answer is in `slides/README.md`
under "Checking a change".
"""
import os
import subprocess
import sys

import pytest

SLIDES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "slides")
CHECK = os.path.join(SLIDES, "check_deck.py")


@pytest.fixture(scope="module")
def deck():
    with open(os.path.join(SLIDES, "index.html"), encoding="utf-8") as handle:
        return handle.read()


def test_the_deck_passes_its_own_structural_check():
    result = subprocess.run([sys.executable, CHECK], capture_output=True,
                            text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_check_is_runnable_on_its_own(repo_root):
    """It is documented as `./slides/check_deck.py`, so it has to be that."""
    assert os.access(CHECK, os.X_OK)
    with open(CHECK, encoding="utf-8") as handle:
        assert handle.readline().startswith("#!")


def test_every_asset_the_deck_asks_for_is_checked_in(deck):
    """A missing stylesheet is a deck that renders as a wall of text and
    still scrolls, which is the kind of failure a rehearsal does not catch."""
    import re
    refs = re.findall(r'(?:href|src)="(assets/[^"]+)"', deck)
    assert refs, "the deck loads no local assets -- did the markup change?"
    for ref in sorted(set(refs)):
        assert os.path.exists(os.path.join(SLIDES, ref)), ref


def test_every_grc_figure_the_deck_uses_is_one_render_grc_produces(deck):
    """A picture of a flowgraph drifts; a render of one cannot.

    The point of `render_grc.py` is that re-running it reproduces every
    figure in the deck. An `<img>` pointing at a file the script does not
    know how to make is a hand-placed screenshot that will quietly go stale,
    so it fails here rather than at the next parameter change.

    Read out of the source with `ast` rather than by importing: the script
    needs PyGObject, and this suite runs in a venv that cannot see it.
    """
    import ast
    import re

    with open(os.path.join(SLIDES, "render_grc.py"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    figures = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "FIGURES" for t in node.targets):
            figures = ast.literal_eval(node.value)
    assert figures, "render_grc.py has no FIGURES manifest any more"

    produced = {stem + ".png"
                for flowgraph in figures.values() for stem in flowgraph}
    used = {os.path.basename(src)
            for src in re.findall(r'<img[^>]+src="img/([^"]+)"', deck)}
    assert used, "the deck references no rendered figures"
    assert used <= produced, (
        "the deck uses figures render_grc.py does not produce: "
        f"{sorted(used - produced)}")


def test_no_rendered_figure_is_dead_weight():
    """Every committed image is one the deck actually shows."""
    import re
    with open(os.path.join(SLIDES, "index.html"), encoding="utf-8") as fh:
        used = set(re.findall(r'<img[^>]+src="img/([^"]+)"', fh.read()))
    on_disk = {f for f in os.listdir(os.path.join(SLIDES, "img"))
               if not f.startswith(".")}
    assert on_disk - used == set(), \
        f"committed but never shown: {sorted(on_disk - used)}"


def test_nothing_is_loaded_from_a_third_party_at_run_time(deck):
    """A conference room's network is not a dependency.

    One exception, and it is deliberate: the Google Fonts stylesheet. Every
    rule that uses it names a full fallback stack, so the deck renders
    correctly with the request blocked -- which is how it was checked.
    """
    import re
    allowed = ("https://fonts.googleapis.com", "https://fonts.gstatic.com")
    # Only things the page FETCHES. An <a href> to the repository is a link
    # somebody may follow later, not a load-time dependency.
    remote = re.findall(
        r'<(?:link|script|img|iframe)\b[^>]*\b(?:href|src)="(https?://[^"]+)"',
        deck)
    for url in remote:
        assert url.startswith(allowed), url
    assert not re.search(r'<script[^>]+src="https?://', deck), \
        "no script may come off the network"
