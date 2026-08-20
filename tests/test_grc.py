"""Selection -> GNU Radio block parameters.

The shapes asserted here are gr-iio 3.10's, read off device_source.h and
device_source_impl.cc: `channels` is a list of channel names, `params` is
a list of "<sysfs filename>=<value>" strings whose keys go through
iio_device_identify_filename(). If a test here fails, the block will
either refuse the value or silently write the wrong attribute.
"""

import iio_grc


def build(snapshot, **selection):
    return iio_grc.build(snapshot, selection)


# ---------------------------------------------------------- params keys

def test_channel_attr_gets_its_prefix_back(snapshot):
    """libiio reports "scale"; gr-iio needs "in_voltage0_scale"."""
    result = build(snapshot, device="m2k-adc", channels=["voltage0"],
                   settings=[{"channel": "voltage0", "attr": "scale",
                              "value": "0.0625"}])
    assert result["params"] == ["in_voltage0_scale=0.0625"]
    assert result["warnings"] == []


def test_output_channel_prefix_is_out(snapshot):
    result = build(snapshot, device="m2k-dac-a",
                   settings=[{"channel": "voltage0", "attr": "calibscale",
                              "value": "1.0"}])
    assert result["params"] == ["out_voltage0_calibscale=1.0"]


def test_device_attr_keeps_its_own_name(snapshot):
    result = build(snapshot, device="m2k-adc", channels=["voltage0"],
                   settings=[{"channel": None, "attr": "oversampling_ratio",
                              "value": "4"}])
    assert result["params"] == ["oversampling_ratio=4"]


# ------------------------------------------------------------- validation

def test_unknown_device_is_refused(snapshot):
    result = build(snapshot, device="nonesuch")
    assert result["fields"] == {}
    assert "nonesuch" in result["warnings"][0]


def test_non_scan_channel_cannot_stream(snapshot):
    result = build(snapshot, device="m2k-fabric", channels=["voltage0"])
    assert result["fields"]["channels"] == []
    assert any("cannot stream" in w for w in result["warnings"])


def test_a_dac_device_builds_a_sink(snapshot):
    """m2k-dac-a only has output channels, so it IS a sink.

    Warning that its output channel "belongs on a Device Sink" and then
    emitting a device_source anyway was the bug: the advice was right and
    the generated line was wrong.
    """
    result = build(snapshot, device="m2k-dac-a", channels=["voltage0"])
    assert result["is_sink"] is True
    assert "iio.device_sink(" in result["make"]
    assert not any("belongs on a Device Sink" in w
                   for w in result["warnings"])


def test_sink_constructor_matches_gr_iio(snapshot):
    """device_sink takes interpolation and cyclic; device_source neither."""
    result = build(snapshot, device="m2k-dac-a", channels=["voltage0"],
                   interpolation=4)
    call = result["make"].splitlines()[0]
    assert call.endswith(", 32768, 3, False)"), call
    assert result["fields"]["interpolation"] == 4
    assert "decimation" not in result["fields"]


def test_sink_shows_interpolation_not_decimation(snapshot):
    display = {f["id"]: f for f in
               build(snapshot, device="m2k-dac-a",
                     channels=["voltage0"])["fields_display"]}
    assert "interpolation" in display
    assert "cyclic" in display
    assert "decimation" not in display


def test_output_channel_on_a_mixed_device_is_flagged(snapshot):
    """A device with inputs AND outputs is built as a source.

    Its output channels are then genuinely misplaced and get flagged.
    (An all-output device is a sink, so this cannot arise there -- which
    is why there is no mirror-image check.)
    """
    import copy
    data = copy.deepcopy(snapshot)
    device = [d for d in data["devices"] if d["name"] == "m2k-dac-a"][0]
    stream = copy.deepcopy(device["channels"][0])
    stream["id"], stream["output"], stream["scan_index"] = "voltage1", False, 1
    device["channels"].append(stream)
    result = build(data, device="m2k-dac-a", channels=["voltage0"])
    assert result["is_sink"] is False
    assert any("belongs on a Device Sink" in w for w in result["warnings"])


