# IIO discovery and semantics

Workshop tooling for GNU Radio + ADALM2000. Three tools, deliberately split.

| | needs libiio | needs hardware | what it answers |
| --- | --- | --- | --- |
| `iio_discover.py` | yes | yes | what is here, what is it set to, what values are legal |
| `iio_explain.py` | no | no | what does it *mean* |
| `iio_browse.py` | no | no | what do I type into the GNU Radio block |
| `iio_grc.py` | no | no | the same, as a generated GRC block |

The split matters: capture once on the bench, explain anywhere.

```
on the bench:   ./iio_discover.py --json > m2k.json
anywhere else:  ./iio_explain.py m2k.json --channels
```

That is also how this works in a room of twenty people with one M2K between
them, and why nobody needs to install libiio during the session.

## Setup

Managed with [uv](https://docs.astral.sh/uv/).

```
uv sync
```

That is enough for everything except talking to real hardware. Both tools are
standard library only, so there is nothing to resolve but the test runner.

**For hardware,** `iio_discover.py` needs the libiio Python binding, which uv
cannot install for you — it wraps a native library, and the supported route on
Linux is the distro package (`sudo apt install python3-libiio`), which lands in
system site-packages where a normal venv cannot see it. Build the venv so it
can:

```
uv venv --system-site-packages
uv sync
uv run ./iio_discover.py --scan
```

The `--system-site-packages` flag survives later `uv sync` runs, so this is a
one-time step. Or skip the venv for that one script — its shebang uses system
python, which is why `./iio_discover.py --scan` already works:

```
./iio_discover.py --scan
```

## Try it now

There is a synthetic M2K snapshot checked in, so everything runs with no
hardware:

```
uv run ./iio_explain.py fixtures/m2k-snapshot.json                       # what it measures
uv run ./iio_explain.py fixtures/m2k-snapshot.json --attr raw --limit 1  # one attribute, in depth
uv run ./iio_explain.py fixtures/m2k-snapshot.json --unknown             # what we still cannot explain
uv run ./iio_explain.py fixtures/m2k-snapshot.json --glossary            # participant handout
```

`uv run` is not required for the explainer — it has no dependencies, so plain
`./iio_explain.py` works too. Use whichever you prefer.

Both `fixtures/m2k-real.json` and `fixtures/m2k-snapshot.json` are now captures
from a real Rev.D M2K over the network backend, taken at different moments —
comparing them shows which values are volatile. Take your own with:

```
./iio_discover.py --uri ip:192.168.2.1 --json > fixtures/m2k-real.json
```

## Connecting to an M2K

An M2K normally appears as a USB ethernet gadget at a fixed address, so it is
**not discoverable** — `--scan` finds local and USB backends, plus mDNS if
libiio was built with it, and a board at a static address advertises nothing.
Name it directly:

```
./iio_discover.py --uri ip:192.168.2.1 --json > fixtures/m2k-snapshot.json
```

`--scan` prints this hint itself when it comes up short. If the address times
out, check the host end of the link exists before blaming libiio:

```
ip addr | grep -B2 192.168.2
ping -c1 192.168.2.1
```

The synthetic fixture stays: it keeps the golden output stable and needs no
regeneration. The real one is what participants should be reading.

## Browsing it, and getting block parameters out

```
./iio_browse.py fixtures/m2k-real.json      # then open http://127.0.0.1:8737
```

The same capture, in a browser, with the meaning next to each attribute and
its provenance tag intact. Tick the channels you want, pick values from the
dropdowns the hardware itself published, and the right-hand panel gives you
the fields for GNU Radio's **IIO Device Source** block.

It serves on `127.0.0.1` by default; `--host 0.0.0.0` serves a room from one
laptop. No dependencies beyond the standard library and no build step, which
is what makes it usable in a session that installs nothing.

The mapping it does for you is the one that is easy to get wrong by hand:
gr-iio resolves each `params` key with `iio_device_identify_filename()`, so
the key has to be the full sysfs filename. libiio reports a channel
attribute as `scale`; the block needs `in_voltage0_scale`. It also warns when
a channel has no scan index and therefore cannot stream at all — which is why
you take logic-analyzer samples from `m2k-logic-analyzer-rx` and not from
`m2k-logic-analyzer`.

`iio_grc.py` holds that translation and is tested on its own; the browser
only renders what it returns.

## Blocks with the hardware's own dropdowns

GRC cannot populate a dropdown from live hardware. It does not have to — a
block definition is a YAML file, and the legal values are already in the
capture. So generate the block instead of patching GRC:

```
./iio_grc.py fixtures/m2k-real.json --out grc_blocks
GRC_BLOCKS_PATH=$PWD/grc_blocks gnuradio-companion
```

One block per streaming device, source or sink according to the hardware's
own channel directions. Every attribute that published an `*_available`
list becomes a real dropdown holding real values — `trigger_mux_out` offers
exactly the six the M2K reports, and nothing else.

Two details that make the generated blocks usable rather than merely
correct:

- **Repeats collapse.** `m2k-logic-analyzer-rx` publishes three attributes
  across eighteen channels. Eighteen identical dropdowns is not a usable
  block, so they become one parameter applied to all of them, and the
  per-channel keys go in the block's documentation for anyone who needs to
  set one pin differently. Fifty-six dropdowns become five.
- **Every dropdown starts at "leave alone."** A shown value must never mean
  a value written to the hardware. Open a generated block, close it again,
  and it writes nothing.

The block's Documentation tab carries the meaning across too: the kernel's
own words, the board note, and the provenance tag for each, so a
participant reading a flowgraph never has to leave GRC to find out what
`rate_mux` does or who said so.

The browser has a **generate .block.yml** button that does the same thing
for whichever device you are looking at.

## The deck

```
xdg-open slides/index.html
```

One HTML file. **Read** mode is continuous notes; **present** mode is one frame
a screen with the detail collapsed behind *More detail +* — the same document,
and the detail is always in the page, so presenting cannot lose it. Printing
gives the notes back, one frame per sheet.

It is [ECE 444's frame view](https://github.com/livethisdream/ece444) ported to
a standalone page: no book, no generator, nothing to install.
`slides/README.md` has the authoring rules and `slides/check_deck.py` enforces
the ones that are invisible until they are wrong in front of people.

## Where meaning comes from

Every line of output is tagged with its source, so fact, convention and
guesswork stay distinguishable.

| Tag | Source | Trust |
| --- | --- | --- |
| `[abi]` | the Linux IIO ABI, quoted verbatim from the kernel docs | definitive, and true of every IIO device |
| `[parsed]` | the attribute name itself | certain |
| `[driver]` | the driver named the channel | rare, and trustworthy when present |
| `[libm2k]` | the vendor's library drives this attribute | says which instrument it belongs to |
| `[overlay: sourced]` | traced to vendor source, e.g. libm2k | good, not bench-checked |
| `[overlay: UNVERIFIED]` | written from documentation | **do not teach as fact yet** |

`./iio_explain.py FILE --unknown` reports how much is explained and by what.
On the synthetic fixture that is 95% from the ABI alone. On the real capture
it is 57%, because real hardware exposes a great deal the synthetic fixture
never did — mostly logic-analyzer trigger attributes, which the board pack
does not cover yet.

## The kernel is the source of truth

`iio_abi_fetch.py` downloads `Documentation/ABI/testing/sysfs-bus-iio` from
the Linux tree and parses it into `iio_abi_data.json` (826 documented
attribute names). `iio_explain.py` quotes it rather than paraphrasing:

```
uv run ./iio_abi_fetch.py                        # refresh the cache
uv run ./iio_abi_fetch.py --show in_voltage0_raw # what the kernel says
```

The cache is checked in, so the tools work offline. Re-run the fetch to track
newer kernels.

## Which attributes actually matter

The kernel says what an attribute *means*. It cannot say whether you will
ever need it. For this board libm2k can — it is the library Scopy is built
on, so anything it reads or writes is something operating the M2K as an
instrument requires, and the method that touches it says which instrument:

```
gain                -> M2kAnalogIn::setRange                 -> Oscilloscope
trigger_level       -> M2kHardwareTrigger::setAnalogLevelRaw -> Trigger
oversampling_ratio  -> M2kAnalogIn::setOversamplingRatio     -> Oscilloscope
```

That is a translation table from the knobs people already know in Scopy to
the sysfs names a flowgraph needs — which is the gap the workshop exists to
close. `iio_libm2k_fetch.py` extracts it from vendor source into
`iio_libm2k_data.json`; the explainer and the browser both show it.

```
uv run ./iio_libm2k_fetch.py              # refresh the cache
uv run ./iio_libm2k_fetch.py --show gain  # what drives one attribute
```

**Absence is not a verdict.** `scale` and `offset` are not in that table
because libm2k computes the scope's conversion itself instead of reading it
back — they remain central to every other IIO device. It means "not part of
this board's instrument abstraction", not "unimportant". It is also a text
scan of vendor source, not an API contract: a strong hint about relevance,
which is what it is.

## What `voltage0` actually is

Nothing in libiio says which pin a channel is wired to. `iio_explain.py` asks
four sources in order and reports which one answered:

1. **The channel name** — `iio_channel_get_name()`, i.e. the driver's own
   `extend_name`/`datasheet_name`. Usually empty; believe it when it is not.
2. **The `label` attribute** — same idea, settable from the device tree.
3. **The board pack** (`iio_overlays.py`) — hand-written, carries a confidence.
   For the M2K this is traced to libm2k, which is what Scopy itself uses.
4. **The ABI convention** — the kernel says an indexed channel corresponds to
   an externally available input, and that drivers should use a *named*
   channel when it does not. A strong hint, not a promise.

## Files

```
pyproject.toml        uv project; dependencies are empty on purpose
iio_discover.py       enumeration (the original tool, plus sample-layout capture)
iio_explain.py        the explainer CLI
iio_semantics.py      ABI knowledge: name grammar, units, conversion
iio_abi_fetch.py      pulls the kernel's own descriptions
iio_abi_data.json     generated cache of those descriptions
iio_libm2k_fetch.py   which attributes libm2k drives, and from which call
iio_libm2k_data.json  generated cache of that
iio_overlays.py       board-specific knowledge, confidence-tagged
fixtures/             synthetic M2K snapshot
docs/                 generated participant handout
gr-m2k/               the ADALM2000 blocks and their GRC definitions
flowgraphs/           the flowgraphs those blocks are used in
slides/               the workshop deck -- one HTML file, read or present
tests/                pytest, no hardware required
```

## Tests

```
uv run pytest
```

Everything runs without libiio and without an M2K. `REGEN_GOLDEN=1` accepts
intentional changes to the golden output.

## Still to verify on the bench

- Every `[overlay: UNVERIFIED]` entry in `iio_overlays.py`. Each carries a
  `check` field saying how to confirm it; promote it to `MEASURED` once done.
- Whether `ctx.attrs` hands back strings or attribute objects on the installed
  libiio version — `iio_discover._read()` handles both, but which one is real
  has not been observed.
- The real attribute counts, which is what sizes the GUI work.
