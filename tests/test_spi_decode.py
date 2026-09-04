"""What `SpiDecoder` recovers, and what it refuses to.

These run in the ordinary test interpreter, not the borrowed gnuradio
one, because `m2k_blocks.spi_decode` imports nothing. That is the whole
reason it is a separate module from the block that wraps it.

The frames here are built from the mode 0 rules directly rather than
imported from `bench/spi_loopback.py`, which imports gnuradio. That is
inconvenient but it is also the better test: the bench script is the
thing that produced the hardware evidence, and a decoder checked
against an independent generator is checked against something.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gr-m2k"))

from m2k_blocks.spi_decode import SpiDecoder, as_text   # noqa: E402

HALF = 8                       # samples per half clock
LEAD, SETUP, TAIL, POST = 64, 8, 8, 48


def frame(word, width=8, idle=1, active=0):
    """One CS-framed transfer, as three lists of levels.

    Mode 0 by construction: the bit is put on MOSI while SCLK is low
    and held across the rising edge.
    """
    sclk, mosi, cs = [], [], []

    def emit(count, clock, data, select):
        sclk.extend([clock] * count)
        mosi.extend([data] * count)
        cs.extend([select] * count)

    bits = [(word >> (width - 1 - i)) & 1 for i in range(width)]
    emit(LEAD, 0, 0, idle)
    emit(SETUP, 0, bits[0], active)
    for bit in bits:
        emit(HALF, 0, bit, active)
        emit(HALF, 1, bit, active)
    emit(TAIL, 0, 0, active)
    emit(POST, 0, 0, idle)
    return sclk, mosi, cs


def stream(words, **kwargs):
    """Several frames back to back."""
    sclk, mosi, cs = [], [], []
    for word in words:
        for whole, part in zip((sclk, mosi, cs), frame(word, **kwargs)):
            whole.extend(part)
    return sclk, mosi, cs


def decode(words, decoder=None, **kwargs):
    """Generator and decoder agree on the word width unless told not to."""
    if decoder is None:
        decoder = SpiDecoder(bits_per_word=kwargs.get("width", 8))
    return decoder.feed(*stream(words, **kwargs))


# ------------------------------------------------------- the happy path

def test_one_byte_comes_back():
    assert decode([0xA5]) == [0xA5]


def test_every_byte_there_is():
    """256 frames in one call, which is the bench capture's shape."""
    assert decode(list(range(256))) == list(range(256))


def test_msb_first():
    """0x80 and 0x01 are the same byte read in opposite directions."""
    assert decode([0x80, 0x01]) == [0x80, 0x01]


# --------------------------------------------- state across work() calls

@pytest.mark.parametrize("size", [1, 7, 64, 777, 4096])
def test_chunking_changes_nothing(size):
    """A work() call is handed whatever is in the buffer.

    777 in particular divides nothing -- not the frame, not the half
    clock, not the byte -- so boundaries land mid-bit.
    """
    sclk, mosi, cs = stream(list(range(256)))
    decoder = SpiDecoder()
    got = []
    for start in range(0, len(sclk), size):
        stop = start + size
        got += decoder.feed(sclk[start:stop], mosi[start:stop],
                            cs[start:stop])
    assert got == list(range(256))


def test_a_boundary_mid_byte_holds_the_partial_word():
    """Split inside a frame: nothing from the first half, byte from the
    second. The bits do not arrive twice and do not go missing."""
    sclk, mosi, cs = stream([0xA5])
    cut = LEAD + SETUP + 5 * 2 * HALF          # five bits in
    decoder = SpiDecoder()
    assert decoder.feed(sclk[:cut], mosi[:cut], cs[:cut]) == []
    assert decoder.feed(sclk[cut:], mosi[cut:], cs[cut:]) == [0xA5]


# ------------------------------------------------------------- the framing

def test_a_capture_starting_mid_frame_drops_that_frame():
    """The bits before the cut are gone, so the byte would be wrong.

    This is the failure the arming rule exists to prevent: without it
    the remaining bits shift into the next frame's and every byte after
    is plausible and wrong.
    """
    sclk, mosi, cs = stream([0xA5, 0x3C, 0xFF])
    cut = LEAD + SETUP + 3 * 2 * HALF
    assert SpiDecoder().feed(sclk[cut:], mosi[cut:], cs[cut:]) == [0x3C, 0xFF]


def test_clock_with_cs_released_is_not_data():
    """Idle clock activity between transfers must be ignored."""
    sclk, mosi, cs = stream([0xA5])
    noise = ([0, 1] * 32, [1] * 64, [1] * 64)      # 32 edges, CS high
    for whole, part in zip((sclk, mosi, cs), noise):
        whole.extend(part)
    for whole, part in zip((sclk, mosi, cs), stream([0x5A])):
        whole.extend(part)
    assert SpiDecoder().feed(sclk, mosi, cs) == [0xA5, 0x5A]


