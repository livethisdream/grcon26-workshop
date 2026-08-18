---
name: "#grcon26-workshop"
dateCreated: 2026-08-18
dateModified: 2026-08-18
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

# Plan

**Phase 1 (current) — crawl:** IIO intro and M2K loopback. Run `iio_discover.py`
against live hardware and review `--summary` output to size the GUI work against real
attribute counts.

**Phase 2 — walk:** IIO block anatomy; the discovery tool as a participant-facing
utility.

**Phase 3 — run:** application demos — standing-wave / VSWR, ultrasonic, CN0363
colorimeter.

**Later:** decide which demo becomes the hands-on participant station; move
standing-wave acquisition state server-side; slide production, procurement, session
timing.

# Status

- **Repo scaffolded 2026-08-18.** Contents so far are the seed brief only — neither
  source file below is in the repo yet.
- **`iio_discover.py`** — working library-plus-CLI per the seed. Walks the full IIO
  context hierarchy, folds `*_available` siblings into their parent attribute, exposes
  `enumerate_context()` for GUI reuse. Not yet run against live M2K hardware.
- **`standing_wave_view.jsx`** — complete React component for a browser live display,
  currently driven by `simulateSweep` (simulated data). Log-frequency sweep plot with
  null markers, tube cross-section pressure animation, readout panel (tube length,
  VSWR, first null frequency, null depth, speed of sound). Two teaching features:
  sweep point count visibly degrades the computed ratio at low density, and a
  raw/corrected toggle shows why the free-air reference matters.
- **Hardware:** ADALM2000 (possibly one per station), one CN0363 colorimeter, 10×
  Raspberry Pi Pico, instructor wideband ultrasonic mic board (FEL Communications via
  micbooster). 40 kHz ultrasonic TX/RX pairs on order.
- **Software baseline:** GNU Radio 3.10+, libiio, gr-iio (in-tree as of 3.10). Python
  for hardware interfacing and tooling, React for the web display. `iio_info` and
  `iio_attr` already cover command-line enumeration.

# ToDo

- [ ] Bring `iio_discover.py` and `standing_wave_view.jsx` into the repo.
- [ ] Run `iio_discover.py` against a live M2K; review `--summary` to size GUI work
      against real attribute counts.
- [ ] Bench-measure whether 40 kHz transducers have the bandwidth for sweep-direction
      encoding, or whether it has to be two-tone FSK.
- [ ] Bench-measure whether the M2K input can resolve the mic signal without a gain
      stage.
- [ ] Decide which demo becomes the hands-on participant station — M2K count may exceed
      input-board count, so parts may end up instructor-led.
- [ ] Replace `simulateSweep` with real hardware acquisition.
- [ ] Move standing-wave acquisition state server-side so multiple clients and late
      joiners work.
- [ ] Write participant setup instructions; send two weeks before the session.
- [ ] Slides — after demos run.
