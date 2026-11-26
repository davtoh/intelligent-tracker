"""Base configuration path resolution with opt-in demo scenario isolation."""

import os

DEFAULT_CONFIG_PATH = "configs/default.yaml"
DEMO_CONFIG_PATH = "configs/alert_demo.yaml"
_TRUTHY_VALUES = frozenset({"1", "true", "yes"})


def is_demo_scenarios_enabled() -> bool:
    """Return True when opt-in demo scenarios are enabled via IT_LOAD_DEMO_SCENARIOS."""
    raw = os.environ.get("IT_LOAD_DEMO_SCENARIOS", "")
    return raw.strip().lower() in _TRUTHY_VALUES


def resolve_base_config_path(explicit_path: str | None = None) -> str:
    """Resolve base YAML config path: explicit -> TRACKER_CONFIG -> opt-in demo -> default."""
    if explicit_path and explicit_path.strip():
        return explicit_path.strip()
    env_cfg = os.environ.get("TRACKER_CONFIG", "").strip()
    if env_cfg:
        return env_cfg
    if is_demo_scenarios_enabled():
        return DEMO_CONFIG_PATH
    return DEFAULT_CONFIG_PATH
