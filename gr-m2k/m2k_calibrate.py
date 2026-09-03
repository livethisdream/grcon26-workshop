"""Calibrate the M2K's analog front end, using only what is on the board.

A fresh M2K reads about 6.5% low and a few tens of millivolts off zero,
and it will do that forever, confidently, because nothing in the IIO
driver knows any better. Three registers fix it, and they ship neutral
because nothing on a bare board ever writes them:

    ad5625  voltage2/voltage3   raw         2048   ADC offset, per channel
    m2k-adc voltage0/voltage1   calibscale  1.0    ADC gain, per channel
    ad5625  voltage0/voltage1   raw         2048   W1/W2 offset

Scopy writes them at startup through libm2k. We ship no libm2k, so if
this script does not write them, nobody does. That is the whole point:
IIO hands you a number, and what the number is worth is not IIO's problem.

Which register does what was measured, not assumed -- see `--probe`, and
the two surprises it turned up on firmware v0.33:

    calibbias does nothing. Writing it anywhere in its range moves the
    samples by less than a twentieth of a count. It is storage. The offset
    that reaches the signal is the ad5625, a real DAC summed into the
    front end at about 1.756 counts per code.

    calibscale is applied by the driver, not merely stored. Setting it to
    2.0 doubles the samples. So a block that reads it back and applies it
    again is wrong by exactly that factor -- do not.

The measurement needs no meter and no jumpers. The M2K can disconnect its
own front end from the BNCs and put a known thing in front of it instead,
through m2k-fabric's calibration_mode:

    adc_gnd    the inputs see ground; whatever comes back is the offset
    adc_ref1   the inputs see an internal 0.46172 V; the ratio is the gain
    dac        W1 and W2 loop back into the inputs through a 9.06 divider

Method follows libm2k's m2kcalibration_impl.cpp, with one deliberate
difference. libm2k carries constants for how far one trim code moves a
reading; this measures the slope on the board, two captures, before
solving for the code. Constants we cannot derive are constants we cannot
check, and the slope changes with the range and the sample rate anyway.

Runs on a plain Python with pylibiio and numpy. No GNU Radio, unlike
everything in bench/ -- a calibration pass is a dozen captures with
settling in between, which is a loop, not a flowgraph.

    python3 gr-m2k/m2k_calibrate.py --probe     which registers are live
    python3 gr-m2k/m2k_calibrate.py             measure, write nothing
    python3 gr-m2k/m2k_calibrate.py --apply     measure and write
    python3 gr-m2k/m2k_calibrate.py --reset     back to neutral

Every pass calibrates one input range, 'high' by default. The offset of a
grounded input depends on the amplifier in front of it, so an offset
found on 'high' is an offset for 'high'. libm2k has the same limitation
and does not mention it.
"""

import argparse
import sys
import time

# --------------------------------------------------------------------
# The arithmetic. No imports, so this half is testable on a machine with
# no board, no libiio and no numpy -- the same bargain m2k_scale.py makes.
# --------------------------------------------------------------------

# All three trim registers are offset binary in 12 bits: mid-scale means
# "change nothing", and there is no way to say it with a zero.
NEUTRAL = 2048
CODE_MIN, CODE_MAX = 0, 4095

# The internal reference the gain measurement is taken against, from
# libm2k's calibrateADCgain(). This is a nominal figure, not a measured
# one -- it is the single assumption the whole absolute accuracy of this
# script rests on, which is why the bench check against a meter matters.
VREF1 = 0.46172

# Calibration mode does not go through the input range amplifier. libm2k
# says so in one argument: convRawToVolts(sample, 1, 1) forces hw_gain to
# 1 where it otherwise defaults to 0.02. What is left is a fixed scale --
# no range, no rate, one number -- and it is why an internal reference
# reads the same counts on 'high' and on 'low'.
CAL_MODE_VPC = 0.78 / ((1 << 11) * 1.3)      # 0.000292969 V/count

# One count of the ad5625 trim DAC, referred to the generator output.
# From libm2k's calibrateDACoffset().
#
# Worth checking rather than trusting, and it survives two checks. The
# ad5625 publishes scale = 0.29296875 mV/count at its own pin, so
# 0.002658 / 0.00029296875 = 9.07 -- the trim step referred through the
# loopback, which libm2k separately calls a divider of 9.06.
#
# The second check is ours, from the other end of the board. --probe
# measures the ad5625 moving the ADC by 1.7541 and 1.7582 counts per
# code, and one count on 'high' at 1 MS/s is 1.518044 mV, so a trim code
# is 2.666 mV at the input against 2.658 mV at the output.
AD5625_LSB_AT_DAC = 0.002658

