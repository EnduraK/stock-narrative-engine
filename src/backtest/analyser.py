"""
Backtest performance analyser.

Takes the enriched trade-return rows from loader.py and computes:
  - Overall win rate and average alpha at each horizon
  - Per-politician performance ranking
  - Per-sector performance
  - Bipartisan signal quality
  - Sharpe-like ratio (return / volatility of returns)
  - Best and worst individual trades
  - "Follow score" — who is most worth tracking going forward
"""

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

HORIZONS = ["1d", "5d", "1m", "3m", "6m"]


# ---------------------------------------------------------------------------
# Top-level analysis entry point
# ---------------------------------------------------------------------------
def analyse(trade_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Run the full performance analysis on a list of trade-return dicts
    (as produced by loader.build_trade_returns).

    Returns a structured results dict suitable for reporting.
    """
    if not trade_rows:
        return {"error": "no trades to analyse"}

    return {
        "summary":          _overall_summary(trade_rows),
        "by_politician":    _by_politician(trade_rows),
        "by_sector":        _by_sector(trade_rows),
        "by_party":         _by_party(trade_rows),
        "best_trades":      _best_trades(trade_rows, n=10),
        "worst_trades":     _worst_trades(trade_rows, n=5),
        "follow_scores":    _follow_scores(trade_rows),
        "trade_count":      len(trade_rows),
    }


# ---------------------------------------------------------------------------
# Overall summary
# ---------------------------------------------------------------------------
def _overall_summary(rows: List[Dict]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {"total_trades": len(rows)}

    for h in HORIZONS:
        alphas  = [r[f"alpha_{h}"] for r in rows if r.get(f"alpha_{h}") is not None]
        returns = [r[f"return_{h}"] for r in rows if r.get(f"return_{h}") is not None]
        beats   = [r[f"beat_spy_{h}"] for r in rows if r.get(f"beat_spy_{h}") is not None]

        if not alphas:
            continue

        avg_alpha  = _mean(alphas)
        avg_return = _mean(returns) if returns else None
        win_rate   = sum(1 for b in beats if b) / len(beats) if beats else None
        sharpe     = _sharpe(alphas)

        summary[h] = {
            "avg_return_pct":   round(avg_return, 2) if avg_return else None,
            "avg_alpha_pct":    round(avg_alpha, 2),
            "win_rate":         round(win_rate, 3) if win_rate else None,
            "win_rate_pct":     f"{win_rate*100:.1f}%" if win_rate else "N/A",
            "sharpe_ratio":     round(sharpe, 2) if sharpe else None,
            "sample_size":      len(alphas),
        }

    return summary


# ---------------------------------------------------------------------------
# By politician
# ---------------------------------------------------------------------------
def _by_politician(rows: List[Dict]) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict]] = {}
    for r in rows:
        p = r["politician"]
        groups.setdefault(p, []).append(r)

    results = []
    for politician, trades in groups.items():
        entry: Dict[str, Any] = {
            "politician":    politician,
            "party":         trades[0]["party"],
            "chamber":       trades[0]["chamber"],
            "is_watchlist":  trades[0]["is_watchlist"],
            "trade_count":   len(trades),
            "tickers":       list({t["ticker"] for t in trades}),
        }

        for h in ["1m", "3m"]:   # focus on medium-term for politician ranking
            alphas = [t[f"alpha_{h}"] for t in trades if t.get(f"alpha_{h}") is not None]
            beats  = [t[f"beat_spy_{h}"] for t in trades if t.get(f"beat_spy_{h}") is not None]
            if alphas:
                entry[f"avg_alpha_{h}"]  = round(_mean(alphas), 2)
                entry[f"win_rate_{h}"]   = round(sum(beats) / len(beats), 3) if beats else None

        # Composite "follow score" 0-100
        entry["follow_score"] = _calc_follow_score(trades)
        results.append(entry)

    # Sort by 1-month alpha descending
    results.sort(key=lambda x: x.get("avg_alpha_1m", -999), reverse=True)
    return results[:20]


# ---------------------------------------------------------------------------
# By sector
# ---------------------------------------------------------------------------
def _by_sector(rows: List[Dict]) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict]] = {}
    for r in rows:
        groups.setdefault(r["sector"], []).append(r)

    results = []
    for sector, trades in groups.items():
        entry: Dict[str, Any] = {
            "sector":      sector,
            "trade_count": len(trades),
        }
        for h in HORIZONS:
            alphas = [t[f"alpha_{h}"] for t in trades if t.get(f"alpha_{h}") is not None]
            beats  = [t[f"beat_spy_{h}"] for t in trades if t.get(f"beat_spy_{h}") is not None]
            if alphas:
                entry[f"avg_alpha_{h}"] = round(_mean(alphas), 2)
                entry[f"win_rate_{h}"]  = round(sum(beats) / len(beats), 3) if beats else None
        results.append(entry)

    results.sort(key=lambda x: x.get("avg_alpha_1m", -999), reverse=True)
    return results


# ---------------------------------------------------------------------------
# By party
# ---------------------------------------------------------------------------
def _by_party(rows: List[Dict]) -> Dict[str, Any]:
    dem_trades = [r for r in rows if "D" in r.get("party", "")]
    rep_trades = [r for r in rows if "R" in r.get("party", "")]

    result: Dict[str, Any] = {}
    for label, trades in [("Democrat", dem_trades), ("Republican", rep_trades)]:
        entry: Dict[str, Any] = {"trade_count": len(trades)}
        for h in ["1m", "3m"]:
            alphas = [t[f"alpha_{h}"] for t in trades if t.get(f"alpha_{h}") is not None]
            beats  = [t[f"beat_spy_{h}"] for t in trades if t.get(f"beat_spy_{h}") is not None]
            if alphas:
                entry[f"avg_alpha_{h}"]  = round(_mean(alphas), 2)
                entry[f"win_rate_{h}"]   = round(sum(beats)/len(beats), 3) if beats else None
        result[label] = entry

    # Bipartisan trades (tickers bought by both parties)
    dem_tickers = {r["ticker"] for r in dem_trades}
    rep_tickers = {r["ticker"] for r in rep_trades}
    bipartisan_tickers = dem_tickers & rep_tickers
    bipartisan_rows = [r for r in rows if r["ticker"] in bipartisan_tickers]

    bp: Dict[str, Any] = {"tickers": list(bipartisan_tickers), "trade_count": len(bipartisan_rows)}
    for h in ["1m", "3m"]:
        alphas = [t[f"alpha_{h}"] for t in bipartisan_rows if t.get(f"alpha_{h}") is not None]
        if alphas:
            bp[f"avg_alpha_{h}"] = round(_mean(alphas), 2)
    result["Bipartisan"] = bp

    return result


# ---------------------------------------------------------------------------
# Best / worst individual trades
# ---------------------------------------------------------------------------
def _best_trades(rows: List[Dict], n: int = 10) -> List[Dict]:
    valid = [r for r in rows if r.get("alpha_1m") is not None]
    valid.sort(key=lambda x: x["alpha_1m"], reverse=True)
    return [_trade_summary(r) for r in valid[:n]]


def _worst_trades(rows: List[Dict], n: int = 5) -> List[Dict]:
    valid = [r for r in rows if r.get("alpha_1m") is not None]
    valid.sort(key=lambda x: x["alpha_1m"])
    return [_trade_summary(r) for r in valid[:n]]


def _trade_summary(r: Dict) -> Dict:
    return {
        "politician":       r["politician"],
        "ticker":           r["ticker"],
        "sector":           r["sector"],
        "disclosure_date":  r["disclosure_date"],
        "amount_range":     f"${r['amount_min']:,.0f}–${r['amount_max']:,.0f}",
        "return_1m":        r.get("return_1m"),
        "alpha_1m":         r.get("alpha_1m"),
        "return_3m":        r.get("return_3m"),
        "alpha_3m":         r.get("alpha_3m"),
    }


# ---------------------------------------------------------------------------
# Follow scores — who is most worth tracking?
# ---------------------------------------------------------------------------
def _follow_scores(rows: List[Dict]) -> List[Dict[str, Any]]:
    """
    Rank politicians by a composite follow score (0–100) that rewards:
      - High average alpha at 1m and 3m
      - High win rate
      - Larger trade amounts (more conviction)
      - More trades (larger sample)
    """
    groups: Dict[str, List[Dict]] = {}
    for r in rows:
        groups.setdefault(r["politician"], []).append(r)

    scores = []
    for pol, trades in groups.items():
        score = _calc_follow_score(trades)
        scores.append({
            "politician":   pol,
            "party":        trades[0]["party"],
            "chamber":      trades[0]["chamber"],
            "is_watchlist": trades[0]["is_watchlist"],
            "trade_count":  len(trades),
            "follow_score": score,
            "verdict":      _follow_verdict(score),
        })

    scores.sort(key=lambda x: x["follow_score"], reverse=True)
    return scores[:15]


def _calc_follow_score(trades: List[Dict]) -> float:
    """Composite 0-100 follow score."""
    score = 0.0

    # Alpha component (max 40 pts)
    alphas_1m = [t["alpha_1m"] for t in trades if t.get("alpha_1m") is not None]
    if alphas_1m:
        avg_alpha = _mean(alphas_1m)
        score += min(40.0, max(0.0, avg_alpha * 4))

    # Win rate component (max 30 pts)
    beats = [t["beat_spy_1m"] for t in trades if t.get("beat_spy_1m") is not None]
    if beats:
        win_rate = sum(beats) / len(beats)
        score += win_rate * 30

    # Sample size component (max 15 pts — more trades = more reliable)
    score += min(15.0, len(trades) * 1.5)

    # Amount size component (max 15 pts — bigger bets = more conviction)
    avg_amount = _mean([t["amount_min"] for t in trades])
    if avg_amount >= 100_000:
        score += 15
    elif avg_amount >= 50_000:
        score += 10
    elif avg_amount >= 15_000:
        score += 5

    return round(min(100.0, score), 1)


def _follow_verdict(score: float) -> str:
    if score >= 75:
        return "🔥 Must Follow"
    if score >= 55:
        return "✅ Worth Following"
    if score >= 35:
        return "👀 Monitor"
    return "⚪ Low Signal"


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------
def _mean(vals: List[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _std(vals: List[float]) -> float:
    if len(vals) < 2:
        return 0.0
    m = _mean(vals)
    variance = sum((v - m) ** 2 for v in vals) / (len(vals) - 1)
    return math.sqrt(variance)


def _sharpe(alphas: List[float], risk_free: float = 0.0) -> Optional[float]:
    """Simplified Sharpe: mean excess return / std dev of returns."""
    if len(alphas) < 3:
        return None
    std = _std(alphas)
    if std == 0:
        return None
    return (_mean(alphas) - risk_free) / std
