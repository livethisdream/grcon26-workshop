---
name: "#grcon26-workshop"
dateCreated: 2026-08-18
dateModified: 2026-09-03
container: cdocker
---
# Overview

Hands-on workshop material teaching GNU Radio with the ADALM2000 (M2K) as the input
device, for GRCon26 (September 2026). The M2K is the instrument; every other board sits
on its input side as a signal source. libiio / gr-iio is the interface layer for every
flowgraph in the workshop. Audience is ~20 participants with basic GNU Radio
familiarity, in a 90–120 minute session structured crawl (IIO intro, loopback) → walk
(IIO block anatomy, discovery tool) → run (application demos). Scope spans tooling (a
standalone Python IIO discovery program), demo applications (a React standing-wave
display), and the session material itself.

# Special Instructions

- Plan first, then execute. Show the plan before writing code.
- Crawl, walk, run. Get the smallest thing working before adding scope.
- If you find yourself fixated on one aspect, stop and ask whether that's the right
  thing to be focused on. Don't assume permission to stay there.
- Be curious, not judgmental. Don't guess at the next step or chase side quests.
- No jargon. Clear and concise.
- Don't end responses with leading questions. If you have a real question, ask it.
- Active working focus is code — tooling and demos. Slides, procurement, and session
  timing are tracked here but are not the current work.


# Traps

- **`'low'` is the WIDE +/-25 V range, `'high'` is +/-2.5 V.** The name is the
  amplifier gain, not the volts. Backwards from every guess.
- **The M2K ADC always returns both channels, interleaved.** Ask for one and gr-iio
  splits the two-channel buffer as if it were one: channel 2 lands in channel 1, the
  time base is 2x slow, and it presents as a tone at exactly Nyquist.
- **The ADC front end comes up powered down** on an uninitialised board, and gives a
  plausible flat line rather than an error. Clear `powerdown` on `m2k-fabric`.
- **Cyclic buffers quantise frequency.** A repeating N-sample buffer only produces
  multiples of `rate/N`, so 10 kHz comes back as 9979.2 Hz and that is correct.
- **Volts-per-count depends on the sample rate**, through the decimation filter's gain
  -- and the same correction applies to the trigger level, which otherwise sits 9% from
  where the scope says it is. The generator has the same problem, less regularly.
- **Reading trigger attributes back proves nothing.** A silently free-running trigger
  sets every one correctly and delivers every sample. Only alignment, a stall above the
  peak, and the edge's slope tell them apart.
- **`-tx` and `-rx` hold separate `sampling_frequency`.** Each digital block writes
  only its own device, so a Sink and a Source given different rates disagree about time
  and neither complains.
- **At rest the digital sink is the opposite of the generator.** The DAC holds its last
  cyclic buffer; DIO pins snap back to `raw`.
- **The keep-alive means `tb.run()` never returns** -- it waits for every block and the
  updater never ends. A `head`-terminated graph looks like a hung board. Use
  `start`/`stop`/`wait`.
- **Positive digital `trigger_delay` is approximate.** Zero and negative are exact and
  repeat; positive lands tens of samples off, differently each run, reading back right.
- **`calibbias` is storage; `calibscale` is not.** Write `calibbias`, read it back, and
  it holds the value while changing nothing in the samples -- the ADC's offset trim is
  really `ad5625` channels 2 and 3. `calibscale` is the opposite: the driver applies it
  before you see the sample, so a block that reads it back and multiplies again is
  wrong by exactly that factor.
- **Calibration mode reads the same counts on both ranges.** Its references and the
  generator loopback arrive past the input amplifier, so `volts_per_count()` mis-scales
  them by 4.7x. Convert at a fixed 0.29297 mV/count instead.
- **A disconnected input reads as a clean, stable, plausible number** -- its own
  offset. Input 1 sat at -13.9 counts through a full-volt swing on a generator wired
  to the wrong socket, three runs, and -13.9 was a genuinely correct prior
  measurement. Only sweeping the source and watching for *no* response tells a dead
  wire from a real reading.
- **gr-iio's `device_sink` drives ONE DIO pin, silently.** Sixteen 1-bit fields share
  one 16-bit word; each channel's write is a full-width store that erases the last, so
  only the highest pin survives. No error. `docs/gr-iio-multipin-sink.md`.
