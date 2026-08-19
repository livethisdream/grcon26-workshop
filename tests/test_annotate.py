"""The machine-readable half of iio_explain.

The browser renders exactly what these functions return, so anything the
CLI can say and these cannot is something a participant will not see.
"""

import sys

import iio_explain


def attrs_of(annotated, device_label):
    device = next(d for d in annotated["devices"] if d["label"] == device_label)
    flat = list(device["device_attrs"]) + list(device["buffer_attrs"]) \
        + list(device["debug_attrs"])
    for channel in device["channels"]:
        flat.extend(channel["attrs"])
    return device, flat


def test_annotating_needs_no_libiio(snapshot):
    iio_explain.annotate(snapshot)
    assert "iio" not in sys.modules


def test_every_attribute_carries_its_sources(snapshot):
    annotated = iio_explain.annotate(snapshot)
    _, flat = attrs_of(annotated, "m2k-adc")
    assert flat
    for attr in flat:
        # The name always says something, so "parsed" is always present;
        # anything richer has to be earned.
        assert "parsed" in attr["provenance"]
        assert attr["sysfs_name"]


def test_the_kernel_is_quoted_not_paraphrased(snapshot):
    annotated = iio_explain.annotate(snapshot)
    _, flat = attrs_of(annotated, "m2k-adc")
    raw = next(a for a in flat if a["sysfs_name"] == "in_voltage0_raw")
    assert "abi" in raw["provenance"]
    assert raw["abi"]["paragraphs"]
    assert raw["abi"]["source"] == "sysfs-bus-iio"
    assert raw["needs_conversion"] is True


def test_board_notes_keep_their_confidence(snapshot):
    annotated = iio_explain.annotate(snapshot)
    _, flat = attrs_of(annotated, "m2k-adc")
    note = next(a for a in flat if a["name"] == "oversampling_ratio")["overlay"]
    assert note["confidence"] in ("measured", "sourced", "unverified")
    assert any(p.startswith("overlay:") for p in
               next(a for a in flat
                    if a["name"] == "oversampling_ratio")["provenance"])


def test_channel_carries_identity_and_wire_format(snapshot):
    annotated = iio_explain.annotate(snapshot)
    device, _ = attrs_of(annotated, "m2k-adc")
    channel = next(c for c in device["channels"] if c["id"] == "voltage0")
    assert channel["description"]
    assert channel["identity"]
    assert channel["data_format"]["shorthand"].startswith("le:")


def test_unexplained_attributes_are_marked_not_hidden(snapshot):
    """--unknown's honesty has to survive into the browser."""
    annotated = iio_explain.annotate(snapshot)
    _, flat = attrs_of(annotated, "m2k-adc")
    assert all(isinstance(a["understood"], bool) for a in flat)


def test_channel_attribute_note_reaches_through_the_prefix(real_snapshot):
    """A channel attr must reduce to its info word to find a board note.

    in_voltage0_oversampling_ratio has to hit the flat "oversampling_ratio"
    entry in the pack, or entries get written and never displayed.
    """
    annotated = iio_explain.annotate(real_snapshot)
    device, _ = attrs_of(annotated, "m2k-adc")
    found = [a for a in device["device_attrs"]
             if a["name"] == "oversampling_ratio" and a["overlay"]]
    assert found, "board note did not reach the attribute"


def test_real_capture_annotates_whole(real_snapshot):
    annotated = iio_explain.annotate(real_snapshot)
    assert len(annotated["devices"]) == len(real_snapshot["devices"])
    total = sum(len(d["device_attrs"]) + len(d["buffer_attrs"])
                + len(d["debug_attrs"])
                + sum(len(c["attrs"]) for c in d["channels"])
                for d in annotated["devices"])
    assert total == 317