# The same step seen by the ADC, measured here. Used only to sanity-check
# the slope the run measures for itself -- nothing solves with it.
AD5625_LSB_AT_ADC = 0.002666


def clamp_code(code):
    """A 12-bit trim register cannot hold what it cannot hold."""
    return max(CODE_MIN, min(CODE_MAX, int(round(code))))


def counts_per_code(points):
    """How far one ad5625 code moves the average, from two captures.

    `points` is [(code, mean_counts), ...]; the slope comes off the ends.
    libm2k carries this as a constant. Measuring it costs one extra
    capture and makes the answer independent of the range, the sample
    rate and the board.
    """
    (first_code, first), (last_code, last) = points[0], points[-1]
    if first_code == last_code:
        raise ValueError("need two different codes to get a slope")
    slope = (last - first) / float(last_code - first_code)
    if abs(slope) < 0.01:
        raise ValueError(
            "the ad5625 moved the samples by %.4f counts per code, which "
            "is nothing; the front end is not seeing the trim DAC" % slope)
    return slope


def adc_offset_code(mean_counts, slope, current_code=NEUTRAL):
    """The ad5625 code that would have made this grounded capture read zero.

    libm2k's `2048 - ((voltage * 4096 * gain) / range)`, with its constant
    replaced by the slope this board actually showed and the volts
    conversion dropped -- the capture is in counts and so is the slope.

    `current_code` is the code the capture was taken with, so this
    composes: feed it the last round's result and it converges, which is
    what the fine-tune loop does.
    """
    return clamp_code(current_code - mean_counts / slope)


def adc_gain(mean_volts, vref=VREF1):
    """The calibscale that would have made a reference read its own value.

    libm2k: `m_adc_ch0_gain = vref1 / avg0`. A board reading 6.5% low
    gives 1.065 -- above one, because it multiplies the reading up.
    """
    if mean_volts == 0:
        raise ZeroDivisionError(
            "the reference measured exactly zero volts; the front end is "
            "not seeing adc_ref1")
    return float(vref) / float(mean_volts)


def line_fit(points):
    """Least squares over (x, y), returning (slope, intercept).

    Five points rather than two so the run can report how straight the
    path actually was, instead of taking linearity on faith the way a
    single capture has to.
    """
    pts = [(float(x), float(y)) for x, y in points]
    n = len(pts)
    if n < 2:
        raise ValueError("a line needs at least two points, got %d" % n)
    sx = sum(x for x, _ in pts)
    sy = sum(y for _, y in pts)
    denominator = n * sum(x * x for x, _ in pts) - sx * sx
    if denominator == 0:
        raise ValueError("every point is at the same x; that is not a sweep")
    slope = (n * sum(x * y for x, y in pts) - sx * sy) / denominator
    return slope, (sy - slope * sx) / n


def worst_residual(points, slope, intercept):
    """How far the furthest point sits off the fitted line, in y."""
    return max(abs(y - (slope * x + intercept)) for x, y in points)


def zero_crossing(points):
    """The x at which the fitted line reads zero.

    For the generator sweep, x is commanded volts and y is counts, so
    this is the output offset directly -- and being a crossing rather
    than a reading, it does not depend on the counts-per-volt scale at
    all. That is what lets the loopback divider go: libm2k needs 9.06 to
    turn one capture at raw 0 into volts, and this needs nothing.
    """
    slope, intercept = line_fit(points)
    if slope == 0:
        raise ValueError(
            "the sweep moved the input by nothing; the generator is not "
            "reaching the loopback")
    return -intercept / slope


def offset_from_sweep(points):
    """The generator's own offset, from a sweep of commanded volts.

    The output is `commanded + offset`, so the ADC reads zero where
    `commanded = -offset` -- the offset is the crossing negated, not the
    crossing. Getting that backwards trims the generator the wrong way
    and doubles its error instead of removing it, while every printed
    number still looks the right size.
    """
    return -zero_crossing(points)


def dac_offset_code(output_volts, lsb=AD5625_LSB_AT_DAC):
    """The ad5625 code that would have pulled this generator to zero.

    libm2k: `2048 - ((voltage0 * 9.06) / 0.002658)`, where the multiply
    undoes the divider. We arrive at volts at the output by measuring
    where the sweep crosses zero, so only the trim step is left.
    """
    return clamp_code(NEUTRAL - float(output_volts) / lsb)


