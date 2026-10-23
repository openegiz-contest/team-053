"""Publishing plan for the twin telemetry (spec 1.1, 1.2).

``PublishPlanner`` decides which things are due at a moment of real time, from the tier of each
thing (S, M, L) and the periods of ``params.json``, and never lets more messages through than the
budget ``publish.max_msg_per_s``. It holds no sockets: the service asks ``due(now)`` and sends
``ditto_modify(...)`` for each name it gets back.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Mapping, Optional

TIER_ORDER = ("S", "M", "L")

#: Things published in the same pass as another, at the faster of their two periods: the second
#: repeats a value of the first. ``mon-volchevka.discharge_m3h`` (the outfall, tier L) and
#: ``water.discharge_m3h`` (the water balance, tier M) are one quantity, the rolling 1-hour mean
#: of the discharge to the Volchevka; published at different moments they read differently on
#: one screen while that mean moves (by 25 m3/h and more after the pumps restart on full ponds).
PUBLISHED_TOGETHER = (("water", "mon-volchevka"),)


def ditto_features(features: Mapping[str, Any]) -> Dict[str, Any]:
    """``{feature_id: value}`` in the Ditto shape ``{feature_id: {"properties": {"value": value}}}``."""
    return {fid: {"properties": {"value": value}} for fid, value in features.items()}


def ditto_modify(namespace: str, name: str, features: Mapping[str, Any]) -> Dict[str, Any]:
    """Ditto-protocol ``modify`` of all features of a thing (spec 1.1), ready for ``json.dumps``."""
    return {"topic": f"{namespace}/{name}/things/twin/commands/modify", "path": "/features",
            "value": ditto_features(features)}


def telemetry_topic(name: str) -> str:
    """MQTT topic of a thing's telemetry (spec 1.1)."""
    return f"telemetry/sekis/{name}"


class PublishPlanner:
    """Which things to publish now.

    ``scale`` multiplies every period (environment variable ``PUBLISH_SCALE`` of the service).
    Things of tier ``on_change`` (the scenario thing) are never due here; use
    ``Simulator.changed_since`` for them. Things of one tier are spread evenly over the period.
    A thing of ``PUBLISHED_TOGETHER`` is returned right after the thing it follows, in the same
    call, and never on its own.
    """

    def __init__(self, sim: Any, scale: Optional[float] = None):
        self.sim = sim
        p = sim.p
        self.scale = float(p("publish.scale_default") if scale is None else scale)
        self.budget_per_s = float(p("publish.max_msg_per_s"))
        self._periods = {"S": float(p("publish.period_fast_s")), "M": float(p("publish.period_medium_s")),
                         "L": float(p("publish.period_slow_s"))}
        self._fast_loaded = float(p("publish.period_fast_loaded_s"))
        self._fast_limit = int(p("publish.fast_units_limit"))
        self._names = [name for name, thing in sim.things.items() if thing["tier"] in TIER_ORDER]
        self._followers: Dict[str, List[str]] = {}
        for leader, follower in PUBLISHED_TOGETHER:
            if leader in self._names and follower in self._names:
                self._followers.setdefault(leader, []).append(follower)
        following = {name for names in self._followers.values() for name in names}
        #: The names with a schedule of their own: every name but the followers.
        self._scheduled = [name for name in self._names if name not in following]
        self._last: Dict[str, float] = {}
        self._sent_at: deque = deque()      # times of the names returned in the last second
        self._started = False
        self.sent = 0

    def periods(self) -> Dict[str, float]:
        """Present period of each tier in real seconds; the fast tier slows down when more than
        ``publish.fast_units_limit`` fast units are active (spec 1.2)."""
        fast_units = sum(1 for name in self._names if self.sim.tier(name) == "S")
        periods = dict(self._periods)
        if fast_units > self._fast_limit:
            periods["S"] = self._fast_loaded
        return {tier: period * self.scale for tier, period in periods.items()}

    def period(self, name: str, periods: Optional[Mapping[str, float]] = None) -> float:
        """Present publishing period of a thing in real seconds: that of its tier, or for a thing
        published together with others (``PUBLISHED_TOGETHER``) the shortest of the group's."""
        periods = periods if periods is not None else self.periods()
        for leader, followers in self._followers.items():
            if name == leader or name in followers:
                return min(periods[self.sim.tier(member)] for member in [leader] + followers)
        return periods[self.sim.tier(name)]

    def due(self, now_s: float) -> List[str]:
        """Names of the things to publish at real time ``now_s`` (seconds on any monotonic clock).

        Call it on every loop of the service. A thing is due when its tier period has passed since
        it was last due; the thing that is most periods behind comes first. No more than
        ``publish.max_msg_per_s`` names are returned within any one second; what does not fit
        stays due for the next call.
        """
        if not self._started:
            self._started = True
            self._spread(now_s)
        sent_at = self._sent_at
        while sent_at and sent_at[0] <= now_s - 1.0:
            sent_at.popleft()
        room = int(self.budget_per_s) - len(sent_at)
        periods = self.periods()
        waiting = []
        for index, name in enumerate(self._scheduled):
            period = self.period(name, periods)
            overdue = now_s - self._last[name] - period
            if overdue >= 0.0:
                waiting.append((-overdue / period, index, name, period))
        waiting.sort()
        out = []
        for _, _, name, period in waiting:
            group = [name] + self._followers.get(name, [])
            if len(group) > room:
                break                       # what does not fit stays due, in its order
            room -= len(group)
            # keep the rhythm: the next period counts from when the thing was due, unless it is
            # a whole period behind
            due_at = self._last[name] + period
            self._last[name] = due_at if now_s - due_at < period else now_s
            for member in group:
                sent_at.append(now_s)
                out.append(member)
        self.sent += len(out)
        return out

    def _spread(self, now_s: float) -> None:
        """First publishing times: things of a tier are spaced evenly over the tier's period."""
        periods = self.periods()
        by_tier: Dict[str, List[str]] = {tier: [] for tier in TIER_ORDER}
        for name in self._scheduled:
            by_tier[self.sim.tier(name)].append(name)
        for tier, names in by_tier.items():
            for index, name in enumerate(names):
                # due for the first time after index / len of a period
                self._last[name] = now_s - periods[tier] * (1.0 - index / max(1, len(names)))
