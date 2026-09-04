"""Section 11: decode the bus inside the running flowgraph, not after it.

`bench/spi_loopback.py` proved the bus by capturing three streams and
decoding them offline, once the run had finished. This runs the real
`m2k_spi_decode` block in the graph, which is a different claim: it has
to carry its state across `work()` calls that land wherever the
scheduler puts them, and it has to keep up with 1 MS/s.

Same three jumpers as section 9:

    DIO0 -> DIO4   SCLK
    DIO1 -> DIO5   MOSI
    DIO2 -> DIO6   CS

Run from the repo root:

    python3 bench/spi_flowgraph.py              # 'M2K', half = 4, 8, 16
    python3 bench/spi_flowgraph.py hello        # any message
    python3 bench/spi_flowgraph.py hi 8         # one bus speed only

Three things it is actually asking:

  * do the bytes come back, and keep coming back
  * does the bus speed not matter -- half is 4, 8 and 16 in one run,
    because a decoder that had a frame length baked into it would pass
    at one and fail at the others
  * does the stream start where the message starts. A decoder emitting
    from a partial frame produces bytes that are real, plausible and
    rotated; the first byte landing on the first byte sent is what says
    the arming rule held on hardware.

Needs a gnuradio interpreter -- the project .venv does not have one.
"""
import os
import sys
import time

sys.path.insert(0, "gr-m2k")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pmt                                                   # noqa: E402
from gnuradio import blocks, gr                              # noqa: E402

import spi_loopback as bus                                   # noqa: E402
from m2k_blocks.digital import digital_sink, digital_source  # noqa: E402
from m2k_blocks.spi import spi_decode                        # noqa: E402

URI, RATE = bus.URI, bus.RATE
SINK_PINS, SOURCE_PINS = bus.SINK_PINS, bus.SOURCE_PINS
LINE_NAMES = bus.LINE_NAMES
SCLK, MOSI, CS = bus.SCLK, bus.MOSI, bus.CS
RUN_SECONDS = 6


def frames_for(message, half):
    """The buffer for `message` at a bus speed: whole frames, nothing else.

    One frame is the whole message, so a buffer of whole frames is a
    buffer of whole messages -- and the capture's CS-falling trigger
    lands on the start of one every time.
    """
    bus.HALF = half
    frame = bus.frame_len(len(message), half)
    repeats = max(1, 16384 // frame)
    pins = [[], [], []]
    for _ in range(repeats):
        for pin, samples in zip(pins, bus.frame_for(message)):
            pin.extend(samples)
    return pins, frame


class collector(gr.sync_block):
    """Message Debug, except it keeps what it saw instead of printing it."""

    def __init__(self):
        gr.sync_block.__init__(self, "collector", None, None)
        self.seen = []
        self.message_port_register_in(pmt.intern("bytes"))
        self.set_msg_handler(pmt.intern("bytes"), self._got)

    def _got(self, msg):
        self.seen.append(list(pmt.u8vector_elements(pmt.cdr(msg))))


def run(message, half):
    """One pass: play `message` cyclically, decode it inside the graph."""
    pins, frame = frames_for([ord(ch) for ch in message], half)
    cap = len(pins[0])

    tb = gr.top_block()
    sink = digital_sink(uri=URI, pins=SINK_PINS, names=LINE_NAMES,
                        sample_rate=RATE, buffer_size=cap,
                        cyclic=True, idle_level="low")
    for port in range(3):
        tb.connect(blocks.vector_source_s(pins[port], True), (sink, port))

    src = digital_source(uri=URI, pins=SOURCE_PINS, names=LINE_NAMES,
                         sample_rate=RATE, buffer_size=cap,
                         trigger_pin=SOURCE_PINS[CS],
                         trigger_condition="edge-falling", trigger_delay=0)
    decode = spi_decode(bits_per_word=8, cs_active_low=True)
    heard = collector()
    taps = []
    for port in (SCLK, MOSI, CS):
        tap = blocks.vector_sink_s()
        tb.connect((src, port), tap)
        tb.connect((src, port), (decode, port))
        taps.append(tap)
    tb.msg_connect(decode, "bytes", heard, "bytes")

    tb.start(); time.sleep(RUN_SECONDS); tb.stop(); tb.wait()

    return {"frame": frame, "samples": [len(t.data()) for t in taps],
            "chunks": heard.seen,
            "words": [b for chunk in heard.seen for b in chunk],
            "cs": list(taps[CS].data())}


def first_cs_falls_at(cs):
    """The index of the first falling edge on CS, or None."""
    for i in range(1, len(cs)):
        if cs[i - 1] == 1 and cs[i] == 0:
            return i
    return None


def report(message, half, out):
    sent = [ord(ch) for ch in message]
    words = out["words"]
    print("half %-3d frame %-4d captured %s samples, %d message%s, %d bytes"
          % (half, out["frame"], out["samples"], len(out["chunks"]),
             "" if len(out["chunks"]) == 1 else "s", len(words)))
    if not words:
        print("  RESULT nothing decoded")
        return False

    text = "".join(chr(b) if 32 <= b < 127 else "." for b in words)
    print("  sent  %r" % message)
    print("  heard %r%s" % (text[:3 * len(message)],
                            "..." if len(text) > 3 * len(message) else ""))

    repeats = len(words) // len(sent)
    expect = sent * repeats
    # Every chunk should be whole messages: one frame is one message, so
    # a chunk that is not a multiple of the message length means the
    # capture started somewhere other than a CS falling edge.
    ragged = [len(c) for c in out["chunks"] if len(c) % len(sent)]
    if repeats < 1 or words[:len(expect)] != expect:
        bad = next((i for i, (a, b) in enumerate(zip(words, expect))
                    if a != b), 0)
        print("  RESULT MISMATCH at byte %d: %02X, expected %02X"
              % (bad, words[bad], sent[bad % len(sent)]))
        return False

    if ragged:
        print("  RESULT %d chunk(s) not a whole number of messages: %s"
              % (len(ragged), sorted(set(ragged))[:8]))
        return False

    print("  RESULT %d passes of %r, first CS falls at sample %s"
          % (repeats, message, first_cs_falls_at(out["cs"])))
    return True


if __name__ == "__main__":
    message = sys.argv[1] if len(sys.argv) > 1 else "M2K"
    halves = [int(sys.argv[2])] if len(sys.argv) > 2 else [4, 8, 16]
    results = []
    for half in halves:
        results.append(report(message, half, run(message, half)))
        print("")
    print("SECTION 11 %s" % ("PASSES" if all(results) else "FAILS"))
    sys.stdout.flush()
    os._exit(0 if all(results) else 1)
