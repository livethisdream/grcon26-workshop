"""Our SPI bus, read by a decoder nobody here wrote.

`tests/test_spi_encode.py` sends a message through `SpiEncoder` and
reads it back with `SpiDecoder`, and every one of those passes. That
proves the two halves agree with each other. It cannot prove they agree
with SPI: both were written from the same three sentences about mode 0,
and a shared misreading -- LSB first, sampling on the falling edge, CS
moving a half clock too early -- round-trips perfectly and is still
wrong on a real bus.

So the waveform goes to libsigrokdecode's `spi` decoder instead, the
one PulseView uses, written by people who have never seen this repo. If
it reads back what we queued, our mode 0 is the same mode 0 as
everyone else's.

Skipped where `sigrok-cli` is not installed, the same way the GNU Radio
tests skip. `sudo apt install sigrok-cli`.
"""

import os
import random
import re
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gr-m2k"))

from m2k_blocks.spi_decode import SpiDecoder          # noqa: E402
from m2k_blocks.spi_encode import SpiEncoder          # noqa: E402

SIGROK = shutil.which("sigrok-cli")
needs_sigrok = pytest.mark.skipif(
    SIGROK is None, reason="sigrok-cli is not installed")

# Only the time axis. The decoder works off edges, so this changes what
# the annotations are timestamped with and nothing about what they say.
RATE = 1000000


def wire(message, **kwargs):
    """The three lines `SpiEncoder` would put on the bus for `message`."""
    encoder = SpiEncoder(**kwargs)
    encoder.send(message)
    return encoder.pull(encoder.pending() + encoder.gap)


def sigrok(sclk, mosi, cs, tmp_path, cs_active_low=True, bits_per_word=8,
           **override):
    """What libsigrokdecode makes of those three lines.

    Channel names come from the CSV's own header row, which is why the
    binding below can say `clk=clk` instead of guessing at whatever
    libsigrok would have called column 0. `override` changes a decoder
    option, which only the negative control has any business doing.
    """
    path = tmp_path / "bus.csv"
    path.write_text("clk,mosi,cs\n" + "".join(
        "%d,%d,%d\n" % triple for triple in zip(sclk, mosi, cs)))

    options = {"clk": "clk", "mosi": "mosi", "cs": "cs",
               "cpol": 0, "cpha": 0, "bitorder": "msb-first",
               "wordsize": bits_per_word,
               "cs_polarity": ("active-low" if cs_active_low
                               else "active-high")}
    options.update(override)
    result = subprocess.run(
        [SIGROK,
         "-i", str(path),
         "-I", "csv:header=true:samplerate=%d" % RATE,
         "-P", "spi:" + ":".join("%s=%s" % kv for kv in options.items()),
         "-A", "spi=mosi-data"],
        capture_output=True, text=True)
    # An unknown option exits 1 and decodes nothing, which would
    # otherwise read as a quiet bus rather than as a broken command.
    assert result.returncode == 0, result.stderr[-2000:]
    return [int(word, 16)
            for word in re.findall(r"\b([0-9A-Fa-f]{2,8})\b",
                                   result.stdout.replace("spi-1:", ""))]


# ------------------------------------------------- the independent read

@needs_sigrok
def test_sigrok_reads_what_we_queued(tmp_path):
    assert sigrok(*wire(b"M2K"), tmp_path=tmp_path) == [0x4D, 0x32, 0x4B]


@needs_sigrok
def test_every_byte_there_is(tmp_path):
    """All 256 in one transaction, which is the longest thing we send."""
    assert sigrok(*wire(list(range(256))), tmp_path=tmp_path) == \
        list(range(256))


@needs_sigrok
@pytest.mark.parametrize("half", [2, 4, 8, 16])
def test_bus_speed_does_not_change_the_reading(half, tmp_path):
    """A decoder with a frame length baked in would pass at one speed."""
    assert sigrok(*wire(b"M2K", half=half),
                  tmp_path=tmp_path) == [0x4D, 0x32, 0x4B]