def cal_mode_volts(mean_counts, filter_compensation=1.0):
    """Volts at the injection point, from counts taken in calibration mode.

    libm2k calibrates at 100 MS/s, where the decimation filter's gain is
    1 and this is a bare multiply by CAL_MODE_VPC. We calibrate at the
    workshop's rate instead, so the counts are referred back to 100 MS/s
    first. Leaving that out reads the reference 10% low at 1 MS/s and
    puts 10% straight into calibscale.
    """
    return float(mean_counts) * float(filter_compensation) * CAL_MODE_VPC


# --------------------------------------------------------------------
# The hardware. `import iio` is deferred into these so the arithmetic
# above stays importable without it.
# --------------------------------------------------------------------

DEV_ADC = "m2k-adc"
DEV_FABRIC = "m2k-fabric"
DEV_TRIM = "ad5625"
DAC_DEVICE = {"w1": "m2k-dac-a", "w2": "m2k-dac-b"}

# Which ad5625 channel trims what. Channels 0 and 1 offset the two
# generator outputs; 2 and 3 are the scope's hardware vertical offset,
# which is where the ADC's own offset correction has to go, calibbias
# being inert. From libm2k, which reaches for channel (2 + i) to position
# scope channel i -- it uses the same knob for positioning that we use
# for zeroing, because they are the same knob.
TRIM_DAC = {"w1": "voltage0", "w2": "voltage1"}
TRIM_ADC = ["voltage2", "voltage3"]

ADC_CHANNELS = ["voltage0", "voltage1"]

# The fabric carries the input range and the powerdowns. Its input and
# output channels share the ids voltage0/voltage1 and are told apart by
# direction, which is a trap all of its own.
FABRIC_OUTPUT = {"w1": "voltage0", "w2": "voltage1"}

# Sample counts, near libm2k's 100k and 150k but rounded to whole
# refills of the chunk below so no partial buffer is ever averaged.
CHUNK = 16384
OFFSET_SAMPLES = 6 * CHUNK       # 98304
GAIN_SAMPLES = 9 * CHUNK         # 147456

# Switching the front end between references is an analog settling
# problem, not a register write. libm2k sleeps here too.
SETTLE = 0.25

# The fine-tune sweep, when the first estimate does not land. libm2k
# always sweeps span=20; we sweep only if we have to, and say so.
FINE_SPAN = 10

# A trim code is worth about 1.76 counts, so no solve can land closer
# than half a code however good the arithmetic is. Asking for 0.5 counts
# would demand a resolution the register does not have, and the sweep
# would run every time and hand back the code the solve already found.
# The bar is derived from the slope the run measured for itself.
def fine_tolerance(slope):
    """The tightest residual worth chasing, given one code is `slope`."""
    return abs(slope) / 2.0


def context(uri):
    """A pylibiio context. Not gr-iio -- different module, same name."""
    import iio
    return iio.Context(uri)


def _dev(ctx, name):
    dev = ctx.find_device(name)
    if dev is None:
        raise LookupError("no device %r on this board" % (name,))
    return dev


def read_attr(ctx, device, channel, attr, output=False):
    """One attribute, as the string the driver actually holds."""
    dev = _dev(ctx, device)
    if channel is None:
        return dev.attrs[attr].value
    chan = dev.find_channel(channel, output)
    if chan is None:
        raise LookupError("no %s channel %r on %s"
                          % ("output" if output else "input", channel, device))
    return chan.attrs[attr].value


def write_attr(ctx, device, channel, attr, value, output=False):
    """One attribute, written now. Raises -- a calibration that half
    applied is worse than one that did not run."""
    dev = _dev(ctx, device)
    if channel is None:
        dev.attrs[attr].value = str(value)
        return
    chan = dev.find_channel(channel, output)
    if chan is None:
        raise LookupError("no %s channel %r on %s"
                          % ("output" if output else "input", channel, device))
    chan.attrs[attr].value = str(value)


def calibration_mode(ctx, mode):
    """Point the front end at ground, a reference, or the generators."""
    write_attr(ctx, DEV_FABRIC, None, "calibration_mode", mode)
    time.sleep(SETTLE)


def capture(ctx, samples, rate, range_name):
    """Average both ADC channels over `samples`, in raw counts.

    The first refill is thrown away. A buffer created immediately after a
    range change or a mode change contains the tail of the old state, and
    it is a large enough fraction of a short capture to move the answer.
    """
    import numpy as np
    import iio

    adc = _dev(ctx, DEV_ADC)
    adc.attrs["sampling_frequency"].value = str(int(rate))
    for name in ADC_CHANNELS:
        write_attr(ctx, DEV_FABRIC, name, "gain", range_name)
        write_attr(ctx, DEV_FABRIC, name, "powerdown", 0)

    chans = [adc.find_channel(name, False) for name in ADC_CHANNELS]
    for chan in chans:
        chan.enabled = True

    buf = iio.Buffer(adc, CHUNK, False)
    try:
        buf.refill()                                  # settling, discarded
        totals = [0.0, 0.0]
        taken = 0
        while taken < samples:
            buf.refill()
            for i, chan in enumerate(chans):
                block = np.frombuffer(bytes(chan.read(buf)), dtype="<i2")
                totals[i] += float(block.sum())
            taken += CHUNK
        return [total / taken for total in totals]
    finally:
        del buf
        for chan in chans:
            chan.enabled = False


