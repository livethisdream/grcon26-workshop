---
name: "#grcon26-workshop"
dateCreated: 2026-08-18
dateModified: 2026-09-01
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

- **`'low'` is the WIDE +/-25 V range, `'high'` is +/-2.5 V.** The name describes the
  amplifier gain, not the volts. Backwards from every guess.
- **gr-iio's `device_phy` must name a real device.** `""` is not "none" -- it goes
  through `iio_context_find_device` and always fails with `Device not found`.
- **The M2K ADC always returns both channels, interleaved.** Ask for one and gr-iio
  splits a two-channel buffer as if it were one: channel 2 lands in channel 1 and the
  time base is 2x slow. Presents as a tone at exactly Nyquist.
- **The ADC front end comes up powered down** on a board nothing has initialised, and
  the result is a plausible flat line, not an error. Clear `powerdown` on `m2k-fabric`.
- **`set_len_tag_key` on a sink** demands a tagged stream and refuses without one.
  Harmless on a source.
- **Cyclic buffers quantise frequency.** A repeating N-sample buffer can only produce
  multiples of `rate/N`, so 10 kHz comes back as 9979.2 Hz and that is correct.
- **One `iio_buffer_push` per cyclic buffer.** Later pushes return `-EBUSY`; the
  `Device or resource busy (16)` warning is expected, not a fault.
- **Volts-per-count depends on the sample rate**, through the decimation filter's gain.
  Same for the generator, with a much less regular table.
- **The scope and generator clocks are 100 MS/s and 75 MS/s** and no rate is legal for
  both.
- **`attr_sink` writes nothing for the first `CONFIG_INTERVAL_MS`** (currently 1000).
  Short captures finish before their own configuration arrives.
- **A loopback cannot check absolute accuracy.** Errors at the two ends multiply, and
  two wrong numbers can look right.

# Decisions

- The IIO discovery tool is a standalone Python program, optionally packaged
  out-of-tree — not a GRC patch. Reason: GRC can't do dropdowns populated from live
  hardware.
- Every flowgraph uses libiio / gr-iio as its source. Reason: the workshop teaches the
  IIO path specifically; no flowgraph uses a different source block.
- No live software installs during the session. Reason: setup instructions go out two
  weeks prior instead.
- Demos must run before any slides get written.
- Hardware scarcity is solved by architecture where possible — one instructor unit,
  many receive-only stations. Reason: works for the ultrasonic and standing-wave
  demos. Does not work for the CN0363, where there is genuinely only one board.
- Enumeration and explanation are separate tools; `iio_explain.py` never imports
  libiio. Reason: a snapshot captured once on the bench explains anywhere, on any
  laptop, with no hardware — which is also how one M2K serves twenty people with no
  installs during the session. The architecture absorbs the hardware-scarcity
  constraint instead of the logistics doing it.
- Attribute meaning is quoted verbatim from the kernel IIO ABI, not paraphrased, and
  every line is tagged with its source: `[abi]`, `[parsed]`, `[driver]`,
  `[overlay: sourced]`, `[overlay: UNVERIFIED]`. Reason: keeps fact, convention and
  guesswork distinguishable — unverified board-specific claims must not be taught as
  fact.
- Overlay entries are written from read-only evidence plus libm2k source tracing. The
  `check` field records how to confirm each claim on the bench later.
- Overlay confidence policy: `MEASURED` only for what a capture directly proves — an
  attribute exists on a device, and its legal values as read from the folded
  `*_available` sibling. `SOURCED` where behaviour traces to libm2k. `UNVERIFIED` for
  anything inferred from option names alone.
- The real capture goes in alongside `fixtures/m2k-snapshot.json`, not over it. Reason:
  the synthetic fixture keeps the goldens stable and needs no regeneration, while
  participants should be explaining real data — handing them a fiction undercuts the
  "capture once, explain anywhere" premise the whole tool split exists to serve.
- `pll` and `ad9963` internals, plus `dma_sync_start` / `raw_enable` / `trigger_status`,
  are deferred from the board pack. Reason: chip-internal plumbing with low teaching
  value for a workshop about the IIO path, and they would have to be written from
  datasheets rather than from evidence.

- **2026-09-01** — Calibration is a standalone script run once per session, not block
  init. Reason: it seizes the whole analog front end, is a closed loop `attr_sink`
  cannot express, and its result persists on the device.
- **2026-09-01** — Blocks read `calibscale`/`calibbias` and apply them. Reason: libm2k
  applies the gain in software, so the driver does not correct the samples for us.
- **2026-09-01** — The filter corrections are arithmetic, not calibration, and live in
  `m2k_scale.py`. Reason: fixed property of the converters, identical on every board.
- **2026-09-01** — libm2k may be used to check our numbers on the bench, but the
  workshop ships no libm2k dependency. Reason: the point is that IIO alone does not
  know what a sample is worth.
- **2026-09-01** — Writes to the instrument are allowed with per-write approval,
  superseding the read-only default of 2026-08-18. Reason: the bench work needs them.

# Plan

**Phase 1 (current) — crawl:** The four M2K blocks now run against real hardware and
the loopback is accurate to a few percent. Open: the trigger path, the digital blocks,
and a calibration script to close the last ~7%. Then the 43% explanation gap, by
writing the logic-analyzer board pack — Tier 1 (96 attributes) + Tier 2 (8), which
should take coverage to ~90%.

**Phase 2 — walk:** IIO block anatomy, taught through the discover/explain pair. The
generated handout in `docs/reading-iio-attributes.md` is the participant-facing
artifact.

