"""Deep dictionary merge utility preserving nested defaults over partial overrides."""

from copy import deepcopy
from typing import Any


def deep_merge(base: dict[str, Any] | None, override: dict[str, Any] | None) -> dict[str, Any]:
    """Recursively merge override onto base; nested dicts merge, scalars/lists/None replace."""
    result: dict[str, Any] = deepcopy(base) if isinstance(base, dict) else {}
    if not isinstance(override, dict):
        return result
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], val)
        else:
            result[key] = deepcopy(val)
    return result
