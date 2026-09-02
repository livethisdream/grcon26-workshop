# The M2K as an instrument

GNU Radio blocks that treat the ADALM2000 as a scope and a signal
generator, rather than as fourteen IIO devices you have to understand
first.

```
export PYTHONPATH=$PWD/gr-m2k:$PYTHONPATH
export GRC_BLOCKS_PATH=$PWD/gr-m2k/grc:$GRC_BLOCKS_PATH
gnuradio-companion flowgraphs/m2k_scope.grc
```

Two lines, no build step, nothing to install. `[ADALM2000]` appears in the
block tree.

## Why not the stock IIO Device Source

Eight parameters, of which about two can be guessed:

| stock parameter | the problem |
| --- | --- |
| IIO context URI | no example of a legal value |
| Device Name/ID | which devices exist, spelled how? |
| PHY Device Name/ID | "PHY" means nothing here |
| Channels | a Python list of strings you must already know |
| Decimation | factor, or samples dropped? |
| Parameters | free-text `key=value` with an unguessable naming rule |
| Packet Length Tag | opaque, and irrelevant to most flowgraphs |

## M2K Analog Source

Every parameter says what it does and what its values are:

| parameter | values | quietly becomes |
| --- | --- | --- |
| M2K address | `ip:192.168.2.1` — the default is the example | context uri |
| Channel 1 (1+) / Channel 2 (2+) | On / Off | the channel list |
| Sample rate | 100 MS/s … 1 kS/s | `sampling_frequency` on `m2k-adc` |
| Channel N input range | ± 25 V / ± 2.5 V | `gain` on `m2k-fabric` |
| Output | Volts (float) / Raw counts (short) | the output port's type |
| Samples per buffer | 16384 | buffer size |
| Trigger on | Free running / Channel 1 / Channel 2 | `m2k-adc-trigger` |
| Trigger when signal is | Rising / Falling / Above / Below level | `trigger` |
| Trigger level (V) | volts | `trigger_level`, in counts |

The last two appear only once the trigger is on. The range fields appear
only for channels that are enabled.

Those settings live on **three different IIO devices**, which is why a
stock Device Source cannot express them: its `params` go to exactly one.

### Illegal combinations are refused in GRC

Not discovered at run time:

- no channels enabled
- a zero buffer
- a trigger level outside the input range you picked — which could never
  fire, and nothing else would tell you

## What has been checked

Against GNU Radio 3.10 itself, with no hardware
(`tests/test_grc_integration.py`, `tests/test_m2k_scale.py`):

- GRC's real loader accepts the block; its parameters carry no IIO
  vocabulary at all — asserted, not eyeballed
- a flowgraph using it validates and generates Python that parses
- run headless, it reaches `RuntimeError: Unable to create context` —
  everything but the board
- the arithmetic is tested with no GNU Radio present, including that the
  sample-rate list matches what a real M2K publishes

## What has not

**The volts conversion.** `volts_per_count` comes from libm2k's
`getScalingFactor()` and no signal has confirmed it. Right shape, wrong
amplitude means suspect this — and switch Output to **Raw counts**, which
are untouched by it.

**The configuration path.** gr-iio's `attr_sink` needs a live context to
construct, so range and trigger writes cannot be exercised here. They are
built from libm2k's own attribute usage, but they have never run.

## Two things the build turned up

**The hardware publishes its own sample rates.** An earlier version
computed them as 100 MS/s ÷ `oversampling_ratio` and produced a dropdown
that wrongly excluded 1 kS/s. `sampling_frequency_available` lists six
exact rates; when the hardware publishes a list, the list wins.

**`option_labels: [On, Off]`** silently becomes `True / False` — YAML 1.1
reads those as booleans. Quote every option label. There is a test.
