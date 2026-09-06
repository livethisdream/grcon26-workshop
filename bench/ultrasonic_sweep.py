"""Sweep W1 across the transducer's band and find where it actually resonates.

A 40 kHz transducer is a mechanical filter with a couple of kHz of
bandwidth, and "40 kHz" is the number on the bag, not the number on the
part. Everything downstream -- the burst frequency for ranging, the two
tones for FSK -- needs the real one, so this measurement comes first.

    W1 -> TX transducer -> GND
    RX transducer -> 1+, its other leg -> 1- and GND

Transducers facing each other, a hand's width apart. No amplifier: the
disc is about 2 nF, roughly 2 kOhm at 40 kHz, and a 50 Ohm generator
does not notice that load.

Three runs give the four numbers the demo needs:

    as wired                 f0 and the -6 dB bandwidth
    at several distances     amplitude vs range, i.e. do we need gain
    receiver turned away     the electrical crosstalk floor

WHAT THIS DOES NOT DO is ask for a frequency and believe it got one. A
cyclic buffer of N samples repeats forever, so the generator can only
produce multiples of rate/N -- ask for 40.1 kHz with a round buffer and
you get 40.09 kHz and no warning. So the buffer length is chosen per
point to hold a whole number of cycles, and the frequency printed is the
one the hardware really made. The requested and actual columns differing
in the last digits is the trap being handled, not a bug.

Amplitude is measured by correlating the capture against the tone that
was actually generated, windowed -- a one-bin DFT. That rejects
everything off-frequency, which matters because the interesting part of
this measurement is 20 dB down the skirt of a resonance.

Conditions, which have to match anything this is combined with:

    generator 750 kS/s      the third rung of the DAC's rate ladder
    scope     1 MS/s        the third rung of the ADC's, and not the same
    input 1 'high'          the +/-2.5 V range, despite the name

Run from the repo root, with a gnuradio interpreter:

    python3 bench/ultrasonic_sweep.py
    python3 bench/ultrasonic_sweep.py --start 38000 --stop 42000 --step 50
    python3 bench/ultrasonic_sweep.py --csv /tmp/sweep.csv --label crosstalk

The arithmetic here imports nothing, so tests/test_ultrasonic_sweep.py
checks it on a machine with no GNU Radio and no board.
"""
import argparse
import cmath
import math
import os
import sys

URI = "ip:192.168.2.1"
GEN_RATE, SCOPE_RATE = 750000, 1000000
RANGE = "high"                 # the +/-2.5 V one
SCOPE_BUF = 16384
SETTLE, CAPTURE = 1.2, 0.05    # config writes land ~1 s in; 50 ms is 2000 cycles
ANALYSE = 32768                # samples per point actually correlated

# The DAC takes buffer lengths in whole multiples of this. Keeping to it
# costs a few Hz of frequency error and avoids finding out the hard way.
BUFFER_GRANULARITY = 4
TARGET_BUFFER = 8192

# Full scale is +/-2048 counts whatever the range is called, so clipping
# is a count, not a voltage. Leave a few counts of margin.
CLIP_COUNTS = 2040


# ------------------------------------------------------------------ arithmetic

def cyclic_buffer(freq, rate, target=TARGET_BUFFER,
                  granularity=BUFFER_GRANULARITY, span=0.35):
    """Pick a cyclic buffer length that holds a whole number of cycles.

    Returns (length, cycles, actual_freq). The generator repeats the
    buffer, so the tone it emits is exactly cycles * rate / length -- a
    length that does not divide evenly is a frequency error that no
    amount of care downstream can undo.

    Searches lengths near `target` that are multiples of `granularity`
    and keeps the one whose achievable frequency is closest to what was
    asked for, breaking ties toward the target length.
    """
    if freq <= 0:
        raise ValueError("frequency must be positive, got %r" % (freq,))
    if freq * 2 >= rate:
        raise ValueError(
            "%g Hz is at or above Nyquist for a %g S/s generator" % (freq, rate))

    low = max(granularity, int(target * (1.0 - span)))
    high = int(target * (1.0 + span))

    best = None
    for length in range(low - low % granularity + granularity, high + 1,
                        granularity):
        cycles = int(round(length * freq / float(rate)))
        if cycles < 1:
            continue
        actual = cycles * float(rate) / length
        key = (abs(actual - freq), abs(length - target))
        if best is None or key < best[0]:
            best = (key, length, cycles, actual)

    if best is None:                # only if the whole window is below one cycle
        raise ValueError("no usable buffer length near %d for %g Hz"
                         % (target, freq))
    return best[1], best[2], best[3]


def sine(length, cycles, amplitude):
    """One cyclic buffer's worth of sine, closing exactly on itself."""
    step = 2.0 * math.pi * cycles / length
    return [amplitude * math.sin(step * n) for n in range(length)]


