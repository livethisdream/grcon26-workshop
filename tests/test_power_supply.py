"""The rails: the arithmetic, the write policy, and the block's face.

None of this needs GNU Radio, libiio or a board. The conversion is in
m2k_scale, the rate limiting is in rate_limit, and the block itself is
read as text rather than imported -- it imports gnuradio, which the
interpreter running these tests usually does not have.
"""

import ast
import importlib.util
import os
import sys

import pytest

GR_M2K = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gr-m2k")
sys.path.insert(0, GR_M2K)

from m2k_blocks import m2k_scale as scale
from m2k_blocks.rate_limit import rate_limiter

needs_yaml = pytest.mark.skipif(
    importlib.util.find_spec("yaml") is None,
    reason="no PyYAML in the interpreter running the tests")


# ------------------------------------------------------------ the arithmetic

def test_counts_per_volt_is_libm2k_s_write_coefficient():
    """4095 / (rail_gain * 1.2), from M2kPowerSupplyImpl's constructor."""
    assert scale.supply_counts_per_volt("positive") == pytest.approx(
        4095.0 / (5.02 * 1.2))
    assert scale.supply_counts_per_volt("negative") == pytest.approx(
        4095.0 / (-5.1 * 1.2))


def test_the_dac_behind_the_rail_is_a_1v2_part():
    """0.29296875 mV per count -- which the board publishes as `scale`.

    The same figure calibration converts at. A 1.2 V converter setting a
    5 V rail only works because of the amplifier after it, and that
    amplifier is the whole of the difference between the two numbers.
    """
    assert scale.SUPPLY_DAC_MV_PER_COUNT == pytest.approx(0.29296875)
    at_the_dac = 3399 * scale.SUPPLY_DAC_MV_PER_COUNT / 1000.0
    assert at_the_dac == pytest.approx(0.9958, abs=1e-4)
    assert at_the_dac * scale.SUPPLY_RAIL_GAIN["positive"] == pytest.approx(
        5.0, abs=0.01)


def test_five_volts_uncorrected_and_corrected():
    """The corrections are this board's, from fixtures/m2k-real.json."""
    assert scale.volts_to_supply_raw(5.0, "positive") == 3399
    assert scale.volts_to_supply_raw(
        5.0, "positive", 0.9986241178820292, 0.0031000000000000055) == 3396

    assert scale.volts_to_supply_raw(-5.0, "negative") == 3346
    assert scale.volts_to_supply_raw(
        -5.0, "negative", 0.9998222538215429, 0.01659999999999999) == 3334


def test_the_negative_rail_is_driven_by_a_positive_count():
    """Its amplifier has the sign in it, so the DAC never goes negative."""
    for volts in (0.0, -1.0, -2.5, -5.0):
        raw = scale.volts_to_supply_raw(volts, "negative")
        assert 0 <= raw <= scale.SUPPLY_MAX_RAW


def test_a_correction_can_push_zero_below_the_floor_and_it_clamps():
    """Regression: a negative count in a 12-bit register is full scale.

    V- at 0 V with this board's +16.6 mV offset correction wants about
    -11 counts. Clamped, not wrapped, exactly as libm2k does.
    """
    raw = scale.volts_to_supply_raw(0.0, "negative", 0.9998222538215429,
                                    0.01659999999999999)
    assert raw == 0


def test_the_top_of_the_range_clamps_too():
    huge = scale.volts_to_supply_raw(5.0, "positive", gain=2.0)
    assert huge == scale.SUPPLY_MAX_RAW


def test_past_five_volts_is_refused():
    with pytest.raises(ValueError) as caught:
        scale.volts_to_supply_raw(5.5, "positive")
    assert "5" in str(caught.value)


