"""Setting attributes on devices other than the one you are streaming.

Every M2K instrument needs this. The scope's input range lives on
m2k-fabric; the DIO direction lives on m2k-logic-analyzer; neither is the
device carrying the samples. gr-iio's device_source and device_sink apply
their `params` to exactly one device, so anything else needs another way
in.

The way in is gr-iio's own attribute blocks: attr_updater emits
{attr: value} on an interval, attr_sink writes whatever arrives. Two
blocks to set one string, and no libiio Python bindings or libm2k
required -- which is the trade being made.

Note gr-iio has no one-shot attribute write, so a slow updater stands in
for one. The side effect is mild and occasionally useful: a setting
changed underneath the flowgraph gets put back.
"""

from gnuradio import iio

# gr-iio takes the attribute category as a number, matching its own
# Attribute Sink block: 0 Channel, 1 Device, 2 Buffer, 3 Debug.
ATTR_CHANNEL = 0
ATTR_DEVICE = 1

CONFIG_INTERVAL_MS = 1000


def write_channel_attr(block, keep, uri, device, channel, attr, value,
                       output=False):
    """Set one channel attribute on any device the context can reach.

    `keep` is a list the caller holds on to. A hier block that lets these
    go loses them to garbage collection and the write silently stops
    happening.
    """
    updater = iio.attr_updater(attr, str(value), CONFIG_INTERVAL_MS)
    sink = iio.attr_sink(uri, device, channel, ATTR_CHANNEL, output)
    block.msg_connect((updater, "out"), (sink, "attr"))
    keep.extend([updater, sink])
    return sink


def write_device_attr(block, keep, uri, device, attr, value):
    """Set one device-level attribute on any device."""
    updater = iio.attr_updater(attr, str(value), CONFIG_INTERVAL_MS)
    sink = iio.attr_sink(uri, device, "", ATTR_DEVICE, False)
    block.msg_connect((updater, "out"), (sink, "attr"))
    keep.extend([updater, sink])
    return sink
