"""SPI mode 0, built into three streams of levels, with nothing imported.

The mirror of `spi_decode`, and kept clear of GNU Radio and numpy for
the same reason: this is the part that has to be right, and it should
be testable on a machine with no gnuradio, no libiio, no board and no
third-party packages at all. A message that survives a round trip
through both halves of this pair has been checked against something.

Mode 0 only, MSB first, CS framing -- the same three rules the decoder
reads, written the other way round. The bit goes on MOSI while the
clock is low and is held across the rising edge, so the receiver
samples a settled line.

One frame is one whole transaction: CS falls once, every byte of the
message is clocked out back to back, CS rises once. Not per byte. A
triggered capture arms on the falling edge, and if that edge came once
per byte the capture would start on an arbitrary byte of the message.
Section 11 of docs/bench-checklist.md has what that looked like.

The encoder is pulled from in chunks and keeps its state between them,
because a GNU Radio work() call asks for whatever fits in the buffer
and a frame does not care where that lands. Between messages it hands
back idle -- clock low, data low, CS released -- for as long as anyone
asks, so the block downstream of it never starves.

`align` is the one thing here that exists because of the hardware. A
non-cyclic digital sink hands the board one DMA buffer at a time and
the board is not guaranteed to join them seamlessly, so a frame lying
across a buffer boundary can be torn in the middle. Nothing downstream
can see where those boundaries are -- but this encoder's sample index
IS the sink's position in its buffer, because every sample it produces
goes into the sink in order and the sink pushes every `buffer_size` of
them. So it can hold a queued frame until the next boundary and start
it there. Costs up to one buffer of latency, which nobody clicking a
button will notice.
"""


class SpiEncoder:
    """Streaming SPI mode 0 encoder. Queue bytes, pull levels.

        enc = SpiEncoder()
        enc.send([0xA5])
        sclk, mosi, cs = enc.pull(1024)

    `pull` always returns exactly the number of samples asked for. What
    is not part of a frame is idle, which is a real level on a real pin
    and not padding: the bus rests there.
    """

    def __init__(self, bits_per_word=8, cs_active_low=True, half=8,
                 lead=64, setup=8, tail=8, gap=48, align=0):
        bits_per_word = int(bits_per_word)
        if bits_per_word < 1 or bits_per_word > 32:
            raise ValueError("bits per word must be between 1 and 32, got %r"
                             % bits_per_word)
        half = int(half)
        if half < 1:
            raise ValueError("samples per half clock must be at least 1, "
                             "got %r" % half)
        for name, value in (("lead", lead), ("setup", setup),
                            ("tail", tail), ("gap", gap)):
            if int(value) < 0:
                raise ValueError("%s cannot be negative, got %r"
                                 % (name, value))
        self.bits_per_word = bits_per_word
        self.cs_active_low = bool(cs_active_low)
        self.half = half
        self.lead = int(lead)
        self.setup = int(setup)
        self.tail = int(tail)
        self.gap = int(gap)
        if int(align) < 0:
            raise ValueError("align cannot be negative, got %r" % align)
        self.align = int(align)
        self.reset()

    # ------------------------------------------------------------ levels

    @property
    def _idle_cs(self):
        return 1 if self.cs_active_low else 0

    @property
    def _active_cs(self):
        return 0 if self.cs_active_low else 1

    def frame_len(self, count):
        """Samples one frame of `count` words occupies, gap included."""
        return (self.lead + self.setup
                + 2 * self.half * self.bits_per_word * count
                + self.tail + self.gap)

    # ------------------------------------------------------------- state

    def reset(self):
        """Forget the queue and any frame in progress.

        Called at construction and again at flowgraph start, so a second
        run does not resume half a message from the first.
        """
        self._pending = []         # frames built and not yet handed out
        self._started = False      # a frame is part-way out
        self.produced = 0          # samples pulled since the last reset
        self.sent = 0              # complete frames pulled, for reporting

    def send(self, message):
        """Queue one frame carrying `message`, a sequence of word values.

        An empty message is not a frame and is dropped -- CS asserting
        with nothing clocked through it is a decoder's silence, not a
        message, and queueing it would only add a pause.
        """
        words = [int(word) for word in message]
        limit = 1 << self.bits_per_word
        for word in words:
            if word < 0 or word >= limit:
                raise ValueError("%r does not fit in %d bits"
                                 % (word, self.bits_per_word))
        if not words:
            return 0
        self._pending.append(self._frame(words))
        return self.frame_len(len(words))

    def pending(self):
        """Samples still queued and not yet pulled."""
        return sum(len(frame[0]) for frame in self._pending)

    # ------------------------------------------------------------ output

    def pull(self, count):
        """Exactly `count` samples of each line: frames first, then idle.

        A frame already under way always continues. A new one starts
        only where `align` allows, and the space before that is idle.
        """
        count = int(count)
        if count < 0:
            raise ValueError("cannot pull %r samples" % count)
        sclk, mosi, cs = [], [], []

        def idle(n):
            sclk.extend([0] * n)
            mosi.extend([0] * n)
            cs.extend([self._idle_cs] * n)

        while len(sclk) < count:
            want = count - len(sclk)
            if not self._pending:
                idle(want)
                break
            if not self._started:
                skip = self._to_boundary(self.produced + len(sclk))
                if skip:
                    idle(min(skip, want))
                    continue
            frame = self._pending[0]
            take = min(len(frame[0]), want)
            for whole, line in zip((sclk, mosi, cs), frame):
                whole.extend(line[:take])
            if take == len(frame[0]):
                self._pending.pop(0)
                self._started = False
                self.sent += 1
            else:
                self._pending[0] = tuple(line[take:] for line in frame)
                self._started = True

        self.produced += count
        return sclk, mosi, cs

    def _to_boundary(self, position):
        """Idle samples before a frame may start at `position`."""
        if not self.align:
            return 0
        return -position % self.align

    # ------------------------------------------------------------- frame

    def _frame(self, words):
        """One whole transaction as three equal-length lists."""
        sclk, mosi, cs = [], [], []

        def emit(count, clock, data, select):
            sclk.extend([clock] * count)
            mosi.extend([data] * count)
            cs.extend([select] * count)

        width = self.bits_per_word
        bits = [(word >> (width - 1 - i)) & 1
                for word in words for i in range(width)]
        idle, active = self._idle_cs, self._active_cs

        emit(self.lead, 0, 0, idle)             # bus at rest
        emit(self.setup, 0, bits[0], active)    # CS low, first bit presented
        for bit in bits:
            emit(self.half, 0, bit, active)     # MOSI settles, clock low
            emit(self.half, 1, bit, active)     # receiver samples here
        emit(self.tail, 0, 0, active)
        emit(self.gap, 0, 0, idle)              # CS released, bus at rest
        return sclk, mosi, cs