@pytest.mark.parametrize("volts,rail", [(-1.0, "positive"), (1.0, "negative")])
def test_the_wrong_sign_is_refused_and_says_where_it_belongs(volts, rail):
    """The failure this replaces is silent: the count clamps at zero, the
    rail sits at 0 V, and every attribute reads back as written."""
    with pytest.raises(ValueError) as caught:
        scale.check_supply_volts(volts, rail)
    assert ("V-" if rail == "positive" else "V+") in str(caught.value)


def test_zero_is_legal_on_both_rails():
    assert scale.check_supply_volts(0.0, "positive") == 0.0
    assert scale.check_supply_volts(0.0, "negative") == 0.0


def test_an_unknown_rail_is_refused():
    with pytest.raises(ValueError):
        scale.supply_counts_per_volt("ground")


@pytest.mark.parametrize("rail,volts",
                         [("positive", 3.3), ("positive", 1.8),
                          ("negative", -3.3), ("negative", -1.8)])
def test_round_trip_within_half_a_count(rail, volts):
    raw = scale.volts_to_supply_raw(volts, rail)
    back = scale.supply_raw_to_volts(raw, rail)
    per_count = abs(1.0 / scale.supply_counts_per_volt(rail))
    assert back == pytest.approx(volts, abs=per_count / 2)


def test_the_board_publishes_the_dac_scale_we_assume(real_snapshot):
    """Our 1.2 V full scale against what the hardware says it is."""
    device = [d for d in real_snapshot["devices"] if d["name"] == "ad5627"][0]
    channel = [c for c in device["channels"]
               if c["id"] == "voltage0" and c["output"]][0]
    published = float(
        [a for a in channel["attrs"] if a["name"] == "scale"][0]["value"])
    assert published == pytest.approx(scale.SUPPLY_DAC_MV_PER_COUNT)


def test_the_board_carries_the_corrections_the_block_reads(real_snapshot):
    names = {a["name"] for a in real_snapshot["context_attrs"]}
    for rail in ("pos", "neg"):
        assert "cal,gain_%s_dac" % rail in names
        assert "cal,offset_%s_dac" % rail in names


# --------------------------------------------------------- the write policy

class FakeClock(object):
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeTimer(object):
    """Records what was armed. The test decides when it fires."""

    def __init__(self):
        self.armed = []

    def __call__(self, delay, function):
        self.armed.append([delay, function, False])
        return self

    def cancel(self):
        if self.armed:
            self.armed[-1][2] = True

    def fire(self):
        delay, function, cancelled = self.armed.pop()
        assert not cancelled
        return function()


def limiter(interval=1.0):
    applied, clock, timer = [], FakeClock(), FakeTimer()
    limited = rate_limiter(applied.append, interval, clock=clock, timer=timer)
    return limited, applied, clock, timer


def test_the_first_value_goes_straight_out():
    limited, applied, _, timer = limiter()
    limited.submit(5.0)
    assert applied == [5.0]
    assert timer.armed == []


def test_a_value_too_soon_is_held_not_dropped():
    limited, applied, clock, timer = limiter()
    limited.submit(5.0)
    clock.now += 0.2
    limited.submit(4.0)
    assert applied == [5.0]

    clock.now += 0.8
    timer.fire()
    assert applied == [5.0, 4.0]


def test_only_the_last_held_value_survives():
    """A slider drag, which is the whole reason for this."""
    limited, applied, clock, timer = limiter()
    limited.submit(5.0)
    for value in (4.0, 3.0, 2.0, 1.0):
        clock.now += 0.05
        limited.submit(value)
    assert applied == [5.0]
    assert len(timer.armed) == 1, "one timer for the whole drag"

    clock.now += 1.0
    timer.fire()
    assert applied == [5.0, 1.0], "where the hand stopped, not where it passed"


def test_the_timer_waits_out_the_remainder_not_the_whole_interval():
    limited, _, clock, timer = limiter()
    limited.submit(5.0)
    clock.now += 0.3
    limited.submit(4.0)
    assert timer.armed[0][0] == pytest.approx(0.7)


