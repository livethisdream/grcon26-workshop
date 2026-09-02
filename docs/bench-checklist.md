# What to check on hardware

Ordered so that each step makes the next one meaningful.

Nothing here needs the discovery tool. It needs an M2K, a wire, and
ideally a meter.

**State as of 2026-09-02:** sections 1, 2, 3, 5, 6, 7 and 8 pass, both
the analog and the digital trigger included. Section 4 passes on
everything relative and fails on absolute accuracy, for a reason that is
now understood.

Board used: Rev.D (Z7010), fw v0.33, reached at `ip:192.168.2.1`.

---

## 1. The blocks appear and load — PASSES

```
export PYTHONPATH=$PWD/gr-m2k:$PYTHONPATH
export GRC_BLOCKS_PATH=$PWD/gr-m2k/grc:$GRC_BLOCKS_PATH
gnuradio-companion flowgraphs/m2k_loopback_native.grc
```

- [x] `[ADALM2000]` is in the block tree with four blocks
- [x] the flowgraph opens with no red blocks

Loading is not constructing. All four blocks threw `Device not found`
the first time they met a board, because `device_phy` was passed as `""`
and gr-iio resolves that with `iio_context_find_device` exactly like the
streaming device. An empty string is not "no phy device"; it is a lookup
that always fails.

## 2. Loopback, raw counts first — PASSES

Wire **W1 to 1+**, and **ground to 1-**. Use
`flowgraphs/m2k_loopback_raw.grc`, which has none of our arithmetic in
the path.

- [x] a waveform appears at all
- [x] its frequency matches `tone_hz`
- [x] the counts stay inside ±2047

Two things had to be fixed before a waveform appeared, and neither
looked like what it was:

**A flat line at −12.5 counts, not an error.** The ADC's input stage
comes up powered down on a board nothing has initialised. `analog_source`
wrote the input range to `m2k-fabric` but not the `powerdown` sitting
next to it. libm2k does this in `M2kImpl::initialize`; nothing else
here would. The failure mode is the expensive kind — plausible-looking
data, no complaint.

**A strong tone at exactly 500 kHz.** That is Nyquist at 1 MS/s, which
should have been the tell. The ADC always delivers both channels,
interleaved, whatever you ask for. Request one and gr-iio de-interleaves
a two-channel buffer as if it were one, so channel 2's samples land in
channel 1's stream and the time base comes out 2× slow. First sixteen
samples were `[18, 41, 18, 41, ...]`; with the generator on, the even
samples had std 43.49 and the odd ones 0.22. The block now takes both
channels and publishes only the ports that were asked for, which is what
`M2kAnalogIn` does.

**Read the frequency carefully.** A 10 kHz request comes back as
9979.2 Hz, and that is correct, not error. A cyclic buffer of 16384
samples at 750 kS/s repeats at 45.78 Hz, so the tone can only land on a
multiple of that: 218 × 750000/16384 = 9979.2 exactly. The buffer holds
218.45 cycles and the repeat snaps it to 218. It also confirms the DAC
clock is exactly 750 kS/s.

## 3. Does the configuration actually get written? — PASS

Was the least-tested thing in the project. `attr_updater`/`attr_sink`
needs a live context to construct, so none of these writes had ever
executed.

```
./iio_discover.py --uri ip:192.168.2.1 --device m2k-fabric
./iio_discover.py --uri ip:192.168.2.1 --device m2k-adc-trigger
```

- [x] `m2k-fabric` `gain` matches the input range the block was set to
- [x] changing the block's range and restarting changes it
- [x] `sampling_frequency` on `m2k-adc` reads back what was asked for
- [x] `powerdown` is cleared on the channels in use
- [x] `m2k-adc-trigger` `voltage0/trigger` matches the trigger edge chosen
- [x] `voltage4/mode` is `analog` when triggered, `always` when free running
- [x] `voltage6/logic_mode` is `a` for channel 1, `b` for channel 2

**The trigger works, and reading back the attributes is not how you
know.** A trigger that is silently free-running sets every attribute
correctly and delivers every sample. Three things separate them, and
all three were run against a 4989.6 Hz sine at 1.0 V, `high` range,
1 MS/s, 4096-sample buffers:

