"""Which DIO pins each digital block claims.

`pins_for` decides this, and getting it wrong is expensive: a source and
a sink that overlap fight over `direction`, and the loser reads or drives
nothing without saying so. These are the only tests that pin the mapping
down.

`m2k_blocks.digital` imports gnuradio, which is usually not the
interpreter running this suite, so the checks run in the same borrowed
Python that test_grc_integration finds.
"""

import json
import os

import pytest

from test_grc_integration import needs_gnuradio, run_in_gr

PRELUDE = '''
import json, sys
sys.path.insert(0, sys.argv[1])
from m2k_blocks.digital import pins_for, PIN_COUNT
'''


def pins(repo_root, expr):
    """Evaluate `expr` against pins_for in the gnuradio interpreter."""
    out = run_in_gr(PRELUDE + "print(json.dumps(%s))" % expr,
                    os.path.join(repo_root, "gr-m2k"))
    return json.loads(out)


def refused(repo_root, expr):
    """The ValueError message pins_for raises for `expr`, or None."""
    script = PRELUDE + '''
try:
    pins_for(%s)
except ValueError as exc:
    print(json.dumps(str(exc)))
else:
    print(json.dumps(None))
''' % expr
    return json.loads(run_in_gr(script, os.path.join(repo_root, "gr-m2k")))


@needs_gnuradio
def test_default_still_starts_at_dio0(repo_root):
    """The old one-argument behaviour is unchanged."""
    assert pins(repo_root, "pins_for(1)") == ["voltage0"]
    assert pins(repo_root, "pins_for(4)") == ["voltage%d" % i for i in range(4)]


@needs_gnuradio
def test_first_pin_offsets_the_range(repo_root):
    assert pins(repo_root, "pins_for(1, 1)") == ["voltage1"]
    assert pins(repo_root, "pins_for(2, 5)") == ["voltage5", "voltage6"]
    assert pins(repo_root, "pins_for(1, 15)") == ["voltage15"]


@needs_gnuradio
def test_a_sink_and_source_can_be_kept_apart(repo_root):
    """The whole reason first_pin exists: no shared pin, no fight."""
    sink = pins(repo_root, "pins_for(1, 0)")
    source = pins(repo_root, "pins_for(1, 1)")
    assert not set(sink) & set(source)


@needs_gnuradio
def test_the_full_span_still_fits(repo_root):
    assert len(pins(repo_root, "pins_for(16, 0)")) == 16


@needs_gnuradio
@pytest.mark.parametrize("expr,word", [
    ("0", "pin count"),
    ("17", "pin count"),
    ("1, -1", "first pin"),
    ("1, 16", "first pin"),
])
def test_out_of_range_is_refused(repo_root, expr, word):
    message = refused(repo_root, expr)
    assert message is not None, expr
    assert word in message, message


@needs_gnuradio
def test_a_range_running_off_the_end_is_refused(repo_root):
    """In range individually, impossible together."""
    message = refused(repo_root, "4, 14")
    assert message is not None
    assert "DIO14" in message and "2 pins" in message
