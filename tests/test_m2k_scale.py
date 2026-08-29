"""The M2K's arithmetic, tested with no GNU Radio in sight.

These are the numbers every instrument block depends on, so they live in
a module that imports nothing and can be checked anywhere.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gr-m2k"))

from m2k_blocks import m2k_scale as scale


def test_volts_per_count_matches_libm2k():
    """0.78 / (2048 * 1.3 * range_gain), from getScalingFactor()."""
    assert scale.volts_per_count("low") == pytest.approx(0.014525, abs=1e-6)
    assert scale.volts_per_count("high") == pytest.approx(0.001380, abs=1e-6)


def test_the_wide_range_gives_more_volts_per_count():
    """A sanity check that survives the numbers being wrong.

    Whatever the exact figures, the +/-25 V range must be the coarser one.
    'low' naming the WIDE range is the confusing part.
    """
    assert scale.volts_per_count("low") > scale.volts_per_count("high")


def test_full_scale_is_about_the_named_range():
    """2048 counts times volts-per-count should land near the label."""
    for name, nominal in scale.RANGE_VOLTS.items():
        full = 2048 * scale.volts_per_count(name)
        assert nominal <= full <= nominal * 1.25, (name, full)


def test_unknown_range_is_refused_with_the_options():
    with pytest.raises(ValueError) as excinfo:
        scale.volts_per_count("wide")
    assert "high" in str(excinfo.value) and "low" in str(excinfo.value)


def test_sample_rates_are_the_ones_hardware_publishes():
    """Taken from sampling_frequency_available on a real m2k-adc.

    Computing them as 100 MS/s / oversampling_ratio instead produced a
    list that wrongly excluded 1 kS/s.
    """
    import json
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "fixtures", "m2k-real.json")) as handle:
        capture = json.load(handle)
    adc = [d for d in capture["devices"] if d["name"] == "m2k-adc"][0]
    published = [a for a in adc["device_attrs"]
                 if a["name"] == "sampling_frequency"][0]["available"]["values"]
    assert sorted(int(v) for v in published) == sorted(scale.SAMPLE_RATES)


def test_a_rate_the_board_will_not_take_is_refused():
    with pytest.raises(ValueError) as excinfo:
        scale.check_sample_rate(500000)
    assert "1000000" in str(excinfo.value)      # the error lists the options


def test_trigger_level_round_trips_through_counts():
    for volts in (0.0, 0.5, -1.25, 12.0):
        counts = scale.volts_to_raw(volts, "low")
        assert scale.raw_to_volts(counts, "low") == pytest.approx(
            volts, abs=scale.volts_per_count("low"))


def test_the_same_level_is_more_counts_on_the_sensitive_range():
    assert (scale.volts_to_raw(1.0, "high") >
            scale.volts_to_raw(1.0, "low"))


def test_divider_is_explanatory_only_but_correct():
    assert scale.divider_for(100000000) == 1
    assert scale.divider_for(1000000) == 100
    assert scale.divider_for(1000) == 100000