| check | free-running | triggered |
|---|---|---|
| spread of `buffer[0]` over 36 buffers | 1.8793 V | **0.0288 V** |

0.0288 V is one sample step at this slew rate (2*pi*4990 V/s x 1 us =
31 mV), so the alignment is as tight as the sample clock allows.

- **A level above the peak must stall.** +2.0 V against a 1.0 V peak
  produced zero samples in six seconds, and
  `Unable to refill buffer: Connection timed out (110)`. That warning
  is the trigger working. A capture that runs anyway means the trigger
  is not in the path.
- **`edge-falling` must fall.** At 0 V it starts at the same voltage
  rising does; only the slope tells them apart. Measured -0.0886 V over
  the first three samples.
- **The level is in volts the scope agrees with.** Asked +0.500 V above
  the 0 V case, got +0.5007 V — 0.14%. The decimation filter's
  correction belongs on the trigger level too: leave it out and this
  lands 9% off. (The shared ~15 mV zero offset appears in both cases and
  is the ADC's, not the trigger's.)

Also found: `set_len_tag_key("packet_len")` on a sink puts it in
tagged-burst mode against an untagged stream and it refuses with
`Input stream not tagged!`. Harmless on a source, where it only labels
the output. The `Unable to refill buffer: Connection timed out (110)`
that came with it was downstream, not a second bug — the ADC was waiting
for a signal the failed sink never produced.

**Fixed: `CONFIG_INTERVAL_MS = 1000` in `m2k_config.py`.** `attr_sink`
republishes on a timer, so for the first second of any flowgraph *no
setting was in force*. A short capture could finish before its own
configuration arrived. This produced a nonsense range comparison — 0.3
counts on one range against 72.3 on the other — until the test scripts
were changed to skip two seconds of samples. `m2k_config` now writes
each attribute directly with libiio at construction time, before
`start()`, and keeps the updater as a keep-alive. Verified by planting
`gain=low, powerdown=1`, asking for the high range, and capturing 4096
samples starting 100 ms in — one tenth of the interval. The planted
state was gone before `start()` and the capture read +635.19 counts,
the high-range value. The two-second skip is no longer needed.

**Benign but noisy:** `device_sink: Unable to push buffer: Device or
resource busy (16)` on every cyclic run. libiio permits exactly one
`iio_buffer_push` on a cyclic buffer; the hardware repeats it from then
on and further pushes return `-EBUSY`. Expected, but it reads like a
failure and should be explained or suppressed.

## 4. The volts number — RELATIVE PASSES, ABSOLUTE FAILS BY ~7%

Method: hold W1 at a DC level, read it with a meter on 1+/1−, capture
counts, fit a line through three points. Requested 0.0 / 1.0 / 2.0 V,
meter 0.049 / 1.217 / 2.383 V, counts on ±25 V −10.95 / +57.05 / +125.43.
One further point on ±2.5 V at +1.0 V requested gave +737.13 counts.

- [x] switching range does not change the reading of the same input
- [x] the two ranges agree on their correction to 0.34%
- [ ] ±25 V range: reading matches the meter within a few percent
- [ ] ±2.5 V range: same

The third box was called the real test and it passes: the ranges agree
to 0.01%, and their ratio is 10.53 against a predicted 10.526. The scale
*is* being applied per range rather than by luck.

What failed was absolute accuracy, by 17.6%. Two separate causes:

**Most of it was a missing table, now fixed.** Reaching a rate below
100 MS/s means decimating, and the decimation filter does not have unity
gain. libm2k multiplies volts-per-count by a per-rate correction —
1.00 at 100 MS/s, 1.05, **1.10 at 1 MS/s**, 1.15, 1.20, 1.26 at 1 kS/s —
and `m2k_scale.py` did not have it. Applying it accounts for 10 of the
17.6 points.

**The rest is calibration, and is real.** The residual is a gain of
about 1.07, i.e. the ADC reads roughly 7% low. `m2k-adc voltage0` and
`voltage1` both carry `calibbias = 2048` and `calibscale = 1.000000`,
the driver's uncalibrated defaults — 2048 is the neutral value that
turns offset binary into signed, not an offset of 2048 counts. There is
also a fixed **−13.9 count** offset, the same on both ranges.