- **GRC `dtype: enum` values are raw strings.** `'0' + '3'` concatenates, `int("'6'")`
  raises, and an assert that raises makes GRC fall back to defaults without saying so.

# Decisions

- Board-pack authoring rules — evidence tiers and the `check` field, the real capture
  alongside the fixture rather than over it, chip plumbing deferred — are settled and
  still binding; the archive has them in full.

- **2026-09-01** — Calibration is a standalone script run once per session, not block
  init. Reason: it seizes the whole analog front end, is a closed loop `attr_sink`
  cannot express, and its result persists on the device.
- **2026-09-01** — The filter corrections are arithmetic, not calibration, and live in
  `m2k_scale.py`. Reason: fixed property of the converters, same on every board.
- **2026-09-01** — libm2k may check our numbers on the bench, but the workshop ships no
  libm2k dependency. Reason: the point is that IIO alone does not know what a sample is
  worth.
- **2026-09-01** — Writes to the instrument are allowed with per-write approval,
  superseding the read-only default of 2026-08-18.
- **2026-09-02** — Both digital blocks take `first_pin`, and a sink and source in one
  flowgraph get disjoint ranges. Reason: `pins_for` counted from DIO0 only, so any pair
  fought over `direction` and the loser did nothing silently.
- **2026-09-02** — Blocks are named on the analog/digital axis, not by instrument, and
  the supply (`ad5627`) gets no block for now. Reason: the four cover nine Scopy
  instruments between them; nothing planned needs the supply.
- **2026-09-02** — `digital_sink` defaults `idle_level` to `'low'` rather than leaving
  `raw` alone. Reason: the resting level was otherwise leftover state from whatever
  last touched the board.
- **2026-09-02** — `digital_sink` packs the 16-bit output word itself with pylibiio
  instead of using `iio.device_sink`. Reason: device_sink can only drive one pin;
  patching gr-iio upstream is deferred.
- **2026-09-03** — `m2k_calibrate.py` trims DAC offset only, and ADC gain *and* offset,
  both per channel. Reason: two-point meter runs put both DAC gains within 0.25% of
  unity while the two ADC gains differ 0.52%.
- **2026-09-03** — Calibration lands on the `ad5625` trim DAC and `m2k-adc calibscale`;
  blocks apply neither. Reason: `calibbias` is inert and the driver applies `calibscale`
  itself, so a block re-applying it double-counts the gain.
- **2026-09-03** — Calibration-mode captures convert at a fixed 0.29297 mV/count, not
  `volts_per_count()`. Reason: the internal references bypass the input range amplifier,
  which is why libm2k forces `hw_gain` to 1 there.
- **2026-09-03** — Generator offset comes from a five-point sweep's zero crossing, not
  libm2k's single capture through a 9.06 divider. Reason: a crossing needs no scale
  factor at all, and this board's loopback measures 8.34.

# Plan

**Phase 1 (current) — crawl:** Block-building is done and hardware-verified, both
triggers and a real SPI bus included, and calibration has closed the absolute error.
Open: the board pack (Tier 1 + Tier 2, 104 attributes, ~90% coverage expected).

**Timing:** GRCon26 is this month, Phases 2 and 3 have not started, slides are gated
behind working demos, and setup instructions are due two weeks prior.

**Phase 2 — walk:** IIO block anatomy through the discover/explain pair; the handout in
`docs/reading-iio-attributes.md` is the participant-facing artifact.

**Phase 3 — run:** standing-wave / VSWR, ultrasonic, CN0363 colorimeter.

**Later:** rebuild the standing-wave display; pick the hands-on participant station;
move acquisition state server-side; slides, procurement, timing.

# Status

- **Repo:** `main` at `b5a3b67`. `gr-m2k/m2k_calibrate.py`, `tests/test_calibrate.py`
  and a corrected `m2k_scale.py` docstring are new and uncommitted.
  `m2k-discovery-gui` is merged and deletable.
