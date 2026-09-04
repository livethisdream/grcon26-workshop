"""What `SpiEncoder` puts on the wire, checked by reading it back.

Like the decoder's tests these run in the ordinary interpreter, because
`m2k_blocks.spi_encode` imports nothing. Most of them go through
`SpiDecoder`, which is the point: the two halves were written from the
same three rules and a message that survives the round trip has been
checked against an independent reading of them. The tests that do not
use the decoder are the ones about shape -- lengths, idle, alignment --
which the decoder is deliberately blind to.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gr-m2k"))

from m2k_blocks.spi_decode import SpiDecoder          # noqa: E402
from m2k_blocks.spi_encode import SpiEncoder          # noqa: E402


def roundtrip(message, chunk=None, encoder=None, decoder=None, **kwargs):
    """Queue `message`, pull it all back, and decode what came out."""
    encoder = encoder or SpiEncoder(**kwargs)
    decoder = decoder or SpiDecoder(
        bits_per_word=kwargs.get("bits_per_word", 8),
        cs_active_low=kwargs.get("cs_active_low", True))
    encoder.send(message)
    total = encoder.pending() + 2 * encoder.frame_len(1)
    got = []
    for _ in range(0, total, chunk or total):
        got += decoder.feed(*encoder.pull(chunk or total))
    return got


# ------------------------------------------------------- the happy path

def test_one_byte_comes_back():
    assert roundtrip([0xA5]) == [0xA5]


def test_every_byte_there_is():
    """One frame carrying all 256, which is the longest thing we send."""
    assert roundtrip(list(range(256))) == list(range(256))


def test_msb_first():
    """0x80 and 0x01 are the same byte clocked in opposite directions."""
    assert roundtrip([0x80, 0x01]) == [0x80, 0x01]


def test_text_survives():
    assert bytes(roundtrip(b"ADALM2000")) == b"ADALM2000"


# ------------------------------------------------- state across pulls

@pytest.mark.parametrize("chunk", [1, 7, 64, 777, 4096])
def test_chunking_changes_nothing(chunk):
    """A work() call gets whatever fits in the buffer.

    777 divides nothing here -- not the frame, not the half clock, not
    the byte -- so the boundaries land mid-bit.
    """
    assert bytes(roundtrip(b"M2K", chunk=chunk)) == b"M2K"


def test_pull_always_returns_what_was_asked_for():
    """Short output is a scheduler bug waiting to happen."""
    enc = SpiEncoder()
    enc.send([0xA5])
    for count in (0, 1, 3, 100, 512, 5000):
        lines = enc.pull(count)
        assert [len(line) for line in lines] == [count] * 3


def test_two_messages_queue_and_come_out_in_order():
    enc = SpiEncoder()
    dec = SpiDecoder()
    enc.send(b"M2K")
    enc.send(b"ADI")
    got = dec.feed(*enc.pull(enc.pending() + 512))
    assert bytes(got) == b"M2KADI"
    assert enc.sent == 2
    assert enc.pending() == 0


def test_a_message_queued_mid_pull_goes_out_next_time():
    """The GUI sends whenever the user presses Enter, not on a boundary."""
    enc = SpiEncoder()
    dec = SpiDecoder()
    assert dec.feed(*enc.pull(1000)) == []       # idle, nothing queued
    enc.send(b"M2K")
    assert bytes(dec.feed(*enc.pull(enc.pending()))) == b"M2K"


# ------------------------------------------------------------ the idle

def test_idle_before_and_after_carries_nothing():
    """Between messages the bus rests, and rest is not a frame."""
    enc = SpiEncoder()
    dec = SpiDecoder()
    assert dec.feed(*enc.pull(4096)) == []
    enc.send([0xA5])
    assert dec.feed(*enc.pull(enc.pending())) == [0xA5]
    assert dec.feed(*enc.pull(4096)) == []
    assert dec.frames == 1


def test_idle_is_clock_low_data_low_chip_select_released():
    sclk, mosi, cs = SpiEncoder().pull(256)
    assert set(sclk) == {0} and set(mosi) == {0} and set(cs) == {1}


def test_active_high_idle_is_chip_select_low():
    sclk, mosi, cs = SpiEncoder(cs_active_low=False).pull(256)
    assert set(cs) == {0}


# --------------------------------------------------------- the framing

def test_one_falling_edge_per_message_however_many_bytes():
    """The whole reason a frame is a transaction and not a byte.

    A capture triggered on CS falling starts at that edge. If CS fell
    once per byte the capture would start on an arbitrary byte and the
    decoded message would come out rotated -- see section 11 of
    docs/bench-checklist.md, which is where this was found.
    """
    for message in (b"M", b"M2K", b"ADALM2000", bytes(range(64))):
        enc = SpiEncoder()
        enc.send(message)
        _, _, cs = enc.pull(enc.pending())
        falling = [i for i in range(1, len(cs))
                   if cs[i - 1] == 1 and cs[i] == 0]
        assert len(falling) == 1, (message, falling)
        assert cs[0] == 1 and cs[-1] == 1


def test_the_frame_length_is_what_frame_len_says():
    for count in (1, 3, 8, 64):
        enc = SpiEncoder()
        assert enc.send([0] * count) == enc.frame_len(count)
        assert enc.pending() == enc.frame_len(count)


@pytest.mark.parametrize("half", [1, 2, 8, 32])
def test_half_sets_the_bus_speed_and_nothing_else(half):
    enc = SpiEncoder(half=half)
    assert enc.frame_len(3) == 128 + 16 * half * 3
    assert bytes(roundtrip(b"M2K", encoder=enc, half=half)) == b"M2K"


def test_an_empty_message_is_not_a_frame():
    """CS asserting with nothing clocked through it is silence."""
    enc = SpiEncoder()
    assert enc.send([]) == 0
    assert enc.pending() == 0
    _, _, cs = enc.pull(1024)
    assert set(cs) == {1}


# ------------------------------------------------------- the alignment

ALIGN = 2048


def frame_starts(cs, idle=1):
    """Where CS falls, which is `lead` samples into a frame."""
    return [i for i in range(1, len(cs)) if cs[i - 1] == idle
            and cs[i] != idle]


def test_a_frame_starts_only_on_an_alignment_boundary():
    """A non-cyclic sink pushes one buffer at a time and the board need
    not join them seamlessly, so a frame across a seam can be torn."""
    enc = SpiEncoder(align=ALIGN)
    cs = []
    for i in range(12):
        if i in (0, 1, 5, 9):
            enc.send(b"M2K")
        cs += enc.pull(700)[2]
    for start in frame_starts(cs):
        assert (start - enc.lead) % ALIGN == 0, start


def test_alignment_pads_with_idle_not_silence_of_a_different_kind():
    """Waiting for the boundary must look exactly like resting."""
    enc = SpiEncoder(align=ALIGN)
    enc.pull(100)                        # push the position off a boundary
    enc.send(b"M2K")
    sclk, mosi, cs = enc.pull(ALIGN - 100)
    assert set(sclk) == {0} and set(mosi) == {0} and set(cs) == {1}
    assert enc.sent == 0


def test_alignment_delays_a_message_but_never_drops_one():
    enc = SpiEncoder(align=ALIGN)
    dec = SpiDecoder()
    got = []
    for i in range(20):
        if i % 3 == 0:
            enc.send(b"M2K")
        got += dec.feed(*enc.pull(999))
    got += dec.feed(*enc.pull(4 * ALIGN))
    assert bytes(got) == b"M2K" * 7
    assert enc.sent == 7


def test_without_alignment_frames_go_out_immediately():
    enc = SpiEncoder()
    enc.pull(100)
    enc.send(b"M2K")
    _, _, cs = enc.pull(enc.pending())
    assert frame_starts(cs) == [enc.lead]


def test_reset_forgets_the_queue_and_the_position():
    """A second run must not resume half a message from the first."""
    enc = SpiEncoder(align=ALIGN)
    enc.pull(100)
    enc.send(b"M2K")
    enc.reset()
    assert enc.pending() == 0 and enc.sent == 0 and enc.produced == 0
    enc.send(b"ADI")
    _, _, cs = enc.pull(enc.pending())
    assert frame_starts(cs) == [enc.lead]


# ----------------------------------------------------------- the options

def test_sixteen_bit_words():
    assert roundtrip([0xBEEF, 0x1234], bits_per_word=16) == [0xBEEF, 0x1234]


def test_a_word_width_that_does_not_divide_the_frame():
    """12-bit words, which real ADCs actually use."""
    assert roundtrip([0xABC], bits_per_word=12) == [0xABC]


def test_active_high_chip_select():
    assert roundtrip([0xA5, 0x5A], cs_active_low=False) == [0xA5, 0x5A]


def test_an_active_low_decoder_hears_nothing_on_an_active_high_bus():
    """Wrong polarity is silence, not garbage -- CS never falls."""
    enc = SpiEncoder(cs_active_low=False)
    enc.send([0xA5])
    assert SpiDecoder().feed(*enc.pull(enc.pending())) == []


# ---------------------------------------------------------- the refusals

@pytest.mark.parametrize("width", [0, -1, 33])
def test_an_impossible_word_width_is_refused(width):
    with pytest.raises(ValueError, match="bits per word"):
        SpiEncoder(bits_per_word=width)


def test_a_half_clock_of_zero_is_refused():
    with pytest.raises(ValueError, match="half clock"):
        SpiEncoder(half=0)


@pytest.mark.parametrize("name", ["lead", "setup", "tail", "gap"])
def test_a_negative_timing_is_refused(name):
    with pytest.raises(ValueError, match=name):
        SpiEncoder(**{name: -1})


def test_a_negative_alignment_is_refused():
    with pytest.raises(ValueError, match="align"):
        SpiEncoder(align=-1)


def test_a_word_too_wide_for_the_bus_is_refused():
    with pytest.raises(ValueError, match="does not fit"):
        SpiEncoder().send([0x100])
    with pytest.raises(ValueError, match="does not fit"):
        SpiEncoder().send([-1])


def test_a_refused_message_leaves_the_queue_alone():
    """The bad word is caught before anything is built."""
    enc = SpiEncoder()
    enc.send(b"M2K")
    before = enc.pending()
    with pytest.raises(ValueError):
        enc.send([0x00, 0x1FF])
    assert enc.pending() == before


def test_pulling_a_negative_count_is_refused():
    with pytest.raises(ValueError, match="cannot pull"):
        SpiEncoder().pull(-1)