Measured constants, for checking a calibration routine against:

| | formula says | measured | correction |
| --- | --- | --- | --- |
| ADC ±25 V, 1 MS/s | 0.015977 V/count | 0.017114 | ×1.0711 |
| ADC ±2.5 V, 1 MS/s | 0.001518 V/count | 0.001620 | ×1.0675 |
| ADC offset | 0 | −13.9 counts | same on both ranges |

Note the board publishes factory constants as context attributes —
`cal,gain_pos_adc = 0.99906`, `cal,gain_neg_adc = 0.99581`, and five
more. They are all within 0.5% of unity, so they are a fine trim and do
**not** explain the 7%.

**How calibration will work** (decided 2026-09-01, not yet built): a
standalone `m2k_calibrate.py`, run once per session, not block init. It
seizes the whole front end via `m2k-fabric calibration_mode`
(`none adc_ref1 adc_ref2 adc_gnd dac`) and the `ad5625` calibration DAC,
it is a closed loop that `attr_sink` structurally cannot express, and
its result persists on the device — so repeating it per run is waste.
The blocks then *read* `calibscale`/`calibbias` and apply them, because
libm2k applies the gain in software (`getScalingFactor` multiplies by
`m_adc_calib_gain`) rather than the driver correcting the samples.

The `ad5625` publishes `scale = 0.292968750` mV/count, so raw 2048 is
exactly 600.0 mV and full scale is 1.2 V. That is a genuinely
independent chain for zero, linearity and range ratio — but not for
absolute traceability, because the path gain between `adc_ref1` and the
front end is unknown. A meter is still the only external reference.

## 5. Sample rate is really the rate — PASSES

- [x] a known tone reads back at the right frequency at 1 MS/s
- [x] and at 100 kS/s
- [x] `sampling_frequency` on `m2k-adc` reads back what was asked for

Writing `sampling_frequency` directly, from the list of six values the
hardware publishes, is right. The earlier version that computed it from
`oversampling_ratio` got the list wrong.

The 5% amplitude difference seen between 1 MS/s and 100 kS/s was
recorded here as unexplained. It is the filter correction from section
4: 1.15 / 1.10 = 1.045.

## 6. The generator — PASS, WITH A PER-CHANNEL OFFSET

- [x] the waveform is not inverted
- [x] Repeat forever keeps generating with the flowgraph idle
- [x] a 1.0 V amplitude request measures ~1.0 V on a meter
- [x] W2 works and is independent of W1

The amplitude box failed first: the meter fit gave

```
actual = 1.1670 x requested + 0.0493 V
```

16.7% high. That is the generator's own filter correction, which
`M2kAnalogOut::getScalingFactor` divides by and we did not have. At
750 kS/s — the loopback's rate — libm2k's table says **1.164153**. The
meter said 1.1670. Fixed in `m2k_scale.DAC_FILTER_COMP`.

The DAC's table is not a smooth roll-off and cannot be guessed:
1.00, 1.525879, **1.164153**, 1.776357, 1.355253, 1.033976, from
75 MS/s down to 750 S/s.

The remaining offset is calibration, like the ADC's — and it is
**per channel**, which W2 is what showed.

**W2 works, and the offsets do not match.** W1 to input 1, W2 to
input 2, both `high` range at 1 MS/s, three cases: `W1 +1.0 / W2 -0.5`,
the same swapped, and `W1 0.0 / W2 held`. The swap is the part that
matters — two outputs that both work but land on the wrong inputs pass
a single case and fail this one.

| path | gain | offset |
|---|---|---|
| W1 to input 1 | 0.9401 | **+25 mV** |
| W2 to input 2 | 0.9335 | **+169 mV** |

Gains agree to 0.7%, so both paths lose the same ~6.5% and it is one
shared error. The offsets are 6.8x apart. On the +/-2.5 V range 169 mV
is 6.8% of full scale, which is not a trim — it is the thing
`calibbias` exists for, and it has to be measured per channel rather
than derived once and applied everywhere.

