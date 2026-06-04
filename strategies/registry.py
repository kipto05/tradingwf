"""
Strategy registry — import all strategies here so main.py
can discover/enable/disable them via a single dropdown in the dashboard.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from strategies.base import BaseStrategy, StrategyMeta

# Registry populated by decorator
_REGISTRY: dict[str, type] = {}


def register(cls: type) -> type:
    """Decorator: auto-registers a strategy class."""
    name = cls.meta.name
    _REGISTRY[name] = cls
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

_discover()
