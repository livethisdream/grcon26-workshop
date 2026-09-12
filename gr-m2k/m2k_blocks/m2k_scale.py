"""The M2K's numbers, with nothing imported.

Kept clear of GNU Radio on purpose: these are the conversions everything
else in the block depends on, and they should be testable on a machine
that has no gnuradio, no libiio and no board.

Every figure here is traceable to libm2k, the library Scopy is built on.
The ones that have now met a signal say so.
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

# Getting to a rate below 100 MS/s means filtering and decimating, and
# the filter does not have unity gain. libm2k keeps a correction per rate
# and multiplies the volts-per-count by it; leave it out and the reading
# is low by up to 26%. From M2kAnalogInImpl's constructor.
#
# This is not calibration. It is a fixed property of the decimation
# filter, the same on every board, and it belongs in the arithmetic
# rather than in anything measured. Omitting it is what made our first
# bench measurements read 17.6% low, and it is also why the same signal
# read 5% smaller at 100 kS/s than at 1 MS/s -- 1.15 / 1.10.
ADC_FILTER_COMP = {
    100000000: 1.00,
    10000000: 1.05,
    1000000: 1.10,
    100000: 1.15,
    10000: 1.20,
    1000: 1.26,
}


def adc_filter_compensation(sample_rate):
    """The decimation filter's gain correction at a given rate."""
    return ADC_FILTER_COMP[check_sample_rate(sample_rate)]


def volts_per_count(range_name, sample_rate):
    """What one ADC count is worth in volts, on a range at a rate.

    From M2kAnalogIn::getScalingFactor():

        0.78 / (2048 * 1.3 * range_gain) * calib_gain * filter_comp

    filter_comp is the decimation filter's gain, above, and depends on
    the sample rate -- which is why the rate is not optional here. The
    same input really is worth a different number of volts per count at
    1 MS/s and at 100 kS/s.

    calib_gain is the channel's calibscale, and this deliberately leaves
    it at 1.0 -- because the driver has already applied it by the time a
    sample reaches us. Setting calibscale to 2.0 and re-reading the same
    input doubles the counts; m2k_calibrate.py --probe measured exactly
    that. So a block that reads calibscale back and multiplies by it
    again is wrong by precisely that factor. Do not.

    On an uncalibrated board calibscale is 1.0 and the reading sits
    about 7% low, measured against a meter; see docs/bench-checklist.md.
    Running m2k_calibrate.py --apply fixes that in the driver, with no
    change needed here.
    """
    if range_name not in RANGE_GAIN:
        raise ValueError("unknown input range %r; expected one of %s"
                         % (range_name, sorted(RANGE_GAIN)))
    nominal = 0.78 / (2048 * 1.3 * RANGE_GAIN[range_name])
    return nominal * adc_filter_compensation(sample_rate)


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


def volts_to_raw(volts, range_name, sample_rate):
    """A trigger level in volts, as the raw count the hardware wants."""
    return int(round(float(volts) / volts_per_count(range_name, sample_rate)))


def raw_to_volts(counts, range_name, sample_rate):
    """The inverse, for reading a level back."""
    return float(counts) * volts_per_count(range_name, sample_rate)


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

# The generator has an interpolation filter with the same problem as the
# ADC's decimation filter, and a much less tidy table -- it does not fall
# off smoothly, so there is no guessing it. From M2kAnalogOutImpl's
# constructor. Here the correction divides rather than multiplies, so
# leaving it out makes the output too large.
#
# 750 kS/s is the rate the loopback flowgraph uses, and 1.164153 is
# exactly the 16.7% by which a meter caught the generator overshooting.
DAC_FILTER_COMP = {
    75000000: 1.00,
    7500000: 1.525879,
    750000: 1.164153,
    75000: 1.776357,
    7500: 1.355253,
    750: 1.033976,
}


def dac_filter_compensation(sample_rate):
    """The interpolation filter's gain correction at a given rate."""
    return DAC_FILTER_COMP[check_dac_sample_rate(sample_rate)]


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

    filter_compensation defaults to 1.0 so the bare conversion can be
    checked on its own. Anything driving real hardware should pass
    dac_filter_compensation(rate) instead, or the output is too big.
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