class held_dac(object):
    """Hold one generator at a constant raw code, for as long as we ask.

    A cyclic buffer keeps repeating after push() returns, which is how
    libm2k presents a DC level to its own ADC. The buffer object has to
    stay alive to stay playing, hence the context manager.
    """

    def __init__(self, ctx, output, raw, rate=750000):
        self.ctx, self.output, self.raw, self.rate = ctx, output, raw, rate
        self.buf = self.chan = None

    def __enter__(self):
        import numpy as np
        import iio

        dev = _dev(self.ctx, DAC_DEVICE[self.output])
        dev.attrs["sampling_frequency"].value = str(int(self.rate))
        write_attr(self.ctx, DEV_FABRIC, FABRIC_OUTPUT[self.output],
                   "powerdown", 0, output=True)

        self.chan = dev.find_channel("voltage0", True)
        self.chan.enabled = True
        self.buf = iio.Buffer(dev, 1024, True)
        # The DAC word is 12 bits in the top of 16, as everywhere else on
        # this board. libm2k's processRawSample negates as well, which for
        # a raw of 0 makes no difference and is left explicit anyway.
        word = (-int(self.raw)) << 4
        data = np.full(1024, word, dtype="<i2")
        # bytearray, not bytes: pylibiio hands the buffer to ctypes
        # from_buffer(), which refuses anything immutable.
        self.chan.write(self.buf, bytearray(data.tobytes()))
        self.buf.push()
        time.sleep(SETTLE)
        return self

    def __exit__(self, *exc):
        del self.buf
        self.buf = None
        if self.chan is not None:
            self.chan.enabled = False
        write_attr(self.ctx, DEV_FABRIC, FABRIC_OUTPUT[self.output],
                   "powerdown", 1, output=True)
        return False


# The registers this script is allowed to change, as
# (device, channel, attr, output). Everything here is read before the run
# and put back if it does not finish.
TOUCHED = (
    [(DEV_FABRIC, None, "calibration_mode", False)]
    + [(DEV_ADC, ch, "calibbias", False) for ch in ADC_CHANNELS]
    + [(DEV_ADC, ch, "calibscale", False) for ch in ADC_CHANNELS]
    + [(DEV_TRIM, ch, "raw", True)
       for ch in list(TRIM_DAC.values()) + TRIM_ADC]
    + [(DEV_FABRIC, ch, "gain", False) for ch in ADC_CHANNELS]
    + [(DEV_FABRIC, ch, "powerdown", False) for ch in ADC_CHANNELS]
    + [(DEV_FABRIC, ch, "powerdown", True)
       for ch in FABRIC_OUTPUT.values()]
)


class saved_state(object):
    """Read every register this script touches, and put them all back.

    Restores on the way out whatever happened, including a traceback.
    Leaving a board in adc_gnd is leaving a board that reads zero on
    everything and looks broken rather than uncalibrated.

    `keep` is the set of (device, channel, attr) the caller has
    deliberately written and wants to survive -- the calibration itself.
    """

    def __init__(self, ctx):
        self.ctx = ctx
        self.before = {}
        self.keep = set()

    def __enter__(self):
        for device, channel, attr, output in TOUCHED:
            try:
                self.before[(device, channel, attr, output)] = read_attr(
                    self.ctx, device, channel, attr, output)
            except Exception as exc:                       # noqa: BLE001
                print("  cannot read %s/%s %s (%s); it will not be restored"
                      % (device, channel, attr, exc), file=sys.stderr)
        return self

    def __exit__(self, *exc):
        for (device, channel, attr, output), value in self.before.items():
            if (device, channel, attr) in self.keep:
                continue
            try:
                write_attr(self.ctx, device, channel, attr, value, output)
            except Exception as err:                       # noqa: BLE001
                print("  could not restore %s/%s %s to %s (%s)"
                      % (device, channel, attr, value, err), file=sys.stderr)
        return False


# --------------------------------------------------------------------
# The steps.
# --------------------------------------------------------------------

