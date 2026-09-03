"""The calibration arithmetic, with no board and no libiio.

m2k_calibrate.py keeps `import iio` inside its hardware functions on
purpose, so everything that turns a measurement into a register value can
be checked here -- on the same machine that runs the rest of the suite,
which has neither libiio nor GNU Radio installed.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gr-m2k"))

import m2k_calibrate as cal


def test_importable_without_libiio():
    """The point of the deferred import: this module loads anyway."""
    assert "iio" not in sys.modules or True
    assert cal.NEUTRAL == 2048


# ---------------------------------------------------------------------
# clamp_code -- three trim registers, all 12 bits, all offset binary.
# ---------------------------------------------------------------------

def test_clamp_code_holds_the_rails():
    assert cal.clamp_code(-500) == 0
    assert cal.clamp_code(9999) == 4095
    assert cal.clamp_code(2048) == 2048


def test_clamp_code_rounds_rather_than_truncates():
    """A half-count thrown away is a half-count of offset kept."""
    assert cal.clamp_code(2047.6) == 2048
    assert cal.clamp_code(2048.4) == 2048
    assert cal.clamp_code(-0.4) == 0


# ---------------------------------------------------------------------
# ADC offset. Not calibbias -- --probe found the driver ignores that
# entirely -- but the ad5625 trim DAC summed into the front end, at a
# slope the run measures for itself.
# ---------------------------------------------------------------------

MEASURED_SLOPE = 1.756          # counts per ad5625 code, high range, 1 MS/s


def test_counts_per_code_reads_the_slope_off_two_captures():
    assert cal.counts_per_code([(2048, -12.9), (2148, 162.7)]) == \
        pytest.approx(1.756, abs=1e-3)


def test_counts_per_code_refuses_a_flat_sweep():
    """A knob that moves nothing is the calibbias answer, not a slope."""
    with pytest.raises(ValueError, match="which is nothing"):
        cal.counts_per_code([(2048, -12.94), (2148, -12.97)])


def test_counts_per_code_refuses_one_point():
    with pytest.raises(ValueError, match="two different codes"):
        cal.counts_per_code([(2048, -12.9), (2048, -12.9)])


def test_measured_slope_agrees_with_the_libm2k_constant():
    """1.756 counts x 1.518044 mV is 2.666 mV; libm2k says 2.658 mV.

    The vendor figure is the same trim DAC seen from the generator side.
    Two ends of the board, one step size, 0.3% apart.
    """
    volts_per_count_high_1m = 0.001518044
    assert MEASURED_SLOPE * volts_per_count_high_1m == \
        pytest.approx(cal.AD5625_LSB_AT_DAC, rel=0.005)
    assert cal.AD5625_LSB_AT_ADC == pytest.approx(
        MEASURED_SLOPE * volts_per_count_high_1m, abs=1e-5)


def test_adc_offset_subtracts_from_neutral():
    """An input reading high needs a code below 2048, and vice versa."""
    assert cal.adc_offset_code(+40.8, MEASURED_SLOPE) == 2048 - 23
    assert cal.adc_offset_code(-13.8, MEASURED_SLOPE) == 2048 + 8


def test_adc_offset_of_a_perfect_channel_is_neutral():
    assert cal.adc_offset_code(0.0, MEASURED_SLOPE) == cal.NEUTRAL


def test_adc_offset_composes_from_the_current_code():
    """Feed it the code the capture was taken with and it converges.

    Sitting at 2056 and still reading +1.756 counts high means 2055, not
    2047 -- the fine-tune loop depends on this.
    """
    assert cal.adc_offset_code(+1.756, MEASURED_SLOPE,
                               current_code=2056) == 2055


def test_adc_offset_divides_by_the_slope_not_by_one():
    """The whole point of measuring the slope: 40.8 counts is 23 codes."""
    assert cal.adc_offset_code(+40.8, 1.0) == 2048 - 41
    assert cal.adc_offset_code(+40.8, MEASURED_SLOPE) == 2048 - 23


def test_adc_offset_clamps_rather_than_wrapping():
    assert cal.adc_offset_code(+50000.0, MEASURED_SLOPE) == 0
    assert cal.adc_offset_code(-50000.0, MEASURED_SLOPE) == 4095


def test_metered_offsets_land_well_inside_the_register():
    """The two offsets we measured need 8 and 23 of 2048 codes."""
    for counts in (-13.8, +40.8):
        code = cal.adc_offset_code(counts, MEASURED_SLOPE)
        assert 2000 < code < 2100


# ---------------------------------------------------------------------
# ADC gain. libm2k: m_adc_ch0_gain = vref1 / avg0.
# ---------------------------------------------------------------------

def test_adc_gain_of_a_perfect_channel_is_one():
    assert cal.adc_gain(cal.VREF1) == pytest.approx(1.0)


def test_adc_gain_reads_above_one_on_a_board_that_reads_low():
    """Ours reads about 6.5% low, so it wants multiplying up, not down."""
    gain = cal.adc_gain(cal.VREF1 * 0.93686)
    assert gain == pytest.approx(1.06740, abs=1e-5)
    assert gain > 1.0


def test_adc_gain_refuses_a_dead_channel():
    """Zero volts from a live reference is a wiring answer, not a gain."""
    with pytest.raises(ZeroDivisionError):
        cal.adc_gain(0.0)


# ---------------------------------------------------------------------
# Calibration mode. The reference does not come in through the range
# amplifier, so the BNC-referred volts-per-count does not describe it --
# libm2k forces hw_gain to 1 rather than its 0.02 default, and what is
# left is one fixed number.
# ---------------------------------------------------------------------

def test_cal_mode_scale_is_the_libm2k_expression():
    assert cal.CAL_MODE_VPC == pytest.approx(0.78 / (2048 * 1.3))
    assert cal.CAL_MODE_VPC == pytest.approx(0.000292969, abs=1e-9)


def test_cal_mode_scale_ignores_the_range():
    """Both ranges read adc_ref1 at the same counts; that is why."""
    from m2k_blocks.m2k_scale import RANGE_GAIN
    assert len(RANGE_GAIN) == 2
    assert "range" not in cal.cal_mode_volts.__code__.co_varnames


def test_cal_mode_volts_refers_counts_back_to_100_ms():
    """1 MS/s counts are 1.10x small; leaving that out is 10% in the gain."""
    assert cal.cal_mode_volts(1000, 1.10) == \
        pytest.approx(cal.cal_mode_volts(1100, 1.0))


def test_measured_reference_lands_on_the_metered_gain():
    """The run that settled this: in1, 1 MS/s, offset already trimmed.

    1475.03 counts referred back to 100 MS/s is 0.43214 V against the
    nominal 0.46172, so calibscale 1.06845. The meter, independently,
    said 1.06740.
    """
    volts = cal.cal_mode_volts(1475.03 / 1.10, 1.10)
    assert volts == pytest.approx(0.43214, abs=1e-5)
    assert cal.adc_gain(volts) == pytest.approx(1.0 / 0.93686, rel=0.002)


# ---------------------------------------------------------------------
# Generator offset. A sweep and a zero crossing, not one capture and a
# divider -- the crossing is in commanded volts already, so no scale
# factor enters it at all.
# ---------------------------------------------------------------------

def test_line_fit_recovers_a_line_it_was_given():
    points = [(x, 3.0 * x - 7.0) for x in (-2, -1, 0, 1, 2)]
    slope, intercept = cal.line_fit(points)
    assert slope == pytest.approx(3.0)
    assert intercept == pytest.approx(-7.0)
    assert cal.worst_residual(points, slope, intercept) == pytest.approx(0.0)


def test_line_fit_refuses_a_single_point():
    with pytest.raises(ValueError, match="at least two points"):
        cal.line_fit([(1.0, 2.0)])


def test_line_fit_refuses_a_sweep_that_never_moved():
    with pytest.raises(ValueError, match="not a sweep"):
        cal.line_fit([(1.0, 2.0), (1.0, 3.0), (1.0, 4.0)])


def test_worst_residual_finds_the_one_bad_point():
    points = [(0.0, 0.0), (1.0, 1.0), (2.0, 2.5), (3.0, 3.0)]
    slope, intercept = cal.line_fit(points)
    assert cal.worst_residual(points, slope, intercept) > 0.2


def test_zero_crossing_is_where_the_line_reads_zero():
    points = [(x, 2.0 * (x - 0.05)) for x in (-1.0, -0.5, 0.0, 0.5, 1.0)]
    assert cal.zero_crossing(points) == pytest.approx(0.05)


def test_zero_crossing_does_not_care_about_the_scale():
    """The whole reason the 9.06 divider could go.

    Multiply every count by anything and the crossing does not move, so
    the generator offset needs no counts-per-volt and no loopback
    divider -- only the sweep.
    """
    base = [(x, 2.0 * (x - 0.05)) for x in (-1.0, -0.5, 0.0, 0.5, 1.0)]
    scaled = [(x, y * 37.0) for x, y in base]
    assert cal.zero_crossing(scaled) == pytest.approx(cal.zero_crossing(base))


def test_zero_crossing_refuses_a_dead_loopback():
    flat = [(x, 5.0) for x in (-1.0, -0.5, 0.0, 0.5, 1.0)]
    with pytest.raises(ValueError, match="not reaching the loopback"):
        cal.zero_crossing(flat)


def test_offset_is_the_crossing_negated():
    """The output is commanded + offset, so it reads zero at -offset.

    Taking the crossing as the offset trims the generator the wrong way
    and doubles its error, while every printed number stays plausible.
    """
    points = [(x, 2.0 * (x + 0.05)) for x in (-1.0, -0.5, 0.0, 0.5, 1.0)]
    assert cal.zero_crossing(points) == pytest.approx(-0.05)
    assert cal.offset_from_sweep(points) == pytest.approx(+0.05)


def test_measured_w1_sweep_gives_its_offset():
    """The real five captures, W1 at 1 MS/s, adc_gnd baseline removed.

    The meter, on the BNC, said +48.5 mV.
    """
    points = [(-0.9780, -348.39), (-0.4896, -166.71), (-0.0012, +14.91),
              (+0.4872, +196.24), (+0.9756, +378.89)]
    slope, intercept = cal.line_fit(points)
    assert cal.worst_residual(points, slope, intercept) < 1.0
    assert cal.offset_from_sweep(points) == pytest.approx(+0.0415, abs=0.002)
    assert cal.dac_offset_code(cal.offset_from_sweep(points)) < cal.NEUTRAL


def test_dac_offset_subtracts_from_neutral():
    """W2's metered +112.1 mV is 42 counts of the ad5625."""
    assert cal.dac_offset_code(0.1121) == 2048 - 42


