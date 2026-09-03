"""Hold a DC level on W2, capture both inputs, print what our chain thinks.

This is the measurement that splits input 2's own offset out of the
composite W2-to-input-2 figure. Section 4/6 of the bench checklist gave
the composite as gain 0.9335, offset +169 mV, but a composite is a
product: it cannot say how much belongs to the DAC and how much to the
ADC. Two points on W2, each with a meter reading beside the capture,
separates them.

    W2 -> 2+, 2- -> GND, meter across W2 and GND   (--output w2)
    W1 -> 1+, 1- -> GND, meter across W1 and GND   (--output w1)

Only the driven output is powered up; the other one's stage stays down,
so the untouched input is not a control and should not be read as one.

Conditions are not free choices -- they have to match the data this
gets combined with:

    generator 750 kS/s      DAC_FILTER_COMP 1.164153
    scope     1 MS/s        ADC_FILTER_COMP 1.10
    both inputs 'high'      the +/-2.5 V range, despite the name

Capture is in COUNTS, converted here rather than in the block, so the
raw number and our volts both appear and either can be checked by hand.

The generator holds its last cyclic buffer after the graph stops, so
W2 stays at the level while you read the meter. No rush, no race.

Run from the repo root, with a gnuradio interpreter:

    python3 bench/dc_point.py 0.0
    python3 bench/dc_point.py 1.0 --meter 1.112
    python3 bench/dc_point.py 0.0 --output w1
"""
import sys, os, time, argparse
sys.path.insert(0, "gr-m2k")
from gnuradio import gr, blocks
from m2k_blocks.analog_sink import analog_sink
from m2k_blocks.analog_source import analog_source
from m2k_blocks.m2k_scale import volts_per_count

URI = "ip:192.168.2.1"
GEN_RATE, SCOPE_RATE = 750000, 1000000
RANGE = "high"                 # the +/-2.5 V one
BUF = 16384
SETTLE, CAPTURE = 0.5, 1.0


class _graph(gr.top_block):
    def __init__(self, dc_volts, output):
        gr.top_block.__init__(self, "dc_point")
        # One cyclic buffer of a constant is how you hold DC: the DAC
        # repeats it forever and keeps holding it once we stop.
        level = blocks.vector_source_f([dc_volts] * BUF, True)
        self.gen = analog_sink(URI, output=output, sample_rate=GEN_RATE,
                               units="volts", buffer_size=BUF, cyclic=True)
        self.connect(level, self.gen)
        self._level = level

        self.scope = analog_source(URI, ch1_enabled=True, ch2_enabled=True,
                                   sample_rate=SCOPE_RATE,
                                   ch1_range=RANGE, ch2_range=RANGE,
                                   buffer_size=BUF, units="counts",
                                   trigger_source="off")
        self.in1 = blocks.vector_sink_s()
        self.in2 = blocks.vector_sink_s()
        self.connect((self.scope, 0), self.in1)
        self.connect((self.scope, 1), self.in2)


def mean(xs):
    return sum(xs) / float(len(xs)) if xs else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("volts", type=float, help="DC level to request")
    ap.add_argument("--output", choices=("w1", "w2"), default="w2",
                    help="which generator to drive (default w2)")
    ap.add_argument("--meter", type=float, default=None,
                    help="meter reading at the driven output")
    args = ap.parse_args()

    vpc = volts_per_count(RANGE, SCOPE_RATE)

    # W1 pairs with input 1, W2 with input 2 -- that is the wiring this
    # measurement assumes, and it picks which capture is the signal.
    driven = 0 if args.output == "w1" else 1
    tb = _graph(args.volts, args.output)
    # start/stop/wait, never run(): the config keep-alive never ends, so
    # run() waits on a block that is designed not to finish.
    tb.start()
    time.sleep(SETTLE)
    tb.in1.reset(); tb.in2.reset()
    time.sleep(CAPTURE)
    tb.stop(); tb.wait()

    c1, c2 = list(tb.in1.data()), list(tb.in2.data())
    m1, m2 = mean(c1), mean(c2)

    print()
    print("  requested on %s   %+.4f V   at %d S/s, comp 1.164153"
          % (args.output.upper(), args.volts, GEN_RATE))
    print("  range '%s' (+/-2.5 V), scope %d S/s, %.9f V/count" % (RANGE, SCOPE_RATE, vpc))
    print()
    for i, (m, c) in enumerate(((m1, c1), (m2, c2))):
        mark = "<- driven" if i == driven else "  (other input)"
        print("  input %d   %8.2f counts   %+.4f V   (%d samples)  %s"
              % (i + 1, m, m * vpc, len(c), mark))
    print()
    print("  %s is still holding %+.4f V -- read the meter now."
          % (args.output.upper(), args.volts))
    if args.meter is not None:
        print()
        mv = (m1, m2)[driven] * vpc
        print("  meter at %s       %+.4f V" % (args.output.upper(), args.meter))
        print("  input %d reads     %+.4f V" % (driven + 1, mv))
        print("  input %d error     %+.4f V  <- that input's own contribution"
              % (driven + 1, mv - args.meter))
    print()


if __name__ == "__main__":
    main()
