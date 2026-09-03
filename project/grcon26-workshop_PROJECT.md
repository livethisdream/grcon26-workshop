---
name: "#grcon26-workshop"
dateCreated: 2026-08-18
dateModified: 2026-09-02
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
- **One `iio_buffer_push` per cyclic buffer.** Later pushes return `-EBUSY`; the
  `Device or resource busy (16)` warning is expected.
- **Volts-per-count depends on the sample rate**, through the decimation filter's gain
  -- same for the generator, with a much less regular table.
- **The scope and generator clocks are 100 and 75 MS/s**; no rate is legal for both.
- **A loopback cannot check absolute accuracy.** Errors at the two ends multiply and
  two wrong numbers can look right.
- **Reading trigger attributes back proves nothing.** A silently free-running trigger
  sets every one correctly and delivers every sample. Only alignment, a stall above the
  peak, and the edge's slope tell them apart.
- **The decimation filter's correction applies to the trigger level too.** Leave it out
  and the trigger sits 9% from where the scope says it is.
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
- **Offsets are per channel; gain is not.** Both signal paths share one gain error to
  0.7%, but their offsets differ 6.8x. Deriving offset once and applying it everywhere
  is wrong by most of it.
- **gr-iio's `device_sink` drives ONE DIO pin, silently.** Sixteen 1-bit fields share
  one 16-bit word; each channel's write is a full-width store that erases the last, so
  only the highest pin survives. No error. `docs/gr-iio-multipin-sink.md`.
- **GRC `dtype: enum` values are raw strings.** `'0' + '3'` concatenates, `int("'6'")`
  raises, and an assert that raises makes GRC fall back to defaults without saying so.

# Decisions

- Every flowgraph uses libiio / gr-iio as its source. Reason: the workshop teaches the
  IIO path specifically; no flowgraph uses a different source block.
- No live software installs during the session. Reason: setup instructions go out two
  weeks prior instead.
- Demos must run before any slides get written.
- Hardware scarcity is solved by architecture — one instructor unit, many receive-only
  stations. Reason: works for ultrasonic and standing-wave, not CN0363.
- Overlay entries come from read-only evidence plus libm2k source tracing, each with a
  `check` field. Confidence is `MEASURED` only for what a capture proves, `SOURCED`
  where behaviour traces to libm2k, `UNVERIFIED` for anything inferred from a name.
- The real capture goes in alongside `fixtures/m2k-snapshot.json`, not over it.
  Reason: the fixture keeps goldens stable; participants should explain real data.
- `pll` / `ad9963` internals, `dma_sync_start`, `raw_enable` and `trigger_status` are
  deferred from the board pack. Reason: chip plumbing, no evidence to write from.

- **2026-09-01** — Calibration is a standalone script run once per session, not block
  init. Reason: it seizes the whole analog front end, is a closed loop `attr_sink`
  cannot express, and its result persists on the device.
- **2026-09-01** — Blocks read `calibscale`/`calibbias` and apply them. Reason: libm2k
  applies the gain in software, so the driver does not correct the samples for us.
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

# Plan

**Phase 1 (current) — crawl:** Block-building is done and hardware-verified, both
triggers and a real SPI bus included. Open: a calibration script for the last ~6.5%,
then the board pack (Tier 1 + Tier 2, 104 attributes, ~90% coverage expected).

**Scope check:** no Phase 3 demo needs a new M2K block, and the four cover every Scopy
instrument except the supply (`ad5627`), which is deferred and unneeded.

**Timing:** GRCon26 is this month, Phases 2 and 3 have not started, slides are gated
behind working demos, and setup instructions are due two weeks prior.

**Phase 2 — walk:** IIO block anatomy through the discover/explain pair; the handout in
`docs/reading-iio-attributes.md` is the participant-facing artifact.

**Phase 3 — run:** standing-wave / VSWR, ultrasonic, CN0363 colorimeter.

