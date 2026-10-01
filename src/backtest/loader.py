"""
Backtest data loader.

Fetches historical congressional trades (up to 2 years back) and
pulls the corresponding stock price history from yfinance so we can
measure what actually happened after each disclosure.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import pandas as pd
import yfinance as yf

from ..congress.fetcher import fetch_all_congress_trades, CongressTrade

logger = logging.getLogger(__name__)

# Horizons to measure returns at (trading days after disclosure date)
RETURN_HORIZONS = {
    "1d":  1,
    "5d":  5,
    "1m":  21,
    "3m":  63,
    "6m":  126,
}

BENCHMARK = "SPY"   # S&P 500 — everything is measured relative to this


def load_trades_for_backtest(
    days_back: int = 365,
    min_amount: float = 1001.0,     # filter out tiny/trivial trades
    purchases_only: bool = True,    # buys are more predictive than sells
    watchlist_only: bool = False,
) -> List[CongressTrade]:
    """
    Pull historical congress trades ready for backtesting.
    Filters to purchases above a minimum dollar threshold by default.
    """
    logger.info("Fetching congress trades for last %d days...", days_back)
    trades = fetch_all_congress_trades(
        days_back=days_back,
        watchlist_only=watchlist_only,
    )

    if purchases_only:
        trades = [t for t in trades if t.trade_type == "purchase"]

    trades = [t for t in trades if t.amount_min >= min_amount]

    # Need at least 63 trading days (3 months) of future price data
    # so exclude trades too recent to have a meaningful horizon
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    trades = [t for t in trades if t.disclosure_date <= cutoff]

    logger.info("%d trades qualify for backtesting", len(trades))
    return trades


def fetch_price_history(
    tickers: List[str],
    start: datetime,
    end: Optional[datetime] = None,
) -> Dict[str, pd.DataFrame]:
    """
    Download OHLCV history for a list of tickers + the benchmark.
    Returns a dict of {ticker: DataFrame} with a 'Close' column.
    """
    all_tickers = list(set(tickers + [BENCHMARK]))
    end = end or datetime.now(timezone.utc)

    # Add buffer so we always have enough data
    fetch_start = start - timedelta(days=30)

    price_data: Dict[str, pd.DataFrame] = {}

    logger.info("Downloading price history for %d tickers...", len(all_tickers))

    for ticker in all_tickers:
        try:
            df = yf.download(
                ticker,
                start=fetch_start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                auto_adjust=True,
                progress=False,
            )
            if not df.empty:
                price_data[ticker] = df[["Close"]].copy()
                logger.debug("Downloaded %d rows for %s", len(df), ticker)
            else:
                logger.warning("No price data for %s", ticker)
        except Exception as exc:
            logger.warning("Price fetch failed for %s: %s", ticker, exc)

    return price_data


def get_return_at_horizon(
    price_df: pd.DataFrame,
    entry_date: datetime,
    horizon_days: int,
) -> Optional[float]:
    """
    Calculate percentage return from entry_date to entry_date + horizon_days.
    Uses the next available trading day if entry_date is a weekend/holiday.
    Returns None if insufficient data.
    """
    if price_df is None or price_df.empty:
        return None

    closes = price_df["Close"].dropna()

    # Find the first available close on or after entry_date
    entry_str = entry_date.strftime("%Y-%m-%d")
    future = closes[closes.index >= entry_str]

    if future.empty:
        return None

    entry_price = float(future.iloc[0])

    # Find close at horizon
    if len(future) <= horizon_days:
        return None

    exit_price = float(future.iloc[horizon_days])

    if entry_price == 0:
        return None

    return ((exit_price - entry_price) / entry_price) * 100


def build_trade_returns(
    trades: List[CongressTrade],
    price_data: Dict[str, pd.DataFrame],
) -> List[Dict]:
    """
    For each trade, compute returns at all horizons and benchmark-adjusted alpha.
    Returns a list of enriched trade dicts.
    """
    benchmark_df = price_data.get(BENCHMARK)
    results = []

    for trade in trades:
        ticker_df = price_data.get(trade.ticker)
        if ticker_df is None:
            continue

        # Use disclosure_date as entry (when public info is available)
        entry = trade.disclosure_date

        row = {
            "politician":       trade.politician,
            "chamber":          trade.chamber,
            "party":            trade.party,
            "ticker":           trade.ticker,
            "sector":           trade.sector,
            "trade_type":       trade.trade_type,
            "amount_min":       trade.amount_min,
            "amount_max":       trade.amount_max,
            "transaction_date": trade.transaction_date.strftime("%Y-%m-%d"),
            "disclosure_date":  trade.disclosure_date.strftime("%Y-%m-%d"),
            "days_to_disclose": trade.days_to_disclose,
            "is_watchlist":     trade.is_watchlist,
            "watchlist_weight": trade.watchlist_weight,
        }

        for label, days in RETURN_HORIZONS.items():
            ticker_ret   = get_return_at_horizon(ticker_df, entry, days)
            benchmark_ret = get_return_at_horizon(benchmark_df, entry, days) if benchmark_df is not None else None

            row[f"return_{label}"] = round(ticker_ret, 3) if ticker_ret is not None else None
            row[f"spy_{label}"]    = round(benchmark_ret, 3) if benchmark_ret is not None else None

            if ticker_ret is not None and benchmark_ret is not None:
                row[f"alpha_{label}"] = round(ticker_ret - benchmark_ret, 3)
            else:
                row[f"alpha_{label}"] = None

        # Win flags (did the trade beat SPY?)
        for label in RETURN_HORIZONS:
            alpha = row.get(f"alpha_{label}")
            row[f"beat_spy_{label}"] = (alpha > 0) if alpha is not None else None

        results.append(row)

    logger.info("Built returns for %d trades", len(results))
    return results
