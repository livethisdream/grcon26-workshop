"""Are the three jumpers actually in, and in the right holes?

Walks a single 1 across the driven pins and watches which read pin
follows. A missing jumper shows as a line that never moves; a swapped
pair shows as the wrong line moving, which is the failure that otherwise
survives all the way to a decode that returns plausible wrong bytes.

Static levels only -- it writes `raw` on the driven pins and reads `raw`
on the others. No buffers, no rates, nothing streaming.

    python3 bench/dio_continuity.py            # DIO0-2 -> DIO4-6

It leaves every pin an input again, at rest, whatever the outcome.
"""
import os
import sys

sys.path.insert(0, "gr-m2k")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import iio                                                   # noqa: E402

import spi_loopback as bus                                   # noqa: E402

URI = bus.URI
DRIVE, READ, NAMES = bus.SINK_PINS, bus.SOURCE_PINS, bus.LINE_NAMES
DEV = "m2k-logic-analyzer"


def channel(ctx, pin):
    return ctx.find_device(DEV).find_channel("voltage%d" % pin, False)


def main():
    ctx = iio.Context(URI)
    driven = [channel(ctx, pin) for pin in DRIVE]
    read = [channel(ctx, pin) for pin in READ]

    for ch in driven:
        ch.attrs["direction"].value = "out"
    for ch in read:
        ch.attrs["direction"].value = "in"

    try:
        table = []
        for high in range(len(DRIVE)):
            for index, ch in enumerate(driven):
                ch.attrs["raw"].value = "1" if index == high else "0"
            table.append([int(ch.attrs["raw"].value) for ch in read])
    finally:
        for ch in driven:
            ch.attrs["raw"].value = "0"
            ch.attrs["direction"].value = "in"

    print("       " + "  ".join("DIO%-2d" % pin for pin in READ))
    ok = True
    for high, row in enumerate(table):
        want = [1 if i == high else 0 for i in range(len(READ))]
        good = row == want
        ok = ok and good
        print("DIO%-2d  %s   %s%s"
              % (DRIVE[high], "   ".join("  %d" % v for v in row),
                 NAMES[high], "" if good else "   <-- WRONG, want %s" % want))
    print("\n%s" % ("all three jumpers are in and straight" if ok else
                    "check the jumpers: a row of zeros is a missing one, a 1 "
                    "in the wrong column is a swap"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
