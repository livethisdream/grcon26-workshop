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
