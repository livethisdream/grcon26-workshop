# Seed: GNU Radio + ADALM2000 workshop tooling

## What this is

I'm building hands-on workshop material that teaches GNU Radio using the ADALM2000 (M2K)
as the input device. Other boards sit on the input side of the M2K — the M2K is the
instrument, everything else is a signal source feeding it. The IIO library is the
interface layer for every flowgraph in the workshop; nothing uses a different source block.

Workshop shape: ~20 participants, basic GNU Radio familiarity, 90–120 minutes. Structure
is crawl (IIO intro, loopback) → walk (IIO block anatomy, discovery tool) → run
(application demos).

## How I want you to work

- Plan first, then execute. Show me the plan before you write code.
- Crawl, walk, run. Get the smallest thing working before adding scope.
- If you find yourself fixated on one aspect, stop and ask me whether that's the right
  thing to be focused on. Don't assume permission to stay there.
- Be curious, not judgmental. Don't guess at my next step or chase side quests.
- No jargon. Clear and concise.
- Don't end responses with leading questions. If you have a real question, ask it.

## Hardware and software

- ADALM2000 (M2K) — the instrument, possibly one per station
- CN0363 colorimeter — exactly one in hand
- Raspberry Pi Pico ×10
- 40 kHz ultrasonic transmit/receive pairs — on order
- Wideband ultrasonic mic board (FEL Communications via micbooster) — instructor unit
- GNU Radio 3.10+, libiio, gr-iio (in-tree as of 3.10)
- Python for hardware interfacing and tooling; React for the web display
- `iio_info` and `iio_attr` already cover enumeration at the command line

## Code that exists

**`iio_discover.py`** — working library-plus-CLI. Walks the full IIO context hierarchy,
folds `*_available` siblings into their parent attribute, and exposes
`enumerate_context()` so a GUI can reuse it. Next step is running it against a live M2K
and looking at `--summary` output to size the GUI work against real attribute counts.

**`standing_wave_view.jsx`** — complete React component for a browser-based live display,
currently driven by a simulated sweep. Log-frequency sweep plot with null markers, tube
cross-section pressure animation, readout panel (tube length, VSWR, first null frequency,
null depth, speed of sound). Two teaching features: sweep point count visibly degrades the
computed ratio at low density, and a raw/corrected toggle shows why the free-air reference
matters. `simulateSweep` is the single function to replace for real hardware. Acquisition
state should end up server-side so multiple clients and late joiners work.

## Decisions already made

- The discovery tool is a standalone Python program, optionally packaged out-of-tree. It
  is not a GRC patch — GRC can't do dropdowns populated from live hardware.
- No live software installs during the session. Setup instructions go out two weeks prior.
- Demos must run before any slides get written.
- Hardware scarcity gets solved by architecture where possible: one instructor unit, many
  receive-only stations. That works for the ultrasonic and standing-wave demos. It does
  not work for the CN0363, where there is genuinely only one board.

## Open

- Which demo becomes the hands-on participant station. I may have enough M2Ks but not
  enough input boards, so parts of this may end up instructor-led demo. Not locked in.
- Whether 40 kHz transducers have the bandwidth for sweep-direction encoding, or whether
  it has to be two-tone FSK. Needs a bench measurement.
- Whether the M2K input can resolve the mic signal without a gain stage. Also a bench
  measurement.

## Out of scope for this chat

Slide production, procurement, and workshop timing. This chat is for code.
