"""Does GNU Radio actually accept what we generate?

Everything else in this suite checks our own reasoning about gr-iio. This
checks it against GNU Radio itself: GRC's real block loader, its real
flowgraph validator, and its real code generator.

It needs a Python with `gnuradio` importable, which is often not the one
running the tests -- distro packages build for the system interpreter. So
it hunts for one and skips if there is none, rather than failing on a
machine that simply has no GNU Radio.
"""

import json
import os
import shutil
import subprocess
import sys
import textwrap

import pytest

CANDIDATES = ["python3.12", "python3.11", "python3.10", "python3", sys.executable]


def _find_python_with_gnuradio():
    for name in CANDIDATES:
        path = shutil.which(name) if not os.path.isabs(name) else name
        if not path:
            continue
        probe = subprocess.run(
            [path, "-c", "import gnuradio.grc.core.platform"],
            capture_output=True)
        if probe.returncode == 0:
            return path
    return None


GR_PYTHON = _find_python_with_gnuradio()
needs_gnuradio = pytest.mark.skipif(
    GR_PYTHON is None, reason="no Python with gnuradio available")


def run_in_gr(script, *args):
    result = subprocess.run([GR_PYTHON, "-c", textwrap.dedent(script)] + list(args),
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-3000:]
    return result.stdout


@pytest.fixture(scope="session")
def generated_blocks(tmp_path_factory, repo_root, real_snapshot):
    """Write our generated block definitions somewhere GRC can find them."""
    import iio_grc
    out = tmp_path_factory.mktemp("blocks")
    for name, text in iio_grc.generate_all(real_snapshot).items():
        (out / name).write_text(text)
    return str(out)


LOAD = '''
    import json, logging, sys
    logging.disable(logging.CRITICAL)
    from gnuradio.grc.core.platform import Platform
    p = Platform(version="3.10", version_parts=("3", "10", "0"), prefs=None)
    p.build_library(["/usr/share/gnuradio/grc/blocks", sys.argv[1]])
    print(json.dumps({k: len(b.parameters_data)
                      for k, b in p.blocks.items() if k.startswith("m2k_")}))
'''


@needs_gnuradio
def test_generated_blocks_load_in_grc(generated_blocks):
    """Valid YAML is not the same as a block GRC will accept."""
    loaded = json.loads(run_in_gr(LOAD, generated_blocks))
    assert len(loaded) == 5, loaded
    assert "m2k_m2k_adc_source" in loaded
    assert "m2k_m2k_dac_a_sink" in loaded


BUILD = '''
    import ast, json, logging, sys, tempfile
    logging.disable(logging.CRITICAL)
    from gnuradio.grc.core.platform import Platform
    p = Platform(version="3.10", version_parts=("3", "10", "0"), prefs=None)
    p.build_library(["/usr/share/gnuradio/grc/blocks"] + sys.argv[2:])
    fg = p.make_flow_graph(sys.argv[1])
    fg.rewrite(); fg.validate()
    errors = list(fg.iter_error_messages())
    out = tempfile.mkdtemp()
    p.Generator(fg, out).write()
    name = [f for f in __import__("os").listdir(out) if f.endswith(".py")][0]
    source = open(__import__("os").path.join(out, name)).read()
    ast.parse(source)          # a flowgraph that will not compile is not valid
    # A make template can span several lines, so take the whole
    # constructor call, not just the line its name appears on.
    lines = source.splitlines()
    grabbed = []
    for i, line in enumerate(lines):
        if "iio." in line or "set_len_tag_key" in line:
            grabbed.extend(l.strip() for l in lines[i:i + 4])
    print(json.dumps({"valid": fg.is_valid(), "errors": errors,
                      "iio": grabbed}))
'''


@needs_gnuradio
def test_stock_loopback_builds_and_generates(repo_root):
    path = os.path.join(repo_root, "flowgraphs", "m2k_loopback.grc")
    result = json.loads(run_in_gr(BUILD, path))
    assert result["valid"], result["errors"]
    joined = " ".join(result["iio"])
    # The two shapes we claim gr-iio has, straight from GRC's own codegen.
    assert "iio.device_source(uri, 'm2k-adc', ['voltage0'], ''" in joined
    assert "16384, 1 - 1)" in joined
    assert "iio.device_sink(uri, 'm2k-dac-a'" in joined
    assert "1 - 1, False)" in joined
    assert "set_len_tag_key" in joined


@needs_gnuradio
def test_generated_block_loopback_builds(repo_root, generated_blocks):
    path = os.path.join(repo_root, "flowgraphs", "m2k_loopback_generated.grc")
    result = json.loads(run_in_gr(BUILD, path, generated_blocks))
    assert result["valid"], result["errors"]
    joined = " ".join(result["iio"])
    assert "iio.device_source(uri, 'm2k-adc'" in joined
    assert "iio.device_sink(uri, 'm2k-dac-a'" in joined


@needs_gnuradio
def test_an_untouched_dropdown_writes_nothing(repo_root, generated_blocks):
    """"Shown" must never mean "set".

    Every dropdown defaults to empty, and the make template filters those
    out, so a block that has been opened and closed writes nothing to the
    hardware. Checked in GRC's generated code, not in ours.
    """
    path = os.path.join(repo_root, "flowgraphs", "m2k_loopback_generated.grc")
    result = json.loads(run_in_gr(BUILD, path, generated_blocks))
    joined = " ".join(result["iio"])
    assert "if v]" in joined
    assert "('calibrate', '')" in joined      # present, and filtered out
    assert "'oversampling_ratio=100'" in joined   # the one we did set


@needs_gnuradio
def test_flowgraph_description_stays_single_line(repo_root):
    """GRC comments out only the first line of a description.

    A multi-line one drops the rest into the generated file as bare Python,
    which does not parse. Found the hard way; pinned so it stays fixed.
    """
    import yaml
    for name in ("m2k_loopback.grc", "m2k_loopback_generated.grc"):
        with open(os.path.join(repo_root, "flowgraphs", name)) as handle:
            doc = yaml.safe_load(handle)
        description = doc["options"]["parameters"].get("description", "")
        assert "\n" not in description.strip(), name
