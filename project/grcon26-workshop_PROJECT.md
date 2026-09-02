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
- **A loopback cannot check absolute accuracy.** Errors at the two ends multiply, and
  two wrong numbers can look right.
- **Reading trigger attributes back proves nothing.** A trigger that is silently
  free-running sets every one of them correctly and delivers every sample. Only
  alignment, a stall above the peak, and the edge's slope tell them apart.
- **The decimation filter's correction applies to the trigger level too.** Leave it out
  and the trigger sits 9% away from where the scope says it is.
- **Offsets are per channel; gain is not.** Both signal paths share one gain error to
  0.7%, but their offsets differ 6.8x. Deriving offset once and applying it everywhere
  is wrong by most of it.

# Decisions

- Every flowgraph uses libiio / gr-iio as its source. Reason: the workshop teaches the
  IIO path specifically; no flowgraph uses a different source block.
- No live software installs during the session. Reason: setup instructions go out two
  weeks prior instead.
- Demos must run before any slides get written.
- Hardware scarcity is solved by architecture — one instructor unit, many
  receive-only stations. Reason: works for ultrasonic and standing-wave, not CN0363.
- Attribute meaning is quoted verbatim from the kernel IIO ABI and every line tagged
  `[abi]`/`[parsed]`/`[driver]`/`[overlay: sourced]`/`[overlay: UNVERIFIED]`. Reason:
  guesswork must not be taught as fact.
- Overlay entries are written from read-only evidence plus libm2k source tracing. The
  `check` field records how to confirm each claim on the bench later.
- Overlay confidence: `MEASURED` only for what a capture proves, `SOURCED` where
  behaviour traces to libm2k, `UNVERIFIED` for anything inferred from option names.
- The real capture goes in alongside `fixtures/m2k-snapshot.json`, not over it.
  Reason: the fixture keeps goldens stable; participants should explain real data.
- `pll` / `ad9963` internals, `dma_sync_start`, `raw_enable` and `trigger_status` are
  deferred from the board pack. Reason: chip plumbing, and no evidence to write from.

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
- **2026-09-01** — Attributes are written directly with libiio at construction, before
  `start()`; the `attr_updater` pair stays only as a keep-alive. Reason: a timer left
  the board unconfigured for the first second of every flowgraph.
- **2026-09-01** — Calibration offsets are measured per channel, never derived once and
  applied. Reason: the two paths' offsets differ 6.8x while their gains agree to 0.7%.

# Plan

**Phase 1 (current) — crawl:** Block-building is close to done. The scope and
generator are verified against hardware and a meter; the trigger passes. Open: the
digital pair (never run on hardware), a calibration script to close the last ~6.5%,
and a decision on whether the programmable supply gets a block. Then the 43%
explanation gap, by writing the logic-analyzer board pack — Tier 1 (96 attributes) +
Tier 2 (8), which should take coverage to ~90%.

**Scope check:** no Phase 3 demo needs a new M2K block — standing-wave and ultrasonic
are `scope_source` + `waveform_sink`, and the CN0363 is a different IIO device. The
supply (`ad5627`) is the only unrepresented instrument and nothing planned needs it.

**Timing:** GRCon26 is this month, Phases 2 and 3 have not started, slides are gated
behind working demos, and setup instructions are due two weeks prior.

**Phase 2 — walk:** IIO block anatomy, taught through the discover/explain pair. The
generated handout in `docs/reading-iio-attributes.md` is the participant-facing
artifact.

**Phase 3 — run:** application demos — standing-wave / VSWR, ultrasonic, CN0363
colorimeter.

**Later:** rebuild the standing-wave display; decide which demo becomes the hands-on
participant station; move acquisition state server-side; slides, procurement, timing.

# Status

- **Repo:** `main` = `c24304d`, pushed and in sync with `origin`. The
  `m2k-discovery-gui` branch is stale at `93de0e8`, fully merged, and can be deleted.
- **`gr-m2k/` — four blocks** (`scope_source`, `waveform_sink`, `digital` source/sink),
  each with a GRC definition, plus `m2k_scale.py` (arithmetic, imports nothing) and
  `m2k_config.py` (attributes on non-streaming devices).
- **Bench checklist sections 1-6 pass.** Section 7 (digital) is not started, so the
  digital pair has never run against hardware. `docs/bench-checklist.md` is the record.
- **Scope, generator and trigger are verified against hardware and a meter.** The
  trigger aligns to one sample step, stalls above the peak, and honours the edge.
- **The residual absolute error is ~6.5% and it is one shared gain error**, consistent
  with `calibscale` (which reads `1.000000` on this board). Offsets are per channel:
  W1 output +49.4 mV, W2 output +114.5 mV, input 1 -21.4 mV, input 2 not yet split.
- **Live M2K at `ip:192.168.2.1`** (Rev.D Z7010, fw v0.33), network backend, no USB
  passthrough — `--scan` finds only `local:`, so the URI must be given. Currently
  powered down: both stages, calibration mode clear, trigger free-running.
- **Tests:** 184 pass. `pyyaml` is now in `.venv`.
- **Discovery tooling** is unchanged for two sessions. ABI coverage on real hardware is
  57%; 58 of 74 overlay entries are still `UNVERIFIED`.
- **`standing_wave_view.jsx`** is still lost — not in the repo, not on disk.
- **Hardware:** ADALM2000, one CN0363, 10x Pico, instructor ultrasonic mic board.
  40 kHz TX/RX pairs on order.

# ToDo

- [ ] Meter W2 at +1.0 V requested — one reading closes the input-2 offset split.
- [ ] Run bench-checklist section 7 (digital): drive DIO0, read an externally driven
      pin, confirm `direction` and that a dropdown rate is accepted.
- [ ] Decide whether the programmable supply (`ad5627`) gets a block. Only
      unrepresented instrument; no planned demo needs it.
- [ ] Build `m2k_calibrate.py` against `m2k-fabric calibration_mode` and the `ad5625`,
      checked against libm2k's `calibrateADC()`. Must write per-channel offsets.
- [ ] Suppress or explain the cyclic-buffer `Device or resource busy` warning.
- [ ] Delete the merged `m2k-discovery-gui` branch.

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
