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
    """0.78 / (2048 * 1.3 * range_gain), from getScalingFactor().

    At 100 MS/s, where the decimation filter is not in the way and its
    correction is exactly 1.0, so this is the bare formula.
    """
    top = 100000000
    assert scale.volts_per_count("low", top) == pytest.approx(0.014525,
                                                              abs=1e-6)
    assert scale.volts_per_count("high", top) == pytest.approx(0.001380,
                                                               abs=1e-6)


def test_the_filter_correction_is_applied_and_grows_as_the_rate_drops():
    """Reaching a lower rate means more filtering, and more lost gain.

    This is the bug the bench found: without it the scope read 17.6% low
    at 1 MS/s, and the same signal read 5% smaller at 100 kS/s than at
    1 MS/s -- which is 1.15 / 1.10.
    """
    bare = 0.78 / (2048 * 1.3 * scale.RANGE_GAIN["low"])
    for rate in scale.SAMPLE_RATES:
        comp = scale.ADC_FILTER_COMP[rate]
        assert scale.volts_per_count("low", rate) == pytest.approx(bare * comp)
    assert (scale.volts_per_count("low", 100000) >
            scale.volts_per_count("low", 1000000) >
            scale.volts_per_count("low", 100000000))


def test_every_adc_rate_has_a_correction():
    assert sorted(scale.ADC_FILTER_COMP) == sorted(scale.SAMPLE_RATES)


def test_every_dac_rate_has_a_correction():
    assert sorted(scale.DAC_FILTER_COMP) == sorted(scale.DAC_SAMPLE_RATES)


def test_the_dac_correction_at_the_loopback_rate():
    """750 kS/s is what the loopback flowgraph uses.

    A meter caught the generator running 16.7% high there; this is the
    number that accounts for it, from M2kAnalogOutImpl's table.
    """
    assert scale.dac_filter_compensation(750000) == pytest.approx(1.164153)


def test_the_dac_correction_makes_the_output_smaller():
    """It divides, where the ADC's multiplies. Opposite signs of trouble."""
    comp = scale.dac_filter_compensation(750000)
    assert abs(scale.volts_to_dac_raw(1.0, filter_compensation=comp)) < \
        abs(scale.volts_to_dac_raw(1.0))


def test_the_wide_range_gives_more_volts_per_count():
    """A sanity check that survives the numbers being wrong.

    Whatever the exact figures, the +/-25 V range must be the coarser one.
    'low' naming the WIDE range is the confusing part.
    """
    assert (scale.volts_per_count("low", 1000000) >
            scale.volts_per_count("high", 1000000))


def test_full_scale_is_about_the_named_range():
    """2048 counts times volts-per-count should land near the label."""
    for name, nominal in scale.RANGE_VOLTS.items():
        full = 2048 * scale.volts_per_count(name, 100000000)
        assert nominal <= full <= nominal * 1.25, (name, full)


def test_unknown_range_is_refused_with_the_options():
    with pytest.raises(ValueError) as excinfo:
        scale.volts_per_count("wide", 1000000)
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
        counts = scale.volts_to_raw(volts, "low", 1000000)
        assert scale.raw_to_volts(counts, "low", 1000000) == pytest.approx(
            volts, abs=scale.volts_per_count("low", 1000000))


def test_the_same_level_is_more_counts_on_the_sensitive_range():
    assert (scale.volts_to_raw(1.0, "high", 1000000) >
            scale.volts_to_raw(1.0, "low", 1000000))


def test_divider_is_explanatory_only_but_correct():
    assert scale.divider_for(100000000) == 1
    assert scale.divider_for(1000000) == 100
    assert scale.divider_for(1000) == 100000


# ---------------------------------------------------- the generator

def test_dac_rates_are_the_ones_hardware_publishes():
    """And they are NOT the ADC's -- a 75 MS/s clock, not 100."""
    import json
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "fixtures", "m2k-real.json")) as handle:
        capture = json.load(handle)
    dac = [d for d in capture["devices"] if d["name"] == "m2k-dac-a"][0]
    published = [a for a in dac["device_attrs"]
                 if a["name"] == "sampling_frequency"][0]["available"]["values"]
    assert sorted(int(v) for v in published) == sorted(scale.DAC_SAMPLE_RATES)
    # The asymmetry is the point: no rate is valid for both.
    assert not (set(scale.DAC_SAMPLE_RATES) & set(scale.SAMPLE_RATES))


def test_dac_conversion_inverts_the_sign():
    """The hardware's inversion, not a slip. Positive volts, negative counts."""
    assert scale.volts_to_dac_raw(1.0) < 0
    assert scale.volts_to_dac_raw(-1.0) > 0


def test_dac_volts_round_trip():
    for volts in (0.5, -0.5, 2.0, -3.25):
        raw = scale.volts_to_dac_raw(volts)
        assert scale.dac_raw_to_volts(raw) == pytest.approx(
            volts, abs=scale.DAC_VLSB)


def test_dac_full_scale_lands_on_the_container_floor():
    """+/-5 V is where an int16 runs out, which is why that is full scale."""
    assert scale.volts_to_dac_raw(scale.DAC_FULL_SCALE_V) == -32768


def test_dac_word_sits_in_the_top_bits():
    """12-bit DAC in a 16-bit container: the low 4 bits are always clear."""
    for volts in (0.1, 1.0, -2.0, 4.0):
        assert scale.volts_to_dac_raw(volts) % 16 == 0


def test_a_dac_rate_the_board_will_not_take_is_refused():
    with pytest.raises(ValueError) as excinfo:
        scale.check_dac_sample_rate(1000000)     # an ADC rate, not a DAC one
    assert "750000" in str(excinfo.value)