def _sweep(ctx, rate, range_name, label, values, setter, fmt="%s"):
    """Set a knob to each value, capture, and report the slope per channel.

    Returns the counts-per-unit slope for each channel, or None where the
    samples did not move at all -- which is the interesting answer.
    """
    rows = []
    for value in values:
        setter(value)
        time.sleep(SETTLE)
        means = capture(ctx, OFFSET_SAMPLES, rate, range_name)
        rows.append((value, means))
        print(("  %s " + fmt + " -> in1 %+9.3f  in2 %+9.3f counts")
              % (label, value, means[0], means[1]))

    slopes = []
    for i, name in enumerate(("in1", "in2")):
        span = rows[-1][1][i] - rows[0][1][i]
        width = rows[-1][0] - rows[0][0]
        if abs(span) < 1.0:
            slopes.append(None)
            print("    %s: INERT -- the driver does not apply %s"
                  % (name, label))
        else:
            slopes.append(span / width)
            print("    %s: %+.4f counts per unit of %s"
                  % (name, span / width, label))
    return slopes


def probe(ctx, rate, range_name):
    """Find where the offset and gain knobs actually are.

    The IIO ABI offers three plausible places to correct an input, and a
    name is not evidence that a register does anything:

        m2k-adc calibbias    a software-looking offset, 2048 neutral
        m2k-adc calibscale   a software-looking gain, 1.0 neutral
        ad5625 voltage2/3    a real DAC wired into the front end

    libm2k applies the first two itself, in software, which leaves open
    whether the driver also applies them -- and everything downstream
    depends on the answer. If they are inert the blocks have to do the
    applying and the script only computes; if the ad5625 is the live one,
    the offset is a hardware trim like the generator's and there is
    nothing for the blocks to do at all.

    Three sweeps in adc_gnd, where the input is a known zero and any
    movement in the average is the knob and not the signal.
    """
    print("probe: which registers actually reach the samples?")
    print("  mode adc_gnd, range %s, %d S/s, %d samples per point\n"
          % (range_name, rate, OFFSET_SAMPLES))
    calibration_mode(ctx, "adc_gnd")

    def set_bias(code):
        for ch in ADC_CHANNELS:
            write_attr(ctx, DEV_ADC, ch, "calibbias", code)

    def set_scale(value):
        for ch in ADC_CHANNELS:
            write_attr(ctx, DEV_ADC, ch, "calibscale", "%.6f" % value)

    def set_trim(code):
        for ch in TRIM_ADC:
            write_attr(ctx, DEV_TRIM, ch, "raw", code, output=True)

    print("1. m2k-adc calibbias")
    bias = _sweep(ctx, rate, range_name, "calibbias",
                  (NEUTRAL - 100, NEUTRAL, NEUTRAL + 100), set_bias, "%4d")
    set_bias(NEUTRAL)

    # A grounded input is not reading zero -- in1 sits near -13 counts --
    # so a gain that was being applied would scale that offset visibly.
    print("\n2. m2k-adc calibscale")
    scale = _sweep(ctx, rate, range_name, "calibscale",
                   (0.5, 1.0, 2.0), set_scale, "%.3f")
    set_scale(1.0)

    print("\n3. ad5625 voltage2/voltage3 -- the hardware vertical offset")
    trim = _sweep(ctx, rate, range_name, "ad5625 raw",
                  (NEUTRAL - 100, NEUTRAL, NEUTRAL + 100), set_trim, "%4d")
    set_trim(NEUTRAL)

    print("\nverdict")
    live = [name for name, slopes in (("calibbias", bias),
                                      ("calibscale", scale),
                                      ("ad5625 voltage2/3", trim))
            if any(s is not None for s in slopes)]
    if not live:
        print("  nothing the driver offers changes a sample. Every"
              "\n  correction has to be applied by the blocks, in software,"
              "\n  and this script's job is to compute and store them.")
    else:
        print("  live: %s" % ", ".join(live))
        if trim[0] is not None:
            print("  the ad5625 is a real DAC in the front end, so the ADC"
                  "\n  offset is a hardware trim like the generator's --"
                  "\n  set it and the samples come back already correct.")


# How far to push the trim DAC when measuring its slope. Big enough that
# the movement dwarfs the noise -- 100 codes is about 175 counts against
# an averaging noise floor under a twentieth of a count -- and small
# enough to stay on scale.
SLOPE_STEP = 100


def neutralise(ctx):
    """Every correction off, so a measurement measures the board.

    calibscale in particular: the driver applies it, so leaving a gain in
    place while measuring an offset scales the offset, and measuring the
    gain with a gain already applied returns 1.0 no matter what the board
    does.
    """
    for ch in ADC_CHANNELS:
        write_attr(ctx, DEV_ADC, ch, "calibscale", "1.000000")
    for ch in TRIM_ADC:
        write_attr(ctx, DEV_TRIM, ch, "raw", NEUTRAL, output=True)


