"""M2K Digital Source and Sink -- the 16 DIO pins.

Three IIO devices are involved and none of them is optional:

    m2k-logic-analyzer      per-pin configuration. `direction` decides
                            whether a pin is an input or an output, and
                            it lives HERE, not on either data device.
                            So does `raw`, the idle level.
    m2k-logic-analyzer-rx   the samples coming in, and the trigger.
    m2k-logic-analyzer-tx   the samples going out.

A pin is an input or an output, never both, so a source and a sink in
the same flowgraph need ranges that do not overlap. `first_pin` is what
keeps them apart: a sink at DIO0 and a source at DIO1 share no pin and
do not interfere. Each block writes `direction` for its own pins at
construction, so where the ranges DO overlap, whichever is built last
wins and the other block silently reads or drives nothing.

An output pin has two sources of truth. The stream drives it while the
flowgraph runs; `raw` drives it the rest of the time, and the pin snaps
back to `raw` the moment the flowgraph stops. The sink's idle level sets
`raw`, which is both Scopy's Digital IO and the only way to say what the
pins should do when nothing is playing.

One port per pin, carrying one bit per sample in a short. That is
gr-iio's model, not a choice made here: each DIO pin is its own IIO
channel with a 1-bit scan element.
"""

from gnuradio import gr
from gnuradio import iio

from .m2k_config import write_channel_attr, write_now

DEV_CONFIG = "m2k-logic-analyzer"
DEV_RX = "m2k-logic-analyzer-rx"
DEV_TX = "m2k-logic-analyzer-tx"

PIN_COUNT = 16

# The digital side publishes no sampling_frequency_available, unlike the
# scope and the generator. These are the decade divisions of the same
# 100 MS/s clock. All six are confirmed on the bench, timed against the
# scope rather than read back -- see docs/bench-checklist.md section 7.
DIGITAL_SAMPLE_RATES = [100000000, 10000000, 1000000, 100000, 10000, 1000]

# What an output pin does when the flowgraph is not running, and the
# value that goes into `raw` to mean it. 'leave' is the third choice and
# writes nothing at all.
IDLE_LEVELS = {"low": 0, "high": 1}

# m2k-logic-analyzer-rx voltageN trigger_available, minus 'none'. 'none'
# is not offered as a condition because "off" is the pin selector's job.
DIGITAL_TRIGGER_CONDITIONS = ["edge-rising", "edge-falling", "edge-any",
                              "level-high", "level-low"]


def pins_for(count, first=0):
    """Pin ids for `count` DIO pins, counting up from DIO`first`."""
    count = int(count)
    first = int(first)
    if count < 1 or count > PIN_COUNT:
        raise ValueError("pin count must be between 1 and %d, got %r"
                         % (PIN_COUNT, count))
    if first < 0 or first >= PIN_COUNT:
        raise ValueError("first pin must be between 0 and %d, got %r"
                         % (PIN_COUNT - 1, first))
    if first + count > PIN_COUNT:
        raise ValueError("DIO%d upward is only %d pins, so %d will not fit"
                         % (first, PIN_COUNT - first, count))
    return ["voltage%d" % index for index in range(first, first + count)]


def pin_label(channel):
    """'voltage3' -> 'DIO3', for error messages people have to read."""
    return "DIO" + channel[len("voltage"):]


class _digital(gr.hier_block2):
    """Shared plumbing: pick the pins, set their direction, stream."""

    def __init__(self, name, uri, pin_count, sample_rate, buffer_size,
                 direction, first_pin=0):
        self.pins = pins_for(pin_count, first_pin)
        self._config = []
        self._make_signature(name, len(self.pins))

        # Direction first: a pin driven as an output while still
        # configured as an input does nothing at all.
        for pin in self.pins:
            self._write(uri, DEV_CONFIG, pin, "direction", direction)

        self.params = ["sampling_frequency=%d" % int(sample_rate)]
        self.buffer_size = int(buffer_size)
        self.uri = uri

    def _write(self, uri, device, channel, attr, value):
        """Set an attribute, and keep it set for as long as we run."""
        write_channel_attr(self, self._config, uri, device, channel,
                           attr, value)

    def _write_once(self, uri, device, channel, attr, value):
        """Set an attribute now and then leave it alone."""
        write_now(uri, device, channel, attr, value, keepalive=False)