These are composite DAC-times-ADC figures. Splitting them needs the
meter on each output; only W1 has ever been measured absolutely.

Independence is clean: moving W1 by -939.5 mV moved channel 2 by
-1.1 mV.

**Why the loopback said everything was fine.** It read 1.0010 V for a
1.0 V request. The generator was 16.7% high, the scope 15.4% low, and
the product is 0.9905 against 0.988 measured. Two errors that cancel
look exactly like no error. This is the argument for the meter, and it
is worth showing rather than asserting.

## 7. Digital — PASSES

Wire **DIO0 to DIO1** and **DIO0 to 1+**, with **1- to ground**. The
scope leg is what makes the digital result trustworthy: it reads the
same pin in volts, on a clock section 5 already verified.

Use the **`'low'`** range for the scope. 3.3 V logic clips flat on
`'high'`, which is the +/-2.5 V one.

- [x] Digital Sink drives DIO0, confirmed with a meter or an LED
- [x] Digital Source reads a pin driven externally
- [x] `m2k-logic-analyzer` `direction` reads `in`/`out` to match the block
- [x] a rate from the dropdown is accepted

**A loopback needed `first_pin` before it could exist.** `pins_for`
counted from DIO0 upward with no offset, so a sink and a source in one
flowgraph always claimed the same pins and fought over `direction` --
whichever was built last won and the other silently did nothing. Both
blocks now take a first pin, and the sink at DIO0 with the source at
DIO1 share nothing. `direction` afterwards read `out` on DIO0, `in` on
DIO1, and `in` on the untouched DIO2.

**The pin drives a real 3.3 V.** A 16384-sample square at 1 MS/s --
61.04 Hz, one buffer per cycle -- measured on the scope:

| | measured | corrected |
|---|---|---|
| swing | 3.1100 V | **3.33 V** at the known -6.5% |
| high | 2.9028 V | |
| low | **-0.2073 V** | |
| duty | 49.9% | |
| period | 16384.0 samples | 61.04 Hz, exact |

The low rail is the interesting number. Input 1's offset is -21.4 mV on
the `'high'` range, and -0.2073 V is 9.7x that -- near enough the 10x
between the ranges to say the offset is a fixed *count* error that
scales with range, which is what `calibbias` being a raw attribute
predicts. Worth confirming deliberately when `m2k_calibrate.py` gets
written.

Reading DIO1 back through the Digital Source gave values `{0, 1}`, duty
49.9%, and a period of exactly 16384 samples.

**All six dropdown rates are real.** Not read back -- measured. Each
drove a 1024-sample square, whose frequency is rate/1024, timed against
the scope:

| requested | expected | measured | error |
|---|---|---|---|
| 100 MS/s | 97656.25 Hz | 97796.89 Hz | +0.14% |
| 10 MS/s | 9765.62 Hz | 9765.63 Hz | +0.00% |
| 1 MS/s | 976.56 Hz | 976.56 Hz | -0.00% |
| 100 kS/s | 97.66 Hz | 97.66 Hz | +0.00% |
| 10 kS/s | 9.77 Hz | 9.77 Hz | +0.00% |
| 1 kS/s | 0.98 Hz | 0.98 Hz | +0.00% |

The 100 MS/s error is edge quantisation -- the scope had 102 samples per
period -- not a rate error. `DIGITAL_SAMPLE_RATES` is now measured
rather than assumed.

**`-tx` and `-rx` hold separate `sampling_frequency` attributes.** Every
run above left `m2k-logic-analyzer-rx` at 1 MS/s while `-tx` followed
the request. That is correct -- two devices, each block writes its own
-- but a Sink and a Source given different rates in one flowgraph will
disagree about time and neither will complain.

## 8. Digital idle level and trigger — PASSES

Same jumpers as section 7: `DIO0 -> DIO1`, `DIO0 -> 1+`, `1- -> GND`.

- [x] the idle level really drives the pin
- [x] "leave as found" really leaves it
- [x] a trigger that cannot fire stalls the capture
- [x] the trigger lands the buffer on the edge