def test_bits_left_over_at_cs_release_are_discarded():
    """Six clocks and then CS goes away: no byte, and no carry-over."""
    sclk, mosi, cs = stream([0xA5])
    short = LEAD + SETUP + 6 * 2 * HALF
    truncated = [part[:short] + [1] * POST
                 for part in (sclk, mosi, cs)]
    decoder = SpiDecoder()
    assert decoder.feed(*truncated) == []
    assert decoder.frames == 1
    assert decoder.partial_bits == 6
    assert decoder.feed(*stream([0x3C])) == [0x3C]


def test_frames_are_counted():
    decoder = SpiDecoder()
    decode([0x00, 0x11, 0x22], decoder=decoder)
    assert decoder.frames == 3
    assert decoder.partial_bits == 0


def test_reset_forgets_the_frame_it_had_seen():
    decoder = SpiDecoder()
    decode([0xA5], decoder=decoder)
    decoder.reset()
    assert decoder.frames == 0
    sclk, mosi, cs = stream([0x3C])
    cut = LEAD + SETUP + 2 * 2 * HALF
    assert decoder.feed(sclk[cut:], mosi[cut:], cs[cut:]) == []


# ---------------------------------------------------------- the options

def test_sixteen_bit_words():
    assert decode([0xBEEF, 0x1234], width=16) == [0xBEEF, 0x1234]


def test_a_word_width_that_does_not_divide_the_frame():
    """12-bit words, which real ADCs actually use."""
    assert decode([0xABC], width=12) == [0xABC]


def test_active_high_chip_select():
    decoder = SpiDecoder(cs_active_low=False)
    assert decoder.feed(*stream([0xA5, 0x5A], idle=0, active=1)) \
        == [0xA5, 0x5A]


def test_active_low_decoder_hears_nothing_on_an_active_high_bus():
    """Wrong polarity is silence, not garbage -- CS never falls."""
    assert SpiDecoder().feed(*stream([0xA5], idle=0, active=1)) == []


@pytest.mark.parametrize("width", [0, -1, 33])
def test_an_impossible_word_width_is_refused(width):
    with pytest.raises(ValueError, match="bits per word"):
        SpiDecoder(bits_per_word=width)


# ---------------------------------------------------------- the text
#
# What a participant reads. The bytes are the decode; this is the
# column beside them that says the loopback carried what was typed.

def test_text_is_what_was_typed():
    assert as_text(SpiDecoder().feed(*stream(b"M2K"))) == "M2K"


def test_every_printable_character_survives_the_round_trip():
    """All of them, unchanged, except the one that carries the escapes."""
    printable = bytes(range(0x20, 0x7f))
    assert as_text(SpiDecoder().feed(*stream(printable))) == \
        printable.decode("ascii").replace("\\", "\\\\")


@pytest.mark.parametrize("word,shown", [
    (0x00, "\\x00"),
    (0x0a, "\\x0a"),
    (0x1f, "\\x1f"),
    (0x7f, "\\x7f"),
    (0xff, "\\xff"),
])
def test_an_unprintable_byte_says_which_byte_it_was(word, shown):
    """Escaped, not replaced. A row of dots throws the byte away."""
    assert as_text([word]) == shown


def test_a_backslash_is_doubled():
    """Otherwise a literal backslash reads as the start of an escape."""
    assert as_text([0x5c, 0x78, 0x34, 0x31]) == "\\\\x41"


def test_nothing_renders_as_nothing():
    assert as_text([]) == ""


def test_text_and_bytes_agree_on_length_when_it_is_all_printable():
    words = SpiDecoder().feed(*stream(b"hello"))
    assert len(as_text(words)) == len(words)


# -------------------------------------------- the continuous flowgraph
#
# `m2k_spi_loopback_continuous.grc` builds its waveform out of variable
# blocks and repeats it in hardware. The interactive flowgraph next to
# it builds the same waveform in `SpiEncoder` instead, so it has no
# variables to check and is covered by tests/test_spi_encode.py.

FLOWGRAPH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "flowgraphs", "m2k_spi_loopback_continuous.grc")


