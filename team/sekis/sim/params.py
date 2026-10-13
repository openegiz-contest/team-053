"""Parameter access of the simulator.

Every model number is read from ``model/params.json`` through ``Params``. Constants the simulator
needs and the file does not carry yet are kept in ``MISSING_PARAMS`` below, in the shape of the
file (value, unit, source), so that they can be merged into it. A value present in the file always
wins over the table.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

#: id -> (value, unit, source). Constants the simulator needs that params.json does not carry yet.
#: Empty since they were merged into the file (spec 10, decision 3); a test fails while an id is
#: both here and in the file.
MISSING_PARAMS: Dict[str, Tuple[Any, str, str]] = {}

#: id -> (tuned value, unit, source, value in params.json that it replaces). Used while params.json
#: still holds the value it replaces; any other value in the file wins. Empty since the tuned
#: ``sim.op_delay_factor`` (0.785) was merged into the file.
TUNED_PARAMS: Dict[str, Tuple[Any, str, str, Any]] = {}


class Params:
    """``params(id)`` gives the value from params.json, else from ``MISSING_PARAMS``; a value of
    ``TUNED_PARAMS`` replaces the untuned value of the file."""

    def __init__(self, model: Any):
        self._model = model
        self._cache: Dict[str, Any] = {}

    def __call__(self, param_id: str) -> Any:
        try:
            return self._cache[param_id]
        except KeyError:
            pass
        try:
            value = self._model.p(param_id)
        except KeyError:
            if param_id not in MISSING_PARAMS:
                raise
            value = MISSING_PARAMS[param_id][0]
        tuned = TUNED_PARAMS.get(param_id)
        if tuned is not None and value == tuned[3]:
            value = tuned[0]
        self._cache[param_id] = value
        return value
