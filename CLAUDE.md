# CLAUDE.md — tradingwf Agent Instructions

## Environment

- **OS**: Windows 11, PowerShell terminal
- **Python**: Always use the venv interpreter. Activate first or call explicitly:
  `.\venv\Scripts\python.exe` (never bare `python` or `python3`)
- **Venv location**: `.\venv\` in project root
- **metatrader5 package**: installed in venv only, not system Python
- **Working directory**: always `~\tradingwf`

---

## File Editing Rules (CRITICAL)

The `Edit`/`Update` tool fails frequently on Windows/PowerShell due to whitespace
encoding bugs. Follow this protocol strictly:

### Rule 1 — Never use the Edit tool for Python files
PowerShell corrupts indentation when Claude Code applies str_replace edits.
**Always write Python files in full using the `Write` tool.**

### Rule 2 — One Write, one file, one attempt
Do not write partial files. Write the complete file content in a single `Write` call.
Do not chain multiple Write calls to the same file in the same turn.

### Rule 3 — After every Write, verify with py_compile
```powershell
.\venv\Scripts\python.exe -c "import py_compile; py_compile.compile('filename.py', doraise=True); print('OK')"
```
If syntax fails, rewrite the full file — do not patch with Edit.

### Rule 4 — If Write also fails, use inline Python via Bash
```powershell
.\venv\Scripts\python.exe -c "
content = '''<full file content here>'''
with open('filename.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('written')
"
```

### Rule 5 — Never accumulate fix scripts
Do not create fix_indent.py, fix_main.py, fix_all.py etc. These compound the problem.
Fix the actual source file directly and delete any leftover fix scripts.

---

## Python Indentation Rules

- Use 4 spaces everywhere. No tabs. No 1-space indents.
- `if __name__ == "__main__":` block must contain ALL startup logic indented under it.
- `uvicorn.run(...)` must be the LAST statement inside `if __name__ == "__main__":`,
  after the `if/else` for `--dashboard-only`. It runs in BOTH modes.
- Correct structure for main.py tail:

```python
if __name__ == "__main__":
    # ... argparse setup ...
    engine_mode = mode_map.get(args.mode, ScheduleMode.CONTINUOUS)

    if not args.dashboard_only:
        engine.mode = engine_mode
        engine.poll_interval = args.interval
        try:
            engine.init_mt5(...)
        except Exception as exc:
            log.error("MT5 init failed (%s) -- dashboard will still start", exc)
        try:
            engine.start()
        except Exception as exc:
            log.error("Engine start failed (%s)", exc)
    else:
        log.info("Dashboard-only mode -- skipping MT5 connection")

    import uvicorn
    uvicorn.run("dashboard.app:app", host="127.0.0.1", port=8000, log_level="info")
```

---

## Project Architecture

```
tradingwf/
├── main.py                  # Engine entrypoint + uvicorn launcher
├── config/
│   └── schedule.py          # ScheduleMode, in_active_session()
├── execution/
│   ├── mt5_adapter.py       # Live MT5 adapter (requires metatrader5 pkg)
│   ├── mock_mt5.py          # MockMT5Adapter for offline dev/testing
│   ├── order_manager.py     # OrderManager — executes signals, logs trades
│   └── risk_manager.py      # RiskManager — position sizing, session sync
├── strategies/
│   └── registry.py          # get_enabled() → {name: StrategyClass}
├── dashboard/
│   └── app.py               # FastAPI dashboard app
├── logs/
│   ├── trades.csv           # Trade log (source of truth for recent trades)
│   ├── engine_heartbeat     # Written every loop cycle (float timestamp)
│   └── last_balance.txt     # Latest account balance (written by adapter)
└── venv/                    # Project virtualenv
```

## Key Invariants

- `trades.csv` is the source of truth for recent trades in the dashboard.
  A trade appearing there but NOT in MT5 terminal is a MockMT5 artifact.
  Check `adapter.__class__.__name__` — if `MockMT5Adapter`, all trades are fake.
- `engine_heartbeat` timestamp must be < 120s old for dashboard to show "Connected".
- `last_balance.txt` is updated by the live adapter on each sync; MockMT5 writes 1000.0.
- All 8 strategies are enabled via `strategy.config.active = True` in the registry.
  Dashboard "Developing" badge means `config.active` is False for that strategy.
- The dashboard reads open positions from `/api/open-positions` (live MT5 query),
  NOT from trades.csv.

---

## Running the Engine

```powershell
# Full engine + dashboard (requires MT5 terminal open and logged in)
.\venv\Scripts\python.exe main.py --login 12345678 --password yourpass --server JustMarkets-Live

# Dashboard only (no MT5 connection needed)
.\venv\Scripts\python.exe main.py --dashboard-only

# Session-aware mode (only trades during market hours)
.\venv\Scripts\python.exe main.py --mode session_aware --login 12345678 --password yourpass --server JustMarkets-Live
```

Dashboard always runs at: http://127.0.0.1:8000

---

## Debugging Checklist

Before making any code changes, verify:
1. `.\venv\Scripts\python.exe -m py_compile main.py` — must pass with no output
2. `.\venv\Scripts\python.exe main.py --dashboard-only` — dashboard must start
3. Check `logs\engine.log` for the last error before assuming a code bug
4. Check `logs\engine_heartbeat` timestamp — stale = engine loop crashed
5. `curl http://127.0.0.1:8000/api/stats` — verify balance source
6. `curl http://127.0.0.1:8000/api/open-positions` — verify live position count

---

## What NOT To Do

- Do NOT use `Edit`/`Update` tool on any `.py` file — it will corrupt indentation
- Do NOT run `python` or `python3` bare — always use `.\venv\Scripts\python.exe`
- Do NOT create temporary fix scripts (`fix_*.py`) — they accumulate and confuse state
- Do NOT remove emojis from `dashboard/templates/index.html` without explicit user approval
- Do NOT move `uvicorn.run()` outside of `if __name__ == "__main__":` — it will
  execute on import and break everything
- Do NOT nest `uvicorn.run()` inside the `else:` branch — the dashboard must start
  in both engine mode and dashboard-only mode
- Do NOT use system Python to run anything — metatrader5 is only in the venv
