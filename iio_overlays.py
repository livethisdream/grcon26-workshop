#!/usr/bin/env python3
"""
iio_overlays.py -- hand-written meaning that the ABI cannot give you.

iio_semantics.py explains everything the IIO ABI defines, which is most of
any device. What it cannot tell you is what a channel is physically wired
to. Nothing in libiio knows that `voltage0` on m2k-adc is the BNC labelled
1+ on the front of the box. That has to be written down by a person.

Everything in this file is therefore lower-trust than everything in
iio_semantics.py, and it says so. Each entry carries a `confidence`:

    UNVERIFIED  written from documentation, not yet checked against a
                real board. Renderers MUST show this as unverified.
    MEASURED    confirmed by running iio_discover.py against the
                hardware and checking the claim holds.

Promote entries to MEASURED as they get checked, and record how in the
`check` field so the next person can repeat it. Nothing here should be
taught as fact while it still says UNVERIFIED.
"""

UNVERIFIED = "unverified"
SOURCED = "sourced"      # traced to vendor source code, not yet bench-checked
MEASURED = "measured"


def _e(text, confidence=UNVERIFIED, check=None, source=None):
    return {"text": text, "confidence": confidence, "check": check,
            "source": source}


LIBM2K = ("libm2k src/analog/m2kanalogin_impl.cpp -- "
          "https://github.com/analogdevicesinc/libm2k")


# The M2K exposes six IIO devices. Names are matched against the device's
# `name` first and its `id` second, so this works whether libiio reports
# "m2k-adc" or "iio:device0".

DEVICE_PACKS = {
    "m2k-adc": {
        "device": _e("The oscilloscope input. Both scope channels arrive "
                     "through this one device, interleaved in the same "
                     "buffer.",
                     check="iio_discover.py --device m2k-adc; expect two "
                           "input voltage channels."),
        "channels": {
            "voltage0": _e(
                "Scope channel 1. libm2k's M2kAnalogIn indexes this device's "
                "channels directly as ANALOG_IN_CHANNEL_1 and _2, so "
                "voltage0 is the first scope input, not an internal rail.",
                confidence=SOURCED, source=LIBM2K,
                check="Inject a known signal on 1+ and confirm voltage0 "
                      "moves and voltage1 does not."),
            "voltage1": _e("Scope channel 2, by the same indexing.",
                           confidence=SOURCED, source=LIBM2K),
        },
        "attrs": {
            "oversampling_ratio": _e(
                "Decimation. The M2K always samples at 100 MS/s internally; "
                "this divides that down. Your real sample rate is "
                "100e6 / oversampling_ratio, and that is the number a GNU "
                "Radio flowgraph needs.",
                check="Set it, then capture a known tone and confirm the "
                      "measured frequency does not move."),
            "sampling_frequency": _e(
                "The rate after decimation -- what you should feed to every "
                "downstream block."),
            "calibscale": _e(
                "Written by the M2K calibration routine, not by you. "
                "Overwriting it silently invalidates the calibration."),
            "calibbias": _e(
                "Also written by calibration. Same warning."),
        },
    },

    "m2k-dac-a": {
        "device": _e("Waveform generator output W1."),
        "channels": {"voltage0": _e("The W1 output pin.")},
        "attrs": {},
    },

    "m2k-dac-b": {
        "device": _e("Waveform generator output W2."),
        "channels": {"voltage0": _e("The W2 output pin.")},
        "attrs": {},
    },

    "m2k-logic-analyzer-rx": {
        "device": _e("Digital input -- the 16 DIO pins read as logic levels "
                     "rather than voltages."),
        "channels": {},
        "attrs": {},
    },

    "m2k-logic-analyzer-tx": {
        "device": _e("Digital output -- the same 16 DIO pins driven as a "
                     "pattern generator. A pin is either an input or an "
                     "output, not both."),
        "channels": {},
        "attrs": {},
    },

    "ad9963": {
        "device": _e("The mixed-signal front-end chip itself: the actual "
                     "ADC and DAC silicon behind m2k-adc and the two DAC "
                     "devices. You rarely touch it directly; libm2k drives "
                     "it during calibration.",
                     check="Compare its attribute set against the AD9963 "
                           "datasheet register map."),
        "channels": {},
        "attrs": {},
    },

    "m2k-fabric": {
        "device": _e("FPGA fabric control. This is where the analogue front "
                     "end is configured -- it holds settings that change "
                     "what the ADC counts mean but that are not part of the "
                     "ADC device.",
                     check="Toggle gain and watch in_voltage0_scale on "
                           "m2k-adc change."),
        "channels": {
            "voltage0": _e("Front-end control for scope channel 1."),
            "voltage1": _e("Front-end control for scope channel 2."),
        },
        "attrs": {
            "gain": _e(
                "The input range switch. libm2k reads this exact attribute "
                "to decide the range: 'high' means the +/-2.5 V range, "
                "anything else means +/-25 V. It is an attenuator in front "
                "of the ADC, so changing it changes what a raw count is "
                "worth -- re-read _scale on m2k-adc afterwards.",
                confidence=SOURCED, source=LIBM2K,
                check="Set gain, then read in_voltage0_scale on m2k-adc "
                      "and confirm it moved by the expected ratio."),
            "powerdown": _e(
                "Powers the front end down. Remember 1 means off."),
        },
    },
}


# The one CN0363 in the box. Included to show the overlay mechanism is not
# M2K-specific -- and because its channels are a clean example of why
# intensity channels are unitless.

DEVICE_PACKS["cn0363"] = {
    "device": _e("The colorimeter. Measures how much light of each colour "
                 "passes through a sample.",
                 check="Only one board exists -- verify before the workshop, "
                       "not during."),
    "channels": {},
    "attrs": {},
}


# ------------------------------------------------------------------ lookup

def _pack(device):
    """Find the pack for a device dict, by name then by id."""
    if not device:
        return None
    for key in (device.get("name"), device.get("id")):
        if key and key in DEVICE_PACKS:
            return DEVICE_PACKS[key]
    return None


def device_note(device):
    pack = _pack(device)
    return pack.get("device") if pack else None


def channel_note(device, channel):
    pack = _pack(device)
    if not pack or not channel:
        return None
    return pack.get("channels", {}).get(channel.get("id"))


def attr_note(device, info):
    """Look up an attribute note by its parsed info word."""
    pack = _pack(device)
    if not pack or not info:
        return None
    return pack.get("attrs", {}).get(info)


def coverage():
    """How many overlay entries exist and how many are still unverified."""
    total = 0
    counts = {}
    for pack in DEVICE_PACKS.values():
        entries = [pack.get("device")]
        entries += list(pack.get("channels", {}).values())
        entries += list(pack.get("attrs", {}).values())
        for entry in entries:
            if not entry:
                continue
            total += 1
            counts[entry["confidence"]] = counts.get(entry["confidence"], 0) + 1
    counts["total"] = total
    return counts
