"""End-to-end runs of both tools against the fixture. No hardware."""

import os
import subprocess
import sys

import pytest

FIXTURE = "fixtures/m2k-snapshot.json"
GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "golden", "channels-m2k-adc.txt")


def run(repo_root, *args):
    result = subprocess.run([sys.executable] + list(args), cwd=repo_root,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.parametrize("verb", [
    [],                       # defaults to --channels
    ["--channels"],
    ["--tree"],
    ["--unknown"],
    ["--glossary"],
    ["--channels", "--verbose"],
])
def test_every_verb_runs(repo_root, verb):
    out = run(repo_root, "iio_explain.py", FIXTURE, *verb)
    assert out.strip()


def test_attr_lookup_by_bare_and_full_name(repo_root):
    bare = run(repo_root, "iio_explain.py", FIXTURE, "--attr", "raw",
               "--device", "m2k-adc", "--limit", "1")
    full = run(repo_root, "iio_explain.py", FIXTURE, "--attr",
               "in_voltage0_raw", "--device", "m2k-adc", "--limit", "1")
    assert "in_voltage0_raw" in bare
    assert "in_voltage0_raw" in full


def test_attr_shows_the_conversion_worked_out(repo_root):
    out = run(repo_root, "iio_explain.py", FIXTURE, "--attr", "raw",
              "--device", "m2k-adc", "--limit", "1")
    assert "(1234 + -2048) * 0.0625" in out
    assert "-50.875 mV" in out
    assert "-0.050875 V" in out


def test_attr_quotes_the_kernel(repo_root):
    out = run(repo_root, "iio_explain.py", FIXTURE, "--attr", "scale",
              "--device", "m2k-adc", "--limit", "1")
    assert "The kernel's own words" in out
    assert "Linux ABI sysfs-bus-iio" in out


def test_unverified_overlay_entries_are_always_marked(repo_root):
    out = run(repo_root, "iio_explain.py", FIXTURE, "--channels")
    # The ad9963 note is unverified and must never render as plain fact.
    assert "UNVERIFIED" in out


def test_missing_attr_exits_nonzero(repo_root):
    result = subprocess.run(
        [sys.executable, "iio_explain.py", FIXTURE, "--attr", "no_such_attr"],
        cwd=repo_root, capture_output=True, text=True)
    assert result.returncode == 1


def test_reads_from_stdin(repo_root):
    with open(os.path.join(repo_root, FIXTURE)) as handle:
        result = subprocess.run(
            [sys.executable, "iio_explain.py", "-", "--unknown"],
            cwd=repo_root, stdin=handle, capture_output=True, text=True)
    assert result.returncode == 0
    assert "Coverage" in result.stdout


def test_glossary_is_markdown_with_the_central_rule(repo_root):
    out = run(repo_root, "iio_explain.py", FIXTURE, "--glossary")
    assert "# Reading IIO attribute names" in out
    assert "real value = (raw + offset) * scale" in out
    assert "| `voltage` |" in out


def test_discover_still_runs_without_libiio(repo_root):
    """The friendly libiio message must survive, just later than before."""
    result = subprocess.run([sys.executable, "iio_discover.py", "--summary"],
                            cwd=repo_root, capture_output=True, text=True)
    assert result.returncode != 0
    assert "libiio Python bindings" in (result.stdout + result.stderr)


def test_channels_output_matches_golden(repo_root):
    out = run(repo_root, "iio_explain.py", FIXTURE, "--channels",
              "--device", "m2k-adc")
    if os.environ.get("REGEN_GOLDEN"):
        with open(GOLDEN, "w") as handle:
            handle.write(out)
    with open(GOLDEN) as handle:
        assert out == handle.read(), \
            "output changed; review it, then REGEN_GOLDEN=1 pytest to accept"


def test_scan_hint_names_the_m2k_default_address():
    """--scan cannot discover a fixed-address board; it must say so."""
    import iio_discover

    hint = iio_discover.uri_hint()
    assert "ip:192.168.2.1" in hint
    assert "usb:" in hint
    # The reason matters more than the address -- it is why people give up.
    assert "does not advertise" in hint
