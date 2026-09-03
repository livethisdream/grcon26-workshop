# Loopback

The smallest end-to-end M2K flowgraph, and the first thing to run at a
station. **Wire W1 to 1+, and ground to 1-.**

| file | uses |
| --- | --- |
| `m2k_loopback.grc` | the stock gr-iio blocks — works with nothing installed |
| `m2k_loopback_generated.grc` | blocks `iio_grc.py` generated from a capture |

```
gnuradio-companion flowgraphs/m2k_loopback.grc
```

For the generated variant, point GRC at the blocks first:

```
uv run ./iio_grc.py fixtures/m2k-real.json --out blocks/
GRC_BLOCKS_PATH=$PWD/blocks gnuradio-companion flowgraphs/m2k_loopback_generated.grc
```

## The two conversion blocks are the lesson

gr-iio carries **short** samples in both directions — raw ADC counts, not
volts. So `Short To Float` gets you a number, and `Multiply Const` turns
that number into volts. That multiply is the entire counts-to-volts story
in one block, and `volts_per_count` is the variable it lives in.

Everything upstream of that multiply is counts. Everything downstream is
volts. If a participant remembers one thing about IIO, this is a good
candidate.

## What has been checked, and what has not

Verified without hardware, in the test suite (`tests/test_grc_integration.py`),
against GNU Radio 3.10 itself rather than against our own assumptions:

- GRC's real block loader accepts all five generated blocks
- both flowgraphs validate in GRC and generate Python that parses
- the emitted constructors are the shapes we claim:
  `device_source(..., buffer_size, decimation - 1)` and
  `device_sink(..., buffer_size, interpolation - 1, cyclic)`, each followed
  by `set_len_tag_key()`
- an untouched dropdown writes nothing — "shown" never means "set"
- run headless, both get as far as `RuntimeError: Unable to create context`,
  which is the only step that needs a board

Not checked, and the reason to run this at a bench:

- **`volts_per_count = 0.014525`** comes from libm2k's `getScalingFactor()`
  for the ±25 V range. No signal has confirmed it. Put a known amplitude in
  and see whether the plot agrees.
- **`oversampling_ratio` as decimation.** `samp_rate` assumes the ADC's
  100 MS/s divided by 100. If that is wrong, every frequency axis is wrong
  by the same ratio.
- **`amplitude_counts = 1000`** is a guess at a safe DAC level.

## A GRC trap worth knowing

Keep the flowgraph `description` to a single line. GRC comments out only its
first line when generating Python and drops the rest in as bare code, which
does not parse. Multi-line notes belong in `comment`. There is a test pinning
this.

---

# SPI loopback

`m2k_spi_loopback.grc` — a real SPI bus bit-banged out of three DIO pins
and read back on three more. **Three jumpers:**

```
DIO0 -> DIO4      SCLK
DIO1 -> DIO5      MOSI
DIO2 -> DIO6      CS
```

```
export PYTHONPATH=$PWD/gr-m2k:$PYTHONPATH
gnuradio-companion flowgraphs/m2k_spi_loopback.grc
```

Three vector sources hold one 256-sample frame each, repeating. The
Digital Sink plays them as one cyclic buffer at 1 MS/s; with 8 samples
per half-clock that is a 62.5 kHz bus in SPI mode 0. The Digital Source
triggers on **CS falling** on DIO6, so the time sink starts every capture
at a frame boundary rather than wherever the buffer happened to land.

## The frame is a variable, which is the point

```python
spi_bits = [(spi_byte >> (7 - i)) & 1 for i in range(8)]
spi_sclk = [0]*72 + ([0]*half + [1]*half)*8 + [0]*56
spi_mosi = [0]*64 + [spi_bits[0]]*8 + \
           [b for bit in spi_bits for b in [bit]*(2*half)] + [0]*56
spi_cs   = [1]*64 + [0]*144 + [1]*48
```

Change `spi_byte` and the waveform changes. Change `half` and the bus
speed changes. A participant can see mode 0's rule — MOSI settles while
the clock is low, the receiver samples on the rising edge — directly in
the list, which is harder to get from a datasheet timing diagram.

The three lists are all 256 long, and they have to be: they are one
buffer, and a short one would shift the others.

## What has been checked

On hardware, 2026-09-02: 0xA5 first try, then eight edge-case bytes,
then all 256 byte values in a single 65536-sample capture, three repeat
runs, 768 frames, zero errors. Section 9 of `docs/bench-checklist.md` has
the detail.

Use **Repeat forever** (cyclic). Non-cyclic underruns at 1 MS/s and loses
about half its runs.

One Digital Sink per flowgraph — all sixteen pins share one output word
and one DMA buffer.
