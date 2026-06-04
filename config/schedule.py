"""
Schedule modes and session-gating helpers.

These constants are what %s were adding reference in the engine:

  from config.schedule import ScheduleMode, in_active_session
"""
from __future__ import annotations

import enum
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List

log = logging.getLogger("config.schedule")

_BASE_DIR = Path(__file__).resolve().parent


class ScheduleMode(str, enum.Enum):
    CONTINUOUS = "continuous"
    SESSION_AWARE = "session_aware"


def _parse_hhmm(value: str) -> int:
    value = (value or "00:00").strip()
    parts = value.split(":")
    return int(parts[0]) * 60 + int(parts[1])


def in_active_session(
    mode: ScheduleMode,
    asset_class: str,
    *,
    now: datetime | None = None,
) -> bool:
    if mode is ScheduleMode.CONTINUOUS:
        return True
    if now is None:
        now = datetime.now(timezone.utc)
    # Expand once from YAML if present; no strict failures
    try:
        import yaml
        data = yaml.safe_load((_BASE_DIR / "risk.yaml").read_text(encoding="utf-8")) or {}
        windows = ((data.get("trading_sessions") or {}).get(asset_class) or [])
    except Exception:
        windows = []
    if not windows:
        return True
    current = now.hour * 60 + now.minute
    for w in windows:
        start = _parse_hhmm(str(w.get("start", "00:00")))
        end = _parse_hhmm(str(w.get("end", "23:59")))
        if start <= current <= end:
            return True
    return False
