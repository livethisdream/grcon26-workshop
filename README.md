# IIO discovery and semantics

Workshop tooling for GNU Radio + ADALM2000. Two tools, deliberately split.

| | needs libiio | needs hardware | what it answers |
| --- | --- | --- | --- |
| `iio_discover.py` | yes | yes | what is here, what is it set to, what values are legal |
| `iio_explain.py` | no | no | what does it *mean* |

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

`fixtures/m2k-snapshot.json` is hand-authored and says so in the file. Replace
it with a real capture as soon as there is hardware:

```
./iio_discover.py --json > fixtures/m2k-snapshot.json
```

## Where meaning comes from

Every line of output is tagged with its source, so fact, convention and
guesswork stay distinguishable.

| Tag | Source | Trust |
| --- | --- | --- |
| `[abi]` | the Linux IIO ABI, quoted verbatim from the kernel docs | definitive, and true of every IIO device |
| `[parsed]` | the attribute name itself | certain |
| `[driver]` | the driver named the channel | rare, and trustworthy when present |
| `[overlay: sourced]` | traced to vendor source, e.g. libm2k | good, not bench-checked |
| `[overlay: UNVERIFIED]` | written from documentation | **do not teach as fact yet** |

`./iio_explain.py FILE --unknown` reports how much is explained and by what.
On the current fixture that is 95% from the ABI alone, with the remainder
covered by the board pack.

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
iio_overlays.py       board-specific knowledge, confidence-tagged
fixtures/             synthetic M2K snapshot
docs/                 generated participant handout
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
