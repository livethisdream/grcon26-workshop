"""One write per interval, without losing the last one.

A setpoint on a slider produces a stream of values, and each one here is
a round trip to the board over the network. Ten a second is plenty; two
hundred is a queue that arrives after the hand has stopped moving.

Dropping the ones that come too fast is easy and wrong in exactly one
place, which is the place that matters: the last value of a drag is the
one that decides where the rail ends up, and it is the one most likely
to be inside the interval and dropped. So a value that arrives too soon
is not discarded, it is held, and a timer applies it when the interval
is up. Anything arriving in the meantime replaces it.

Nothing here knows what it is applying. It imports threading and time
and nothing else, so the policy can be tested with a fake clock on a
machine with no GNU Radio, no libiio and no board.
"""

import threading
import time


def _daemon_timer(delay, function):
    """A one-shot timer that will not keep the interpreter alive."""
    timer = threading.Timer(delay, function)
    timer.daemon = True
    timer.start()
    return timer


class rate_limiter(object):
    """Call `apply` with the newest value, at most once per interval.

    `clock` and `timer` exist to be replaced in tests. `timer` is called
    as timer(delay_seconds, function) and must return something with a
    .cancel().
    """

    def __init__(self, apply, min_interval, clock=time.monotonic,
                 timer=_daemon_timer):
        self._apply = apply
        self._interval = float(min_interval)
        self._clock = clock
        self._timer_factory = timer
        # Re-entrant because flush() takes the lock and the timer's
        # callback is flush().
        self._lock = threading.RLock()
        self._last = None
        self._pending = None
        self._waiting = False
        self._timer = None

    def submit(self, value):
        """Offer a value. Applied now if the interval allows, else held."""
        with self._lock:
            if self._interval <= 0:
                self._apply_now(value)
                return
            now = self._clock()
            if self._last is None or (now - self._last) >= self._interval:
                self._cancel()
                self._apply_now(value)
                return
            self._pending = value
            self._waiting = True
            if self._timer is None:
                self._timer = self._timer_factory(
                    self._interval - (now - self._last), self.flush)

    def flush(self):
        """Apply whatever is being held, now. Safe with nothing held."""
        with self._lock:
            self._timer = None
            if not self._waiting:
                return
            value, self._pending, self._waiting = self._pending, None, False
            self._apply_now(value)

    def cancel(self):
        """Drop whatever is being held. Nothing further is applied."""
        with self._lock:
            self._cancel()
            self._pending, self._waiting = None, False

    # ------------------------------------------------------------ internals

    def _apply_now(self, value):
        # The timestamp is taken before the call, not after, so a slow
        # write does not push the next one further out than the interval.
        self._last = self._clock()
        self._apply(value)

    def _cancel(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
