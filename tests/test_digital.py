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


# --------------------------------------------------------------- config

# _apply_trigger and _apply_idle are the whole of what the trigger and the
# idle level do, and both are pure attribute writes. Running them against
# a stub that records the writes tests the real code without a board --
# which matters, because on a board a wrong attribute is silent.

CONFIG_PRELUDE = '''
import json, sys
sys.path.insert(0, sys.argv[1])
from m2k_blocks.digital import digital_source, digital_sink, pins_for


class Stub(object):
    """Everything _apply_* touches, without a hier block or a board."""

    def __init__(self, count, first=0):
        self.pins = pins_for(count, first)
        self.writes = []

    def _write(self, uri, device, channel, attr, value):
        self.writes.append([device, channel, attr, str(value)])

    _write_once = _write
'''


def writes(repo_root, body):
    """The attribute writes `body` makes, as [device, channel, attr, value]."""
    out = run_in_gr(CONFIG_PRELUDE + body + "\nprint(json.dumps(s.writes))",
                    os.path.join(repo_root, "gr-m2k"))
    return json.loads(out)


def rejected(repo_root, body):
    """The ValueError message `body` raises, or None."""
    script = CONFIG_PRELUDE + '''
try:
%s
except ValueError as exc:
    print(json.dumps(str(exc)))
else:
    print(json.dumps(None))
''' % "\n".join("    " + line for line in body.strip().splitlines())
    return json.loads(run_in_gr(script, os.path.join(repo_root, "gr-m2k")))


def attr(records, channel, name):
    """The last value written to one attribute, or None."""
    found = [value for _, chan, key, value in records
             if chan == channel and key == name]
    return found[-1] if found else None


@needs_gnuradio
def test_free_running_disarms_every_pin(repo_root):
    """'none' on all of them is the only way to say off."""
    records = writes(repo_root, '''
s = Stub(4)
digital_source._apply_trigger(s, "ip:none", "off", "edge-rising", 0)
''')
    for pin in ["voltage%d" % i for i in range(4)]:
        assert attr(records, pin, "trigger") == "none", pin


@needs_gnuradio
def test_arming_touches_one_pin_and_disarms_the_rest(repo_root):
    records = writes(repo_root, '''
s = Stub(4)
digital_source._apply_trigger(s, "ip:none", "2", "edge-falling", 0)
''')
    assert attr(records, "voltage2", "trigger") == "edge-falling"
    for pin in ["voltage0", "voltage1", "voltage3"]:
        assert attr(records, pin, "trigger") == "none", pin


@needs_gnuradio
def test_the_trigger_pin_is_absolute_not_an_offset(repo_root):
    """DIO9 means DIO9, whatever the block's range starts at."""
    records = writes(repo_root, '''
s = Stub(4, 8)
digital_source._apply_trigger(s, "ip:none", "9", "edge-rising", 0)
''')
    assert attr(records, "voltage9", "trigger") == "edge-rising"
    assert attr(records, "voltage8", "trigger") == "none"


@needs_gnuradio
@pytest.mark.parametrize("pin", ["off", "0"])
def test_leftover_board_state_is_always_overwritten(repo_root, pin):
    """A stale 'and', or a mux pointing elsewhere, silently eats the
    trigger. Both are rewritten whether we are arming or not."""
    records = writes(repo_root, '''
s = Stub(2)
digital_source._apply_trigger(s, "ip:none", "%s", "edge-rising", 7)
''' % pin)
    assert attr(records, "voltage0", "trigger_logic_mode") == "or"
    assert attr(records, "voltage0", "trigger_mux_out") == "trigger-logic"
    assert attr(records, "voltage0", "trigger_delay") == "7"


@needs_gnuradio
def test_a_trigger_pin_outside_the_range_is_refused(repo_root):
    """Otherwise it is a capture that never fires, which looks like a hang."""
    message = rejected(repo_root, '''
s = Stub(2, 4)
digital_source._apply_trigger(s, "ip:none", "9", "edge-rising", 0)
''')
    assert message is not None
    assert "DIO9" in message and "DIO4" in message and "DIO5" in message


@needs_gnuradio
def test_an_unknown_trigger_condition_is_refused(repo_root):
    message = rejected(repo_root, '''
s = Stub(2)
digital_source._apply_trigger(s, "ip:none", "0", "edge-sideways", 0)
''')
    assert message is not None
    assert "edge-sideways" in message


@needs_gnuradio
def test_the_condition_is_not_checked_when_free_running(repo_root):
    """Nothing reads it, so nothing should complain about it."""
    records = writes(repo_root, '''
s = Stub(1)
digital_source._apply_trigger(s, "ip:none", "off", "nonsense", 0)
''')
    assert attr(records, "voltage0", "trigger") == "none"


@needs_gnuradio
@pytest.mark.parametrize("level,raw", [("low", "0"), ("high", "1")])
def test_the_idle_level_sets_raw_on_every_pin(repo_root, level, raw):
    records = writes(repo_root, '''
s = Stub(3)
digital_sink._apply_idle(s, "ip:none", "%s")
''' % level)
    for pin in ["voltage0", "voltage1", "voltage2"]:
        assert attr(records, pin, "raw") == raw, pin


