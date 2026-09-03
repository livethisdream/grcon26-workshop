"""Are four DIO ports sample-aligned with each other?

Four patterns of period 2/4/8/16 go out on DIO0-3 and come back on
DIO4-7. If the captured streams share ONE rotation against the 16-sample
word that generated them, the ports are coherent and a bus decoded off
them means something.

The capture buffer is deliberately large. At 1 MS/s a 512-sample buffer
is 1953 refills a second over the network, and a dropped one shows up as
a phase jump that looks exactly like skew.

Run from the repo root, with DIO0-3 jumpered to DIO4-7:

    python3 bench/digital_coherence.py cyclic
    python3 bench/digital_coherence.py once 16384

Needs a gnuradio interpreter -- the project .venv does not have one.
"""
import sys, os, time
sys.path.insert(0, "gr-m2k")
from gnuradio import gr, blocks
from m2k_blocks.digital import digital_source, digital_sink

CYCLIC = sys.argv[1] == "cyclic"
URI, RATE, WORD = "ip:192.168.2.1", 1000000, 16
BUF, SKIP, CAP = 16384, 200000, 512
TXBUF = int(sys.argv[2]) if len(sys.argv) > 2 else WORD * 64

word = [[(i // (1 << ch)) % 2 for ch in range(4)] for i in range(WORD)]
streams = [[word[i][ch] for i in range(WORD)] * (TXBUF // WORD) for ch in range(4)]

tb = gr.top_block()
sink = digital_sink(uri=URI, pin_count=4, first_pin=0, sample_rate=RATE,
                    buffer_size=TXBUF, cyclic=CYCLIC, idle_level="low")
for ch in range(4):
    tb.connect(blocks.vector_source_s(streams[ch], True), (sink, ch))

src = digital_source(uri=URI, pin_count=4, first_pin=4, sample_rate=RATE,
                     buffer_size=BUF)
vecs = []
for ch in range(4):
    v = blocks.vector_sink_s()
    tb.connect((src, ch), blocks.skiphead(gr.sizeof_short, SKIP),
               blocks.head(gr.sizeof_short, CAP), v)
    vecs.append(v)

tb.start(); time.sleep(6)
got = [list(v.data()) for v in vecs]
n = min(len(g) for g in got)
print("captured %s samples per channel" % [len(g) for g in got])
if n < 64:
    print("RESULT too few samples to judge"); sys.stdout.flush(); os._exit(1)

def fitting(ch, upto):
    return [r for r in range(WORD)
            if all(got[ch][i] == word[(i + r) % WORD][ch] for i in range(upto))]

common = set(range(WORD))
for ch in range(3):                       # DIO7 is unwired and floats high
    fits = fitting(ch, n)
    common &= set(fits)
    if not fits:                          # say WHERE it broke, not just that
        good = fitting(ch, 16)
        if good:
            r = good[0]
            bad = next(i for i in range(n)
                       if got[ch][i] != word[(i + r) % WORD][ch])
            print("DIO%d  holds rotation %d until sample %d, then jumps"
                  % (4 + ch, r, bad))
        else:
            print("DIO%d  fits no rotation even over 16 samples" % (4 + ch))
    else:
        print("DIO%d  rotations that fit all %d samples: %s" % (4 + ch, n, fits))

print("RESULT common rotation across the three wired pins: %s"
      % (sorted(common) or "NONE"))
for ch in range(4):
    print("  DIO%d head %s" % (4 + ch, "".join(str(v) for v in got[ch][:32])))
sys.stdout.flush(); os._exit(0)