def tone_amplitude(samples, freq, rate):
    """Peak amplitude of a tone at `freq`, by correlating with it.

    A Hann window before the correlation, because the record does not
    hold a whole number of cycles and the leakage from that would show up
    as ripple along the sweep -- which is exactly the shape we are trying
    to read.

    For x[n] = A cos(wn + phi) the windowed correlation sums to
    (A/2) exp(j phi) * sum(w), so A is 2|X| / sum(w).
    """
    count = len(samples)
    if count == 0:
        return 0.0
    step = 2.0 * math.pi * freq / rate
    total = 0j
    weight = 0.0
    for n, value in enumerate(samples):
        w = 0.5 - 0.5 * math.cos(2.0 * math.pi * n / count)
        weight += w
        total += w * value * cmath.exp(-1j * step * n)
    return 2.0 * abs(total) / weight if weight else 0.0


def rms(samples):
    """Root mean square of the whole capture, tone and everything else."""
    if not samples:
        return 0.0
    return math.sqrt(sum(v * v for v in samples) / len(samples))


def off_tone_rms(samples, amplitude):
    """What is left once the tone's own power is taken out.

    A sine of peak amplitude A carries A^2/2 of mean square, so the rest
    is whatever the total has above that. Clamped at zero: a measurement
    slightly below its own tone is rounding, not negative noise.
    """
    rest = rms(samples) ** 2 - amplitude * amplitude / 2.0
    return math.sqrt(rest) if rest > 0 else 0.0


def db(value, reference):
    """Ratio in dB, with a floor so an empty channel prints rather than raises."""
    if value <= 0 or reference <= 0:
        return float("-inf")
    return 20.0 * math.log10(value / reference)


def _cross(points, peak, direction, fraction):
    """Where the curve falls through `fraction` of the peak, walking outward.

    Linear interpolation between the last point above and the first below.
    None when the sweep ended before the curve got there -- which means
    the span was too narrow, and saying so beats extrapolating.
    """
    target = points[peak][1] * fraction
    index = peak
    while 0 <= index + direction < len(points):
        index += direction
        if points[index][1] <= target:
            f_in, a_in = points[index - direction]
            f_out, a_out = points[index]
            if a_in == a_out:
                return f_out
            return f_in + (a_in - target) * (f_out - f_in) / (a_in - a_out)
    return None


def resonance(points, fraction=0.5):
    """Peak and -6 dB edges of a swept response.

    `points` is [(freq, amplitude), ...] in frequency order. The default
    fraction of 0.5 is half amplitude, which is -6 dB -- the convention
    for a transducer, and not the -3 dB half-power one.
    """
    if not points:
        raise ValueError("no points to find a resonance in")
    peak = max(range(len(points)), key=lambda i: points[i][1])
    low = _cross(points, peak, -1, fraction)
    high = _cross(points, peak, +1, fraction)
    return {
        "f0": points[peak][0],
        "amplitude": points[peak][1],
        "low": low,
        "high": high,
        "bandwidth": (high - low) if (low is not None and high is not None)
                     else None,
    }


# Half amplitude and half power are different edges. A transducer is
# specified at -6 dB, which is where amplitude halves; Q is defined
# against the -3 dB bandwidth, which is narrower by sqrt(3) for a
# single resonance. Reporting the -6 dB number as Q makes the part look
# lower-Q than it is and understates the ringdown by the same factor.
SIXDB_TO_THREEDB = 1.0 / math.sqrt(3.0)


def quality_factor(f0, six_db_bandwidth):
    """Q from a -6 dB bandwidth, converted to the -3 dB one it is defined on."""
    if six_db_bandwidth <= 0:
        raise ValueError("bandwidth must be positive, got %r"
                         % (six_db_bandwidth,))
    return f0 / (six_db_bandwidth * SIXDB_TO_THREEDB)


def ringdown(f0, q, floor_db=40.0):
    """How long the resonator keeps sounding after the drive stops.

    It decays with a time constant of Q / (pi * f0), so reaching
    `floor_db` below the drive takes that many time constants times
    ln(10) * floor_db / 20. This sets the blind zone: nothing new can be
    heard until the receiver has gone quiet.
    """
    return (math.log(10.0) * floor_db / 20.0) * q / (math.pi * f0)


def bar(value, peak, width=34):
    """One row of an ASCII response curve."""
    if peak <= 0:
        return ""
    return "#" * int(round(width * max(0.0, value) / peak))


# -------------------------------------------------------------------- hardware

