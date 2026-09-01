"""M2K Digital Source and Sink -- the 16 DIO pins.

Three IIO devices are involved and none of them is optional:

    m2k-logic-analyzer      per-pin configuration. `direction` decides
                            whether a pin is an input or an output, and
                            it lives HERE, not on either data device.
    m2k-logic-analyzer-rx   the samples coming in.
    m2k-logic-analyzer-tx   the samples going out.

A pin is an input or an output, never both, so these two blocks must not
be pointed at the same pins in one flowgraph. Each block sets `direction`
for the pins it uses, so whichever starts last wins -- which is worth
knowing before it happens to you.

One output port per pin, carrying one bit per sample in a short. That is
gr-iio's model, not a choice made here: each DIO pin is its own IIO
channel with a 1-bit scan element.
"""

from gnuradio import gr
from gnuradio import iio

from .m2k_config import write_channel_attr

DEV_CONFIG = "m2k-logic-analyzer"
DEV_RX = "m2k-logic-analyzer-rx"
DEV_TX = "m2k-logic-analyzer-tx"

PIN_COUNT = 16

# The digital side publishes no sampling_frequency_available, unlike the
# scope and the generator. These are the decade divisions of the same
# 100 MS/s clock and are the obvious candidates, but the hardware has not
# confirmed them -- if one is refused, gr-iio logs it and carries on at
# whatever rate was already set.
DIGITAL_SAMPLE_RATES = [100000000, 10000000, 1000000, 100000, 10000, 1000]


def pins_for(count):
    """Pin ids for the first `count` DIO pins, DIO0 upward."""
    count = int(count)
    if count < 1 or count > PIN_COUNT:
        raise ValueError("pin count must be between 1 and %d, got %r"
                         % (PIN_COUNT, count))
    return ["voltage%d" % index for index in range(count)]


class _digital(gr.hier_block2):
    """Shared plumbing: pick the pins, set their direction, stream."""

    def __init__(self, name, uri, pin_count, sample_rate, buffer_size,
                 direction):
        self.pins = pins_for(pin_count)
        self._config = []
        self._make_signature(name, len(self.pins))

        # Direction first: a pin driven as an output while still
        # configured as an input does nothing at all.
        for pin in self.pins:
            write_channel_attr(self, self._config, uri, DEV_CONFIG, pin,
                               "direction", direction)

        self.params = ["sampling_frequency=%d" % int(sample_rate)]
        self.buffer_size = int(buffer_size)
        self.uri = uri


class digital_source(_digital):
    """Read the DIO pins. One output port per pin, DIO0 first."""

    def __init__(self, uri="ip:192.168.2.1", pin_count=1,
                 sample_rate=1000000, buffer_size=16384):
        _digital.__init__(self, "m2k_digital_source", uri, pin_count,
                          sample_rate, buffer_size, "in")
        self.source = iio.device_source(
            uri, DEV_RX, self.pins, DEV_RX, self.params, self.buffer_size, 0)
        self.source.set_len_tag_key("packet_len")
        for index in range(len(self.pins)):
            self.connect((self.source, index), (self, index))

    def _make_signature(self, name, nports):
        gr.hier_block2.__init__(
            self, name, gr.io_signature(0, 0, 0),
            gr.io_signature(nports, nports, gr.sizeof_short))


class digital_sink(_digital):
    """Drive the DIO pins. One input port per pin, DIO0 first."""

    def __init__(self, uri="ip:192.168.2.1", pin_count=1,
                 sample_rate=1000000, buffer_size=16384,
                 drive="push-pull", cyclic=False):
        _digital.__init__(self, "m2k_digital_sink", uri, pin_count,
                          sample_rate, buffer_size, "out")
        for pin in self.pins:
            write_channel_attr(self, self._config, uri, DEV_CONFIG, pin,
                               "outputmode", drive)
        self.sink = iio.device_sink(
            uri, DEV_TX, self.pins, DEV_TX, self.params, self.buffer_size, 0,
            bool(cyclic))
        for index in range(len(self.pins)):
            self.connect((self, index), (self.sink, index))

    def _make_signature(self, name, nports):
        gr.hier_block2.__init__(
            self, name, gr.io_signature(nports, nports, gr.sizeof_short),
            gr.io_signature(0, 0, 0))
