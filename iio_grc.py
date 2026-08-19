#!/usr/bin/env python3
"""
iio_grc.py -- turn a discovery selection into GNU Radio block parameters.

iio_discover.py answers "what is here". iio_explain.py answers "what does
it mean". This answers the question that follows both: "what do I type
into the IIO Device Source block to get it".

It imports no libiio. It works off a snapshot, like iio_explain.py, so
the mapping can be taught anywhere.

The shapes below are read off gr-iio 3.10, not guessed:

    iio.device_source(uri, device, channels, device_phy, params,
                      buffer_size, decimation - 1)

  channels  list of channel names, one stream output each. Only scan
            elements can stream -- a channel with no scan index is
            configuration, not data.
  params    list of "<attribute name>=<value>" strings. gr-iio feeds each
            key to iio_device_identify_filename(), which wants the full
            sysfs filename: "in_voltage0_oversampling_ratio", not the bare
            "oversampling_ratio" that libiio reports against the channel.
            Restoring that prefix is what sysfs_name() is for, and it is
            the single easiest thing to get wrong by hand.
  device_phy  where params are applied, if that is not the streaming
            device itself. Left empty, gr-iio uses the streaming device.

In GRC, `uri` and `device` are string fields -- type the text bare, no
quotes. `channels` and `params` are raw fields -- type a Python list.
"""

import iio_semantics as sem

DEFAULT_BUFFER_SIZE = 0x8000


# ------------------------------------------------------------- lookups

def find_device(data, wanted):
    """A device by name or id. Returns None if the snapshot has no such device."""
    for device in data.get("devices", []):
        if wanted in (device.get("name"), device.get("id")):
            return device
    return None


def find_channel(device, chan_id):
    for channel in (device or {}).get("channels", []):
        if chan_id in (channel.get("id"), channel.get("name")):
            return channel
    return None


def stream_channels(device):
    """The channels that can actually carry samples: the scan elements."""
    return [c for c in (device or {}).get("channels", [])
            if c.get("scan_element")]


def sysfs_name(channel, attr_name):
    """The full filename gr-iio needs for a params key.

    A device-level attribute already carries its own full name. A channel
    attribute does not -- libiio strips the prefix, so "raw" has to become
    "in_voltage0_raw" before gr-iio can find it again.
    """
    return sem.parse_attr_name(attr_name, channel)["sysfs_name"]


def find_attr(device, chan_id, attr_name):
    """Locate an attribute. Returns (channel_or_None, attr) or (None, None).

    chan_id None means look at device, buffer and debug level. gr-iio's
    set_params() tries device attributes then debug attributes, so both
    are legal here.
    """
    if chan_id:
        channel = find_channel(device, chan_id)
        if channel is None:
            return None, None
        for attr in channel.get("attrs", []):
            if attr["name"] == attr_name:
                return channel, attr
        return channel, None

    for group in ("device_attrs", "buffer_attrs", "debug_attrs"):
        for attr in (device or {}).get(group, []):
            if attr["name"] == attr_name:
                return None, attr
    return None, None


# ---------------------------------------------------------- validation

