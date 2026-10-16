"""Expansion Advisor (spec 3.4): the decision module of the Sekisovskoye twin.

``engine`` holds the pure logic (constraint loop, ladder, projection, effects, report),
``horizon`` the ten-year horizon of a target (measures with lead times, trucks as the mine
deepens, tailings stages, the year the target holds to, the ten-year economics after tax),
``wording`` the Russian text, ``service`` the process that reads the twins, publishes the
advisor twin and serves ``/report`` and ``/apply``.
"""

from .engine import Advisor, Inputs, Plan, Step

__all__ = ["Advisor", "Inputs", "Plan", "Step"]
