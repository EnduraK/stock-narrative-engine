"""
Market data layer — pulls price, momentum and fundamental context via yfinance.

Functions return lightweight dicts so the AI layer can embed them in prompts
without dealing with pandas DataFrames.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import yfinance as yf

from .sectors import SECTOR_ETFS, SECTOR_TICKERS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Single-ticker snapshot
# ---------------------------------------------------------------------------
def get_ticker_snapshot(symbol: str) -> Dict[str, Any]:
    """
    Return a compact snapshot for one ticker:
      price, 1d/5d/1m/3m change %, 52-week range, volume ratio, market cap.
    """
    try:
        tk = yf.Ticker(symbol)
        info = tk.fast_info   # lighter than .info

        price        = _safe(info, "last_price")
        prev_close   = _safe(info, "previous_close")
        week52_high  = _safe(info, "year_high")
        week52_low   = _safe(info, "year_low")
        market_cap   = _safe(info, "market_cap")
        volume       = _safe(info, "three_month_average_volume")

        change_1d = _pct(price, prev_close)

        # Historical closes for multi-period returns
        hist = tk.history(period="3mo", auto_adjust=True)
        if not hist.empty:
            closes = hist["Close"]
            change_5d  = _pct(closes.iloc[-1], closes.iloc[-6])  if len(closes) > 5  else None
            change_1m  = _pct(closes.iloc[-1], closes.iloc[-22]) if len(closes) > 21 else None
            change_3m  = _pct(closes.iloc[-1], closes.iloc[0])
        else:
            change_5d = change_1m = change_3m = None

        return {
            "symbol":       symbol,
            "price":        round(price, 2)       if price        else None,
            "change_1d":    round(change_1d, 2)   if change_1d    else None,
            "change_5d":    round(change_5d, 2)   if change_5d    else None,
            "change_1m":    round(change_1m, 2)   if change_1m    else None,
            "change_3m":    round(change_3m, 2)   if change_3m    else None,
            "week52_high":  round(week52_high, 2) if week52_high  else None,
            "week52_low":   round(week52_low, 2)  if week52_low   else None,
            "market_cap_b": round(market_cap / 1e9, 1) if market_cap else None,
            "avg_volume_3m": int(volume)          if volume       else None,
        }

    except Exception as exc:
        logger.warning("Snapshot failed for %s: %s", symbol, exc)
        return {"symbol": symbol, "error": str(exc)}


# ---------------------------------------------------------------------------
# Sector-level summary
# ---------------------------------------------------------------------------
def get_sector_summary(sector: str, top_n: int = 5) -> Dict[str, Any]:
    """
    Pull price snapshots for the top-N tickers in a sector plus the ETF proxy.
    Returns a structured dict suitable for embedding in an AI prompt.
    """
    tickers = SECTOR_TICKERS.get(sector, [])[:top_n]
    etf     = SECTOR_ETFS.get(sector)

    snapshots = [get_ticker_snapshot(t) for t in tickers]
    etf_data  = get_ticker_snapshot(etf) if etf else None

    # Aggregate momentum score (average 1-month return of constituents)
    valid_1m = [s["change_1m"] for s in snapshots if s.get("change_1m") is not None]
    momentum = round(sum(valid_1m) / len(valid_1m), 2) if valid_1m else None

    return {
        "sector":           sector,
        "etf":              etf_data,
        "top_constituents": snapshots,
        "avg_1m_momentum":  momentum,
        "momentum_label":   _momentum_label(momentum),
        "timestamp":        datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Broad market snapshot (SPY, QQQ, VIX, TLT, DXY)
# ---------------------------------------------------------------------------
def get_macro_context() -> Dict[str, Any]:
    """Return a quick macro picture for the AI to anchor narratives."""
    symbols = {
        "SPY":  "S&P 500",
        "QQQ":  "Nasdaq 100",
        "IWM":  "Russell 2000",
        "TLT":  "Long Treasury (20y+)",
        "GLD":  "Gold",
        "^VIX": "VIX (Fear Index)",
        "DX-Y.NYB": "US Dollar Index",
    }

    macro: Dict[str, Any] = {}
    for sym, label in symbols.items():
        snap = get_ticker_snapshot(sym)
        snap["label"] = label
        macro[sym] = snap

    return macro


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _safe(obj: Any, attr: str) -> Optional[float]:
    try:
        val = getattr(obj, attr, None)
        return float(val) if val is not None else None
    except Exception:
        return None


def _pct(current: Optional[float], base: Optional[float]) -> Optional[float]:
    if current is None or base is None or base == 0:
        return None
    return ((current - base) / abs(base)) * 100


def _momentum_label(pct: Optional[float]) -> str:
    if pct is None:
        return "unknown"
    if pct >= 10:
        return "strong bull"
    if pct >= 3:
        return "mild bull"
    if pct >= -3:
        return "neutral"
    if pct >= -10:
        return "mild bear"
    return "strong bear"