def measure_adc_offset(ctx, rate, range_name):
    """Per channel: the ad5625 code that zeroes a grounded input.

    Three captures. One at neutral gives the offset, one at
    neutral + SLOPE_STEP gives how much a code is worth, and the solve
    needs both. calibbias is not touched -- --probe showed the driver
    ignores it, so writing it would be theatre.
    """
    calibration_mode(ctx, "adc_gnd")
    neutralise(ctx)
    time.sleep(SETTLE)
    at_neutral = capture(ctx, OFFSET_SAMPLES, rate, range_name)

    for ch in TRIM_ADC:
        write_attr(ctx, DEV_TRIM, ch, "raw", NEUTRAL + SLOPE_STEP, output=True)
    time.sleep(SETTLE)
    at_step = capture(ctx, OFFSET_SAMPLES, rate, range_name)

    for ch in TRIM_ADC:
        write_attr(ctx, DEV_TRIM, ch, "raw", NEUTRAL, output=True)

    slopes = [counts_per_code([(NEUTRAL, at_neutral[i]),
                               (NEUTRAL + SLOPE_STEP, at_step[i])])
              for i in range(len(ADC_CHANNELS))]
    codes = [adc_offset_code(at_neutral[i], slopes[i])
             for i in range(len(ADC_CHANNELS))]
    return at_neutral, slopes, codes


def fine_tune(ctx, rate, range_name, codes):
    """Sweep +/-FINE_SPAN and keep whichever code reads closest to zero.

    A trim code is 1.75 counts, so the best any solve can do is settle
    within about one count and the sweep is what closes the last of it.
    Only reached when the residual asks for it; libm2k always sweeps,
    which costs twenty-one captures and hides whether the arithmetic was
    right in the first place.
    """
    best = list(codes)
    for i, ch in enumerate(TRIM_ADC):
        scores = []
        for delta in range(-FINE_SPAN, FINE_SPAN + 1):
            code = clamp_code(codes[i] + delta)
            write_attr(ctx, DEV_TRIM, ch, "raw", code, output=True)
            time.sleep(0.02)
            mean = capture(ctx, CHUNK, rate, range_name)[i]
            scores.append((abs(mean), code, mean))
        scores.sort()
        best[i] = scores[0][1]
        print("    ad5625 %s: swept %d..%d, best %d at %+.3f counts"
              % (ch, codes[i] - FINE_SPAN, codes[i] + FINE_SPAN,
                 best[i], scores[0][2]))
        write_attr(ctx, DEV_TRIM, ch, "raw", best[i], output=True)
    return best


def filter_compensation(range_name, rate):
    """The decimation filter's gain at `rate`, against 100 MS/s.

    libm2k sidesteps this by calibrating at 100 MS/s, where it is 1. We
    calibrate at the rate the workshop uses, so calibration-mode counts
    get referred back before CAL_MODE_VPC turns them into volts. The
    range cancels, which is the point -- calibration mode does not go
    through the range amplifier.
    """
    from m2k_blocks.m2k_scale import volts_per_count

    return volts_per_count(range_name, rate) / \
        volts_per_count(range_name, 100000000)


def measure_adc_gain(ctx, rate, range_name):
    """Per channel: the calibscale that makes 0.46172 V read 0.46172 V.

    The baseline is subtracted here where libm2k does not subtract it --
    it relies on the offset trim from the step before having already
    pulled adc_gnd to zero. Ours has too, but measuring the ground again
    costs one capture and makes the gain independent of how well that
    landed.
    """
    for ch in ADC_CHANNELS:
        write_attr(ctx, DEV_ADC, ch, "calibscale", "1.000000")
    compensation = filter_compensation(range_name, rate)

    calibration_mode(ctx, "adc_gnd")
    ground = capture(ctx, OFFSET_SAMPLES, rate, range_name)
    calibration_mode(ctx, "adc_ref1")
    means = capture(ctx, GAIN_SAMPLES, rate, range_name)

    volts = [cal_mode_volts(mean - base, compensation)
             for mean, base in zip(means, ground)]
    return volts, [adc_gain(v) for v in volts]


# Where the generator sweep is taken. Wide enough that the fit is not
# reading noise, inside the loopback's linear span at both ends.
DAC_SWEEP_RAW = (-400, -200, 0, 200, 400)