**Later:** rebuild the standing-wave display; pick the hands-on participant station;
move acquisition state server-side; slides, procurement, timing.

# Status

- **Repo:** `main`. Uncommitted: the packed sink, both digital ymls, the SPI
  flowgraph, `bench/`, and three docs. `m2k-discovery-gui` is merged and deletable.
- **`gr-m2k/` — four blocks**: `analog_source`, `analog_sink`, `digital_source`,
  `digital_sink`, plus `m2k_scale.py` (arithmetic, imports nothing) and
  `m2k_config.py`.
- **Bench checklist sections 1-9 all pass**, section 4's absolute accuracy aside.
  `docs/bench-checklist.md` is the record. Section 9 is a real SPI mode-0 bus on
  three DIO pins, verified over all 256 byte values with zero errors.
- **Everything the four blocks do is hardware-verified.** `raw` both drives and
  reads a pin with no flowgraph — that is Scopy's Digital IO, in both directions.
- **Residual absolute error is ~6.5%, one shared gain error**, consistent with
  `calibscale` (`1.000000` here). Offsets are per channel: W1 +49.4 mV, W2
  +114.5 mV, input 1 -21.4 mV, input 2 not yet split.
- **Live M2K at `ip:192.168.2.1`** (Rev.D Z7010, fw v0.33), network backend, no USB
  passthrough — `--scan` finds only `local:`. All 16 DIO pins restored to inputs,
  triggers off, board safe to unplug.
- **Tests:** 212 pass, 7 new around the packed digital sink.
- **Discovery tooling** unchanged for four sessions. Real-hardware ABI coverage 57%;
  58 of 74 overlay entries still `UNVERIFIED`.
- **Hardware:** ADALM2000, one CN0363, 10x Pico, instructor ultrasonic mic board.
  40 kHz TX/RX pairs on order.

# ToDo

- [ ] Meter W2 at +1.0 V — one reading closes the input-2 offset split.
- [ ] Build `m2k_calibrate.py` against `m2k-fabric calibration_mode` and the `ad5625`,
      checked against libm2k's `calibrateADC()`. Per-channel offsets. Confirm on the
      way whether the input offset is a fixed count error scaling with range.
- [ ] Add `flowgraphs/m2k_digital_loopback.grc` — sink at DIO0, source at DIO1.
- [ ] Non-cyclic digital streaming underruns at 1 MS/s (half the runs) — find the rate
      where it stops.
- [ ] Delete the merged `m2k-discovery-gui` branch.

- [ ] Confirm `attr_note()` reaches these attributes before writing prose — channel
      attrs like `in_voltage0_trigger_delay` must reduce to `trigger_delay`, and
      device attrs must hit the same flat `pack["attrs"]` dict. Otherwise entries get
      written and never displayed.
- [ ] Write the Tier 1 board-pack entries (96 attributes) — new packs for
      `m2k-logic-analyzer` and `-rx`, plus the shared trigger attributes on `-tx` and
      both DACs. Section 8 of the bench checklist now measures most of the `-rx`
      trigger set, so those go in as `MEASURED`.
- [ ] Write the Tier 2 entries (8 attributes) — `m2k-adc-trigger` as a new pack,
      `m2k-fabric` `calibration_mode` + `clk_powerdown`, `m2k-adc` `calibrate`.
- [ ] Add tests covering the new overlay entries, and re-run the coverage report to
      confirm the number actually moved (57% → ~90% expected).
- [ ] Review the `tests/golden/channels-m2k-adc.txt` diff by hand when adding
      `calibrate`, rather than blanket-accepting `REGEN_GOLDEN=1`.
- [ ] Commit the real capture alongside the synthetic fixture (not over it) and point
      README demos at it. Decide whether to scrub `hw_serial` and `cal,*` first.
- [ ] Correct the README's "95%" coverage claim — report synthetic and real separately.
- [ ] Verify every `[overlay: UNVERIFIED]` entry in `iio_overlays.py` using its `check`
      field; promote to `MEASURED`.
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
