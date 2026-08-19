"""Generated GRC block definitions.

GRC will not tell you politely when a block file is wrong -- it drops the
block from the tree, or generates Python that fails at flowgraph build
time. So the checks here are the ones GRC would have made: the YAML
parses, the ids are usable, and the make template is valid Python once
its defaults are substituted.
"""

import re

import pytest

import iio_grc

yaml = pytest.importorskip("yaml")


def blocks(snapshot):
    return {name: yaml.safe_load(text)
            for name, text in iio_grc.generate_all(snapshot).items()}


# ------------------------------------------------------------- structure

def test_a_block_per_streaming_device(real_snapshot):
    generated = blocks(real_snapshot)
    names = sorted(generated)
    assert names == [
        "m2k_m2k_adc_source.block.yml",
        "m2k_m2k_dac_a_sink.block.yml",
        "m2k_m2k_dac_b_sink.block.yml",
        "m2k_m2k_logic_analyzer_rx_source.block.yml",
        "m2k_m2k_logic_analyzer_tx_sink.block.yml",
    ]


def test_direction_follows_the_hardware(real_snapshot):
    """The DACs only make sense as sinks; nobody has to say so."""
    generated = blocks(real_snapshot)
    dac = generated["m2k_m2k_dac_a_sink.block.yml"]
    assert "inputs" in dac and "outputs" not in dac
    adc = generated["m2k_m2k_adc_source.block.yml"]
    assert "outputs" in adc and "inputs" not in adc


def test_parameter_ids_are_python_identifiers(real_snapshot):
    for block in blocks(real_snapshot).values():
        ids = [p["id"] for p in block["parameters"]]
        assert len(ids) == len(set(ids)), "duplicate parameter id"
        for name in ids:
            assert re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name), name


def test_channels_are_ordered_by_the_hardware_not_the_alphabet(real_snapshot):
    """voltage10 must not sit between voltage1 and voltage2."""
    block = blocks(real_snapshot)["m2k_m2k_logic_analyzer_rx_source.block.yml"]
    channels = next(p for p in block["parameters"] if p["id"] == "channels")
    assert eval(channels["default"])[:4] == \
        ["voltage0", "voltage1", "voltage2", "voltage3"]


# --------------------------------------------------------------- options

def test_options_come_from_the_hardware(real_snapshot):
    block = blocks(real_snapshot)["m2k_m2k_logic_analyzer_rx_source.block.yml"]
    mux = next(p for p in block["parameters"] if p["id"] == "p_trigger_mux_out")
    # Read straight off the folded *_available sibling in the capture.
    assert mux["options"] == ["''", "'trigger-logic'", "'trigger-in'",
                              "'trigger-logic-and-trigger-in'",
                              "'trigger-logic-or-trigger-in'",
                              "'trigger-logic-xor-trigger-in'", "'disabled'"]
    assert mux["option_labels"][0] == "leave alone"


def test_string_options_carry_their_own_quotes(real_snapshot):
    """An enum option is substituted verbatim, never evaluated.

    Without the inner quotes GRC would generate `'x=' + push-pull`.
    """
    for block in blocks(real_snapshot).values():
        for param in block["parameters"]:
            if param.get("dtype") != "enum":
                continue
            for option in param["options"]:
                assert option.startswith("'") and option.endswith("'"), option


def test_leaving_a_dropdown_alone_writes_nothing(real_snapshot):
    """A block that was opened and closed must not touch the hardware."""
    for block in blocks(real_snapshot).values():
        for param in block["parameters"]:
            if param.get("dtype") == "enum" and param["id"].startswith("p_"):
                assert param["default"] == "''"


def test_repeated_channel_attributes_collapse(real_snapshot):
    """18 identical trigger_mux_out dropdowns is not a usable block."""
    block = blocks(real_snapshot)["m2k_m2k_logic_analyzer_rx_source.block.yml"]
    dropdowns = [p for p in block["parameters"] if p["id"].startswith("p_")]
    assert len(dropdowns) == 5
    mux = next(p for p in dropdowns if p["id"] == "p_trigger_mux_out")
    assert "all 18 channels" in mux["label"]
    # Nothing is taken away: the per-channel keys are still written. The
    # trailing quote keeps this from also counting ${p_trigger_mux_out}.
    assert block["templates"]["make"].count("_trigger_mux_out'") == 18


# -------------------------------------------------------------- template

def substitute(block):
    """Fill every ${param} with that parameter's default, as GRC would."""
    text = block["templates"]["make"]
    for param in block["parameters"]:
        default = param.get("default", "")
        if param["dtype"] == "string":
            default = repr(str(default))
        elif param["dtype"] in ("raw", "int", "bool", "enum"):
            default = str(default)
        text = text.replace("${%s}" % param["id"], str(default))
    return text


def test_make_template_is_valid_python(real_snapshot):
    for name, block in blocks(real_snapshot).items():
        filled = substitute(block)
        assert "${" not in filled, "unsubstituted placeholder in " + name
        compile(filled, name, "eval")


def test_defaults_produce_an_empty_parameter_list(real_snapshot):
    """With every dropdown left alone, params must come out empty."""
    for name, block in blocks(real_snapshot).items():
        params = eval(substitute(block).split(",\n", 1)[1]
                      .rsplit(",\n", 1)[0].strip())
        assert params == [], name


def test_the_call_matches_gr_iio(real_snapshot):
    """Arity is not negotiable: source takes 7 arguments, sink takes 8."""
    generated = blocks(real_snapshot)
    source = substitute(generated["m2k_m2k_adc_source.block.yml"])
    assert source.startswith("iio.device_source(")
    assert len(eval("_args" + source[len("iio.device_source"):],
                    {"_args": lambda *a: a})) == 7

    sink = substitute(generated["m2k_m2k_dac_a_sink.block.yml"])
    assert sink.startswith("iio.device_sink(")
    assert len(eval("_args" + sink[len("iio.device_sink"):],
                    {"_args": lambda *a: a})) == 8


# --------------------------------------------------------- documentation

def test_documentation_carries_meaning_and_provenance(real_snapshot):
    block = blocks(real_snapshot)["m2k_m2k_adc_source.block.yml"]
    doc = block["documentation"]
    assert "[abi]" in doc or "kernel:" in doc
    assert "[overlay:" in doc
    assert "legal values:" in doc


def test_per_channel_keys_are_documented_when_collapsed(real_snapshot):
    doc = blocks(real_snapshot)[
        "m2k_m2k_logic_analyzer_rx_source.block.yml"]["documentation"]
    assert "in_voltage7_trigger_mux_out" in doc


def test_unknown_device_is_refused(real_snapshot):
    with pytest.raises(ValueError):
        iio_grc.generate_block(real_snapshot, "nonesuch")
