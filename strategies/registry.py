"""
Strategy registry — import all strategies here so main.py
can discover/enable/disable them via a single dropdown in the dashboard.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from strategies.base import BaseStrategy, StrategyMeta

# Registry populated by decorator
_REGISTRY: dict[str, type] = {}


def _states_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config" / "strategy_states.json"


_STATES: dict[str, dict] = {}


def register(cls: type) -> type:
    """Decorator: auto-registers a strategy class."""
    name = cls.meta.name
    _REGISTRY[name] = cls
    # Apply persisted state if we've already loaded states file
    state = _STATES.get(name)
    if state is not None and "enabled" in state:
        cls.meta.enabled = state["enabled"]
    return cls


def get_registered() -> dict[str, type]:
    return dict(_REGISTRY)


def get_enabled() -> dict[str, type]:
    return {k: v for k, v in _REGISTRY.items() if v.meta.enabled}


def load_strategy(name: str) -> "BaseStrategy":
    """Instantiate a registered strategy by name."""
    cls = _REGISTRY.get(name)
    if cls is None:
        raise KeyError(f"Strategy '{name}' not found. Registered: {list(_REGISTRY)}")
    return cls()


def _load_states() -> dict[str, dict]:
    global _STATES
    path = _states_path()
    if path.exists():
        try:
            _STATES = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            _STATES = {}
    return _STATES


def _save_states() -> None:
    path = _states_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    states = {
        name: {"enabled": cls.meta.enabled}
        for name, cls in _REGISTRY.items()
    }
    path.write_text(
        json.dumps(states, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def set_state(name: str, enabled: bool) -> bool:
    """Toggle a strategy's enabled state — returns True if found."""
    cls = _REGISTRY.get(name)
    if cls is None:
        return False
    cls.meta.enabled = enabled
    _STATES[name] = {"enabled": enabled}
    _save_states()
    return True


# Auto-import all strategy submodule files at startup
_STRATEGIES_DIR = Path(__file__).parent


def _discover():
    for pkg in ("gold", "forex", "crypto", "stocks"):
        pkg_dir = _STRATEGIES_DIR / pkg
        if not pkg_dir.is_dir():
            continue
        for py in pkg_dir.glob("*.py"):
            if py.stem.startswith("_"):
                continue
            mod_name = f"strategies.{pkg}.{py.stem}"
            importlib.import_module(mod_name)


_load_states()
_discover()