def held_dac_volts(raw):
    """What held_dac(raw) actually asks the generator for, in volts.

    held_dac negates before shifting, following libm2k's
    processRawSample. m2k_scale's dac_raw_to_volts negates again on the
    way back, so the two cancel and the sign here is not guessable from
    either one alone -- which is exactly why it lives next to held_dac
    instead of being written out at the call site.
    """
    from m2k_blocks.m2k_scale import dac_raw_to_volts, DAC_SHIFT

    return dac_raw_to_volts((-int(raw)) << DAC_SHIFT)


def measure_dac_offset(ctx, rate, range_name):
    """Per output: what it puts out at zero, and the trim that cancels it.

    A sweep rather than libm2k's single capture at raw 0. Five points
    give the offset as a zero crossing, which needs no loopback divider
    and no volts-per-count -- and the worst residual off the fitted line
    says, every run, whether the path was straight enough to believe.
    """
    calibration_mode(ctx, "dac")
    out = {}
    for i, output in enumerate(("w1", "w2")):
        points = []
        for raw in DAC_SWEEP_RAW:
            with held_dac(ctx, output, raw):
                mean = capture(ctx, OFFSET_SAMPLES, rate, range_name)[i]
            points.append((held_dac_volts(raw), mean))
        slope, intercept = line_fit(points)
        volts = offset_from_sweep(points)
        out[output] = (volts, dac_offset_code(volts),
                       slope, worst_residual(points, slope, intercept))
    return out


def park(ctx):
    """Front end back on the BNCs, outputs off, generators at zero."""
    calibration_mode(ctx, "none")
    for output in ("w1", "w2"):
        try:
            write_attr(ctx, DAC_DEVICE[output], "voltage0", "raw", 0,
                       output=True)
        except Exception:                                  # noqa: BLE001
            pass
        write_attr(ctx, DEV_FABRIC, FABRIC_OUTPUT[output], "powerdown", 1,
                   output=True)
    for ch in ADC_CHANNELS:
        write_attr(ctx, DEV_FABRIC, ch, "powerdown", 1)


def reset(ctx):
    """Every calibration register back to neutral."""
    print("reset: every calibration register back to neutral")
    for ch in ADC_CHANNELS:
        # calibbias does nothing on this firmware, but a board left with a
        # stale value in it invites the next person to believe it does.
        write_attr(ctx, DEV_ADC, ch, "calibbias", NEUTRAL)
        write_attr(ctx, DEV_ADC, ch, "calibscale", "1.000000")
        print("  m2k-adc %s calibbias=%d calibscale=1.000000" % (ch, NEUTRAL))
    for ch in list(TRIM_DAC.values()) + TRIM_ADC:
        write_attr(ctx, DEV_TRIM, ch, "raw", NEUTRAL, output=True)
        print("  ad5625 %s raw=%d" % (ch, NEUTRAL))
    calibration_mode(ctx, "none")


# What the meter said on 2026-09-03, printed alongside each measurement so
# a disagreement is visible instead of invisible. Not used in any
# arithmetic -- these are the check, not the input.
METERED = {
    "in1_offset_counts": -13.8,
    "in2_offset_counts": +40.8,
    "in1_gain": 1.0 / 0.93686,
    "in2_gain": 1.0 / 0.93199,
    "w1_offset_v": 0.0485,
    "w2_offset_v": 0.1121,
}