# ---------------------------------------------------------------------
# The power supplies, V+ and V-.
#
# These are not the generator with a different name. W1 and W2 play
# samples; the rails hold a level, and nothing streams to them at all.
# Behind each one is a channel of an entirely different converter --
# ad5627, a two-channel 12-bit DAC that also serves calibration -- with
# a fixed-gain amplifier after it.
#
# The DAC's own output is small. It publishes scale = 0.29296875, which
# is mV per count: 4096 counts over 1.2 V. The board multiplies that up,
# by about 5.02 for V+ and about -5.1 for V-, and those two numbers are
# the only reason a 1.2 V converter can set a 5 V rail.
#
# From M2kPowerSupplyImpl's constructor:
#
#     write_coefficient = 4095.0 / (rail_gain * 1.2)
#
# which is counts per volt AT THE RAIL, amplifier included. Both figures
# are libm2k's and neither has met a meter here yet.
# ---------------------------------------------------------------------

# What the ad5627 puts out at full scale, before the rail amplifier.
SUPPLY_DAC_FULL_SCALE_V = 1.2

# mV per count at the DAC, which the board publishes as `scale` and which
# is the same 0.29297 mV/count the calibration path converts at.
SUPPLY_DAC_MV_PER_COUNT = 1000.0 * SUPPLY_DAC_FULL_SCALE_V / 4096

# The fixed gain between the DAC and the rail. The negative rail's is
# negative, which is what makes a positive count produce a negative
# voltage -- the same trick as the generator's sign inversion, in
# hardware rather than in the arithmetic.
SUPPLY_RAIL_GAIN = {"positive": 5.02, "negative": -5.1}

# The DAC is 12 bits and libm2k divides by 4095, not 4096. Kept as it is
# rather than tidied: the off-by-one is worth about 0.2 counts at the top
# of the range and changing it would put us a count away from Scopy for
# no measured reason.
SUPPLY_MAX_RAW = 4095

# libm2k refuses anything past this and so do we. The rails reach about
# 6 V by the arithmetic; the board is specified to 5.
SUPPLY_LIMIT_V = 5.0


def supply_counts_per_volt(rail):
    """Counts per volt at the rail, amplifier included."""
    if rail not in SUPPLY_RAIL_GAIN:
        raise ValueError("unknown rail %r; expected 'positive' or 'negative'"
                         % (rail,))
    return SUPPLY_MAX_RAW / (SUPPLY_RAIL_GAIN[rail] * SUPPLY_DAC_FULL_SCALE_V)


def check_supply_volts(volts, rail):
    """Reject a setpoint the rail cannot hold, including a sign it cannot.

    The sign check is not pedantry. Ask V- for +5 and the arithmetic
    produces a negative count, the count clamps at zero, and the rail
    sits at 0 V with every attribute reading back exactly as written.
    That is a long afternoon, so it is an error here instead.
    """
    value = float(volts)
    if abs(value) > SUPPLY_LIMIT_V:
        raise ValueError(
            "the M2K's supplies are limited to +/-%g V; %g V is outside that"
            % (SUPPLY_LIMIT_V, value))
    if rail == "positive" and value < 0:
        raise ValueError(
            "V+ cannot hold %g V. Negative setpoints belong on V-, which is "
            "a separate instance of the block." % (value,))
    if rail == "negative" and value > 0:
        raise ValueError(
            "V- cannot hold %g V. Positive setpoints belong on V+, which is "
            "a separate instance of the block." % (value,))
    return value


def volts_to_supply_raw(volts, rail, gain=1.0, offset=0.0):
    """A rail setpoint in volts, as the count the DAC wants.

    From M2kPowerSupply::pushChannel():

        raw = (volts * gain + offset) * counts_per_volt

    `gain` and `offset` are the board's own corrections, which live in
    the context attributes rather than on any device -- cal,gain_pos_dac
    and cal,offset_pos_dac for V+, the neg pair for V-. They default to
    the identity here so the bare conversion can be checked on its own.

    The result is clamped rather than allowed to wrap. libm2k clamps the
    bottom for the same reason: a small setpoint plus a positive offset
    correction can land below zero, and a negative count written to a
    12-bit register is not a small voltage, it is a large one.

    Rounded, where libm2k passes a double and lets the kernel truncate.
    That is at most one count -- about 1.5 mV at the rail -- and it is
    deliberate: the demo compares commanded against measured, so the
    commanded number should be the closest one available.
    """
    value = check_supply_volts(volts, rail)
    raw = (value * float(gain) + float(offset)) * supply_counts_per_volt(rail)
    return max(0, min(SUPPLY_MAX_RAW, int(round(raw))))


def supply_raw_to_volts(raw, rail, gain=1.0, offset=0.0):
    """The inverse: what a count already in the register asks the rail for.

    Note this is what was COMMANDED, not what the rail is doing. The
    board holds a separate reading of each rail on ad9963; the scope and
    a meter are better answers still, and disagreeing with this one is
    the entire point of the precision demo.
    """
    volts = int(raw) / supply_counts_per_volt(rail)
    return (volts - float(offset)) / float(gain)