@needs_sigrok
def test_active_high_chip_select(tmp_path):
    lines = wire(b"M2K", cs_active_low=False)
    assert sigrok(*lines, tmp_path=tmp_path,
                  cs_active_low=False) == [0x4D, 0x32, 0x4B]


@needs_sigrok
@pytest.mark.parametrize("width,words", [
    (12, [0x123, 0xABC]),
    (16, [0x0141, 0xFFFF]),
])
def test_wider_words(width, words, tmp_path):
    assert sigrok(*wire(words, bits_per_word=width),
                  bits_per_word=width, tmp_path=tmp_path) == words


@needs_sigrok
def test_the_idle_before_and_after_is_not_data(tmp_path):
    """Long quiet stretches either side, and still exactly three bytes.

    Ours drops them because CS is released. If sigrok found bytes in
    there, the levels we call idle are not idle.
    """
    assert sigrok(*wire(b"M2K", lead=4096, gap=4096),
                  tmp_path=tmp_path) == [0x4D, 0x32, 0x4B]


# ------------------------------------------- the two decoders compared
#
# Above, sigrok checks what we PUT on the wire. These check what we
# READ off it, on samples both decoders see. Our encoder's waveform is
# regular by construction -- every half clock exactly `half` samples --
# so `jittered` builds one it would never produce, which is where a
# decoder that quietly counts samples instead of watching edges falls
# over and an independent reading is worth having.

def jittered(words, seed=0, width=8):
    """A mode 0 frame whose clock periods are all different lengths."""
    rng = random.Random(seed)
    sclk, mosi, cs = [], [], []

    def emit(count, clock, data, select):
        sclk.extend([clock] * count)
        mosi.extend([data] * count)
        cs.extend([select] * count)

    emit(rng.randint(8, 64), 0, 0, 1)
    emit(rng.randint(2, 20), 0, 0, 0)
    for word in words:
        for i in range(width):
            bit = (word >> (width - 1 - i)) & 1
            emit(rng.randint(2, 25), 0, bit, 0)     # settle while low
            emit(rng.randint(2, 25), 1, bit, 0)     # held across the edge
    emit(rng.randint(2, 20), 0, 0, 0)
    emit(rng.randint(8, 64), 0, 0, 1)
    return sclk, mosi, cs


@needs_sigrok
@pytest.mark.parametrize("message", [b"M2K", b"a", bytes(range(64))])
def test_both_decoders_read_the_same_bytes(message, tmp_path):
    lines = wire(message)
    assert SpiDecoder().feed(*lines) == sigrok(*lines, tmp_path=tmp_path)


@needs_sigrok
@pytest.mark.parametrize("seed", range(6))
def test_they_agree_on_a_clock_that_is_not_regular(seed, tmp_path):
    """No two half clocks the same length, and still the same bytes."""
    words = [0x4D, 0x32, 0x4B, 0x00, 0xFF, 0xA5]
    lines = jittered(words, seed=seed)
    assert SpiDecoder().feed(*lines) == words
    assert sigrok(*lines, tmp_path=tmp_path) == words


# ------------------------------------------------ the negative control

@needs_sigrok
@pytest.mark.parametrize("wrong", [
    {"bitorder": "lsb-first"},
    {"cpha": 1},
    {"cpol": 1},
    {"cs_polarity": "active-high"},
])
def test_the_wrong_settings_read_something_else(wrong, tmp_path):
    """A harness that cannot fail has not checked anything.

    Each of these is one of the misreadings the round-trip tests are
    blind to. If sigrok returned our bytes whatever it was told, the
    tests above would be measuring the encoder against nothing.
    """
    assert sigrok(*wire(b"M2K"), tmp_path=tmp_path, **wrong) != \
        [0x4D, 0x32, 0x4B]