- **`gr-m2k/` — four blocks**: `analog_source`, `analog_sink`, `digital_source`,
  `digital_sink`, plus `m2k_scale.py` (arithmetic, imports nothing) and
  `m2k_config.py`.
- **Bench checklist sections 1-9 all pass**, section 4's absolute accuracy aside.
  `docs/bench-checklist.md` is the record. Section 9 is a real SPI mode-0 bus on
  three DIO pins, verified over all 256 byte values with zero errors.
- **Everything the four blocks do is hardware-verified.** `raw` both drives and
  reads a pin with no flowgraph — that is Scopy's Digital IO, in both directions.
- **Absolute error is closed and meter-verified.** `gr-m2k/m2k_calibrate.py --apply`
  moved input 1 from gain 0.93686 / offset -20.9 mV to 1.00080 / -1.0 mV, input 2 from
  0.93199 / +61.9 mV to 1.00310 / -0.35 mV, W1's offset from +48.5 mV to +10.0 mV and
  W2's from +112.1 mV to +17.0 mV. A 1.0 V input read 0.916 V before and reads 0.9998 V
  now. Internal references only -- the meter was the independent check, not an input.
  The generators keep ~10 and ~17 mV because the internal loopback never sees a DMM's
  load. Evidence: `bench/dc_point.py`, checklist section 10.
- **Live M2K at `ip:192.168.2.1`** (Rev.D Z7010, fw v0.33), network backend, no USB
  passthrough. Calibrated and held; all 16 DIO pins are inputs, triggers off.
- **Tests:** 253 pass, 41 new around the calibration arithmetic.
- **Discovery tooling** unchanged for four sessions. Real-hardware ABI coverage 57%;
  58 of 74 overlay entries still `UNVERIFIED`.
- **Hardware:** ADALM2000, one CN0363, 10x Pico, instructor ultrasonic mic board.
  40 kHz TX/RX pairs on order.

# ToDo

- [ ] Add `flowgraphs/m2k_digital_loopback.grc` — sink at DIO0, source at DIO1.
- [ ] Non-cyclic digital streaming underruns at 1 MS/s (half the runs) — find the rate
      where it stops.
- [ ] Delete the merged `m2k-discovery-gui` branch.

- [ ] Confirm `attr_note()` reaches these attributes first — `in_voltage0_trigger_delay`
      must reduce to `trigger_delay`, device attrs must hit the same flat `pack["attrs"]`.
      Otherwise entries get written and never displayed.
- [ ] Tier 1 (96 attributes) — new packs for `m2k-logic-analyzer` and `-rx`, plus the
      shared trigger attributes on `-tx` and both DACs. Checklist section 8 measures
      most of the `-rx` trigger set, so those go in as `MEASURED`.
- [ ] Tier 2 (8 attributes) — `m2k-adc-trigger` as a new pack, `m2k-fabric`
      `calibration_mode` + `clk_powerdown`, `m2k-adc` `calibrate`. The existing
      `calibrate` entry is wrong: it is `setCalibrateHDL`, FPGA interface training,
      not a rewrite of `calibscale`/`calibbias`.
- [ ] Then the bookkeeping: tests for the new entries; re-run coverage (57% → ~90%
      expected); read the `channels-m2k-adc.txt` golden diff by hand rather than
      `REGEN_GOLDEN=1`; correct the README's "95%" claim to report synthetic and real
      separately; sweep the remaining `[overlay: UNVERIFIED]` entries via each `check`.
- [ ] Commit the real capture alongside the synthetic fixture (not over it) and point
      README demos at it. Decide whether to scrub `hw_serial` and `cal,*` first.
- [ ] Confirm whether `ctx.attrs` returns strings or objects on the installed libiio —
      `iio_discover._read()` handles both, neither observed.
- [ ] Recover or rebuild `standing_wave_view.jsx`.
- [ ] Bench-measure whether 40 kHz transducers have the bandwidth for sweep-direction
      encoding or must use two-tone FSK, and whether the M2K input resolves the mic
      signal without a gain stage.
- [ ] Decide which demo becomes the hands-on participant station.
- [ ] Move standing-wave acquisition state server-side for late joiners.
- [ ] Write participant setup instructions; send two weeks before the session.
- [ ] Slides — after demos run.