def flowgraph_variables(half=None, message=None):
    """Evaluate the .grc's variable blocks, in the order GRC would.

    The flowgraph builds its waveform out of Python expressions in
    variable blocks, which means the waveform can be wrong in a way
    that only shows up on a bench. Evaluating them here is the cheapest
    place to catch it.
    """
    yaml = pytest.importorskip("yaml")
    with open(FLOWGRAPH) as handle:
        graph = yaml.safe_load(handle)
    pending = []
    for block in graph["blocks"]:
        if not block["id"].startswith("variable"):
            continue
        value = block["parameters"]["value"]
        if block["id"] == "variable_qtgui_entry":
            # An entry box holds text, not an expression: 'M2K', not "M2K".
            value = repr(value)
        if half is not None and block["name"] == "half":
            value = str(half)
        if message is not None and block["name"] == "spi_message":
            value = repr(message)
        pending.append((block["name"], value))

    # GRC stores variable blocks alphabetically, not in dependency order,
    # and works out the order itself when it generates. Doing the same by
    # sweeping until nothing new resolves is shorter than a topological
    # sort and fails just as loudly on a genuine mistake.
    namespace = {}
    while pending:
        stuck, again = None, []
        for name, value in pending:
            try:
                exec("%s = %s" % (name, value), namespace)   # noqa: S102
            except NameError as exc:
                stuck = stuck or exc
                again.append((name, value))
        if len(again) == len(pending):
            raise AssertionError(
                "%s: cannot resolve %s (%s)"
                % (os.path.basename(FLOWGRAPH),
                   ", ".join(n for n, _ in again), stuck))
        pending = again
    return namespace


def test_the_flowgraph_sends_the_message_it_says_it_does():
    v = flowgraph_variables()
    got = SpiDecoder().feed(v["spi_sclk"], v["spi_mosi"], v["spi_cs"])
    assert bytes(got).decode() == v["spi_message"]


def test_the_three_lists_are_one_buffer():
    """A short list would shift the others -- they are one 16-bit word."""
    v = flowgraph_variables()
    lengths = {len(v[name]) for name in ("spi_sclk", "spi_mosi", "spi_cs")}
    assert lengths == {v["frame"]}


def test_the_buffer_holds_whole_messages():
    """A cyclic buffer that ends mid-message splices it into the next."""
    v = flowgraph_variables()
    assert v["buffer_len"] % v["frame"] == 0
    assert v["buffer_len"] <= 16384


@pytest.mark.parametrize("half", [2, 4, 8, 16, 32])
def test_changing_half_changes_the_bus_speed_and_nothing_else(half):
    """The README promises this. `frame` used to be hard-coded at 256,
    which made it false for every value but 8."""
    v = flowgraph_variables(half=half)
    assert v["frame"] == 128 + 16 * half * v["spi_capacity"]
    assert len(v["spi_sclk"]) == v["frame"]
    got = SpiDecoder().feed(v["spi_sclk"], v["spi_mosi"], v["spi_cs"])
    assert bytes(got).decode() == v["spi_message"]


def test_the_frame_asserts_chip_select_exactly_once():
    """The fix section 11 forced, and the only test that would have
    caught what it was fixing.

    With CS toggling per byte, a capture that triggers on CS falling
    starts on an arbitrary byte of the message, so a continuously
    running flowgraph prints rotations -- 'M2K', then '2KM', then 'KM2'
    -- with every byte individually correct. One assertion per message
    makes the only falling edge in the frame the start of the message.
    """
    cs = flowgraph_variables()["spi_cs"]
    falling = [i for i in range(1, len(cs)) if cs[i - 1] == 1 and cs[i] == 0]
    assert len(falling) == 1, falling
    assert cs[0] == 1 and cs[-1] == 1


@pytest.mark.parametrize("message", ["", "M", "M2K", "ADALM2K"])
def test_the_frame_is_one_transaction_whatever_the_message(message):
    """One CS assertion per frame, and the frame is always the same length.

    The length matters as much as the edge count. `spi_message` is an
    entry box now, so the message changes while the sink is running --
    and the sink's buffer size is a constructor argument with no
    callback. A frame that grew with the message would stop dividing the
    buffer the moment someone typed a longer one.
    """
    v = flowgraph_variables(message=message)
    assert v["frame"] == 128 + 16 * HALF * v["spi_capacity"]
    lengths = {len(v[name]) for name in ("spi_sclk", "spi_mosi", "spi_cs")}
    assert lengths == {v["frame"]}
    cs = v["spi_cs"]
    assert sum(1 for i in range(1, len(cs))
               if cs[i - 1] == 1 and cs[i] == 0) == 1
    got = SpiDecoder().feed(v["spi_sclk"], v["spi_mosi"], v["spi_cs"])
    assert bytes(got).decode() == message


def test_a_message_too_long_for_the_frame_is_cut_not_wrapped():
    """Truncation is a short message; overflow would be a wrong one."""
    v = flowgraph_variables(message="GRCon 2026 Boulder")
    got = SpiDecoder().feed(v["spi_sclk"], v["spi_mosi"], v["spi_cs"])
    assert bytes(got).decode() == "GRCon 20"[:v["spi_capacity"]]
    assert len(v["spi_cs"]) == v["frame"]


def test_the_padding_is_idle_and_the_decoder_ignores_it():
    """A short message pads with CS high, so the pad carries no bits."""
    v = flowgraph_variables(message="M")
    assert v["spi_pad"] == 16 * HALF * (v["spi_capacity"] - 1)
    tail = v["spi_pad"]
    assert set(v["spi_cs"][-tail:]) == {1}
    assert set(v["spi_sclk"][-tail:]) == {0}
