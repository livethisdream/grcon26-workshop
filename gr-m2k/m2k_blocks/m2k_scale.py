"""The M2K's numbers, with nothing imported.

Kept clear of GNU Radio on purpose: these are the conversions everything
else in the block depends on, and they should be testable on a machine
that has no gnuradio, no libiio and no board.

Every figure here is traceable to libm2k, the library Scopy is built on.
None of them has yet been confirmed against a signal.
"""

# The rates the ADC will accept, taken from what the hardware itself
# publishes in sampling_frequency_available -- not computed. An earlier
# version of this worked the rate out as 100 MS/s divided by
# oversampling_ratio, which is a reasonable guess and produced a dropdown
# offering 1 kS/s as unreachable when the board accepts it happily. When
# the hardware publishes a list, the list wins.
SAMPLE_RATES = [100000000, 10000000, 1000000, 100000, 10000, 1000]

# The ADC's own clock. Every rate above is this divided down internally;
# that is background, not something this module configures.
BASE_RATE = 100000000

# Front-end gain per input range, from M2kAnalogIn::getValueForRange().
# 'low' is the WIDE range: the name describes the amplifier, not the volts,
# which is the wrong way round from how anyone would guess.
RANGE_GAIN = {"low": 0.02017, "high": 0.21229}

# What each range is called in volts, for labels and for bounds checking.
RANGE_VOLTS = {"low": 25.0, "high": 2.5}


def volts_per_count(range_name):
    """What one ADC count is worth in volts, on a given input range.

    From M2kAnalogIn::getScalingFactor():

        0.78 / (2048 * 1.3 * range_gain) * calib_gain * filter_comp

    calib_gain is the channel's calibscale and filter_comp is a
    per-sample-rate correction; both are 1.0 until calibration runs, so
    this is the fresh-board figure -- about 14.52 mV per count on the
    +/-25 V range, 1.380 mV on +/-2.5 V.
    """
    if range_name not in RANGE_GAIN:
        raise ValueError("unknown input range %r; expected one of %s"
                         % (range_name, sorted(RANGE_GAIN)))
    return 0.78 / (2048 * 1.3 * RANGE_GAIN[range_name])


def check_sample_rate(sample_rate):
    """Reject a rate the ADC will not accept, with the list that it will."""
    rate = int(sample_rate)
    if rate not in SAMPLE_RATES:
        raise ValueError(
            "sample rate %s is not one the M2K accepts; choose from %s"
            % (sample_rate, ", ".join(str(r) for r in SAMPLE_RATES)))
    return rate


def divider_for(sample_rate):
    """How far the ADC's own clock is divided down to reach a rate.

    Not used to configure anything -- sampling_frequency is written
    directly. Here because "1 MS/s means every hundredth sample of the
    real 100 MS/s clock" is worth being able to show.
    """
    return BASE_RATE // check_sample_rate(sample_rate)


def volts_to_raw(volts, range_name):
    """A trigger level in volts, as the raw count the hardware wants."""
    return int(round(float(volts) / volts_per_count(range_name)))


def raw_to_volts(counts, range_name):
    """The inverse, for reading a level back."""
    return float(counts) * volts_per_count(range_name)


# ---------------------------------------------------------------------
# The waveform generator.
#
# Its numbers are not the ADC's, which is the first thing that catches
# people: a different base clock, a different rate list, and a conversion
# that inverts the sign.
# ---------------------------------------------------------------------

# Published by the hardware in sampling_frequency_available on m2k-dac-a.
# Note these are NOT the ADC's rates -- the DAC's base clock is 75 MS/s,
# so a flowgraph that generates and captures at "the same" rate is doing
# no such thing unless you picked from both lists deliberately.
DAC_SAMPLE_RATES = [75000000, 7500000, 750000, 75000, 7500, 750]

# Volts per LSB before calibration, from M2kAnalogOut's constructor:
# 10.0 / (2**12 - 1). Calibration replaces it per channel; this is the
# fresh-board figure, the DAC's counterpart to calib_gain = 1.0.
DAC_VLSB = 10.0 / ((1 << 12) - 1)

# The DAC word is 12 bits sitting in the top of a 16-bit container, which
# is what the shift below is for.
DAC_SHIFT = 4

# Where the conversion runs out of container, and therefore the largest
# amplitude worth asking for.
DAC_FULL_SCALE_V = 5.0


def volts_to_dac_raw(volts, vlsb=DAC_VLSB, filter_compensation=1.0):
    """Volts to the int16 the DAC wants, from M2kAnalogOut::convVoltsToRaw().

        raw = ((volts * -1/vlsb) - 0.5) / filter_comp, then shifted up 4

    The sign inversion is real and is the hardware's, not a slip here:
    a positive voltage becomes a negative count. Anyone converting by hand
    and getting an upside-down waveform has just met it.
    """
    scaled = ((float(volts) * (-1.0 / vlsb)) - 0.5) / filter_compensation
    return int(scaled) << DAC_SHIFT


def dac_raw_to_volts(raw, vlsb=DAC_VLSB, filter_compensation=1.0):
    """The inverse, for reading a level back."""
    return -(((int(raw) >> DAC_SHIFT) * filter_compensation) + 0.5) * vlsb


def check_dac_sample_rate(sample_rate):
    """Reject a rate the DAC will not accept, with the list that it will."""
    rate = int(sample_rate)
    if rate not in DAC_SAMPLE_RATES:
        raise ValueError(
            "sample rate %s is not one the M2K's generator accepts; choose "
            "from %s" % (sample_rate,
                         ", ".join(str(r) for r in DAC_SAMPLE_RATES)))
    return rate