class digital_source(_digital):
    """Read the DIO pins. One output port per pin, lowest pin first."""

    def __init__(self, uri="ip:192.168.2.1", pin_count=1,
                 sample_rate=1000000, buffer_size=16384, first_pin=0,
                 trigger_pin="off", trigger_condition="edge-rising",
                 trigger_delay=0):
        _digital.__init__(self, "m2k_digital_source", uri, pin_count,
                          sample_rate, buffer_size, "in", first_pin)
        self._apply_trigger(uri, trigger_pin, trigger_condition, trigger_delay)
        self.source = iio.device_source(
            uri, DEV_RX, self.pins, DEV_RX, self.params, self.buffer_size, 0)
        self.source.set_len_tag_key("packet_len")
        for index in range(len(self.pins)):
            self.connect((self.source, index), (self, index))

    def _make_signature(self, name, nports):
        gr.hier_block2.__init__(
            self, name, gr.io_signature(0, 0, 0),
            gr.io_signature(nports, nports, gr.sizeof_short))

    def _apply_trigger(self, uri, trigger_pin, condition, delay):
        """Arm the trigger on one pin, or free-run.

        Every pin carries its own `trigger`, and 'none' on all of them is
        what free-running means -- there is no separate off switch, the
        same shape as the scope's 'always'.

        `trigger_logic_mode` and `trigger_mux_out` are written every time
        rather than only when arming. Both are board state that outlives
        the program that set them, and either one left over from
        something else -- 'and' across pins that are not triggering, or a
        mux pointing at the external trigger input -- stops a perfectly
        correct single-pin trigger from ever firing. A trigger that never
        fires looks like a hung flowgraph, not like a wrong setting.
        """
        armed = None
        if trigger_pin != "off":
            armed = "voltage%d" % int(trigger_pin)
            if armed not in self.pins:
                raise ValueError(
                    "the trigger pin %s is not one of the pins this block "
                    "reads (%s)"
                    % (pin_label(armed),
                       ", ".join(pin_label(pin) for pin in self.pins)))
            if condition not in DIGITAL_TRIGGER_CONDITIONS:
                raise ValueError(
                    "trigger condition must be one of %s, got %r"
                    % (", ".join(DIGITAL_TRIGGER_CONDITIONS), condition))

        first = self.pins[0]
        self._write(uri, DEV_RX, first, "trigger_logic_mode", "or")
        self._write(uri, DEV_RX, first, "trigger_mux_out", "trigger-logic")
        self._write(uri, DEV_RX, first, "trigger_delay", int(delay))

        for pin in self.pins:
            self._write(uri, DEV_RX, pin, "trigger",
                        condition if pin == armed else "none")


class digital_sink(_digital):
    """Drive the DIO pins. One input port per pin, lowest pin first."""

    def __init__(self, uri="ip:192.168.2.1", pin_count=1,
                 sample_rate=1000000, buffer_size=16384,
                 drive="push-pull", cyclic=False, first_pin=0,
                 idle_level="low"):
        _digital.__init__(self, "m2k_digital_sink", uri, pin_count,
                          sample_rate, buffer_size, "out", first_pin)
        for pin in self.pins:
            self._write(uri, DEV_CONFIG, pin, "outputmode", drive)
        self._apply_idle(uri, idle_level)
        self.sink = iio.device_sink(
            uri, DEV_TX, self.pins, DEV_TX, self.params, self.buffer_size, 0,
            bool(cyclic))
        for index in range(len(self.pins)):
            self.connect((self, index), (self.sink, index))

    def _make_signature(self, name, nports):
        gr.hier_block2.__init__(
            self, name, gr.io_signature(nports, nports, gr.sizeof_short),
            gr.io_signature(0, 0, 0))

    def _apply_idle(self, uri, idle_level):
        """Set what the pins do when the flowgraph is not running.

        `raw` is a second output register, entirely separate from the
        stream. The stream wins while the flowgraph runs; the moment it
        stops, the pins snap back to whatever `raw` holds. Note that this
        is the opposite of the analog generator, which keeps playing its
        last cyclic buffer with the flowgraph stopped.

        'leave' is offered but is not the default, because leaving it
        alone means the resting level is whatever the last program to
        touch this board happened to set -- invisible from the flowgraph
        and different every session.

        Written once, with no keep-alive. A keep-alive here would spend
        the whole run rewriting a register the stream is deliberately
        overriding, once a second, for no reason.
        """
        if idle_level not in IDLE_LEVELS and idle_level != "leave":
            raise ValueError(
                "idle level must be one of %s, got %r"
                % (", ".join(sorted(IDLE_LEVELS) + ["leave"]), idle_level))
        if idle_level == "leave":
            return
        for pin in self.pins:
            self._write_once(uri, DEV_CONFIG, pin, "raw",
                             IDLE_LEVELS[idle_level])
