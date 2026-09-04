"""Bit-bang SPI mode 0 out of three DIO pins and decode it back.

    DIO0 -> DIO4   SCLK
    DIO1 -> DIO5   MOSI
    DIO2 -> DIO6   CS

The pins are named in SINK_PINS and SOURCE_PINS below and need not be
adjacent or ascending -- scatter them to check that arbitrary pin
mapping really does hold on hardware, which the contiguous default
cannot tell you.

Mode 0 means MOSI is stable while SCLK is high, so a receiver samples on
the rising edge. At 1 MS/s with 8 samples per half clock that is a
62.5 kHz bus.

One frame is one whole transaction -- idle, CS low, every byte of the
message clocked out back to back, CS high again -- which is what real
SPI does and is not merely tidier. CS framing per byte also decodes, but
a triggered capture then starts on an arbitrary byte of the message
rather than on the message, and a continuously running flowgraph prints
rotations of the string. See section 11 of docs/bench-checklist.md.

The buffer is cyclic. Non-cyclic streaming underruns roughly half the
time at this rate and drops samples mid-frame.

Run from the repo root, with the three jumpers in place:

    python3 bench/spi_loopback.py                 # 0xA5
    python3 bench/spi_loopback.py 0x00 0xFF 0x55  # any list of bytes
    python3 bench/spi_loopback.py $(seq 0 255)    # every byte there is

Needs a gnuradio interpreter -- the project .venv does not have one.
"""
import sys, os, time
sys.path.insert(0, "gr-m2k")
from gnuradio import gr, blocks
from m2k_blocks.digital import digital_source, digital_sink

URI, RATE = "ip:192.168.2.1", 1000000
SINK_PINS = [0, 1, 2]         # SCLK, MOSI, CS -- the driven side
SOURCE_PINS = [4, 5, 6]       # the same three, read back
LINE_NAMES = ["SCLK", "MOSI", "CS"]
HALF = 8                      # samples per half clock -> 62.5 kHz SCLK
LEAD, SETUP, TAIL, POST = 64, 8, 8, 48
SCLK, MOSI, CS = 0, 1, 2

def frame_len(count, half=None):
    """Samples in one frame carrying `count` bytes. 512 for 3 at half 8."""
    half = HALF if half is None else half
    return LEAD + SETUP + 16 * half * count + TAIL + POST

def frame_for(message):
    """One SPI transaction as three per-pin sample lists.

    CS falls once, every byte is clocked out back to back, CS rises
    once. The bytes are not separately framed, so the only CS falling
    edge in the frame is the start of the message -- which is what a
    triggered capture needs to land on.
    """
    sclk, mosi, cs = [], [], []
    def emit(n, s, m, c):
        sclk.extend([s] * n); mosi.extend([m] * n); cs.extend([c] * n)
    bits = [(byte >> (7 - i)) & 1 for byte in message for i in range(8)]
    emit(LEAD, 0, 0, 1)                     # idle, CS high
    emit(SETUP, 0, bits[0], 0)              # CS low, first bit presented
    for bit in bits:
        emit(HALF, 0, bit, 0)               # MOSI settles while SCLK low
        emit(HALF, 1, bit, 0)               # receiver samples on this edge
    emit(TAIL, 0, 0, 0)
    emit(POST, 0, 0, 1)                     # CS high again
    assert len(sclk) == frame_len(len(message))
    return sclk, mosi, cs

def decode(sclk, mosi, cs):
    """Every bit MOSI held at a rising SCLK edge with CS asserted."""
    return [mosi[i] for i in range(1, len(sclk))
            if cs[i] == 0 and sclk[i] == 1 and sclk[i - 1] == 0]

def bytes_from(bits):
    return [int("".join(str(b) for b in bits[i:i + 8]), 2)
            for i in range(0, len(bits) - 7, 8)]

def run(sent, repeats):
    """Send `sent` (a list of bytes) on a cyclic buffer and read it back."""
    pins = [[], [], []]
    for _ in range(repeats):
        for pin, samples in zip(pins, frame_for(sent)):
            pin.extend(samples)

    tb = gr.top_block()
    sink = digital_sink(uri=URI, pins=SINK_PINS, names=LINE_NAMES,
                        sample_rate=RATE, buffer_size=len(pins[0]),
                        cyclic=True, idle_level="low")
    for port in range(3):
        tb.connect(blocks.vector_source_s(pins[port], True), (sink, port))

    cap = len(pins[0])
    src = digital_source(uri=URI, pins=SOURCE_PINS, names=LINE_NAMES,
                         sample_rate=RATE, buffer_size=cap,
                         trigger_pin=SOURCE_PINS[CS],
                         trigger_condition="edge-falling", trigger_delay=0)
    vecs = []
    for port in range(3):
        v = blocks.vector_sink_s()
        tb.connect((src, port), blocks.head(gr.sizeof_short, cap), v)
        vecs.append(v)

    tb.start(); time.sleep(6); tb.stop(); tb.wait()
    got = [list(v.data()) for v in vecs]
    if min(len(g) for g in got) < cap:
        return None, got
    return bytes_from(decode(got[SCLK], got[MOSI], got[CS])), got

if __name__ == "__main__":
    sent = [int(a, 0) for a in sys.argv[1:]] or [0xA5]
    reps = max(1, 16384 // frame_len(len(sent)))
    heard, raw = run(sent, reps)
    if heard is None:
        print("capture short: %s" % [len(r) for r in raw])
        sys.stdout.flush(); os._exit(1)
    print("frame %d samples, %d byte%s each, %d frames sent, %d bytes decoded"
          % (frame_len(len(sent)), len(sent), "" if len(sent) == 1 else "s",
             reps, len(heard)))
    print("  sent  %s" % " ".join("%02X" % b for b in sent))
    print("  heard %s" % " ".join("%02X" % b for b in heard[:len(sent) * 2]))
    expect = (sent * reps)
    print("  RESULT %s" % ("all %d frames match" % len(expect)
                           if heard[:len(expect)] == expect
                           else "MISMATCH at frame %d"
                           % next(i for i, (a, b) in
                                  enumerate(zip(heard, expect)) if a != b)))
    sys.stdout.flush(); os._exit(0)
