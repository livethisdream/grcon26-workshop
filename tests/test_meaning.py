"""Provenance, overlays, and the channel-identity ladder."""

import iio_overlays
import iio_semantics as sem


def adc(snapshot):
    return [d for d in snapshot["devices"] if d["name"] == "m2k-adc"][0]


def test_overlay_only_applies_to_its_own_device(snapshot):
    fabric = [d for d in snapshot["devices"] if d["name"] == "m2k-fabric"][0]
    assert iio_overlays.attr_note(fabric, "gain") is not None
    # The same info word on a different device must not pick up the note.
    assert iio_overlays.attr_note(adc(snapshot), "gain") is None


def test_unknown_device_gets_no_overlay():
    assert iio_overlays.device_note({"id": "iio:device9",
                                     "name": "not-a-real-device"}) is None


def test_every_overlay_entry_declares_a_confidence():
    for pack in iio_overlays.DEVICE_PACKS.values():
        entries = [pack.get("device")]
        entries += list(pack.get("channels", {}).values())
        entries += list(pack.get("attrs", {}).values())
        for entry in entries:
            if entry is None:
                continue
            assert entry["confidence"] in (iio_overlays.UNVERIFIED,
                                           iio_overlays.SOURCED,
                                           iio_overlays.MEASURED)


def test_sourced_entries_cite_their_source():
    """If we claim better than unverified, we must say where it came from."""
    for pack in iio_overlays.DEVICE_PACKS.values():
        entries = [pack.get("device")]
        entries += list(pack.get("channels", {}).values())
        entries += list(pack.get("attrs", {}).values())
        for entry in entries:
            if entry and entry["confidence"] == iio_overlays.SOURCED:
                assert entry["source"], entry["text"][:40]


def test_identity_prefers_driver_name_over_convention():
    device = {"id": "iio:device0", "name": "m2k-adc"}
    channel = {"id": "voltage0", "name": "scope_1_plus", "output": False,
               "attrs": []}
    findings = sem.channel_identity(device, channel, iio_overlays)
    assert findings[0]["provenance"] == sem.DRIVER
    assert "scope_1_plus" in findings[0]["text"]


def test_identity_reads_the_label_attribute():
    device = {"id": "iio:device0", "name": "unknown"}
    channel = {"id": "voltage0", "name": None, "output": False,
               "attrs": [{"name": "label", "value": "ANTENNA_A",
                          "type": "channel", "read_error": None,
                          "available_raw": None, "available": None}]}
    findings = sem.channel_identity(device, channel, iio_overlays)
    assert any("ANTENNA_A" in f["text"] for f in findings)


def test_identity_falls_back_to_the_abi_convention(snapshot):
    device = {"id": "iio:device9", "name": "unknown-device"}
    channel = {"id": "voltage3", "name": None, "output": False, "attrs": []}
    findings = sem.channel_identity(device, channel, iio_overlays)
    assert len(findings) == 1
    assert findings[0]["provenance"] == sem.ABI
    assert findings[0]["fallback"] is True
    assert "input 3" in findings[0]["text"]


def test_channel_description_names_the_unit(snapshot):
    channel = adc(snapshot)["channels"][0]
    text = sem.describe_channel(channel)
    assert "millivolts" in text and "input" in text


def test_differential_channel_is_called_out():
    text = sem.describe_channel({"id": "voltage0-voltage1", "output": False})
    assert "differential" in text
