"""The sweep's arithmetic, with no board and no GNU Radio.

bench/ultrasonic_sweep.py keeps its gnuradio imports inside measure() on
purpose, the same trick m2k_calibrate.py uses, so everything that turns a
requested frequency into a buffer and a capture into a number can be
checked on the machine that runs the rest of the suite.
"""

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bench"))

import ultrasonic_sweep as sweep


GEN_RATE = 750000
SCOPE_RATE = 1000000


def test_importable_without_gnuradio():
    """The point of the deferred import: this module loads anyway."""
    assert "gnuradio" not in sys.modules
    assert sweep.GEN_RATE == GEN_RATE


# ------------------------------------------------------- the cyclic buffer trap

def test_buffer_holds_a_whole_number_of_cycles():
    """The frequency reported must be the one the buffer really makes."""
    for freq in (36000, 38500, 40000, 41750, 44000):
        length, cycles, actual = sweep.cyclic_buffer(freq, GEN_RATE)
        assert actual == pytest.approx(cycles * GEN_RATE / float(length))


def test_40k_is_exact_at_750k():
    """750 kS/s divides 40 kHz evenly, so there is no excuse for an error."""
    _, _, actual = sweep.cyclic_buffer(40000, GEN_RATE)
    assert actual == pytest.approx(40000.0, abs=1e-9)


def test_frequency_error_stays_small_across_the_band():
    """Off-ratio requests land close, which is the whole reason to search."""
    for freq in range(36000, 44001, 50):
        _, _, actual = sweep.cyclic_buffer(freq, GEN_RATE)
        assert abs(actual - freq) < 10.0, freq


def test_length_is_a_whole_number_of_dac_chunks():
    for freq in range(36000, 44001, 250):
        length, _, _ = sweep.cyclic_buffer(freq, GEN_RATE)
        assert length % sweep.BUFFER_GRANULARITY == 0


def test_rejects_nonsense_frequencies():
    with pytest.raises(ValueError):
        sweep.cyclic_buffer(0, GEN_RATE)
    with pytest.raises(ValueError):
        sweep.cyclic_buffer(-40000, GEN_RATE)
    with pytest.raises(ValueError):
        sweep.cyclic_buffer(GEN_RATE, GEN_RATE)      # at and above Nyquist


def test_sine_closes_on_itself():
    """A cyclic buffer with a step at the seam is a buffer full of clicks."""
    length, cycles, _ = sweep.cyclic_buffer(40000, GEN_RATE)
    wave = sweep.sine(length, cycles, 4.0)
    assert len(wave) == length
    assert max(wave) == pytest.approx(4.0, rel=1e-3)
    # The sample after the last one is the first one again.
    step = 2.0 * math.pi * cycles / length
    assert 4.0 * math.sin(step * length) == pytest.approx(wave[0], abs=1e-9)


# ------------------------------------------------------------- the measurement

def _tone(freq, rate, count, amplitude, phase=0.0):
    return [amplitude * math.cos(2.0 * math.pi * freq * n / rate + phase)
            for n in range(count)]


def test_amplitude_recovers_a_known_tone():
    for amplitude in (0.001, 0.05, 1.0):
        samples = _tone(40000, SCOPE_RATE, 8192, amplitude)
        assert sweep.tone_amplitude(samples, 40000, SCOPE_RATE) == \
            pytest.approx(amplitude, rel=0.01)


def test_amplitude_does_not_care_about_phase():
    for phase in (0.0, 0.7, math.pi / 2, 3.0):
        samples = _tone(40000, SCOPE_RATE, 8192, 0.2, phase)
        assert sweep.tone_amplitude(samples, 40000, SCOPE_RATE) == \
            pytest.approx(0.2, rel=0.01)


def test_amplitude_rejects_an_off_frequency_tone():
    """This is what lets the sweep read 20 dB down the skirt."""
    samples = _tone(30000, SCOPE_RATE, 8192, 1.0)
    assert sweep.tone_amplitude(samples, 40000, SCOPE_RATE) < 0.01


def test_amplitude_finds_a_small_tone_under_a_large_neighbour():
    samples = [a + b for a, b in zip(_tone(40000, SCOPE_RATE, 8192, 0.01),
                                     _tone(25000, SCOPE_RATE, 8192, 1.0))]
    assert sweep.tone_amplitude(samples, 40000, SCOPE_RATE) == \
        pytest.approx(0.01, rel=0.1)


def test_empty_capture_is_zero_not_an_exception():
    assert sweep.tone_amplitude([], 40000, SCOPE_RATE) == 0.0
    assert sweep.rms([]) == 0.0


# 8200 samples at 1 MS/s is a whole number of cycles of both 40 kHz and
# 25 kHz. That matters here and not above: the RMS of a partial cycle is
# not exactly A/sqrt(2), so a ragged record would be testing the test
# signal rather than the function.
WHOLE = 8200


