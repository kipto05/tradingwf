#!/usr/bin/env python3
"""Simple engine starter for use by watchdog or manual runs.

Usage:
    python launch_engine.py
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

APP_DIR = Path(r"C:\Users\hp\tradingwf")
ENGINE = APP_DIR / "main.py"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("launcher")


def main() -> int:
    cands = [
        APP_DIR / ".venv" / "Scripts" / "python.exe",
        APP_DIR / "venv" / "Scripts" / "python.exe",
        Path(sys.executable),
    ]
    py = next((p for p in cands if p.is_file()), None)
    if py is None:
        log.error("No python executable found")
        return 1
    log.info("Launching engine: %s %s", py, ENGINE)
    os.execv(py, [str(py), str(ENGINE)])


if __name__ == "__main__":
    raise SystemExit(main())
