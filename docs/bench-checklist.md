# What to check on hardware

Everything below has been reasoned about, sourced or tested without a
board, and none of it has met a signal. Ordered so that each step makes
the next one meaningful.

Nothing here needs the discovery tool. It needs an M2K, a wire, and
ideally a meter.

---

## 1. The blocks appear and load

```
export PYTHONPATH=$PWD/gr-m2k:$PYTHONPATH
export GRC_BLOCKS_PATH=$PWD/gr-m2k/grc:$GRC_BLOCKS_PATH
gnuradio-companion flowgraphs/m2k_loopback_native.grc
```

- [ ] `[ADALM2000]` is in the block tree with four blocks
- [ ] the flowgraph opens with no red blocks

*Checked here:* GRC's own loader accepts all four; the flowgraph validates
and generates Python that parses and runs to the point of needing a board.
*Not checked:* that GRC's UI renders them sensibly.

## 2. Loopback, raw counts first

Wire **W1 to 1+**, and **ground to 1-**. Set the scope block's Output to
**Raw counts** so nothing we computed is in the path.

- [ ] a waveform appears at all
- [ ] its frequency matches `tone_hz`
- [ ] the counts stay inside ±2047

If nothing appears, the failure is upstream of every number in this
document, and the raw path is the one to debug.

## 3. Does the configuration actually get written?

**The least-tested thing in the project.** gr-iio's `attr_sink` needs a
live context to construct, so range, trigger and DIO direction writes have
never executed. They are built from libm2k's own attribute usage.

With the flowgraph running:

```
./iio_discover.py --uri ip:192.168.2.1 --device m2k-fabric
./iio_discover.py --uri ip:192.168.2.1 --device m2k-adc-trigger
```

- [ ] `m2k-fabric` `gain` matches the input range the block was set to
- [ ] changing the block's range and restarting changes it
- [ ] `m2k-adc-trigger` `voltage0/trigger` matches the trigger edge chosen
- [ ] `voltage4/mode` is `analog` when triggered, `always` when free running
- [ ] `voltage6/logic_mode` is `a` for channel 1, `b` for channel 2

If these are unset, `attr_updater`/`attr_sink` is not doing the job and
the fix is probably to write them with libiio's Python bindings instead.

## 4. The volts number — the big one

`volts_per_count` = **0.014525 V** on ±25 V, **0.001380 V** on ±2.5 V, from
libm2k's `getScalingFactor()` with calibration at 1.0.

Feed a known DC level in (a bench supply, measured with a meter) and read
it with the scope block set to **Volts**.

- [ ] ±25 V range: reading matches the meter within a few percent
- [ ] ±2.5 V range: same
- [ ] switching range does not change the reading of the same input

The third is the real test — it is what proves the scale is being applied
per range rather than by luck.

If it is wrong, everything downstream inherits it: the GUI, the handout,
`m2k_scale.volts_per_count`, and the scope block's Volts mode.

## 5. Sample rate is really the rate

- [ ] a known tone reads back at the right frequency at 1 MS/s
- [ ] and at 100 kS/s
- [ ] `sampling_frequency` on `m2k-adc` reads back what was asked for

We now write `sampling_frequency` directly because the hardware publishes
a list of six legal values. An earlier version computed it from
`oversampling_ratio` and got the list wrong, so this is worth confirming
rather than assuming.

## 6. The generator

Its base clock is 75 MS/s, so its rates and the scope's do not overlap.

- [ ] a 1.0 V amplitude request measures ~1.0 V on a meter
- [ ] the waveform is not inverted

The second matters: the conversion inverts sign deliberately, per
`M2kAnalogOut::convVoltsToRaw`. If the trace is upside down, that
inversion is wrong or doubled.

- [ ] Repeat forever keeps generating with the flowgraph idle
- [ ] W2 works and is independent of W1

## 7. Digital

- [ ] Digital Sink drives DIO0, confirmed with a meter or an LED
- [ ] Digital Source reads a pin driven externally
- [ ] `m2k-logic-analyzer` `direction` reads `in`/`out` to match the block
- [ ] a rate from the dropdown is accepted

The digital side publishes no `sampling_frequency_available`, so the rates
offered are decade divisions of 100 MS/s by assumption. If one is refused,
gr-iio logs it and carries on at the previous rate — so confirm the rate
took before trusting any timing measurement.

## 8. Promote what passes

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

| assumption | where it bites if wrong |
| --- | --- |
| `volts_per_count` from libm2k | scope Volts mode, GUI, handout |
| DAC `vlsb` = 10/4095 | generator Volts mode |
| the sign inversion on the DAC | waveform appears inverted |
| digital sample rates | timing measurements silently off |
| `attr_updater`/`attr_sink` applies config | range and trigger silently ignored |
| `oversampling_ratio` is decimation | only in the overlay text now, not in code |