def test_no_channels_is_flagged(snapshot):
    result = build(snapshot, device="m2k-adc", channels=[])
    assert any("no outputs" in w for w in result["warnings"])


def test_unknown_attribute_is_flagged(snapshot):
    result = build(snapshot, device="m2k-adc", channels=["voltage0"],
                   settings=[{"channel": "voltage0", "attr": "nonesuch",
                              "value": "1"}])
    assert result["params"] == []
    assert any("nonesuch" in w for w in result["warnings"])


def test_value_outside_the_published_options_is_flagged(snapshot):
    """m2k-fabric voltage0 gain publishes its legal values."""
    result = build(snapshot, device="m2k-fabric",
                   settings=[{"channel": "voltage0", "attr": "gain",
                              "value": "loud"}])
    assert any("not one of the values" in w for w in result["warnings"])
    # Still emitted: the hardware is the final authority, not the capture.
    assert result["params"] == ["in_voltage0_gain=loud"]


def test_a_legal_value_is_silent(snapshot):
    device = next(d for d in snapshot["devices"] if d["name"] == "m2k-fabric")
    channel = next(c for c in device["channels"] if c["id"] == "voltage0")
    attr = next(a for a in channel["attrs"] if a["name"] == "gain")
    legal = attr["available"]["values"][0]
    result = build(snapshot, device="m2k-fabric",
                   settings=[{"channel": "voltage0", "attr": "gain",
                              "value": legal}])
    assert not any("not one of the values" in w for w in result["warnings"])


def test_a_number_written_differently_is_still_legal(snapshot):
    """The list says "0.062500". Writing "0.0625" sets the same thing."""
    result = build(snapshot, device="m2k-adc", channels=["voltage0"],
                   settings=[{"channel": "voltage0", "attr": "scale",
                              "value": "0.0625"}])
    assert result["warnings"] == []


def test_attribute_with_no_available_list_is_not_second_guessed(snapshot):
    result = build(snapshot, device="m2k-adc", channels=["voltage0"],
                   settings=[{"channel": "voltage0", "attr": "calibbias",
                              "value": "-40000"}])
    assert result["warnings"] == []


# ---------------------------------------------------------------- fields

def test_fields_match_the_block(snapshot):
    result = build(snapshot, device="m2k-adc",
                   channels=["voltage0", "voltage1"])
    fields = result["fields"]
    assert fields["uri"] == "usb:1.5.5"
    assert fields["device"] == "m2k-adc"
    assert fields["channels"] == ["voltage0", "voltage1"]
    assert fields["buffer_size"] == iio_grc.DEFAULT_BUFFER_SIZE
    labels = [f["label"] for f in result["fields_display"]]
    # Every parameter the real gr-iio 3.10 block declares, in its order.
    assert labels == ["IIO context URI", "Device Name/ID",
                      "PHY Device Name/ID", "Channels", "Buffer size",
                      "Decimation", "Parameters", "Packet Length Tag"]


def test_display_says_how_grc_reads_each_box(snapshot):
    display = {f["id"]: f for f in
               build(snapshot, device="m2k-adc",
                     channels=["voltage0"])["fields_display"]}
    # String boxes take bare text, raw boxes take Python literals. Typing
    # quotes into a string box is the classic first mistake.
    assert display["uri"]["kind"] == "string"
    assert display["uri"]["text"] == "usb:1.5.5"
    assert display["channels"]["kind"] == "raw"
    assert display["channels"]["text"] == "['voltage0']"


def test_decimation_is_one_less_in_the_constructor(snapshot):
    """GRC shows a factor; gr-iio takes samples-to-drop."""
    result = build(snapshot, device="m2k-adc", channels=["voltage0"],
                   decimation=4)
    assert result["fields"]["decimation"] == 4
    assert result["make"].splitlines()[0].endswith(", 32768, 3)")


def test_make_sets_the_length_tag_key(snapshot):
    """GRC emits a second line after the constructor; so must we."""
    result = build(snapshot, device="m2k-adc", channels=["voltage0"])
    lines = result["make"].splitlines()
    assert len(lines) == 2
    assert lines[1] == "self.blk.set_len_tag_key('packet_len')"


