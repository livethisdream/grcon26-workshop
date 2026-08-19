# IIO discovery and semantics

Workshop tooling for GNU Radio + ADALM2000. Three tools, deliberately split.

| | needs libiio | needs hardware | what it answers |
| --- | --- | --- | --- |
| `iio_discover.py` | yes | yes | what is here, what is it set to, what values are legal |
| `iio_explain.py` | no | no | what does it *mean* |
| `iio_browse.py` | no | no | what do I type into the GNU Radio block |

The split matters: capture once on the bench, explain anywhere.

```
on the bench:   ./iio_discover.py --json > m2k.json
anywhere else:  ./iio_explain.py m2k.json --channels
```

That is also how this works in a room of twenty people with one M2K between
them, and why nobody needs to install libiio during the session.

## Try it now

There is a synthetic M2K snapshot checked in, so everything runs with no
hardware:

```
./iio_explain.py fixtures/m2k-snapshot.json                       # what it measures
./iio_explain.py fixtures/m2k-snapshot.json --attr raw --limit 1  # one attribute, in depth
./iio_explain.py fixtures/m2k-snapshot.json --unknown             # what we still cannot explain
./iio_explain.py fixtures/m2k-snapshot.json --glossary            # participant handout
```

`fixtures/m2k-snapshot.json` is hand-authored and says so in the file.
`fixtures/m2k-real.json` is a capture from an actual Rev.D M2K over the
network backend, and is what the examples below use. Take your own with:

```
./iio_discover.py --uri ip:192.168.2.1 --json > fixtures/m2k-real.json
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
On the synthetic fixture that is 95% from the ABI alone. On the real capture
it is 57%, because real hardware exposes a great deal the synthetic fixture
never did — mostly logic-analyzer trigger attributes, which the board pack
does not cover yet.

## The kernel is the source of truth

`iio_abi_fetch.py` downloads `Documentation/ABI/testing/sysfs-bus-iio` from
the Linux tree and parses it into `iio_abi_data.json` (826 documented
attribute names). `iio_explain.py` quotes it rather than paraphrasing:

```
./iio_abi_fetch.py                        # refresh the cache
./iio_abi_fetch.py --show in_voltage0_raw # what the kernel says
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
python3 -m pytest tests -q
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
