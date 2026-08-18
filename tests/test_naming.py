"""The attribute-name grammar. These are all real names from real drivers."""

import pytest

import iio_semantics as sem


# (full sysfs name, direction, channel type, index, modifier, info word)
NAMES = [
    ("in_voltage0_raw",              "in",  "voltage",     0, None, "raw"),
    ("in_voltage0_scale",            "in",  "voltage",     0, None, "scale"),
    ("in_voltage0_offset",           "in",  "voltage",     0, None, "offset"),
    ("out_voltage1_raw",             "out", "voltage",     1, None, "raw"),
    ("out_altvoltage0_frequency",    "out", "altvoltage",  0, None, "frequency"),
    ("out_altvoltage0_phase",        "out", "altvoltage",  0, None, "phase"),
    ("in_temp0_input",               "in",  "temp",        0, None, "input"),
    ("in_temp_raw",                  "in",  "temp",     None, None, "raw"),
    ("in_accel_x_raw",               "in",  "accel",    None, "x",  "raw"),
    ("in_anglvel_z_scale",           "in",  "anglvel",  None, "z",  "scale"),
    ("in_intensity_red_raw",         "in",  "intensity", None, "red", "raw"),
    ("in_intensity_clear_raw",       "in",  "intensity", None, "clear", "raw"),
    ("in_voltage0_calibbias",        "in",  "voltage",     0, None, "calibbias"),
    ("in_voltage0_hardwaregain",     "in",  "voltage",     0, None, "hardwaregain"),
    ("in_voltage2_peak_raw",         "in",  "voltage",     2, None, "peak_raw"),
    ("in_current7_raw",              "in",  "current",     7, None, "raw"),
    ("in_pressure0_input",           "in",  "pressure",    0, None, "input"),
    ("in_magn_x_raw",                "in",  "magn",     None, "x",  "raw"),
    ("out_voltage0_powerdown",       "out", "voltage",     0, None, "powerdown"),
    ("in_voltage0_sampling_frequency", "in", "voltage",    0, None,
     "sampling_frequency"),
    ("in_voltage10_raw",             "in",  "voltage",    10, None, "raw"),
]


@pytest.mark.parametrize("name,direction,ctype,index,modifier,info", NAMES)
def test_full_sysfs_names(name, direction, ctype, index, modifier, info):
    parsed = sem.parse_attr_name(name)
    assert parsed["direction"] == direction
    assert parsed["channel_type"] == ctype
    assert parsed["channel_index"] == index
    assert parsed["modifier"] == modifier
    assert parsed["info"] == info


def test_differential_pair():
    parsed = sem.parse_attr_name("in_voltage0-voltage1_raw")
    assert parsed["differential"] is True
    assert parsed["channel_index"] == 0
    assert parsed["channel_index2"] == 1
    assert parsed["info"] == "raw"


def test_bare_channel_attr_gets_prefix_rebuilt():
    """libiio strips the prefix from channel attrs; we put it back."""
    channel = {"id": "voltage0", "output": False, "attrs": []}
    parsed = sem.parse_attr_name("raw", channel)
    assert parsed["sysfs_name"] == "in_voltage0_raw"
    assert parsed["channel_type"] == "voltage"
    assert parsed["info"] == "raw"


def test_output_channel_gets_out_prefix():
    channel = {"id": "voltage0", "output": True, "attrs": []}
    assert sem.parse_attr_name("raw", channel)["sysfs_name"] == "out_voltage0_raw"


def test_device_level_attr_has_no_channel():
    parsed = sem.parse_attr_name("sampling_frequency")
    assert parsed["channel_type"] is None
    assert parsed["info"] == "sampling_frequency"


def test_data_available_is_not_an_option_list():
    """Regression: data_available is its own attribute, not data + _available."""
    parsed = sem.parse_attr_name("data_available")
    assert parsed["info"] == "data_available"
    assert parsed["is_available"] is False


def test_real_option_list_is_recognised():
    parsed = sem.parse_attr_name("sampling_frequency_available")
    assert parsed["info"] == "sampling_frequency"
    assert parsed["is_available"] is True


def test_channel_id_variants():
    assert sem.parse_channel_id("altvoltage0")["type"] == "altvoltage"
    assert sem.parse_channel_id("altvoltage0")["index"] == 0
    assert sem.parse_channel_id("temp")["index"] is None
    assert sem.parse_channel_id("accel_x")["modifier"] == "x"
    assert sem.parse_channel_id("") is None


def test_unknown_info_word_is_reported_as_unknown():
    parsed = sem.parse_attr_name("some_vendor_thing")
    assert not sem.is_understood(parsed)