def measure(freq, amplitude, uri, input_range):
    """Generate one tone, capture it, return what came back.

    GNU Radio is imported here rather than at the top so that everything
    above can be tested without it.
    """
    import time
    from gnuradio import gr, blocks

    sys.path.insert(0, "gr-m2k")
    from m2k_blocks.analog_sink import analog_sink
    from m2k_blocks.analog_source import analog_source
    from m2k_blocks.m2k_scale import volts_per_count

    length, cycles, actual = cyclic_buffer(freq, GEN_RATE)

    tb = gr.top_block("ultrasonic_sweep")
    wave = blocks.vector_source_f(sine(length, cycles, amplitude), True)
    gen = analog_sink(uri, output="w1", sample_rate=GEN_RATE, units="volts",
                      buffer_size=length, cyclic=True)
    tb.connect(wave, gen)

    scope = analog_source(uri, ch1_enabled=True, ch2_enabled=False,
                          sample_rate=SCOPE_RATE, ch1_range=input_range,
                          buffer_size=SCOPE_BUF, units="volts",
                          trigger_source="off")
    captured = blocks.vector_sink_f()
    tb.connect((scope, 0), captured)

    # start/stop/wait, never run(): the config keep-alive never finishes.
    tb.start()
    time.sleep(SETTLE)
    captured.reset()
    time.sleep(CAPTURE)
    tb.stop()
    tb.wait()

    samples = list(captured.data())[:ANALYSE]
    volts = tone_amplitude(samples, actual, SCOPE_RATE)
    clip = CLIP_COUNTS * volts_per_count(input_range, SCOPE_RATE)
    return {
        "requested": freq,
        "actual": actual,
        "length": length,
        "cycles": cycles,
        "amplitude": volts,
        "noise": off_tone_rms(samples, volts),
        "samples": len(samples),
        "clipped": any(abs(v) >= clip for v in samples),
    }


# ------------------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--start", type=float, default=36000.0)
    ap.add_argument("--stop", type=float, default=44000.0)
    ap.add_argument("--step", type=float, default=100.0)
    ap.add_argument("--amplitude", type=float, default=4.0,
                    help="drive amplitude in volts, peak (default 4.0)")
    ap.add_argument("--range", dest="input_range", default=RANGE,
                    choices=("low", "high"),
                    help="input range; 'high' is the +/-2.5 V one")
    ap.add_argument("--uri", default=URI)
    ap.add_argument("--csv", default=None, help="also write the sweep here")
    ap.add_argument("--label", default=None,
                    help="tag for this run, e.g. 'crosstalk' or '30cm'")
    args = ap.parse_args()

    if args.step <= 0:
        ap.error("--step must be positive")
    if args.stop < args.start:
        ap.error("--stop must not be below --start")

    count = int(round((args.stop - args.start) / args.step)) + 1
    requests = [args.start + i * args.step for i in range(count)]

    print()
    print("  sweep %s  %.0f - %.0f Hz in %.0f Hz steps, %d points"
          % (args.label or "", args.start, args.stop, args.step, count))
    print("  W1 at %.2f V peak, %d S/s   input 1 range '%s', %d S/s"
          % (args.amplitude, GEN_RATE, args.input_range, SCOPE_RATE))
    print()
    print("     requested     actual    buffer      amp      SNR")

    results = []
    for freq in requests:
        row = measure(freq, args.amplitude, args.uri, args.input_range)
        results.append(row)
        print("   %9.1f  %9.1f  %5d/%-4d  %7.2f mV  %5.1f dB%s"
              % (row["requested"], row["actual"], row["length"], row["cycles"],
                 row["amplitude"] * 1000.0,
                 db(row["amplitude"], row["noise"]),
                 "   CLIPPED" if row["clipped"] else ""))

    points = [(r["actual"], r["amplitude"]) for r in results]
    found = resonance(points)
    peak = found["amplitude"]

    print()
    print("  response, relative to the peak")
    print()
    for row in results:
        print("   %9.1f Hz  %7.1f dB  %s"
              % (row["actual"], db(row["amplitude"], peak),
                 bar(row["amplitude"], peak)))

    print()
    print("  f0            %9.1f Hz   at %.2f mV" % (found["f0"], peak * 1000.0))
    if found["bandwidth"] is not None:
        print("  -6 dB band    %9.1f - %.1f Hz" % (found["low"], found["high"]))
        q = quality_factor(found["f0"], found["bandwidth"])
        print("  bandwidth     %9.1f Hz   at -6 dB, so Q = %.1f"
              % (found["bandwidth"], q))
        ring = ringdown(found["f0"], q)
        print("  ringdown      %9.3f ms  to -40 dB, i.e. about %.0f cm of blind path"
              % (ring * 1000.0, ring * 343.0 * 100.0))
    else:
        side = "below" if found["low"] is None else "above"
        print("  -6 dB band    not reached %s the peak -- widen the sweep" % side)

    if any(r["clipped"] for r in results):
        print()
        print("  Some points clipped the input. Lower --amplitude or move the")
        print("  transducers apart; the amplitudes above are not trustworthy.")

    if args.csv:
        with open(args.csv, "w") as handle:
            handle.write("requested_hz,actual_hz,buffer,cycles,amplitude_v,"
                         "noise_v,clipped\n")
            for row in results:
                handle.write("%.3f,%.3f,%d,%d,%.9f,%.9f,%d\n"
                             % (row["requested"], row["actual"], row["length"],
                                row["cycles"], row["amplitude"], row["noise"],
                                int(row["clipped"])))
        print()
        print("  wrote %s" % os.path.abspath(args.csv))
    print()


if __name__ == "__main__":
    main()
