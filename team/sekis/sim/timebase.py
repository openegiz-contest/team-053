"""Time base of the simulator (spec 2.1): the day of two shifts and two blast windows, the
productive blocks inside a shift, and rolling means for the displayed rates.

Simulated time is counted in seconds from the epoch. A day starts with shift A at the hour
``regime.shift_a_start_h``; the epoch may lie at any time of the day. The epoch of ``sim.epoch``
lies inside the first productive block of shift A, so that a run opens on a working mine.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from typing import Callable, List, Optional, Tuple

SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400

SHIFT_A, SHIFT_B, SHIFT_BLAST = "A", "B", "blast"


class Calendar:
    """Lookup tables over the steps of one day.

    Index ``i`` is the step of the day counted from the start of shift A. For every step:
    ``shift[i]`` (``A``, ``B`` or ``blast``), ``productive[i]`` (inside a productive block),
    ``block_end_s[i]`` (second of the day at which the current productive block ends, or -1),
    ``in_blast[i]``. ``fire_steps`` are the steps at which rings are fired: the re-entry time
    before the end of each blast window, so that re-entry is complete when the next shift starts.
    """

    def __init__(self, p: Callable[[str], object], epoch: datetime):
        self.epoch = epoch
        self.step_s = int(p("sim.step_s"))
        shift_s = int(round(p("regime.shift_h") * SECONDS_PER_HOUR))
        blast_s = int(round(p("regime.blast_window_h") * SECONDS_PER_HOUR))
        allowance_s = int(round(p("regime.shift_end_allowance_h") * SECONDS_PER_HOUR))
        meal_s = int(round(p("regime.meal_h") * SECONDS_PER_HOUR))
        productive_s = int(round(p("regime.productive_h") * SECONDS_PER_HOUR))
        reentry_s = int(round(p("vent.reentry_min") * 60))
        shifts = int(p("regime.shifts"))
        if shifts * (shift_s + blast_s) != SECONDS_PER_DAY:
            raise ValueError("shifts and blast windows do not fill a day")
        if 2 * allowance_s + meal_s + productive_s > shift_s:
            raise ValueError("allowances, meal and productive time exceed the shift")
        if SECONDS_PER_DAY % self.step_s:
            raise ValueError("sim.step_s does not divide a day")
        self.shift_s = shift_s
        self.productive_shift_s = productive_s
        self.steps_per_day = SECONDS_PER_DAY // self.step_s

        tokens = (SHIFT_A, SHIFT_B) if shifts == 2 else tuple(f"S{k + 1}" for k in range(shifts))
        half = productive_s // 2
        #: (token, start, end) of each shift, seconds of the day
        self.shifts: List[Tuple[str, int, int]] = []
        #: (start, end) of each productive block
        self.blocks: List[Tuple[int, int]] = []
        #: (start, end) of each blast window
        self.blast_windows: List[Tuple[int, int]] = []
        for k, token in enumerate(tokens):
            start = k * (shift_s + blast_s)
            self.shifts.append((token, start, start + shift_s))
            first = start + allowance_s
            self.blocks.append((first, first + half))
            self.blocks.append((first + half + meal_s, first + productive_s + meal_s))
            self.blast_windows.append((start + shift_s, start + shift_s + blast_s))

        n = self.steps_per_day
        self.shift: List[str] = [SHIFT_BLAST] * n
        self.productive: List[bool] = [False] * n
        self.block_end_s: List[int] = [-1] * n
        self.in_blast: List[bool] = [False] * n
        for i in range(n):
            second = i * self.step_s
            for token, start, end in self.shifts:
                if start <= second < end:
                    self.shift[i] = token
            for start, end in self.blocks:
                if start <= second < end:
                    self.productive[i] = True
                    self.block_end_s[i] = end
            for start, end in self.blast_windows:
                if start <= second < end:
                    self.in_blast[i] = True
        self.fire_steps = frozenset((end - reentry_s) // self.step_s % n for _, end in self.blast_windows)

        # Step of the day at the epoch (0 when the epoch is the start of shift A).
        day_start_h = p("regime.shift_a_start_h")
        epoch_s = epoch.hour * SECONDS_PER_HOUR + epoch.minute * 60 + epoch.second
        offset_s = (epoch_s - int(round(day_start_h * SECONDS_PER_HOUR))) % SECONDS_PER_DAY
        self.offset_steps = offset_s // self.step_s

    def index(self, tick: int) -> int:
        """Step of the day for a simulation tick."""
        return (tick + self.offset_steps) % self.steps_per_day

    def worked_s(self, i: int) -> Tuple[int, int]:
        """Productive seconds already worked at step ``i`` of the day: (in the productive block
        that is running, in the shift that is running). Both are 0 outside a shift; the first is
        0 outside a productive block."""
        second = i * self.step_s
        for _, shift_start, shift_end in self.shifts:
            if shift_start <= second < shift_end:
                blocks = [(start, end) for start, end in self.blocks if shift_start <= start < shift_end]
                in_block = sum(second - start for start, end in blocks if start <= second < end)
                in_shift = sum(min(second, end) - start for start, end in blocks if start < second)
                return in_block, in_shift
        return 0, 0

    def iso(self, t_s: float) -> str:
        """ISO 8601 clock for a simulated time."""
        return (self.epoch + timedelta(seconds=int(t_s))).isoformat(timespec="seconds")


def parse_epoch(value: object) -> datetime:
    """Epoch from an ISO 8601 string or a ``datetime``."""
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


class Rolling:
    """Rolling sum over a time window, kept in buckets.

    ``add(amount)`` books an amount now, ``tick(dt_s)`` moves time on. ``per_hour()`` is the mean
    rate over the window, ``total()`` the amount over a full window at that rate. ``prefill``
    (amount per hour) starts the window as if that rate had held before the epoch.
    """

    __slots__ = ("bucket_s", "window_s", "_full", "_sum", "_cur", "_elapsed")

    def __init__(self, window_s: float, bucket_s: float, prefill: Optional[float] = None):
        self.bucket_s = float(bucket_s)
        self.window_s = float(window_s)
        size = max(1, int(round(window_s / bucket_s)) - 1)
        self._full: deque = deque(maxlen=size)
        self._sum = 0.0
        self._cur = 0.0
        self._elapsed = 0.0
        if prefill is not None:
            amount = prefill * self.bucket_s / SECONDS_PER_HOUR
            for _ in range(size):
                self._full.append(amount)
            self._sum = amount * size

    def add(self, amount: float) -> None:
        self._cur += amount

    def tick(self, dt_s: float) -> None:
        self._elapsed += dt_s
        if self._elapsed >= self.bucket_s:
            if len(self._full) == self._full.maxlen:
                self._sum -= self._full[0]
            self._full.append(self._cur)
            self._sum += self._cur
            self._cur = 0.0
            self._elapsed = 0.0

    def per_hour(self) -> float:
        covered = len(self._full) * self.bucket_s + self._elapsed
        value = (self._sum + self._cur) / max(covered, self.bucket_s) * SECONDS_PER_HOUR
        return value if value > 0.0 else 0.0

    def total(self) -> float:
        return self.per_hour() * self.window_s / SECONDS_PER_HOUR