**Phase 3 — run:** application demos — standing-wave / VSWR, ultrasonic, CN0363
colorimeter.

**Later:** rebuild the standing-wave display; decide which demo becomes the hands-on
participant station; move acquisition state server-side; slides, procurement, timing.

# Status

- **Branch:** `m2k-discovery-gui`, three commits added 2026-09-01 (2a6e5cf, 5224133,
  e6f610a) on top of the waveform/digital block work. **Nothing pushed; `main` is still
  4+ commits ahead of `origin/main`.**
- **`gr-m2k/` — four GNU Radio blocks** (`scope_source`, `waveform_sink`, `digital`
  source/sink) plus `m2k_scale.py`, which holds the arithmetic and imports nothing.
- **All four blocks now run against real hardware.** Bench checklist sections 1, 2, 5
  and 6 pass; 3 passes except the trigger; 4 passes relative and is ~7% out absolute;
  7 not started. `docs/bench-checklist.md` is the record.
- **Scope and generator volts are accurate to a few percent** since the filter
  corrections went in. The residual is `calibscale`, which is `1.000000` on this board.
- **Live M2K at `ip:192.168.2.1`** (Rev.D Z7010, fw v0.33) over the network backend. No
  USB passthrough; `--scan` finds only `local:`, so the URI must be given.
- **Tests:** the scale suite passes. Three failures in `tests/test_grc_integration.py`
  are a missing `yaml` in `.venv`, pre-existing and unrelated.
- **Discovery tooling** (`iio_discover.py` / `iio_explain.py` / `iio_semantics.py` /
  `iio_overlays.py`) is on `main` and unchanged this session. ABI coverage on real
  hardware is 57%; 58 of 74 overlay entries are still `UNVERIFIED`.
- **`standing_wave_view.jsx`** is still lost — not in the repo, not on disk.
- **Hardware:** ADALM2000, one CN0363, 10x Pico, instructor ultrasonic mic board.
  40 kHz TX/RX pairs on order.

# ToDo

- [ ] Test the trigger path — `m2k-adc-trigger` writes have never executed.
- [ ] Run bench-checklist section 7 (digital): drive DIO0, read an externally driven
      pin, confirm `direction` and that a dropdown rate is accepted.
- [ ] Fix `CONFIG_INTERVAL_MS = 1000` in `m2k_config.py` — no setting is in force for
      the first second of any flowgraph.
- [ ] Suppress or explain the cyclic-buffer `Device or resource busy (16)` warning.
- [ ] Build `m2k_calibrate.py` against `m2k-fabric calibration_mode` and the `ad5625`,
      checked against libm2k's own `calibrateADC()` / `getAdcGain()`.
- [ ] Confirm W2 works and is independent of W1.
- [ ] Add `yaml` to `.venv` — three `test_grc_integration.py` tests cannot run.

- [ ] Push `main` (4 commits ahead of `origin/main`, unpushed).
- [ ] Confirm the `attr_note()` lookup path actually reaches these attributes before
      writing prose — channel attrs like `in_voltage0_trigger_delay` must reduce to the
      info word `trigger_delay`, and device-level attrs must hit the same flat
      `pack["attrs"]` dict. If they don't, entries get written but never displayed.
- [ ] Write the Tier 1 board-pack entries (96 attributes): `m2k-logic-analyzer` as a new
      pack with `direction`, `outputmode`, `clocksource`; `m2k-logic-analyzer-rx` with
      `trigger_delay`, `trigger_logic_mode`, `trigger_mux_out`, `data_delay_auto`,
      `data_in_delay`, `rate_mux`; shared `trigger_condition` / `trigger_src` on
      `m2k-logic-analyzer-tx`, `m2k-dac-a`, `m2k-dac-b`.
- [ ] Write the Tier 2 entries (8 attributes): `m2k-adc-trigger` as a new pack
      (`direction`, `holdoff_raw`, `delay`, `embedded`, `logic_mode`), `m2k-fabric`
      `calibration_mode` + `clk_powerdown`, `m2k-adc` `calibrate`.
- [ ] Add tests covering the new overlay entries, and re-run the coverage report to
      confirm the number actually moved (57% → ~90% expected).
- [ ] Watch `tests/golden/channels-m2k-adc.txt` when adding `calibrate` to `m2k-adc` —
      review the diff before regenerating rather than blanket-accepting `REGEN_GOLDEN=1`.
- [ ] Commit the real capture alongside the synthetic fixture (not over it); point
      README demo commands at the real one. Decide whether to scrub `hw_serial` and the
      `cal,*` constants first.
- [ ] Correct the README's "95%" coverage claim to report synthetic and real
      separately.
- [ ] Verify every `[overlay: UNVERIFIED]` entry in `iio_overlays.py` using its `check`
      field; promote to `MEASURED`.
- [ ] Confirm whether `ctx.attrs` returns strings or attribute objects on the installed
      libiio — `iio_discover._read()` handles both, but neither has been observed.
- [ ] Recover or rebuild `standing_wave_view.jsx`.
- [ ] Bench-measure whether 40 kHz transducers have the bandwidth for sweep-direction
      encoding, or whether it has to be two-tone FSK.
- [ ] Bench-measure whether the M2K input can resolve the mic signal without a gain
      stage.
- [ ] Decide which demo becomes the hands-on participant station.
- [ ] Move standing-wave acquisition state server-side for multiple clients and late
      joiners.
- [ ] Write participant setup instructions; send two weeks before the session.
- [ ] Slides — after demos run.
