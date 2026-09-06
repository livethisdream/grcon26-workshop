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