def test_off_tone_rms_takes_the_tone_out():
    samples = _tone(40000, SCOPE_RATE, WHOLE, 1.0)
    assert sweep.off_tone_rms(samples, 1.0) < 0.01


def test_off_tone_rms_keeps_what_is_left():
    """A tone plus a known second tone: the residue is the second one."""
    samples = [a + b for a, b in zip(_tone(40000, SCOPE_RATE, WHOLE, 1.0),
                                     _tone(25000, SCOPE_RATE, WHOLE, 0.5))]
    assert sweep.off_tone_rms(samples, 1.0) == \
        pytest.approx(0.5 / math.sqrt(2), rel=0.05)


def test_off_tone_rms_never_goes_negative():
    assert sweep.off_tone_rms([0.0] * 100, 1.0) == 0.0


# ------------------------------------------------------------- reading a curve

def _resonant(f0, bandwidth, freqs, peak=1.0):
    """A single-pole response whose edges are known in advance.

    `bandwidth` is the -3 dB one, f0/Q, because that is what the textbook
    formula produces. The -6 dB bandwidth the sweep reports is wider by
    sqrt(3), and keeping the two apart in the test is the point: half
    amplitude and half power are not the same edge, and a transducer
    datasheet means the first one.
    """
    q = f0 / bandwidth
    out = []
    for f in freqs:
        detune = q * (f / f0 - f0 / f)
        out.append((f, peak / math.sqrt(1.0 + detune * detune)))
    return out


SIXDB = math.sqrt(3.0)      # -6 dB bandwidth / -3 dB bandwidth


def test_resonance_finds_the_peak():
    points = _resonant(40500.0, 2000.0, [36000 + 50 * i for i in range(161)])
    found = sweep.resonance(points)
    assert found["f0"] == pytest.approx(40500.0, abs=100.0)
    assert found["amplitude"] == pytest.approx(1.0, rel=0.01)


def test_resonance_finds_the_minus_6db_edges():
    """Half amplitude, not half power -- the transducer convention."""
    points = _resonant(40000.0, 2000.0, [36000 + 25 * i for i in range(321)])
    found = sweep.resonance(points)
    assert found["bandwidth"] == pytest.approx(2000.0 * SIXDB, rel=0.05)
    assert found["low"] < 40000.0 < found["high"]


def test_resonance_says_so_when_the_sweep_was_too_narrow():
    """Better than extrapolating off the end of the data."""
    points = _resonant(40000.0, 8000.0, [39500 + 25 * i for i in range(41)])
    found = sweep.resonance(points)
    assert found["bandwidth"] is None
    assert found["low"] is None and found["high"] is None


def test_resonance_needs_points():
    with pytest.raises(ValueError):
        sweep.resonance([])


def test_db_floors_instead_of_raising():
    assert sweep.db(0.0, 1.0) == float("-inf")
    assert sweep.db(1.0, 0.0) == float("-inf")
    assert sweep.db(0.5, 1.0) == pytest.approx(-6.0206, abs=1e-3)


def test_bar_scales_to_the_peak():
    assert sweep.bar(1.0, 1.0, width=10) == "#" * 10
    assert sweep.bar(0.0, 1.0, width=10) == ""
    assert sweep.bar(0.5, 1.0, width=10) == "#" * 5
    assert sweep.bar(1.0, 0.0, width=10) == ""


def test_q_is_defined_against_the_3db_bandwidth():
    """Feed it the -6 dB number and it must not report a low-Q part.

    A resonance with a -3 dB bandwidth of 2000 Hz at 40 kHz has Q = 20.
    Its -6 dB bandwidth is sqrt(3) wider, and dividing straight into that
    would report 11.5.
    """
    assert sweep.quality_factor(40000.0, 2000.0 * SIXDB) == \
        pytest.approx(20.0, rel=1e-6)


def test_q_rejects_a_nonsense_bandwidth():
    with pytest.raises(ValueError):
        sweep.quality_factor(40000.0, 0.0)


def test_ringdown_matches_the_decay_it_describes():
    """Q/(pi f0) is the time constant; -40 dB is ln(10)*2 of them."""
    q, f0 = 20.0, 40000.0
    tau = q / (math.pi * f0)
    assert sweep.ringdown(f0, q) == pytest.approx(tau * math.log(10.0) * 2.0)


def test_ringdown_is_sub_millisecond_for_a_real_transducer():
    """The blind zone the demo has to live with: tens of centimetres."""
    ring = sweep.ringdown(40000.0, 20.0)
    assert 0.0003 < ring < 0.0015
    assert 10.0 < ring * 343.0 * 100.0 < 50.0        # centimetres of path