def test_after_the_interval_a_value_goes_straight_out_again():
    limited, applied, clock, timer = limiter()
    limited.submit(5.0)
    clock.now += 1.5
    limited.submit(4.0)
    assert applied == [5.0, 4.0]
    assert timer.armed == []


def test_a_value_arriving_before_the_timer_cancels_it():
    limited, applied, clock, timer = limiter()
    limited.submit(5.0)
    clock.now += 0.2
    limited.submit(4.0)
    clock.now += 1.0
    limited.submit(3.0)
    assert applied == [5.0, 3.0]
    assert timer.armed[-1][2] is True, "the pending timer was cancelled"


def test_flush_with_nothing_held_does_nothing():
    limited, applied, _, _ = limiter()
    limited.flush()
    assert applied == []


def test_cancel_drops_what_is_held():
    limited, applied, clock, timer = limiter()
    limited.submit(5.0)
    clock.now += 0.2
    limited.submit(4.0)
    limited.cancel()
    limited.flush()
    assert applied == [5.0]


def test_no_interval_means_no_limiting():
    limited, applied, _, timer = limiter(interval=0)
    for value in (5.0, 4.0, 3.0):
        limited.submit(value)
    assert applied == [5.0, 4.0, 3.0]
    assert timer.armed == []


# ------------------------------------------------------------- the GRC block

BLOCK_YML = os.path.join(GR_M2K, "grc", "m2k_power_supply.block.yml")


def block_source():
    with open(os.path.join(GR_M2K, "m2k_blocks", "power_supply.py")) as handle:
        return ast.parse(handle.read())


def constructor_arguments():
    for node in ast.walk(block_source()):
        if isinstance(node, ast.FunctionDef) and node.name == "__init__":
            return [arg.arg for arg in node.args.args if arg.arg != "self"]
    raise AssertionError("power_supply has no __init__")


@needs_yaml
def test_every_grc_parameter_is_a_constructor_argument():
    """A typo here is a TypeError at run time and nothing sooner."""
    import yaml
    with open(BLOCK_YML) as handle:
        block = yaml.safe_load(handle)
    declared = [p["id"] for p in block["parameters"]]
    assert declared == constructor_arguments()


@needs_yaml
def test_the_block_has_no_ports():
    """A rail is not a stream. If this grows ports, something is wrong."""
    import yaml
    with open(BLOCK_YML) as handle:
        block = yaml.safe_load(handle)
    assert not block.get("inputs")
    assert not block.get("outputs")


@needs_yaml
def test_the_setpoint_and_the_rail_are_callbacks():
    """Without these the slider moves and the board does not."""
    import yaml
    with open(BLOCK_YML) as handle:
        block = yaml.safe_load(handle)
    callbacks = block["templates"]["callbacks"]
    assert any(call.startswith("set_voltage(") for call in callbacks)
    assert any(call.startswith("set_enabled(") for call in callbacks)


@needs_yaml
def test_option_labels_survived_yaml():
    """YAML 1.1 reads On/Off/Yes/No as booleans, silently."""
    import yaml
    with open(BLOCK_YML) as handle:
        block = yaml.safe_load(handle)
    for parameter in block["parameters"]:
        for label in parameter.get("option_labels", []):
            assert isinstance(label, str), (parameter["id"], label)


def test_the_block_writes_the_setpoint_before_it_powers_anything_up():
    """Order, pinned. `raw` is 2048 from reset -- about +3 V at the rail.

    Read off the source rather than run, because running it needs GNU
    Radio and a board. The order is the thing that has to be right.
    """
    source = block_source()
    init = [n for n in ast.walk(source)
            if isinstance(n, ast.FunctionDef) and n.name == "__init__"][0]
    calls = [ast.unparse(node.value) for node in init.body
             if isinstance(node, ast.Expr)]
    write = [i for i, call in enumerate(calls) if "_write_voltage" in call]
    power = [i for i, call in enumerate(calls) if "set_enabled" in call]
    assert write and power, calls
    assert write[0] < power[0]
