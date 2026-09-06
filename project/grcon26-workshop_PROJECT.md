---
name: "#grcon26-workshop"
dateCreated: 2026-08-18
dateModified: 2026-09-06
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
- **The two directions never share a rate.** On the digital side `-tx` and `-rx` hold
  separate `sampling_frequency`, so a Sink and a Source given different rates disagree
  about time. On the analog side the ladders themselves differ -- 75 MS/s decades for
  the generator, 100 MS/s decades for the scope. Neither case complains.
- **At rest the digital sink is the opposite of the generator.** The DAC holds its last
  cyclic buffer; DIO pins snap back to `raw`.
- **The keep-alive means `tb.run()` never returns** -- it waits for every block and the
  updater never ends. A `head`-terminated graph looks like a hung board. Use
  `start`/`stop`/`wait`.
- **Positive digital `trigger_delay` is approximate.** Zero and negative are exact and
  repeat; positive lands tens of samples off, differently each run, reading back right.
- **Calibration mode reads the same counts on both ranges.** Its references and the
  generator loopback arrive past the input amplifier, so `volts_per_count()` mis-scales
  them by 4.7x. Convert at a fixed 0.29297 mV/count instead.
- **gr-iio's `device_sink` drives ONE DIO pin, silently.** Sixteen 1-bit fields share
  one 16-bit word; each channel's write is a full-width store that erases the last, so
  only the highest pin survives. No error. `docs/gr-iio-multipin-sink.md`.
- **GRC `dtype: enum` values are raw strings.** `'0' + '3'` concatenates, `int("'6'")`
  raises, and an assert that raises makes GRC fall back to defaults without saying so.
- **A triggered digital capture is gapped between buffers and re-arms per buffer**, so
  the trigger edge is a frame boundary. CS framed per byte makes every buffer start on
  an arbitrary byte: the stream prints rotations, every byte individually correct.
- **gr-iio's `device_source` ends itself on any refill error.** `work()` returns
  WORK_DONE on a timeout, so a triggered source waiting on a human never comes back --
  one message decodes and the capture is gone. `set_timeout_ms` stores its value and
  never hands it to libiio. Free-run the source; trigger the display.
- **A non-cyclic digital sink pushes one DMA buffer at a time and need not join them.**
  A frame lying across the seam tears mid-message. `m2k_spi_encode`'s "Align frames to"
  holds a queued frame until the next boundary; its sample count is the sink's position.

# Decisions

- Closed and rotated to the archive, which has the reasoning in full: the board-pack
  authoring rules (settled, still binding), the three digital-block decisions, and
  calibration's four. Their live halves are traps and `docs/gr-iio-multipin-sink.md`.

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
- **2026-09-04** — Build a DC power supply block, reversing the 2026-09-02 "no supply
  block" decision. Reason: GNU Radio cannot control a power rail at all, and the
  setpoint spans four places including the context `cal,*` attributes.
- **2026-09-04** — Standing-wave / VSWR is out of the workshop. Reason: scope control
  with GRCon26 this month; it carried the most unbuilt work of the three.
- **2026-09-04** — Discovery tooling drops to "if we have time"; the intro gets one
  slide on what IIO is and which M2K attributes matter. Reason: the blocks need no
  overlays, and `iio_explain.py --glossary` generates the slide content.
- **2026-09-04** — Ultrasonic reuses ECE448's `fsk_project.grc` (AFSK, 200 baud,
  600 Hz deviation) retuned to 40 kHz. Reason: already end to end; only the endpoints
  and the rates change, which is itself the lesson.
- **2026-09-04** — Ultrasonic transmits at 750 kS/s and receives at 1 MS/s. Reason:
  DAC and ADC have different rate ladders, and 40 kHz needs the third rung of each.
- **2026-09-04** — One SPI frame is one whole transaction, CS asserted once across all
  bytes. Reason: the capture re-arms per buffer, so per-byte CS framing starts each
  buffer on a random byte -- and one assertion is what real SPI does anyway.
- **2026-09-04** — Digital blocks take a pin list plus an optional name per line, not a
  count and an offset. Reason: a bus is not always contiguous, and a name only has to
  make an error legible — GRC will not evaluate a port label.
- **2026-09-04** — SPI sends on demand through a new `m2k_spi_encode` block; the cyclic
  version is kept as `m2k_spi_loopback_continuous.grc`. Reason: a cyclic buffer is
  repeated by the hardware and nothing downstream can gate it.
- **2026-09-04** — The decoded PDU carries the bytes as text in its metadata,
  not as the payload. Reason: the loopback's own proof, the way Scopy shows a text
  column, while the payload stays what was on the wire.
- **2026-09-04** — SPI mode 0 is checked against libsigrokdecode, not only against
  our own decoder. Reason: encoder and decoder were written from the same sentences, so
  a shared misreading round-trips clean and is still wrong on a real bus.

- **2026-09-06** — The deck is ECE444's frame view, ported standalone into `slides/`.
  Reason: one document serves the projector, the participant's notes and the printed
  handout, and nothing in it can be lost by presenting it. No book, no generator: one
  HTML file and three assets, published to Pages by a workflow.
- **2026-09-06** — Slides are written for the demos that run, with the two that do not
  as labelled placeholders. Reason: the SPI half is bench-verified end to end and
  gating the whole deck on the ultrasonic link would leave nothing written this month.

# Plan

