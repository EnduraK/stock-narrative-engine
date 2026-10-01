# Stock Narrative Engine — Work Log & Continuity

*Read this first when resuming. Generated 1 Oct 2026 from repo state (no git history present).*

## What it is
An automated engine that generates stock "narrative" research reports on a schedule — pulls data, builds the analysis/narrative, writes report files, and runs unattended via Windows Task Scheduler.

## Where it lives
- **Engine (live):** `Desktop\💻 Tech & Dev Projects\stock_narrative_engine`
- **Report output:** `OneDrive\StockReports` (the engine writes reports here)
- **Finance docs & notes:** `Desktop\Projects\Stock_Narrative_Engine_Finance`
- **Performance tracker:** `Desktop\SNE Performance Tracker.xlsx`

## Structure
- `main.py` — entry point / orchestrator
- `backtest.py` — backtesting
- `monitor.py` — monitoring
- `config.py` — configuration
- `src/` — engine modules
- `reports/` — generated reports
- `run_engine.bat` + `setup_scheduler.ps1` — scheduled run (Task Scheduler)
- `sne_current_run.log` — latest run log
- `requirements.txt`

## State & notes
- ⚠️ **No git repo — this project isn't version-controlled.** That means there's no history and nothing protecting uncommitted state against a move/reinstall. Recommend `git init` + first commit as the first action. (I can set that up.)
- Check `sne_current_run.log` and the Performance Tracker for the latest run status and date.
- Deployment is local/scheduled (setup_scheduler.ps1 → run_engine.bat), output to OneDrive.

## Where to continue
1. **Put it under git** — first priority, for safety + history.
2. Review the latest run log / tracker for current performance.
3. _(add your next priorities here)_
