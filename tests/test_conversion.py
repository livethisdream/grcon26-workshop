"""The conversion contract: real = (raw + offset) * scale."""

import pytest

import iio_semantics as sem


def test_offset_is_applied_before_scale():
    result = sem.convert_raw("1234", "-2048", "0.0625", "voltage")
    assert result["value"] == pytest.approx(-50.875)
    # The wrong order would give 1234 * 0.0625 - 2048 = -1970.875
    assert result["value"] != pytest.approx(-1970.875)


def test_expression_shows_the_working():
    result = sem.convert_raw("1234", "-2048", "0.0625", "voltage")
    assert result["expression"] == "(1234 + -2048) * 0.0625"


def test_units_are_abi_units_not_si():
    result = sem.convert_raw("1000", None, "1", "voltage")
    assert result["unit"] == "millivolts"
    assert result["si_value"] == pytest.approx(1.0)
    assert result["si_unit"] == "volts"


def test_temperature_is_millidegrees():
    result = sem.convert_raw("31450", "-2732", "1.0", "temp")
    assert result["value"] == pytest.approx(28718.0)
    assert result["si_value"] == pytest.approx(28.718)
    assert result["si_unit"] == "degrees Celsius"


def test_missing_offset_is_allowed():
    result = sem.convert_raw("100", None, "2", "voltage")
    assert result["value"] == pytest.approx(200.0)
    assert result["used_offset"] is False


def test_missing_scale_is_allowed():
    result = sem.convert_raw("100", "10", None, "voltage")
    assert result["value"] == pytest.approx(110.0)
    assert result["used_scale"] is False


def test_unreadable_raw_gives_nothing():
    assert sem.convert_raw(None, "0", "1", "voltage") is None
    assert sem.convert_raw("not a number", None, None, "voltage") is None


def test_unitless_type_has_no_si_line():
    result = sem.convert_raw("500", None, "1", "intensity")
    assert result["si_value"] is None


def test_identity_si_factor_is_not_repeated():
    """accel is already m/s^2 -- do not print the same number twice."""
    result = sem.convert_raw("9", None, "1", "accel")
    assert result["si_value"] is None
