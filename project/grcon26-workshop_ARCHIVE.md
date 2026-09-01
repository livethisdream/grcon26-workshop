---
name: "#grcon26-workshop"
dateModified: 2026-09-01
---
# Superseded Decisions

- **2026-08-18** — "Overlay entries are written from read-only evidence; the instrument
  is not written to." Superseded 2026-09-01: bench work required writes, taken with
  per-write approval. The read-only default still holds for enumeration.

# Session Log

## 2026-08-18 — discovery tooling, first real capture

- **Repo:** `main` = 269d203, the merge of `claude/m2k-iio-parameter-discovery-12g30y`
  into the scaffold. All tooling is now on `main`. **4 commits ahead of `origin/main`
  and unpushed.** The merge hit the expected add/add conflict on `.gitignore`, resolved
  to the union of both sides.
- **Venv:** in-tree `.venv/` (uv, Python 3.12.13, pytest 9.1.1), gitignored per the
  WSL-native convention.
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
- **Tests:** 73 passing locally in ~1.1 s (`.venv/bin/python -m pytest tests -q`), with
  no hardware and no libiio.
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
- **The capture lives at `/tmp/m2k-real.json` and is not committed** — it will not
  survive a reboot. Re-capture with
  `./iio_discover.py --uri ip:192.168.2.1 --json > <file>` if it is gone.
- **`m2k-logic-analyzer` has no board-pack entry at all** — that single omission is 33
  of the unexplained attributes. `m2k-logic-analyzer-rx` and `-tx` have entries with
  empty `channels` and `attrs`.
- **The folded `*_available` lists are strong evidence for the missing entries**, read
  straight off hardware: `trigger_mux_out` offers
  `trigger-logic / trigger-in / -and- / -or- / -xor- / disabled` (a combining stage, not
  a selector); `trigger_logic_mode` is `or / and`; `direction` is `in / out`;
  `outputmode` is `push-pull / open-drain`; `rate_mux` is
  `logic_analyzer / oscilloscope`; `trigger_src` differs between the DACs
  (`trigger-Ti`) and the TX path (`trigger-i_0`, `trigger-i_1`).
- **Overlay work is planned but not started.** Tier 1 = `m2k-logic-analyzer` (new pack),
  `m2k-logic-analyzer-rx`, and the shared trigger vocabulary on `-tx` / `m2k-dac-a` /
  `m2k-dac-b` — 96 attributes. Tier 2 = `m2k-adc-trigger` (new pack), `m2k-fabric`
  `calibration_mode` + `clk_powerdown`, `m2k-adc` `calibrate` — 8 more. Awaiting go.
- **`standing_wave_view.jsx`** — described in the seed but **not in the repo, not on
  either branch, and not anywhere on disk.** Treat as lost unless it turns up.
- **Hardware:** ADALM2000 (possibly one per station), one CN0363 colorimeter, 10×
  Raspberry Pi Pico, instructor wideband ultrasonic mic board. 40 kHz ultrasonic
  TX/RX pairs on order.

## 2026-09-01 — first bench session with a live M2K

Ran `docs/bench-checklist.md` sections 1-6 against the board. Found four bugs that
stopped anything working, one that is still open, and two arithmetic omissions that a
loopback could never have caught. Full detail, measured constants and method are in
`docs/bench-checklist.md`; the fixes are in commits 2a6e5cf and 5224133.

Absolute calibration was done with a handheld meter against three DC levels, because
the M2K's own voltmeter is the same ADC through the same scaling factor and cannot
check itself. The `ad5625` internal reference chain was investigated as an alternative
and is good for zero, linearity and range ratio, but not for absolute accuracy -- the
path gain between `adc_ref1` and the front end is unknown.

# Ruled Out

- **The factory `cal,*` context attributes explain the absolute error.** They do not.
  `cal,gain_pos_adc = 0.99906`, `cal,gain_neg_adc = 0.99581` and the other six are all
  within 0.5% of unity; the error was 17.6%.
- **`9979.2 Hz` instead of 10 kHz is a rate bug.** It is cyclic-buffer quantisation:
  218 x 750000/16384 = 9979.2 exactly. It confirms the DAC clock rather than
  questioning it.
- **The loopback reading 1.0010 V for 1.0 V means the volts path is correct.** The
  generator was 16.7% high and the scope 15.4% low; the product is 0.99.
