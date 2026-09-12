"""M2K Power Supply -- the V+ and V- rails.

This is the one instrument on the board that GNU Radio has no concept
of. A rail is not a stream: nothing flows to it, nothing comes back,
and the whole state of it is one number that has to be true before the
first sample of anything else. So the block has no ports at all. It
sits on the canvas, it writes what it is told when it is built, and it
takes a new setpoint from a slider while the flowgraph runs.

Setting one rail touches four places, which is why this exists:

    ad5627        voltage0 (V+) or voltage1 (V-), `raw` -- the setpoint
                  itself, as a count for a 12-bit DAC whose own output
                  only reaches 1.2 V.
    ad5627        the same channel's `powerdown` -- the DAC's output
                  stage.
    m2k-fabric    voltage2 for V+, voltage3 for V-, `powerdown` -- the
                  rail regulator, and a different device from the DAC.
    the context   cal,gain_pos_dac and cal,offset_pos_dac, the neg pair
                  for V-. Corrections that belong to the board, stored
                  on no device at all -- they are attributes of the IIO
                  context, which is a place most people never look.

Two of those are inverted (0 means on), two of them are a different
device from the one you would guess, and one of them is not on a device.

Order matters and the board will not say so. `raw` comes up from reset
at 2048 -- mid-scale, about +3 V at the rail -- so clearing the
powerdowns before writing the setpoint brings the rail up at 3 V for as
long as it takes the next write to land. The setpoint is written first,
always.

The rail stays up after the flowgraph stops. That is deliberate and it
matches the generator, which holds its last cyclic buffer: an amplifier
being fed by the M2K should not lose its supply because someone stopped
a capture to change a plot. Set Rail output to Down, or run
`bench/dc_rail.py --off`, to bring it down.
"""

import sys

from gnuradio import gr

from .m2k_config import context, write_now
from .m2k_scale import (SUPPLY_LIMIT_V, check_supply_volts,
                        volts_to_supply_raw)
from .rate_limit import rate_limiter

# The DAC behind both rails. Not m2k-dac-a or -b -- those are W1 and W2,
# a different converter entirely.
DEV_DAC = "ad5627"
DAC_CHANNEL = {"positive": "voltage0", "negative": "voltage1"}

# And the rail regulators, which live with every other power-up on the
# board: the scope's input range and the generator's output stage are on
# this same device.
DEV_FABRIC = "m2k-fabric"
FABRIC_CHANNEL = {"positive": "voltage2", "negative": "voltage3"}

# The board's own corrections, held as context attributes.
CAL_ATTRS = {"positive": ("cal,gain_pos_dac", "cal,offset_pos_dac"),
             "negative": ("cal,gain_neg_dac", "cal,offset_neg_dac")}