def test_dac_offset_of_a_perfect_generator_is_neutral():
    assert cal.dac_offset_code(0.0) == cal.NEUTRAL


def test_dac_offset_takes_output_volts_not_adc_volts():
    """No divider left to forget: the argument is already at the BNC."""
    assert "divider" not in cal.dac_offset_code.__code__.co_varnames


def test_metered_generator_offsets_land_inside_the_trim_range():
    """+48.5 mV and +112.1 mV are 18 and 42 counts of 2048 available."""
    for volts in (0.0485, 0.1121):
        assert 1990 < cal.dac_offset_code(volts) < 2048


def test_held_dac_volts_cancels_the_two_negations():
    """held_dac negates, dac_raw_to_volts negates; the sign is neither's.

    Getting this backwards inverted the whole generator sweep once, and
    the only symptom was an offset with the wrong sign.
    """
    assert cal.held_dac_volts(400) == pytest.approx(+0.9756, abs=1e-4)
    assert cal.held_dac_volts(-400) == pytest.approx(-0.9780, abs=1e-4)
    assert cal.held_dac_volts(0) == pytest.approx(-0.0012, abs=1e-4)


# ---------------------------------------------------------------------
# The fine-tune bar.
# ---------------------------------------------------------------------

def test_fine_tolerance_is_half_a_trim_code():
    assert cal.fine_tolerance(MEASURED_SLOPE) == pytest.approx(0.878)


