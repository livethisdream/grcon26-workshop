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

## Try it now

There is a synthetic M2K snapshot checked in, so everything runs with no
hardware:

```
./iio_explain.py fixtures/m2k-snapshot.json                       # what it measures
./iio_explain.py fixtures/m2k-snapshot.json --attr raw --limit 1  # one attribute, in depth
./iio_explain.py fixtures/m2k-snapshot.json --unknown             # what we still cannot explain
./iio_explain.py fixtures/m2k-snapshot.json --glossary            # participant handout
```

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
