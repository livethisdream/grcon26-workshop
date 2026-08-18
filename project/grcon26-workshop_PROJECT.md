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

# Plan

**Phase 1 (current) — crawl:** Merge the IIO branch to `main`. First real capture is
done; the open work is closing the 43% explanation gap, which is mostly one board-pack
section for the logic analyzer.

**Phase 2 — walk:** IIO block anatomy, taught through the discover/explain pair. The
generated handout in `docs/reading-iio-attributes.md` is the participant-facing
artifact.

**Phase 3 — run:** application demos — standing-wave / VSWR, ultrasonic, CN0363
colorimeter.

**Later:** rebuild the standing-wave display; decide which demo becomes the hands-on
participant station; move acquisition state server-side; slides, procurement, timing.

# Status

- **Repo:** scaffolded 2026-08-18 on top of the pre-existing GitHub history
  (`origin/main` 70c455f, seed file only). `main` = 105539f, one commit ahead of
  `origin/main`, unpushed.
- **The tooling is on an unmerged branch** —
  `claude/m2k-iio-parameter-discovery-12g30y` (80e7c49). `main` does not have it yet.
- **Two-tool split.** `iio_discover.py` (12 KB) enumerates — needs libiio and
  hardware. `iio_explain.py` (23 KB) explains meaning — needs neither. Workflow is
  `./iio_discover.py --json > m2k.json` on the bench, `./iio_explain.py m2k.json`
  anywhere else.
- **`iio_semantics.py`** (33 KB) — ABI knowledge: name grammar, units, conversion.
- **`iio_abi_fetch.py` + `iio_abi_data.json`** — parses the kernel's
  `Documentation/ABI/testing/sysfs-bus-iio` into a checked-in cache of 826 documented
  attribute names, so the tools work offline.
- **`iio_overlays.py`** — board-specific knowledge, confidence-tagged. 20 board notes
  total: 3 sourced, 17 unverified. M2K entries are traced to libm2k. Unverified
  entries each carry a `check` field describing how to confirm them.
- **Channel identity:** four sources consulted in order — driver channel name, `label`
  attribute, board pack, then the ABI convention that an indexed channel is an
  externally available input. Output reports which one answered.
- **`fixtures/m2k-snapshot.json`** — hand-authored synthetic capture, labelled as such
  in the file. Everything runs with no hardware against it.
- **Tests:** 73, no hardware or libiio required, per the branch README. Not yet run
  locally.
- **Live M2K reachable from WSL over the network backend** at `ip:192.168.2.1`
  (Rev.D Z7010, fw v0.33). No USB passthrough needed — `lsusb` is empty and `--scan`
  finds only `local:`, so the URI must be given explicitly.
- **First real capture, 2026-08-18** (154 KB, not yet committed): 14 devices, 98
  channels (36 scan elements), 317 attributes = 39 device + 260 channel + 10 buffer +
  8 debug. 112 channel attributes carry a folded `*_available` sibling — that is the
  dropdown-populating count, and the number that sizes the GUI work. Against the
  synthetic fixture's 44 attributes, real hardware is 7.2× larger.
- **ABI coverage on real hardware is 57%** (181 of 317), not the 95% the README
  reports from the synthetic fixture — that figure was an artifact of a fixture built
  mostly from generic attributes. 136 attributes are unexplained, and 86 of them are
  logic-analyzer trigger/direction attrs (`trigger_delay`, `trigger_logic_mode`,
  `trigger_mux_out` ×18 each; `direction`, `outputmode` ×16 each). The gap is
  concentrated, not diffuse.
- **`standing_wave_view.jsx`** — described in the seed but **not in the repo, not on
  either branch, and not anywhere on disk.** Treat as lost unless it turns up.
- **Hardware:** ADALM2000 (possibly one per station), one CN0363 colorimeter, 10×
  Raspberry Pi Pico, instructor wideband ultrasonic mic board. 40 kHz ultrasonic
  TX/RX pairs on order.

# ToDo

- [ ] Merge `claude/m2k-iio-parameter-discovery-12g30y` into `main` — expect an add/add
      conflict on `.gitignore`; resolve to the union.
- [ ] Push `main` (currently 1 commit ahead of `origin/main`, unpushed).
- [ ] Run `python3 -m pytest tests -q` locally to confirm the 73 tests pass.
- [ ] Write board-pack overlay entries for the logic analyzer — `trigger_delay`,
      `trigger_logic_mode`, `trigger_mux_out`, `direction`, `outputmode`. Closes ~86 of
      136 unexplained attributes.
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