**Phase 1 (current) — crawl:** Six blocks built, all bench-verified; calibration
has closed the absolute error. Open: a DC power supply block, a capability GNU Radio
does not have at all.

**Timing:** GRCon26 is this month and Phase 3 has not started. The deck exists for
everything that runs; setup instructions are due two weeks prior.

**Phase 2 — walk:** IIO block anatomy. One intro slide on what IIO is and which M2K
attributes matter, from `iio_explain.py --glossary`. `docs/reading-iio-attributes.md`
is the participant-facing artifact either way.

**Phase 3 — run:** ultrasonic FSK, then the CN0363 colorimeter. Ultrasonic reuses
ECE448's `fsk_project.grc` retuned to 40 kHz; steps in ToDo. Time-of-flight ranging is
the stretch goal if the FSK link lands early.

# Status

- **Repo:** branch `spi-send-on-demand`, PR open against `main`.
- **`gr-m2k/` — six blocks**: `analog_source`, `analog_sink`, `digital_source`,
  `digital_sink`, `spi_decode`, `spi_encode`, plus `m2k_calibrate.py`, `m2k_scale.py`
  and `spi_decode.py`/`spi_encode.py` (arithmetic, import nothing) and `m2k_config.py`.
  390 tests pass. Decoded messages carry the bytes as text in the PDU metadata.
- **The two digital ymls are generated** by `gr-m2k/generate_digital_grc.py`; a test
  fails if the committed copy drifts.
- **`slides/` — 47 frames**, frame view, read and present from one document. IIO,
  the M2K, the six blocks, SPI, and the loopback built one block at a time;
  ultrasonic and the colorimeter are labelled placeholders. `slides/check_deck.py`
  gates titles, ids and the 40-word present budget; every frame fits one screen at
  1024x768, 1280x800 and 1440x900, and it prints 49 sheets rather than 1.
- **Bench checklist sections 1-13 all pass.** Section 9 is a real SPI mode-0 bus over
  all 256 byte values; 11 runs `m2k_spi_decode` live at half = 4, 8, 16; 12 is
  send-on-demand, 20 sends clean at 100 kS/s, which also proves an untriggered capture
  is not gapped; 13 checks the bus against libsigrokdecode, off the board.
- **Absolute error is closed and meter-verified.** Input gains within 0.31% of unity,
  offsets under 1 mV; generators keep ~10-17 mV (the internal loopback never sees a
  DMM's load). Numbers: checklist section 10.
- **Live M2K at `ip:192.168.2.1`** (Rev.D Z7010, fw v0.33), network backend, no USB
  passthrough. Calibrated and held; all 16 DIO pins are inputs, triggers off.
- **Hardware in hand:** ADALM2000, one CN0363, 10x Pico, instructor ultrasonic mic
  board, 40 kHz TX/RX transducer pairs.
- **The FSK flowgraph Phase 3 reuses:** `~/USAFA/ECE448/L01_Intro/fsk_project.grc`
  (also `~/projects/ece448/faculty/`).

# ToDo

**DC power supply block**
- [ ] Fetch `m2kpowersupply_impl.cpp` via `iio_libm2k_fetch.py` for the raw-to-rail
      expression; measure a two-point sweep against the meter and let the meter win.
- [ ] Block: float setpoint in volts, rate-limited writes, one instance per rail.
      Clears `powerdown` on both `m2k-fabric` user_supply and `ad5627`, applies the
      context `cal,*` corrections.
- [ ] Precision demo — rail to input 1, commanded vs measured.
- [ ] Then the PWM LED application off `digital_sink`.

**Ultrasonic**
- [ ] Sweep 36-44 kHz with `analog_sink` / `analog_source` for resonance and the real
      -6 dB bandwidth. Everything downstream needs f0.
- [ ] Port `fsk_project.grc` to `flowgraphs/m2k_ultrasonic_fsk.grc`: split `samp_rate`
      into 750 kS/s tx and 1 MS/s rx, tones at f0 +/- 300, M2K endpoints, xlating
      filter recentred, `vco_f` output scaled to volts.
- [ ] Bench it, then measure range and off-axis falloff.
- [ ] Confirm non-cyclic analog streaming holds at 750 kS/s; fall back to one cyclic
      buffer if it underruns.

**Loose ends**
- [ ] Add `flowgraphs/m2k_digital_loopback.grc` — sink at DIO0, source at DIO1.
- [ ] Raise `samp_rate` on `m2k_spi_loopback.grc` from 100 kS/s a step at a time and
      record where send-on-demand stops holding. Nothing in the repo knows that rate.
- [ ] Run the sigrok check against a real M2K capture, not the encoder's arithmetic:
      `bench/spi_flowgraph.py M2K 8 --csv`, DIO0-2 wired to DIO4-6.
- [ ] Delete the merged `m2k-discovery-gui` branch.
- [ ] Decide which demo becomes the hands-on participant station.
- [ ] Write participant setup instructions; send two weeks before the session.
- [ ] Turn on Settings -> Pages -> Source: GitHub Actions so `pages.yml` can publish.
- [ ] Fill the two placeholder frames (`#ultrasonic`, `#colorimeter`) once those
      demos run. Everything else in `slides/` is written.

**If we have time**
- [ ] Overlay coverage (Tier 1 + Tier 2, ~104 attributes, 57% → ~90%) is parked. The
      full task list is in the archive under "Parked 2026-09-04".
