"""Scan-element sample layouts -- what gr-iio actually hands you."""

import iio_semantics as sem


def fmt(**kwargs):
    base = {"length": 16, "bits": 12, "shift": 0, "repeat": 1,
            "is_signed": True, "is_be": False}
    base.update(kwargs)
    return base


def test_shorthand_matches_iio_info():
    assert sem.describe_data_format(fmt())["shorthand"] == "le:s12/16>>0"


def test_unsigned_big_endian_with_shift():
    layout = sem.describe_data_format(
        fmt(bits=16, length=16, shift=4, is_signed=False, is_be=True))
    assert layout["shorthand"] == "be:u16/16>>4"
    assert "Shift right by 4 bits" in layout["english"]


def test_repeat_is_shown():
    assert sem.describe_data_format(fmt(repeat=2))["shorthand"].endswith("X2")


def test_full_scale_is_explained_when_padded():
    english = sem.describe_data_format(fmt())["english"]
    # signed 12-bit tops out at 2047, not at the container's 32767
    assert "2047" in english and "32767" in english


def test_no_format_for_non_streaming_channel():
    assert sem.describe_data_format(None) is None


def test_zero_width_format_is_not_a_format():
    """xadc reports bits 0 in a 0-bit container; le:u0/0>>0 is noise."""
    assert sem.describe_data_format(
        fmt(bits=0, length=0, is_signed=False)) is None
