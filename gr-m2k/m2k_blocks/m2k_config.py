"""Setting attributes on devices other than the one you are streaming.

Every M2K instrument needs this. The scope's input range lives on
m2k-fabric; the DIO direction lives on m2k-logic-analyzer; neither is the
device carrying the samples. gr-iio's device_source and device_sink apply
their `params` to exactly one device, so anything else needs another way
in.

gr-iio's own way in is a pair of blocks: attr_updater emits {attr: value}
on an interval, attr_sink writes whatever arrives. Two blocks to set one
string, and no one-shot write anywhere in the API -- a slow updater is
the only thing on offer.

Which is a problem, and it cost us a bench session. An updater on a
1000 ms interval writes nothing at t=0. For the first second of every
flowgraph the hardware is in whatever state the last program left it,
and a short capture can finish before its own configuration arrives. It
does not fail; it returns confident numbers for settings that were never
applied. Comparing two input ranges this way gave 0.3 counts against
72.3, which looks like a broken range and is actually a race.

So each attribute is written twice, deliberately:

    once, immediately, with libiio directly -- before the flowgraph is
    even started, so the setting is in force before the first sample

    then repeatedly, by the updater/sink pair, which keeps it in force if
    something else changes it underneath us

The direct write is what makes the configuration true. The updater is a
keep-alive, which is what it was always good at.

One consequence, and it looks exactly like a hung board: the updater
never finishes, so a flowgraph holding one of these never finishes
either. `tb.run()` on a graph terminated by a `head` block will sit
there forever after the head has all its samples, because run() waits
for every block. Use `tb.start()`, wait, `tb.stop()`, `tb.wait()`
instead. The board is fine; the graph is just never done.
"""

import sys

from gnuradio import iio

# gr-iio takes the attribute category as a number, matching its own
# Attribute Sink block: 0 Channel, 1 Device, 2 Buffer, 3 Debug.
ATTR_CHANNEL = 0
ATTR_DEVICE = 1

# How often the keep-alive rewrites. No longer the thing that decides
# whether a setting is applied at all -- see the direct write below.
CONFIG_INTERVAL_MS = 1000

# libiio contexts are expensive to open and there is no reason to hold
# more than one per board. Keyed by URI.
_CONTEXTS = {}


def context(uri):
    """A libiio context for this URI, opened once and reused.

    This is pylibiio (`import iio`), not gr-iio (`from gnuradio import
    iio`). Different modules with the same name; gr-iio is built on the
    same C library, so having one implies having the other, but the
    Python bindings are a separate package and can be missing.
    """
    if uri not in _CONTEXTS:
        import iio as pyiio
        _CONTEXTS[uri] = pyiio.Context(uri)
    return _CONTEXTS[uri]


def write_now(uri, device, channel, attr, value, output=False,
              kind=ATTR_CHANNEL, keepalive=True):
    """Write one attribute straight away, returning whether it landed.

    Never raises. A board that is unreachable, or bindings that are not
    installed, leave the updater/sink pair to do the job a second later
    -- worse, but not broken. The warning says which happened, because a
    silent fallback here is exactly the failure this module exists to
    stop.

    `keepalive` only changes that warning. It says whether the caller is
    going to follow this up with an updater/sink pair, so the message can
    say "a second late" or "not at all" and be telling the truth. Some
    attributes must NOT be kept alive -- see the digital sink's idle
    level, where a keep-alive would spend the whole run rewriting a
    register the stream is deliberately overriding.
    """
    try:
        dev = context(uri).find_device(device)
        if dev is None:
            raise LookupError("no device %r in the context at %s"
                              % (device, uri))
        if kind == ATTR_DEVICE:
            dev.attrs[attr].value = str(value)
        else:
            chan = dev.find_channel(channel, output)
            if chan is None:
                raise LookupError(
                    "no %s channel %r on %s"
                    % ("output" if output else "input", channel, device))
            chan.attrs[attr].value = str(value)
        return True
    except Exception as exc:                      # noqa: BLE001
        # Drop the cached context; if it went stale, the next call rebuilds.
        _CONTEXTS.pop(uri, None)
        where = device if kind == ATTR_DEVICE else "%s/%s" % (device, channel)
        if keepalive:
            after = ("falling back to the %d ms updater, so it will not be "
                     "in force for the first %.1f s"
                     % (CONFIG_INTERVAL_MS, CONFIG_INTERVAL_MS / 1000.0))
        else:
            after = "and nothing else will set it, so it is not in force"
        print("m2k_config: could not set %s %s=%s immediately (%s); %s"
              % (where, attr, value, exc, after), file=sys.stderr)
        return False


def write_channel_attr(block, keep, uri, device, channel, attr, value,
                       output=False):
    """Set one channel attribute on any device the context can reach.

    `keep` is a list the caller holds on to. A hier block that lets these
    go loses them to garbage collection and the write silently stops
    happening.
    """
    write_now(uri, device, channel, attr, value, output, ATTR_CHANNEL)
    updater = iio.attr_updater(attr, str(value), CONFIG_INTERVAL_MS)
    sink = iio.attr_sink(uri, device, channel, ATTR_CHANNEL, output)
    block.msg_connect((updater, "out"), (sink, "attr"))
    keep.extend([updater, sink])
    return sink


def write_device_attr(block, keep, uri, device, attr, value):
    """Set one device-level attribute on any device."""
    write_now(uri, device, "", attr, value, False, ATTR_DEVICE)
    updater = iio.attr_updater(attr, str(value), CONFIG_INTERVAL_MS)
    sink = iio.attr_sink(uri, device, "", ATTR_DEVICE, False)
    block.msg_connect((updater, "out"), (sink, "attr"))
    keep.extend([updater, sink])
    return sink