### The idle level

An output pin has two sources of truth. The stream drives it while the
flowgraph runs; `raw` on `m2k-logic-analyzer` drives it the rest of the
time. Constructing a sink and never starting it is therefore a static
output — Scopy's Digital IO, with no flowgraph running at all.

Measured on input 1, `high` range, no flowgraph started:

| `idle_level` | `raw` reads | DIO0 measures |
| --- | --- | --- |
| `high` | 1 | **+2.8387 V** |
| `low` | 0 | **-0.0212 V** |
| `leave` | 1, unchanged | +2.8387 V |

The `leave` row is the one that proves the point: it ran straight after a
`high`, wrote nothing, and the pin stayed high. So "leave as found" is
genuinely a no-write, and the resting level of a board nobody has
configured is whatever the last program left behind.

**This is the opposite of the analog generator.** Section 6 records the
DAC holding its last cyclic buffer with the flowgraph stopped. The DIO
pins do not hold theirs — they snap back to `raw` the moment you stop.

### The trigger is real

A trigger you cannot satisfy must hang, or it is not a trigger. Sink
drives DIO0, source reads DIO1, six seconds each:

| DIO0 driven | trigger | result |
| --- | --- | --- |
| low | `level-high` on DIO1 | **STALLED — no samples in 6 s** |
| low | `level-low` on DIO1 | 512 samples |
| high | `level-high` on DIO1 | 512 samples |
| square | off | 512 samples, all zeros |

The last row is worth reading twice. Free-running fills its buffer
immediately at start, before the generator has begun playing, so it
captures the idle level and never sees the square at all. Triggered, it
waits. That contrast is the clearest evidence the trigger works.

### The buffer lands on the edge

200-sample square at 1 MS/s, so a transition every 100 samples:

| trigger | `buffer[0]` | first transition |
| --- | --- | --- |
| `edge-rising` | 1 | sample 100 |
| `edge-falling` | 0 | sample 100 |

Exact, and identical across every repeat.

### Trigger delay: negative is exact, positive is not

`trigger_delay` in samples, same square, `edge-rising`:

| requested | first transition | repeats |
| --- | --- | --- |
| 0 | 100 | 100, 100, 100 — **exact** |
| -50 | 50 | 50, 50, 50 — **exact** |
| -100 | 100 | pre-trigger, `buffer[0]` = 0 |
| +20 | 90 | 80, 60, 60 — **jitters** |
| +40 | 70 | 80, 80, 80 |

Negative delay is real pre-trigger and is repeatable to the sample.
Positive delay moves the buffer the right way but lands tens of samples
off, differently each run. The attribute reads back exactly what was
written in every case, so this is the hardware and not a lost write. Not
explained; treat positive delay as approximate.

## 9. Promote what passes

Each entry in `iio_overlays.py` carries a `check` field describing how to
confirm it. 58 of 74 are still `UNVERIFIED`. As they check out, change
`confidence` to `MEASURED`, and `./iio_explain.py fixtures/m2k-real.json
--unknown` will show the count moving.

Worth re-capturing at the end, so the fixture reflects a board whose
settings you understand:

```
./iio_discover.py --uri ip:192.168.2.1 --json > fixtures/m2k-real.json
```

---

## Things known to be assumptions

| assumption | status |
| --- | --- |
| `volts_per_count` from libm2k | **measured** — right to 7%, the rest is calibscale |
| the filter corrections | **measured** — DAC's confirmed to 0.25% |
| DAC `vlsb` = 10/4095 | **measured** — right, once the filter term is in |
| the sign inversion on the DAC | **measured** — real, and correctly applied |
| `attr_updater`/`attr_sink` applies config | **measured** — yes, after a 1 s delay |
| `calib_gain` and `calibbias` are 1.0 and 0 | **wrong** — the post-calibration case, not the fresh-board one |
| digital sample rates | **measured** — all six, timed against the scope |
| the digital trigger fires | **measured** — an impossible condition stalls |
| digital `trigger_delay` in samples | **measured** — exact at 0 and below, approximate above |
| `oversampling_ratio` is decimation | only in the overlay text now, not in code |