@needs_gnuradio
def test_leave_as_found_writes_nothing(repo_root):
    records = writes(repo_root, '''
s = Stub(3)
digital_sink._apply_idle(s, "ip:none", "leave")
''')
    assert records == []


@needs_gnuradio
def test_an_unknown_idle_level_is_refused(repo_root):
    message = rejected(repo_root, '''
s = Stub(1)
digital_sink._apply_idle(s, "ip:none", "floating")
''')
    assert message is not None
    assert "floating" in message


# -------------------------------------------------------------- packing

PACK_PRELUDE = '''
import json, sys
import numpy
sys.path.insert(0, sys.argv[1])
from m2k_blocks.digital import pack_word, pin_shift, _packed_sink

class FakeBuffer(object):
    """Records the words that would have reached the DMA."""

    def __init__(self):
        self.pushes = []
        self._pending = None

    def write(self, data):
        self._pending = bytes(data)
        return len(self._pending)

    def push(self):
        self.pushes.append(
            [int(w) for w in numpy.frombuffer(self._pending,
                                              dtype=numpy.uint16)])

def sink(pins, buffer_size, cyclic=False):
    """A packed sink wired to a fake buffer, so no board is involved."""
    s = _packed_sink("ip:none", pins, buffer_size, cyclic)
    s._buffer = FakeBuffer()
    s._staged = numpy.empty(0, dtype=numpy.uint16)
    s._pushed = False
    return s

def feed(s, streams):
    """One work() call. `streams` is a list of samples per port."""
    s.work([numpy.array(x, dtype=numpy.int16) for x in streams], [])
    return s._buffer.pushes
'''


def packed(repo_root, body):
    """Evaluate a packing snippet in the gnuradio interpreter."""
    out = run_in_gr(PACK_PRELUDE + body,
                    os.path.join(repo_root, "gr-m2k"))
    return json.loads(out)


@needs_gnuradio
def test_every_port_reaches_the_word(repo_root):
    """The regression test for the gr-iio bug this sink exists to avoid.

    device_sink let each channel overwrite the whole word, so only the
    last pin survived. All three bits must be present at once.
    """
    pushes = packed(repo_root, '''
s = sink(["voltage0", "voltage1", "voltage2"], 4)
print(json.dumps(feed(s, [[1, 0, 1, 0], [1, 1, 0, 0], [1, 0, 0, 1]])))
''')
    assert pushes == [[0b111, 0b010, 0b001, 0b100]]


@needs_gnuradio
def test_the_bit_position_is_the_pin_not_the_port(repo_root):
    """A sink starting at DIO4 puts its first port in bit 4."""
    pushes = packed(repo_root, '''
s = sink(["voltage4", "voltage5"], 2)
print(json.dumps(feed(s, [[1, 0], [0, 1]])))
''')
    assert pushes == [[1 << 4, 1 << 5]]


@needs_gnuradio
def test_pack_word_agrees_with_the_streaming_path(repo_root):
    """The scalar helper and the vectorised one must not drift apart."""
    same = packed(repo_root, '''
pins = ["voltage2", "voltage3", "voltage7"]
shifts = [pin_shift(p) for p in pins]
rows = [[1, 0, 1], [0, 0, 0], [1, 1, 1], [0, 1, 0]]
s = sink(pins, 4)
streamed = feed(s, [[r[i] for r in rows] for i in range(3)])[0]
print(json.dumps([pack_word(r, shifts) for r in rows] == streamed))
''')
    assert same is True


@needs_gnuradio
def test_any_nonzero_sample_is_a_one(repo_root):
    """Ports are one bit. A stream of counts must not truncate to zero."""
    pushes = packed(repo_root, '''
s = sink(["voltage0"], 3)
print(json.dumps(feed(s, [[2, 7, -1]])))
''')
    assert pushes == [[1, 1, 1]]


@needs_gnuradio
def test_a_partial_buffer_is_held_until_it_fills(repo_root):
    """The DMA takes whole buffers only."""
    pushes = packed(repo_root, '''
s = sink(["voltage0"], 4)
first = list(feed(s, [[1, 1]]))
second = feed(s, [[0, 0]])
print(json.dumps([first, second]))
''')
    assert pushes == [[], [[1, 1, 0, 0]]]


@needs_gnuradio
def test_a_cyclic_buffer_is_pushed_exactly_once(repo_root):
    """Later pushes return -EBUSY, so we stop rather than provoke them."""
    pushes = packed(repo_root, '''
s = sink(["voltage0"], 2, cyclic=True)
feed(s, [[1, 0]])
print(json.dumps(feed(s, [[1, 1, 0, 0]])))
''')
    assert pushes == [[1, 0]]


@needs_gnuradio
def test_a_plain_buffer_is_pushed_every_time_it_fills(repo_root):
    pushes = packed(repo_root, '''
s = sink(["voltage0"], 2)
print(json.dumps(feed(s, [[1, 0, 0, 1, 1, 1]])))
''')
    assert pushes == [[1, 0], [0, 1], [1, 1]]
