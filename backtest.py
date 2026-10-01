#!/usr/bin/env python3
"""
Stock Narrative Engine — Backtester
====================================
Tests how well congressional trade disclosures would have performed
historically against the SPY benchmark.

Usage
-----
  # Default: 1 year of data, all trades
  python backtest.py

  # 2 years, watchlist politicians only
  python backtest.py --days 730 --watchlist-only

  # Specific sector
  python backtest.py --sector technology

  # Open report in browser when done
  python backtest.py --open

Full help:
  python backtest.py --help
"""

import argparse
import logging
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import get_config
from src.backtest.loader import (
    load_trades_for_backtest,
    fetch_price_history,
    build_trade_returns,
)
from src.backtest.analyser import analyse
from src.backtest.report import export_backtest_html


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Congress Trade Backtester",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--days",           type=int,  default=365,
                   help="Days of historical trades to test (default: 365)")
    p.add_argument("--watchlist-only", action="store_true",
                   help="Only test trades from high-value watchlist politicians")
    p.add_argument("--sector",         default=None,
                   help="Filter to a specific sector (e.g. technology)")
    p.add_argument("--include-sales",  action="store_true",
                   help="Include sell trades (buys only by default)")
    p.add_argument("--min-amount",     type=float, default=1001.0,
                   help="Minimum trade amount to include (default: $1,001)")
    p.add_argument("--output-dir",     default=None,
                   help="Output directory for reports")
    p.add_argument("--open",           action="store_true",
                   help="Open HTML report in browser when done")
    p.add_argument("--verbose",        action="store_true")
    return p


def run(args) -> int:
    cfg = get_config()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger("backtest")

    output_dir = args.output_dir or cfg.output_dir
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # ── Step 1: load trades ───────────────────────────────────────────────
    log.info("Loading congressional trades (last %d days)...", args.days)
    trades = load_trades_for_backtest(
        days_back=args.days,
        min_amount=args.min_amount,
        purchases_only=not args.include_sales,
        watchlist_only=args.watchlist_only,
    )

    if not trades:
        print("\n⚠️  No trades found for backtesting.")
        print("Tips:")
        print("  • Try --days 730 for more history")
        print("  • Remove --watchlist-only to include all politicians")
        print("  • Check your internet connection (fetches from House/Senate Stock Watcher)\n")
        return 1

    if args.sector:
        trades = [t for t in trades if t.sector == args.sector]
        log.info("Filtered to sector '%s': %d trades", args.sector, len(trades))
        if not trades:
            print(f"No trades found for sector: {args.sector}")
            return 1

    # ── Step 2: fetch price history ───────────────────────────────────────
    tickers = list({t.ticker for t in trades})
    earliest = min(t.disclosure_date for t in trades)

    log.info("Downloading price history for %d tickers from %s...",
             len(tickers), earliest.strftime("%Y-%m-%d"))
    price_data = fetch_price_history(tickers, start=earliest)

    if not price_data:
        log.error("Could not fetch any price data — check yfinance and network")
        return 1

    # ── Step 3: compute returns ───────────────────────────────────────────
    log.info("Calculating returns at all horizons...")
    trade_rows = build_trade_returns(trades, price_data)

    if not trade_rows:
        log.error("No trade-return pairs computed")
        return 1

    # ── Step 4: analyse ───────────────────────────────────────────────────
    log.info("Analysing performance...")
    results = analyse(trade_rows)
    results["trade_count"] = len(trade_rows)

    # ── Step 5: print summary ─────────────────────────────────────────────
    _print_summary(results)

    # ── Step 6: export HTML ───────────────────────────────────────────────
    stem = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    tag  = f"_{args.sector}" if args.sector else ""
    tag += "_watchlist" if args.watchlist_only else ""

    html_path = export_backtest_html(
        results,
        output_path=f"{output_dir}/backtest{tag}_{stem}.html",
    )
    log.info("Report saved: %s", html_path)
    print(f"\n📄 Report: {html_path}")

    if args.open:
        webbrowser.open(f"file://{Path(html_path).resolve()}")

    return 0


def _print_summary(results: dict) -> None:
    from typing import dict
    summary = results.get("summary", {})
    follows = results.get("follow_scores", [])

    sep = "=" * 60
    print(f"\n{sep}")
    print("CONGRESS TRADE BACKTESTER — RESULTS")
    print(f"Trades analysed: {results.get('trade_count', 0)}")
    print(sep)

    print("\n── Overall Performance vs SPY ──")
    for h in ["1d", "5d", "1m", "3m", "6m"]:
        data = summary.get(h)
        if not data:
            continue
        alpha = data.get("avg_alpha_pct", 0)
        wr    = data.get("win_rate_pct", "N/A")
        sign  = "+" if alpha >= 0 else ""
        print(f"  {h:>4}  alpha={sign}{alpha:.2f}%  win_rate={wr}  n={data.get('sample_size')}")

    print("\n── Top 5 Politicians to Follow ──")
    for f in follows[:5]:
        print(f"  {f['follow_score']:>5.1f}  {f['verdict']}  {f['politician']}")

    best = results.get("best_trades", [])
    if best:
        print("\n── Best Trade ──")
        b = best[0]
        print(f"  {b['politician']} → {b['ticker']}  "
              f"1M alpha={b.get('alpha_1m',0):+.2f}%  3M alpha={b.get('alpha_3m',0):+.2f}%")

    print()


# Avoid NameError if _print_summary is called before imports settle
from typing import Dict

if __name__ == "__main__":
    parser = build_parser()
    args   = parser.parse_args()
    sys.exit(run(args))
