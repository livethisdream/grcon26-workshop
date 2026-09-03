"""Bit-bang SPI mode 0 out of three DIO pins and decode it back.

    DIO0 -> DIO4   SCLK
    DIO1 -> DIO5   MOSI
    DIO2 -> DIO6   CS

Mode 0 means MOSI is stable while SCLK is high, so a receiver samples on
the rising edge. At 1 MS/s with 8 samples per half clock that is a
62.5 kHz bus, and one frame is 256 samples: idle, CS low, eight bit
periods, CS high again.

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
HALF = 8                      # samples per half clock -> 62.5 kHz SCLK
LEAD, SETUP, TAIL, POST = 64, 8, 8, 48
FRAME = LEAD + SETUP + 8 * 2 * HALF + TAIL + POST      # 256
SCLK, MOSI, CS = 0, 1, 2

def frame_for(byte):
    """One SPI frame as three per-pin sample lists."""
    sclk, mosi, cs = [], [], []
    def emit(n, s, m, c):
        sclk.extend([s] * n); mosi.extend([m] * n); cs.extend([c] * n)
    bits = [(byte >> (7 - i)) & 1 for i in range(8)]
    emit(LEAD, 0, 0, 1)                     # idle, CS high
    emit(SETUP, 0, bits[0], 0)              # CS low, first bit presented
    for bit in bits:
        emit(HALF, 0, bit, 0)               # MOSI settles while SCLK low
        emit(HALF, 1, bit, 0)               # receiver samples on this edge
    emit(TAIL, 0, 0, 0)
    emit(POST, 0, 0, 1)                     # CS high again
    assert len(sclk) == FRAME
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
    for byte in sent * repeats:
        for pin, samples in zip(pins, frame_for(byte)):
            pin.extend(samples)

    tb = gr.top_block()
    sink = digital_sink(uri=URI, pin_count=3, first_pin=0, sample_rate=RATE,
                        buffer_size=len(pins[0]), cyclic=True, idle_level="low")
    for port in range(3):
        tb.connect(blocks.vector_source_s(pins[port], True), (sink, port))

    cap = len(pins[0])
    src = digital_source(uri=URI, pin_count=3, first_pin=4, sample_rate=RATE,
                         buffer_size=cap, trigger_pin="6",
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
    reps = max(1, 16384 // (FRAME * len(sent)))
    heard, raw = run(sent, reps)
    if heard is None:
        print("capture short: %s" % [len(r) for r in raw])
        sys.stdout.flush(); os._exit(1)
    print("frame %d samples, %d frames sent, %d bytes decoded"
          % (FRAME, len(sent) * reps, len(heard)))
    print("  sent  %s" % " ".join("%02X" % b for b in sent))
    print("  heard %s" % " ".join("%02X" % b for b in heard[:len(sent) * 2]))
    expect = (sent * reps)
    print("  RESULT %s" % ("all %d frames match" % len(expect)
                           if heard[:len(expect)] == expect
                           else "MISMATCH at frame %d"
                           % next(i for i, (a, b) in
                                  enumerate(zip(heard, expect)) if a != b)))
    sys.stdout.flush(); os._exit(0)