# ------------------------------------------------------- on real hardware

def test_real_capture_round_trips(real_snapshot):
    result = iio_grc.build(real_snapshot, {
        "device": "m2k-adc",
        "channels": ["voltage0", "voltage1"],
        "settings": [{"channel": None, "attr": "oversampling_ratio",
                      "value": "4"}],
    })
    assert result["warnings"] == []
    assert result["fields"]["uri"].startswith("ip:")
    assert result["params"] == ["oversampling_ratio=4"]


def test_logic_analyzer_streams_from_rx_not_the_config_device(real_snapshot):
    """The obvious guess is wrong, and the tool should say so.

    m2k-logic-analyzer holds the pin configuration; the samples come out
    of m2k-logic-analyzer-rx.
    """
    config = iio_grc.build(real_snapshot, {"device": "m2k-logic-analyzer",
                                           "channels": ["voltage0"]})
    assert any("cannot stream" in w for w in config["warnings"])

    rx = iio_grc.build(real_snapshot, {"device": "m2k-logic-analyzer-rx",
                                       "channels": ["voltage0"]})
    assert rx["fields"]["channels"] == ["voltage0"]
    assert rx["warnings"] == []


def test_emitted_channels_follow_the_hardware_order(real_snapshot):
    """Port order comes from the hardware, not from the click order."""
    result = iio_grc.build(real_snapshot, {
        "device": "m2k-logic-analyzer-rx",
        "channels": ["voltage10", "voltage2", "voltage1"]})
    assert result["fields"]["channels"] == ["voltage1", "voltage2", "voltage10"]


# ------------------------------------------- devices that cannot stream

def test_config_only_device_refuses_to_become_a_block(real_snapshot):
    """Five of the M2K's fourteen devices have no scan elements.

    A generated block for one carries `asserts: len(channels) > 0` that can
    never be satisfied, so GRC would show it permanently in error.
    """
    import pytest
    for name in ("m2k-fabric", "pll", "xadc", "m2k-dds",
                 "m2k-logic-analyzer"):
        with pytest.raises(ValueError) as excinfo:
            iio_grc.generate_block(real_snapshot, name)
        assert "configuration only" in str(excinfo.value), name
        # The error has to say what to do instead, not just say no.
        assert "device_phy" in str(excinfo.value), name


def test_streaming_devices_still_generate(real_snapshot):
    for name in ("m2k-adc", "m2k-dac-a", "m2k-logic-analyzer-rx"):
        assert iio_grc.generate_block(real_snapshot, name).startswith("id: ")


# ----------------------------------------------- ambiguous channel ids

def test_duplicate_channel_ids_are_real_on_this_board(real_snapshot):
    """Guard the assumption the disambiguation exists for."""
    fabric = iio_grc.find_device(real_snapshot, "m2k-fabric")
    assert iio_grc.channel_is_ambiguous(fabric, "voltage0")


def test_direction_picks_between_duplicate_ids(real_snapshot):
    fabric = iio_grc.find_device(real_snapshot, "m2k-fabric")
    incoming = iio_grc.find_channel(fabric, "voltage0", output=False)
    outgoing = iio_grc.find_channel(fabric, "voltage0", output=True)
    assert incoming is not outgoing
    # The input side is the one carrying the range switch.
    assert any(a["name"] == "gain" for a in incoming["attrs"])
    assert not any(a["name"] == "gain" for a in outgoing["attrs"])
    assert iio_grc.sysfs_name(incoming, "gain") == "in_voltage0_gain"
    assert iio_grc.sysfs_name(outgoing, "powerdown") == "out_voltage0_powerdown"


def test_ambiguous_selection_is_flagged(real_snapshot):
    result = iio_grc.build(real_snapshot, {
        "device": "m2k-fabric",
        "settings": [{"channel": "voltage0", "attr": "gain",
                      "value": "high"}]})
    assert any("names more than one channel" in w for w in result["warnings"])