class power_supply(gr.hier_block2):
    """Hold one rail at a voltage. One instance per rail."""

    def __init__(self, uri="ip:192.168.2.1", rail="positive",
                 voltage=5.0, enabled=True, calibrated=True,
                 min_interval_ms=100):

        if rail not in DAC_CHANNEL:
            raise ValueError("rail must be 'positive' or 'negative', got %r"
                             % (rail,))
        # Raise here rather than at the first write: a setpoint the rail
        # cannot hold is a flowgraph that should not start.
        check_supply_volts(voltage, rail)

        gr.hier_block2.__init__(
            self, "m2k_power_supply",
            gr.io_signature(0, 0, 0), gr.io_signature(0, 0, 0))

        self.uri = uri
        self.rail = rail
        self._voltage = float(voltage)
        self._gain, self._offset = (
            self._calibration(uri, rail) if calibrated else (1.0, 0.0))
        self._fabric_channel, self._fabric_shared = self._fabric(uri, rail)
        self._limiter = rate_limiter(self._write_voltage,
                                     float(min_interval_ms) / 1000.0)

        # Setpoint before power, every time. See the module docstring.
        self._write_voltage(self._voltage)
        self.set_enabled(enabled)

    # ------------------------------------------------------------ controls

    def set_voltage(self, volts):
        """Change the setpoint while the flowgraph runs.

        Out of range is clamped and reported rather than raised. This is
        called from a GRC callback, where an exception takes the whole
        flowgraph down and a slider that has run off the end of its
        range is not worth that.
        """
        try:
            value = check_supply_volts(volts, self.rail)
        except ValueError as exc:
            value = _nearest_legal(volts, self.rail)
            print("m2k_power_supply: %s; holding %g V instead" % (exc, value),
                  file=sys.stderr)
        self._voltage = value
        self._limiter.submit(value)

    def voltage(self):
        """The setpoint as commanded. NOT what the rail is doing."""
        return self._voltage

    def correction(self):
        """This board's (gain, offset) for this rail, as they were read.

        (1.0, 0.0) means either that the block was asked for no
        correction or that the context could not be reached -- which is
        worth being able to tell apart on the bench.
        """
        return self._gain, self._offset

    def set_enabled(self, on):
        """Power the rail up or down.

        The DAC's output stage first, then the regulator, which is
        libm2k's order. Both senses are inverted: powerdown = 0 is on.
        """
        powerdown = 0 if on else 1
        write_now(self.uri, DEV_DAC, DAC_CHANNEL[self.rail], "powerdown",
                  powerdown, output=True, keepalive=False)
        if on or not self._fabric_shared:
            write_now(self.uri, DEV_FABRIC, self._fabric_channel, "powerdown",
                      powerdown, output=True, keepalive=False)
        else:
            # One regulator channel for both rails, on a board old enough
            # not to have voltage3. Powering it down here would take the
            # other rail with it, and this block cannot see the other
            # rail. The DAC's own stage is down, which is enough.
            print("m2k_power_supply: this board powers both rails from one "
                  "control, so V- was left up; stop V+ as well to bring it "
                  "down", file=sys.stderr)

    def close(self):
        """Drop a setpoint that has not been written yet."""
        self._limiter.cancel()

    # ------------------------------------------------------------ internals

    def _write_voltage(self, volts):
        raw = volts_to_supply_raw(volts, self.rail, self._gain, self._offset)
        write_now(self.uri, DEV_DAC, DAC_CHANNEL[self.rail], "raw", raw,
                  output=True, keepalive=False)

    def _calibration(self, uri, rail):
        """The board's own dac corrections, from the context attributes.

        A board that cannot be reached leaves them at the identity, so
        the rail is commanded by the bare arithmetic and is wrong by
        whatever the corrections were worth -- about 0.14% of gain and
        3 mV of offset on the board here. Reported, never raised: the
        same rule as every other write in these blocks.
        """
        gain_attr, offset_attr = CAL_ATTRS[rail]
        try:
            attrs = context(uri).attrs
            return float(attrs[gain_attr]), float(attrs[offset_attr])
        except Exception as exc:                        # noqa: BLE001
            print("m2k_power_supply: no %s/%s from %s (%s); commanding the "
                  "rail with uncorrected arithmetic"
                  % (gain_attr, offset_attr, uri, exc), file=sys.stderr)
            return 1.0, 0.0

    def _fabric(self, uri, rail):
        """Which regulator channel this rail uses, and whether it shares it.

        Boards with individual powerdown have voltage3 for V-; older ones
        control both rails from voltage2. libm2k decides the same way,
        by looking for the channel.
        """
        if rail == "positive":
            return FABRIC_CHANNEL["positive"], False
        try:
            device = context(uri).find_device(DEV_FABRIC)
            if device.find_channel(FABRIC_CHANNEL["negative"], True) is None:
                return FABRIC_CHANNEL["positive"], True
        except Exception:                               # noqa: BLE001
            # Unreachable board, or no bindings. Assume the arrangement
            # every board we have seen has; the write will report its own
            # failure if that is wrong.
            pass
        return FABRIC_CHANNEL["negative"], False


def _nearest_legal(volts, rail):
    """The closest setpoint this rail can actually hold.

    A slider dragged off the end of its range, or dragged through zero
    onto the wrong side of it. Both land on the nearest thing the rail
    can do, which for the wrong sign is zero.
    """
    value = max(-SUPPLY_LIMIT_V, min(SUPPLY_LIMIT_V, float(volts)))
    if rail == "positive":
        return max(0.0, value)
    return min(0.0, value)