def _numerically_in(value, options):
    """Does `value` equal one of `options` as a number?

    Returns False as soon as anything is not a number -- an option list
    of words is compared as words.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    for option in options:
        try:
            if float(option) == number:
                return True
        except (TypeError, ValueError):
            return False
    return False


def check_value(attr, value):
    """Is `value` legal for `attr`, as far as the capture can say?

    Returns None if it is fine or if the hardware published no opinion,
    otherwise a sentence saying what is wrong. The capture only knows
    about attributes that folded an *_available sibling -- silence here
    means unknown, not approved.
    """
    available = (attr or {}).get("available")
    if not available:
        return None

    if available["kind"] == "options":
        if value in available["values"]:
            return None
        # The list is text, but a numeric attribute is compared as a
        # number by the driver: an option printed "0.062500" accepts
        # "0.0625". Complaining about that would be crying wolf.
        if _numerically_in(value, available["values"]):
            return None
        return ("'%s' is not one of the values this attribute accepts "
                "(%s)." % (value, " ".join(available["values"])))

    try:
        number = float(value)
        low = float(available["min"])
        high = float(available["max"])
    except (TypeError, ValueError):
        return None
    if number < low or number > high:
        return ("%s is outside the range the hardware reports (%s to %s)."
                % (value, available["min"], available["max"]))
    return None


# ------------------------------------------------------------- building

def build(data, selection):
    """Selection -> block parameters, with every complaint spelled out.

    `selection` is the object the browser holds and the only thing the
    later GRC-block generator and runtime message path need:

        {"device": "m2k-adc",
         "channels": ["voltage0", "voltage1"],
         "settings": [{"channel": "voltage0", "attr": "raw", "value": "1"},
                      {"channel": null, "attr": "oversampling_ratio",
                       "value": "4"}],
         "buffer_size": 32768, "decimation": 1, "device_phy": ""}

    Returns {"fields", "params", "warnings", "make"}. Warnings never stop
    the emit -- they are teaching material, and the hardware is the final
    authority on all of them.
    """
    warnings = []
    device_name = selection.get("device") or ""
    device = find_device(data, device_name)
    if device is None:
        return {"fields": {}, "params": [], "make": "",
                "warnings": ["No device '%s' in this capture." % device_name]}

    label = device.get("name") or device.get("id")

    channels = []
    for chan_id in selection.get("channels", []):
        channel = find_channel(device, chan_id)
        if channel is None:
            warnings.append("Channel '%s' is not on %s." % (chan_id, label))
            continue
        if not channel.get("scan_element"):
            warnings.append(
                "Channel '%s' has no scan index, so it cannot stream. It is "
                "a configuration channel -- set its attributes through "
                "params instead of listing it here." % chan_id)
            continue
        if channel.get("output"):
            warnings.append(
                "Channel '%s' is an output. A Device Source reads inputs; "
                "an output channel belongs on a Device Sink." % chan_id)
        channels.append(channel.get("id"))

    if not channels:
        warnings.append(
            "No streaming channels selected. The block will have no outputs.")

    params = []
    for setting in selection.get("settings", []):
        attr_name = setting.get("attr")
        chan_id = setting.get("channel")
        value = setting.get("value")
        if attr_name is None or value in (None, ""):
            continue

        channel, attr = find_attr(device, chan_id, attr_name)
        if attr is None:
            where = ("channel %s" % chan_id) if chan_id else "device level"
            warnings.append("No attribute '%s' at %s on %s."
                            % (attr_name, where, label))
            continue

        complaint = check_value(attr, value)
        if complaint:
            warnings.append("%s: %s" % (sysfs_name(channel, attr_name),
                                        complaint))
        params.append("%s=%s" % (sysfs_name(channel, attr_name), value))

    buffer_size = int(selection.get("buffer_size") or DEFAULT_BUFFER_SIZE)
    decimation = int(selection.get("decimation") or 1)
    device_phy = selection.get("device_phy") or ""

    fields = {
        "uri": data.get("uri") or "local:",
        "device": label,
        "device_phy": device_phy,
        "channels": channels,
        "buffer_size": buffer_size,
        "decimation": decimation,
        "params": params,
        "len_tag_key": "packet_len",
    }
    return {"fields": fields, "fields_display": render_fields(fields),
            "params": params, "warnings": warnings,
            "make": render_python(fields)}


# ------------------------------------------------------------ rendering

def render_python(fields):
    """The constructor call GRC generates, for pasting into plain Python.

    gr-iio takes decimation as "samples to drop", which is one less than
    the decimation factor GRC shows -- hence the subtraction in the GRC
    template, reproduced here.
    """
    return ("iio.device_source(%r, %r, %r, %r, %r, %d, %d)"
            % (fields["uri"], fields["device"], fields["channels"],
               fields["device_phy"], fields["params"],
               fields["buffer_size"], fields["decimation"] - 1))


def render_fields(fields):
    """What to type in each GRC box, in the block's own order.

    `kind` says how GRC reads the box: a string field takes bare text, a
    raw field takes a Python literal. Typing quotes into a string field
    is the classic first mistake.
    """
    return [
        {"id": "uri", "label": "IIO context URI", "kind": "string",
         "text": fields["uri"]},
        {"id": "device", "label": "Device Name/ID", "kind": "string",
         "text": fields["device"]},
        {"id": "device_phy", "label": "PHY Device Name/ID", "kind": "string",
         "text": fields["device_phy"]},
        {"id": "channels", "label": "Channels", "kind": "raw",
         "text": repr(fields["channels"])},
        {"id": "buffer_size", "label": "Buffer size", "kind": "raw",
         "text": str(fields["buffer_size"])},
        {"id": "decimation", "label": "Decimation", "kind": "raw",
         "text": str(fields["decimation"])},
        {"id": "params", "label": "Parameters", "kind": "raw",
         "text": repr(fields["params"])},
    ]