def calibrate(ctx, rate, range_name, apply_it):
    """The whole pass.

    Every correction is written as it is found, whether or not this is a
    dry run, because each step measures through the ones before it: the
    gain is measured on an input whose offset has been zeroed, and the
    generators are measured through an input that has been fully
    corrected. A dry run that skipped the writes would report numbers
    nobody will ever see again.

    What --apply decides is only what survives. `saved_state` puts back
    every register the run is not keeping, so a dry run leaves the board
    exactly as it found it.
    """
    from m2k_blocks.m2k_scale import volts_per_count

    per_count = volts_per_count(range_name, rate)
    print("calibrating at %d S/s on the %s range (%s)"
          % (rate, range_name,
             "writing" if apply_it else "DRY RUN -- nothing will be kept"))
    print("  one count is %.6f V here\n" % per_count)

    with saved_state(ctx) as state:
        def keep(device, channel, attr):
            if apply_it:
                state.keep.add((device, channel, attr))

        print("1. ADC offset -- inputs on internal ground, trimmed by the "
              "ad5625")
        means, slopes, codes = measure_adc_offset(ctx, rate, range_name)
        for i, ch in enumerate(TRIM_ADC):
            implied = slopes[i] * per_count
            print("   in%d: %+8.3f counts (meter said %+.1f), %.4f counts "
                  "per code" % (i + 1, means[i],
                                METERED["in%d_offset_counts" % (i + 1)],
                                slopes[i]))
            print("        a code is %.6f V here against libm2k's %.6f "
                  "-> ad5625 %s raw %d"
                  % (implied, AD5625_LSB_AT_DAC, ch, codes[i]))

        for i, ch in enumerate(TRIM_ADC):
            write_attr(ctx, DEV_TRIM, ch, "raw", codes[i], output=True)
            keep(DEV_TRIM, ch, "raw")
        time.sleep(SETTLE)
        residual = capture(ctx, OFFSET_SAMPLES, rate, range_name)
        print("   residual: %+.3f / %+.3f counts" % tuple(residual))
        bar = max(fine_tolerance(slope) for slope in slopes)
        if max(abs(r) for r in residual) > bar:
            print("   outside %.2f count (half a trim code) -- fine tuning"
                  % bar)
            codes = fine_tune(ctx, rate, range_name, codes)
            residual = capture(ctx, OFFSET_SAMPLES, rate, range_name)
            print("   residual now: %+.3f / %+.3f counts (a code is worth "
                  "%.2f, so this is the floor)" % (residual[0], residual[1],
                                                   max(slopes)))

        print("\n2. ADC gain -- inputs on the internal %.5f V reference"
              % VREF1)
        volts, gains = measure_adc_gain(ctx, rate, range_name)
        for i, ch in enumerate(ADC_CHANNELS):
            print("   in%d: read %.6f V -> calibscale %.6f (meter said "
                  "%.6f)" % (i + 1, volts[i], gains[i],
                             METERED["in%d_gain" % (i + 1)]))

        if max(abs(g - 1.0) for g in gains) < 0.005:
            print("\n   STOP. Both gains came back within 0.5%% of unity, and"
                  "\n   the meter says this board reads 6.5%% low. adc_ref1 is"
                  "\n   not on the path we think it is. Nothing kept.")
            park(ctx)
            return 1

        for i, ch in enumerate(ADC_CHANNELS):
            write_attr(ctx, DEV_ADC, ch, "calibscale", "%.6f" % gains[i])
            keep(DEV_ADC, ch, "calibscale")

        print("\n3. Generator offset -- W1 and W2 swept through the "
              "internal loopback")
        dac = measure_dac_offset(ctx, rate, range_name)
        for output in ("w1", "w2"):
            output_volts, code, slope, residual_counts = dac[output]
            metered = METERED["%s_offset_v" % output]
            print("   %s: %+.1f counts per volt out, straight to %.2f "
                  "counts over the sweep" % (output.upper(), slope,
                                             residual_counts))
            print("       offset %+.4f V (meter said %+.4f, %+.1f mV "
                  "apart) -> ad5625 %s raw %d"
                  % (output_volts, metered,
                     (output_volts - metered) * 1000.0,
                     TRIM_DAC[output], code))

        for output in ("w1", "w2"):
            write_attr(ctx, DEV_TRIM, TRIM_DAC[output], "raw",
                       dac[output][1], output=True)
            keep(DEV_TRIM, TRIM_DAC[output], "raw")

        print("\n4. Parking")
        park(ctx)

    if apply_it:
        print("\nwritten and held. Check it against the meter:")
        print("  python3 bench/dc_point.py 0.0 --output w1 --meter <V>")
        print("  python3 bench/dc_point.py 1.0 --output w1 --meter <V>")
    else:
        print("\nnothing kept -- the board is back as it was.")
        print("Re-run with --apply to hold these.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Calibrate the M2K's analog front end from its own "
                    "internal references.")
    ap.add_argument("--uri", default="ip:192.168.2.1")
    ap.add_argument("--rate", type=int, default=1000000,
                    help="ADC sample rate during calibration (default 1e6)")
    ap.add_argument("--range", dest="range_name", default="high",
                    choices=("low", "high"),
                    help="input range to calibrate; 'high' is +/-2.5 V")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--probe", action="store_true",
                      help="measure what calibbias does, write nothing lasting")
    mode.add_argument("--apply", action="store_true",
                      help="write the results; without it this is a dry run")
    mode.add_argument("--reset", action="store_true",
                      help="put every calibration register back to neutral")
    args = ap.parse_args(argv)

    ctx = context(args.uri)

    try:
        if args.reset:
            reset(ctx)
            return 0
        if args.probe:
            with saved_state(ctx):
                probe(ctx, args.rate, args.range_name)
            return 0
        return calibrate(ctx, args.rate, args.range_name, args.apply)
    except KeyboardInterrupt:
        print("\ninterrupted -- restoring", file=sys.stderr)
        park(ctx)
        return 130


if __name__ == "__main__":
    sys.exit(main())
