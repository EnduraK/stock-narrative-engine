#!/usr/bin/env python3
"""
Hormuz Volatility Monitor — Real-Time Trigger Engine
=====================================================
Polls live prices every 30 seconds and fires alerts when:

  1. VIX PANIC      — VIX crosses the panic threshold (default: 25)
  2. OIL SPIKE      — Brent Crude rises >2% intraday
  3. NASDAQ DROP    — QQQ falls >1.5% intraday
  4. DIVERGENCE     — Oil gain minus Nasdaq gain exceeds threshold (stagflation signal)

On trigger: desktop pop-up + Slack message + logged to monitor_log.json

Usage
-----
  python monitor.py                   # run with .env defaults
  python monitor.py --vix 30          # custom VIX panic level
  python monitor.py --poll 60         # poll every 60 seconds
  python monitor.py --once            # single snapshot and exit (no loop)

⚠️  For research/monitoring purposes only. Not financial advice.
    Leveraged instruments (OILU, NRGU, FNGD, SQQQ) carry extreme risk —
    they are designed for intraday use only and decay rapidly if held overnight.
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent))
from config import get_config

log = logging.getLogger("monitor")


# ---------------------------------------------------------------------------
# Colour codes for terminal output
# ---------------------------------------------------------------------------
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"


# ---------------------------------------------------------------------------
# Ticker groups — driven by .env, with sensible defaults
# ---------------------------------------------------------------------------
DEFAULT_LONG  = ["USO", "XLE", "FRO", "TK", "NAT", "DHT", "ITA", "OXY", "CVX"]
DEFAULT_SHORT = ["PSQ", "SQQQ", "FNGD"]
DEFAULT_MACRO = ["^VIX", "BZ=F", "QQQ", "SPY", "DX-Y.NYB"]

TICKER_LABELS = {
    "USO":      "US Oil Fund",
    "XLE":      "Energy ETF",
    "FRO":      "Frontline (Tanker)",
    "TK":       "Teekay (Tanker)",
    "NAT":      "Nordic American Tankers",
    "DHT":      "DHT Holdings (Tanker)",
    "OILU":     "3x Long Oil ETN ⚠️",
    "ITA":      "Defense ETF",
    "OXY":      "Occidental Petroleum",
    "CVX":      "Chevron",
    "PSQ":      "Short QQQ (inverse Nasdaq)",
    "SQQQ":     "3x Short QQQ ⚠️",
    "FNGD":     "3x Short FANG+ ⚠️",
    "^VIX":     "VIX Fear Index",
    "BZ=F":     "Brent Crude Futures",
    "QQQ":      "Nasdaq 100 ETF",
    "SPY":      "S&P 500 ETF",
    "DX-Y.NYB": "US Dollar Index",
}


# ---------------------------------------------------------------------------
# Price snapshot
# ---------------------------------------------------------------------------
def get_snapshot(tickers: List[str]) -> Dict[str, Dict]:
    """Pull current price, prev close, and intraday % change for all tickers."""
    snapshots: Dict[str, Dict] = {}

    for ticker in tickers:
        try:
            tk   = yf.Ticker(ticker)
            info = tk.fast_info
            price      = getattr(info, "last_price",      None)
            prev_close = getattr(info, "previous_close",  None)
            day_high   = getattr(info, "day_high",        None)
            day_low    = getattr(info, "day_low",         None)

            change_pct = None
            if price and prev_close and prev_close != 0:
                change_pct = ((price - prev_close) / prev_close) * 100

            snapshots[ticker] = {
                "price":      round(price, 2)      if price      else None,
                "prev_close": round(prev_close, 2) if prev_close else None,
                "change_pct": round(change_pct, 3) if change_pct is not None else None,
                "day_high":   round(day_high, 2)   if day_high   else None,
                "day_low":    round(day_low, 2)    if day_low    else None,
                "label":      TICKER_LABELS.get(ticker, ticker),
                "ts":         datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            log.debug("Snapshot failed for %s: %s", ticker, exc)
            snapshots[ticker] = {"price": None, "change_pct": None,
                                  "label": TICKER_LABELS.get(ticker, ticker)}

    return snapshots


# ---------------------------------------------------------------------------
# Trigger evaluation
# ---------------------------------------------------------------------------
def evaluate_triggers(
    snap: Dict[str, Dict],
    vix_level: float,
    oil_spike_pct: float,
    nasdaq_drop_pct: float,
    divergence_threshold: float,
) -> List[Dict[str, Any]]:
    """Return a list of triggered alert dicts."""
    alerts = []

    # ── VIX PANIC ──────────────────────────────────────────────────────
    vix_data = snap.get("^VIX", {})
    vix_price = vix_data.get("price")
    if vix_price and vix_price >= vix_level:
        alerts.append({
            "type":    "VIX_PANIC",
            "level":   "🔴 PANIC",
            "message": f"VIX = {vix_price:.1f} ≥ {vix_level} — Market in fear mode",
            "value":   vix_price,
            "ticker":  "^VIX",
        })

    # ── OIL SPIKE ──────────────────────────────────────────────────────
    brent = snap.get("BZ=F", {})
    brent_chg = brent.get("change_pct")
    if brent_chg and brent_chg >= oil_spike_pct:
        alerts.append({
            "type":    "OIL_SPIKE",
            "level":   "🛢️  OIL SPIKE",
            "message": f"Brent Crude +{brent_chg:.2f}% intraday — Energy surge active",
            "value":   brent_chg,
            "ticker":  "BZ=F",
        })

    # ── NASDAQ DROP ────────────────────────────────────────────────────
    qqq = snap.get("QQQ", {})
    qqq_chg = qqq.get("change_pct")
    if qqq_chg and qqq_chg <= nasdaq_drop_pct:
        alerts.append({
            "type":    "NASDAQ_DROP",
            "level":   "📉 TECH SELL-OFF",
            "message": f"QQQ {qqq_chg:.2f}% — Nasdaq under pressure",
            "value":   qqq_chg,
            "ticker":  "QQQ",
        })

    # ── HORMUZ DIVERGENCE (Oil up + Nasdaq down simultaneously) ────────
    if brent_chg is not None and qqq_chg is not None:
        divergence = brent_chg - qqq_chg   # e.g. oil +3%, QQQ -1.5% → divergence = 4.5
        if divergence >= divergence_threshold:
            alerts.append({
                "type":    "HORMUZ_DIVERGENCE",
                "level":   "⚡ DIVERGENCE ACTIVE",
                "message": (
                    f"Hormuz Divergence = {divergence:.2f} "
                    f"(Brent {brent_chg:+.2f}% / QQQ {qqq_chg:+.2f}%) — "
                    f"Stagflation signal firing. Instruments: USO/XLE long, PSQ/SQQQ short tech."
                ),
                "value":   divergence,
                "ticker":  "DIVERGENCE",
            })

    return alerts


# ---------------------------------------------------------------------------
# Terminal display
# ---------------------------------------------------------------------------
def print_dashboard(
    snap: Dict[str, Dict],
    alerts: List[Dict],
    long_tickers: List[str],
    short_tickers: List[str],
    macro_tickers: List[str],
    poll_seconds: int,
    run_count: int,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    os.system("cls" if os.name == "nt" else "clear")

    print(f"{BOLD}{CYAN}{'='*70}{RESET}")
    print(f"{BOLD}  ⚡ HORMUZ VOLATILITY MONITOR   {DIM}{now}  run #{run_count}{RESET}")
    print(f"{BOLD}{CYAN}{'='*70}{RESET}\n")

    def fmt_row(ticker, data):
        price = data.get("price")
        chg   = data.get("change_pct")
        label = data.get("label", ticker)
        if price is None:
            return f"  {ticker:<14} {DIM}unavailable{RESET}"
        color  = GREEN if (chg or 0) >= 0 else RED
        arrow  = "▲" if (chg or 0) >= 0 else "▼"
        chg_str = f"{color}{arrow}{abs(chg):.2f}%{RESET}" if chg is not None else ""
        return f"  {BOLD}{ticker:<10}{RESET}  ${price:<9.2f}  {chg_str:<20}  {DIM}{label}{RESET}"

    print(f"{YELLOW}── MACRO GAUGES ──────────────────────────────────────────{RESET}")
    for t in macro_tickers:
        print(fmt_row(t, snap.get(t, {})))

    print(f"\n{GREEN}── LONG PLAYS (Energy / Tankers / Defense) ───────────────{RESET}")
    for t in long_tickers:
        if t in snap:
            print(fmt_row(t, snap[t]))

    print(f"\n{RED}── SHORT / HEDGE PLAYS ───────────────────────────────────{RESET}")
    for t in short_tickers:
        if t in snap:
            print(fmt_row(t, snap[t]))

    if alerts:
        print(f"\n{BOLD}{RED}{'!'*70}{RESET}")
        for a in alerts:
            print(f"  {BOLD}{a['level']}{RESET}  {a['message']}")
        print(f"{BOLD}{RED}{'!'*70}{RESET}")
    else:
        print(f"\n  {DIM}No triggers fired. Monitoring... (refreshes every {poll_seconds}s){RESET}")

    print(f"\n  {DIM}⚠️  For research only. Not financial advice.  Ctrl+C to stop.{RESET}")


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
def notify_desktop(title: str, message: str) -> None:
    try:
        from plyer import notification
        notification.notify(
            title=title, message=message[:256],
            app_name="Hormuz Monitor", timeout=12,
        )
    except Exception:
        pass


def notify_slack(webhook_url: str, alerts: List[Dict], snap: Dict) -> None:
    if not webhook_url or not alerts:
        return
    try:
        import requests
        brent_chg = (snap.get("BZ=F") or {}).get("change_pct")
        qqq_chg   = (snap.get("QQQ")  or {}).get("change_pct")
        vix       = (snap.get("^VIX") or {}).get("price")

        blocks = [{
            "type": "header",
            "text": {"type": "plain_text", "text": "⚡ Hormuz Monitor — Trigger Fired"}
        }, {
            "type": "section",
            "text": {"type": "mrkdwn", "text":
                f"*VIX:* {vix or '?'}  |  *Brent:* {f'{brent_chg:+.2f}%' if brent_chg else '?'}  |  "
                f"*QQQ:* {f'{qqq_chg:+.2f}%' if qqq_chg else '?'}"
            }
        }]
        for a in alerts:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{a['level']}* — {a['message']}"}
            })
        requests.post(webhook_url, json={"blocks": blocks}, timeout=8)
    except Exception as exc:
        log.debug("Slack notify failed: %s", exc)


# ---------------------------------------------------------------------------
# Log triggered events to JSON file
# ---------------------------------------------------------------------------
def log_trigger(alerts: List[Dict], snap: Dict, log_path: str = "reports/monitor_log.json") -> None:
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "alerts":    alerts,
        "snapshot":  {k: {"price": v.get("price"), "change_pct": v.get("change_pct")}
                      for k, v in snap.items()},
    }
    existing = []
    p = Path(log_path)
    if p.exists():
        try:
            existing = json.loads(p.read_text())
        except Exception:
            pass
    existing.append(entry)
    p.write_text(json.dumps(existing[-500:], indent=2))   # keep last 500 events


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Hormuz Volatility Monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--vix",        type=float, default=None, help="VIX panic threshold")
    p.add_argument("--oil-spike",  type=float, default=None, help="Brent spike %% threshold")
    p.add_argument("--qqq-drop",   type=float, default=None, help="QQQ drop %% threshold")
    p.add_argument("--divergence", type=float, default=None, help="Divergence threshold")
    p.add_argument("--poll",       type=int,   default=None, help="Poll interval seconds")
    p.add_argument("--once",       action="store_true",      help="Single snapshot, then exit")
    p.add_argument("--verbose",    action="store_true")
    return p


def main() -> int:
    parser = build_parser()
    args   = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    cfg = get_config()

    def _envfloat(key: str, default: str) -> float:
        """Read a float env var, safely stripping any inline comments."""
        raw = os.getenv(key, default)
        raw = raw.split("#")[0].strip()   # strip "# comment" suffix
        return float(raw)

    def _envint(key: str, default: str) -> int:
        raw = os.getenv(key, default)
        raw = raw.split("#")[0].strip()
        return int(raw)

    # ── Load config from .env with CLI overrides ──────────────────────
    vix_level    = args.vix        or _envfloat("VIX_PANIC_LEVEL",      "25")
    oil_spike    = args.oil_spike  or _envfloat("OIL_SPIKE_PCT",        "2.0")
    nasdaq_drop  = args.qqq_drop   or _envfloat("NASDAQ_DROP_PCT",      "-1.5")
    divergence_t = args.divergence or _envfloat("DIVERGENCE_THRESHOLD", "3.5")
    poll_secs    = args.poll       or _envint("MONITOR_POLL_SECONDS",   "30")

    # Parse ticker lists from .env
    long_tickers  = [t.strip() for t in os.getenv("MONITOR_LONG",  ",".join(DEFAULT_LONG)).split(",")  if t.strip()]
    short_tickers = [t.strip() for t in os.getenv("MONITOR_SHORT", ",".join(DEFAULT_SHORT)).split(",") if t.strip()]
    macro_tickers = [t.strip() for t in os.getenv("MONITOR_MACRO", ",".join(DEFAULT_MACRO)).split(",") if t.strip()]

    all_tickers  = list(dict.fromkeys(macro_tickers + long_tickers + short_tickers))
    slack_url    = cfg.slack_webhook_url
    desktop_on   = cfg.desktop_notify

    print(f"{BOLD}Starting Hormuz Volatility Monitor...{RESET}")
    print(f"  Watching {len(all_tickers)} tickers  |  VIX trigger: {vix_level}  |  "
          f"Oil spike: +{oil_spike}%  |  QQQ drop: {nasdaq_drop}%  |  "
          f"Divergence: {divergence_t}  |  Poll: {poll_secs}s\n")

    run_count       = 0
    last_alert_hash = ""

    while True:
        run_count += 1
        snap   = get_snapshot(all_tickers)
        alerts = evaluate_triggers(snap, vix_level, oil_spike, nasdaq_drop, divergence_t)

        print_dashboard(snap, alerts, long_tickers, short_tickers, macro_tickers, poll_secs, run_count)

        # Only fire notifications if alerts are new (avoid repeated pings)
        alert_hash = str(sorted(a["type"] for a in alerts))
        if alerts and alert_hash != last_alert_hash:
            last_alert_hash = alert_hash
            log_trigger(alerts, snap)

            top = alerts[0]
            if desktop_on:
                notify_desktop(f"⚡ {top['level']}", top["message"])
            if slack_url:
                notify_slack(slack_url, alerts, snap)

            print(f"\n  {BOLD}[Trigger logged to reports/monitor_log.json]{RESET}")

        if args.once:
            break

        time.sleep(poll_secs)

    return 0


if __name__ == "__main__":
    sys.exit(main())
