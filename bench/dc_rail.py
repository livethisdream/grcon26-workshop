"""Command a rail, measure it, and let the meter settle the arithmetic.

The conversion in m2k_scale came out of libm2k's source and has never
met a meter:

    raw = (volts * gain + offset) * 4095 / (rail_gain * 1.2)

with rail_gain 5.02 for V+ and -5.1 for V-. Both of those are somebody
else's measurement of somebody else's board. This walks a rail across
two or more setpoints, reads each one back through the scope, and -- if
you type in what the meter says -- fits the line that maps what we
command to what the rail actually does.

    V+ -> 1+, 1- -> GND, meter across V+ and GND     (default)
    V- -> 1+, 1- -> GND, meter across V- and GND     (--rail negative)

The rails reach 5 V, so the capture uses the '+/-25 V' input range,
which is the one confusingly called 'low'. At 1 MS/s that is about
16 mV per count, so a single sample is a coarse instrument; the mean of
a buffer is not.

Nothing is disturbed between points. The rail holds its setpoint with
the flowgraph stopped, which is what makes reading a meter unhurried.

Run from the repo root, with a gnuradio interpreter:

    python3 bench/dc_rail.py                        # 1 V and 5 V on V+
    python3 bench/dc_rail.py 1 5 --meter 1.002 4.987
    python3 bench/dc_rail.py --rail negative -1 -5
    python3 bench/dc_rail.py --uncorrected 5        # cal,*_dac left out
    python3 bench/dc_rail.py --off                  # rail down, then stop
"""
import sys, time, argparse
sys.path.insert(0, "gr-m2k")
from gnuradio import gr, blocks
from m2k_blocks.analog_source import analog_source
from m2k_blocks.power_supply import power_supply
from m2k_blocks.m2k_scale import (supply_counts_per_volt, volts_per_count,
                                  volts_to_supply_raw)

URI = "ip:192.168.2.1"
SCOPE_RATE = 1000000
RANGE = "low"                  # the +/-25 V one, despite the name
BUF = 16384
SETTLE, CAPTURE = 0.5, 1.0


class _capture(gr.top_block):
    def __init__(self, channel):
        gr.top_block.__init__(self, "dc_rail")
        self.scope = analog_source(URI, ch1_enabled=(channel == 1),
                                   ch2_enabled=(channel == 2),
                                   sample_rate=SCOPE_RATE,
                                   ch1_range=RANGE, ch2_range=RANGE,
                                   buffer_size=BUF, units="counts",
                                   trigger_source="off")
        self.samples = blocks.vector_sink_s()
        self.connect((self.scope, 0), self.samples)


def mean(xs):
    return sum(xs) / float(len(xs)) if xs else float("nan")


def measure(channel):
    """One buffer's mean, in counts. A fresh graph per point."""
    tb = _capture(channel)
    # start/stop/wait, never run(): the config keep-alive never ends, so
    # run() waits on a block that is designed not to finish.
    tb.start()
    time.sleep(SETTLE)
    tb.samples.reset()
    time.sleep(CAPTURE)
    tb.stop(); tb.wait()
    return mean(list(tb.samples.data())), len(tb.samples.data())


def fit(commanded, measured):
    """Least squares: measured = gain * commanded + offset."""
    n = len(commanded)
    sx, sy = sum(commanded), sum(measured)
    sxx = sum(x * x for x in commanded)
    sxy = sum(x * y for x, y in zip(commanded, measured))
    denominator = n * sxx - sx * sx
    if abs(denominator) < 1e-12:
        return float("nan"), float("nan")
    gain = (n * sxy - sx * sy) / denominator
    return gain, (sy - gain * sx) / n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("volts", type=float, nargs="*",
                    help="setpoints to walk (default two: 1 V and 5 V)")
    ap.add_argument("--rail", choices=("positive", "negative"),
                    default="positive")
    ap.add_argument("--input", type=int, choices=(1, 2), default=1,
                    help="which scope input the rail is wired to")
    ap.add_argument("--meter", type=float, nargs="*", default=[],
                    help="meter readings, one per setpoint")
    ap.add_argument("--uncorrected", action="store_true",
                    help="command the rail without this board's cal,*_dac")
    ap.add_argument("--off", action="store_true",
                    help="take the rail down and stop")
    args = ap.parse_args()

    sign = 1.0 if args.rail == "positive" else -1.0
    setpoints = args.volts or [sign * 1.0, sign * 5.0]
    name = "V+" if args.rail == "positive" else "V-"

    if args.off:
        # Constructing it is what writes; there is nothing to hold on to.
        power_supply(URI, rail=args.rail, voltage=0.0, enabled=False,
                     min_interval_ms=0)
        print("\n  %s down, setpoint 0 V\n" % name)
        return

    if args.meter and len(args.meter) != len(setpoints):
        ap.error("--meter needs one reading per setpoint (%d given, %d wanted)"
                 % (len(args.meter), len(setpoints)))

    # Rate limiting off: this script wants the write to have happened by
    # the time it sleeps, not within a tenth of a second of it.
    rail = power_supply(URI, rail=args.rail, voltage=setpoints[0],
                        enabled=True, calibrated=not args.uncorrected,
                        min_interval_ms=0)
    gain, offset = rail.correction()
    vpc = volts_per_count(RANGE, SCOPE_RATE)
    per_count = abs(1.0 / supply_counts_per_volt(args.rail))

    print()
    print("  %s, correction %s  (gain %.6f, offset %+.4f V)"
          % (name, "off" if args.uncorrected else "this board's cal,*_dac",
             gain, offset))
    print("  rail  %.4f V per count       scope  range '%s', %d S/s, "
          "%.6f V/count" % (per_count, RANGE, SCOPE_RATE, vpc))
    print()
    print("  commanded      raw   input %d       error" % args.input)

    readings = []
    for volts in setpoints:
        rail.set_voltage(volts)
        raw = volts_to_supply_raw(volts, args.rail, gain, offset)
        counts, n = measure(args.input)
        reading = counts * vpc
        readings.append(reading)
        print("  %+7.3f V   %6d   %+8.4f V   %+7.4f V   (%d samples)"
              % (volts, raw, reading, reading - volts, n))

    print()
    print("  %s is still holding %+.3f V -- read the meter now." %
          (name, setpoints[-1]))

    if args.meter:
        print()
        print("  commanded      meter        scope   meter - scope")
        for volts, metered, reading in zip(setpoints, args.meter, readings):
            print("  %+7.3f V   %+8.4f V   %+8.4f V   %+7.4f V"
                  % (volts, metered, reading, metered - reading))
        if len(setpoints) >= 2:
            slope, intercept = fit(setpoints, args.meter)
            assumed = 4095.0 / (supply_counts_per_volt(args.rail) * 1.2)
            print()
            print("  the meter says the rail does   %.5f * commanded %+.4f V"
                  % (slope, intercept))
            print("  so to land on what you ask for, command")
            print("      (wanted %+.4f) / %.5f" % (-intercept, slope))
            print()
            print("  A slope that is not 1.000 within the meter's own")
            print("  resolution says SUPPLY_RAIL_GAIN[%r] is not %g."
                  % (args.rail, assumed))
            print("  Divide it by the slope, and let the meter win.")
    print()


if __name__ == "__main__":
    main()
