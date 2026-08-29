"""M2K Scope Source -- the oscilloscope input, as one block.

Everything this block hides, and where it goes:

    Sample rate       oversampling_ratio on m2k-adc (100 MS/s divided down)
    Input range       gain on m2k-fabric, a DIFFERENT device from the ADC
    Trigger level     trigger_level on m2k-adc-trigger, in RAW COUNTS
    Trigger edge      trigger on m2k-adc-trigger voltage0/voltage1
    Trigger source    logic_mode on m2k-adc-trigger voltage6, plus
                      mode on voltage4/voltage5

That spread across three devices is the reason a stock Device Source
cannot do this on its own: its params go to exactly one of them.

Channel-to-attribute mapping is read out of libm2k, the library Scopy is
built on -- see iio_libm2k_fetch.py in the repository root. Values that
are not attributes at all (the volts-per-count numbers) come from
libm2k's getScalingFactor() and are marked below.
"""

from gnuradio import blocks
from gnuradio import gr
from gnuradio import iio

from .m2k_scale import (RANGE_VOLTS, SAMPLE_RATES, check_sample_rate,
                        volts_per_count, volts_to_raw)

# gr-iio's attr_sink takes the attribute category as a number.
ATTR_CHANNEL = 0

# How often the configuration attributes are re-asserted. gr-iio has no
# one-shot attribute write, so a slow updater stands in for one. The side
# effect is benign and mildly useful: a setting changed underneath us (by
# Scopy, say) gets put back.
CONFIG_INTERVAL_MS = 1000

# The devices this block reaches into.
DEV_ADC = "m2k-adc"
DEV_FABRIC = "m2k-fabric"
DEV_TRIGGER = "m2k-adc-trigger"

# m2k-adc-trigger's channels, by id. Two of them share the NAME
# "trigger_logic", so ids are the only safe way to address them.
TRIG_ANALOG = ["voltage0", "voltage1"]     # condition, level, hysteresis
TRIG_LOGIC = ["voltage4", "voltage5"]      # mode
TRIG_DELAY = "voltage6"                    # logic_mode, i.e. the source


class scope_source(gr.hier_block2):
    """Scope channels 1 and 2, in volts or in raw counts."""

    def __init__(self, uri="ip:192.168.2.1",
                 ch1_enabled=True, ch2_enabled=False,
                 sample_rate=1000000,
                 ch1_range="low", ch2_range="low",
                 buffer_size=16384,
                 units="volts",
                 trigger_source="off",
                 trigger_edge="edge-rising",
                 trigger_level=0.5):

        channels = []
        ranges = []
        if ch1_enabled:
            channels.append("voltage0")
            ranges.append(ch1_range)
        if ch2_enabled:
            channels.append("voltage1")
            ranges.append(ch2_range)
        if not channels:
            raise ValueError(
                "M2K Scope Source: enable at least one channel, or the "
                "block has no outputs.")

        as_volts = (units == "volts")
        item_size = gr.sizeof_float if as_volts else gr.sizeof_short
        gr.hier_block2.__init__(
            self, "m2k_scope_source",
            gr.io_signature(0, 0, 0),
            gr.io_signature(len(channels), len(channels), item_size))

        # Sample rate is the one setting that lives on the streaming
        # device itself, so it can ride along in params. Written as
        # sampling_frequency, which is what the ADC publishes a list of
        # legal values for.
        self.source = iio.device_source(
            uri, DEV_ADC, channels, "",
            ["sampling_frequency=%d" % check_sample_rate(sample_rate)],
            buffer_size, 0)
        self.source.set_len_tag_key("packet_len")

        self._config = []
        self._apply_ranges(uri, ch1_enabled, ch2_enabled, ch1_range, ch2_range)
        self._apply_trigger(uri, trigger_source, trigger_edge, trigger_level,
                            ch1_range, ch2_range)

        for index, range_name in enumerate(ranges):
            if as_volts:
                to_float = blocks.short_to_float(1, 1)
                to_volts = blocks.multiply_const_ff(volts_per_count(range_name))
                self.connect((self.source, index), to_float, to_volts,
                             (self, index))
                # Keep references; a hier block that drops them loses the
                # blocks to garbage collection.
                self._config.extend([to_float, to_volts])
            else:
                self.connect((self.source, index), (self, index))

    # -------------------------------------------------- configuration

    def _write(self, uri, device, channel, attr, value):
        """Set one attribute on any device, using gr-iio's own blocks.

        attr_updater emits {attr: value} on an interval; attr_sink writes
        whatever it receives. Two blocks to set one string, but it needs
        no libiio bindings and no libm2k, which is the whole point.
        """
        updater = iio.attr_updater(attr, str(value), CONFIG_INTERVAL_MS)
        sink = iio.attr_sink(uri, device, channel, ATTR_CHANNEL, False)
        self.msg_connect((updater, "out"), (sink, "attr"))
        self._config.extend([updater, sink])

    def _apply_ranges(self, uri, ch1_enabled, ch2_enabled, ch1_range, ch2_range):
        """Input range lives on m2k-fabric, not on the ADC."""
        if ch1_enabled:
            self._write(uri, DEV_FABRIC, "voltage0", "gain", ch1_range)
        if ch2_enabled:
            self._write(uri, DEV_FABRIC, "voltage1", "gain", ch2_range)

    def _apply_trigger(self, uri, source, edge, level, ch1_range, ch2_range):
        """Arm or disarm the analog trigger.

        'always' on the logic channels is what free-running means; there
        is no separate off switch.
        """
        if source == "off":
            for channel in TRIG_LOGIC:
                self._write(uri, DEV_TRIGGER, channel, "mode", "always")
            return

        index = 0 if source == "ch1" else 1
        range_name = ch1_range if index == 0 else ch2_range

        self._write(uri, DEV_TRIGGER, TRIG_ANALOG[index], "trigger", edge)
        self._write(uri, DEV_TRIGGER, TRIG_ANALOG[index], "trigger_level",
                    volts_to_raw(level, range_name))
        self._write(uri, DEV_TRIGGER, TRIG_LOGIC[index], "mode", "analog")
        # logic_mode on the delay channel is the trigger SOURCE, despite
        # the name: 'a' is channel 1, 'b' is channel 2.
        self._write(uri, DEV_TRIGGER, TRIG_DELAY, "logic_mode",
                    "a" if index == 0 else "b")