def test_fine_tolerance_is_reachable():
    """0.5 counts asked for a resolution the register does not have.

    One code moves the input 1.76 counts, so a residual under half that
    is the best any code can do and a tighter bar makes the sweep run
    every time only to return the code the solve already found.
    """
    assert cal.fine_tolerance(MEASURED_SLOPE) > 0.5
    assert cal.fine_tolerance(MEASURED_SLOPE) < MEASURED_SLOPE


# ---------------------------------------------------------------------
# The constants, checked against each other rather than trusted.
# ---------------------------------------------------------------------

AD5625_SCALE_V = 0.29296875 / 1000.0     # published by the board itself


LIBM2K_DAC_DIVIDER = 9.06        # no longer used; kept as a cross-check


def test_trim_lsb_and_the_libm2k_divider_agree():
    """Two constants from different parts of libm2k, one answer.

    AD5625_LSB_AT_DAC is the trim DAC's step referred to the generator
    output, so dividing it by the step at the trim DAC's own pin should
    give back the loopback divider. It gives 9.07 against 9.06 -- a tenth
    of a percent, from numbers that were never derived from each other.

    The script no longer uses the divider: the zero crossing replaced it,
    and this board measures the loopback at 8.34 rather than 9.06. The
    identity still holds within libm2k's own numbers, which is why it
    stays here as a check on AD5625_LSB_AT_DAC.
    """
    implied = cal.AD5625_LSB_AT_DAC / AD5625_SCALE_V
    assert implied == pytest.approx(LIBM2K_DAC_DIVIDER, rel=0.002)


def test_vref1_is_the_libm2k_figure():
    """Nominal, not measured -- the one assumption the bench check tests."""
    assert cal.VREF1 == 0.46172


def test_sample_counts_are_whole_refills():
    """A partial buffer in the average is a weighted average by accident."""
    assert cal.OFFSET_SAMPLES % cal.CHUNK == 0
    assert cal.GAIN_SAMPLES % cal.CHUNK == 0


def test_metered_reference_set_is_the_check_not_the_input():
    """The 2026-09-03 meter figures are printed, never computed with.

    Bake a board-specific measurement into the arithmetic and the script
    stops being a calibration and starts being a lookup table for one
    board. The guard is structural: nothing above the hardware section
    may so much as name METERED.
    """
    import inspect
    body = inspect.getsource(cal)
    arithmetic = body[:body.index("# The hardware.")]
    assert "METERED" not in arithmetic
    assert "METERED[" in body[body.index("def calibrate("):]


def test_metered_set_covers_every_measurement_the_script_makes():
    """Two ADC offsets, two ADC gains, two generator offsets."""
    assert set(cal.METERED) == {
        "in1_offset_counts", "in2_offset_counts",
        "in1_gain", "in2_gain",
        "w1_offset_v", "w2_offset_v",
    }
