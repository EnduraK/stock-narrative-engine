"""
Congress trade analyser.

Takes raw CongressTrade objects and produces:
  1. Sector-level buy/sell pressure scores
  2. Ticker-level clustering (how many politicians bought the same stock)
  3. Watchlist politician signals (high-weight buys from key names)
  4. Cross-party consensus signals (both parties buying = stronger signal)
  5. AI-powered narrative synthesis of congress trading patterns
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from .fetcher import CongressTrade
from ..ai.providers import complete

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Signal scoring weights
# ---------------------------------------------------------------------------
PURCHASE_WEIGHT  =  1.0
SALE_WEIGHT      = -0.8    # sales are less predictive than buys
WATCHLIST_BONUS  =  0.5    # added per watchlist politician
BIPARTISAN_BONUS =  0.4    # both parties buying same ticker
CLUSTER_BONUS    =  0.3    # per additional politician buying same ticker
RECENCY_DECAY    =  0.02   # score decays 2% per day of age

CONGRESS_SYSTEM_PROMPT = """You are a financial intelligence analyst specialising in
congressional trading patterns and their market implications.
You have deep knowledge of how committee assignments, pending legislation, and
regulatory environments create information asymmetry that shows up in politician trades.
Always respond with valid JSON matching the schema provided."""


# ---------------------------------------------------------------------------
# Output data structures
# ---------------------------------------------------------------------------
@dataclass
class TickerSignal:
    ticker: str
    sector: str
    net_score: float              # positive = net buy pressure
    buy_count: int
    sell_count: int
    total_traders: int
    watchlist_buyers: List[str]
    bipartisan: bool              # True if both parties are buying
    total_amount_min: float       # sum of lower-bound amounts
    total_amount_max: float       # sum of upper-bound amounts
    most_recent_trade: datetime
    trades: List[CongressTrade]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker":           self.ticker,
            "sector":           self.sector,
            "net_score":        round(self.net_score, 3),
            "buy_count":        self.buy_count,
            "sell_count":       self.sell_count,
            "total_traders":    self.total_traders,
            "watchlist_buyers": self.watchlist_buyers,
            "bipartisan":       self.bipartisan,
            "amount_range":     f"${self.total_amount_min:,.0f} – ${self.total_amount_max:,.0f}",
            "most_recent":      self.most_recent_trade.strftime("%Y-%m-%d"),
        }


@dataclass
class SectorSignal:
    sector: str
    net_score: float
    buy_count: int
    sell_count: int
    top_tickers: List[TickerSignal]
    signal_label: str             # "Strong Buy", "Buy", "Neutral", "Sell", "Strong Sell"
    watchlist_activity: bool      # any watchlist politician active in sector


@dataclass
class CongressIntelReport:
    generated_at: datetime
    days_analysed: int
    total_trades: int
    watchlist_trades: int
    top_ticker_signals: List[TickerSignal]     # highest-scoring tickers
    sector_signals: Dict[str, SectorSignal]
    watchlist_highlights: List[Dict[str, Any]] # notable watchlist activity
    ai_narrative: str
    ai_opportunities: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_at":       self.generated_at.isoformat(),
            "days_analysed":      self.days_analysed,
            "total_trades":       self.total_trades,
            "watchlist_trades":   self.watchlist_trades,
            "top_ticker_signals": [t.to_dict() for t in self.top_ticker_signals],
            "sector_signals":     {
                k: {
                    "net_score":    round(v.net_score, 3),
                    "buy_count":    v.buy_count,
                    "sell_count":   v.sell_count,
                    "signal_label": v.signal_label,
                }
                for k, v in self.sector_signals.items()
            },
            "watchlist_highlights": self.watchlist_highlights,
            "ai_narrative":        self.ai_narrative,
            "ai_opportunities":    self.ai_opportunities,
        }


# ---------------------------------------------------------------------------
# Core analysis function
# ---------------------------------------------------------------------------
def analyse_congress_trades(
    trades: List[CongressTrade],
    days_back: int = 90,
    min_ticker_score: float = 0.5,
    provider: str = "auto",
    model: Optional[str] = None,
    **provider_kwargs,
) -> CongressIntelReport:
    """
    Full analysis pipeline for a list of CongressTrade objects.
    Returns a CongressIntelReport with scores, signals, and AI narrative.
    """
    now = datetime.now(timezone.utc)

    if not trades:
        return CongressIntelReport(
            generated_at=now, days_analysed=days_back,
            total_trades=0, watchlist_trades=0,
            top_ticker_signals=[], sector_signals={},
            watchlist_highlights=[], ai_narrative="No trades to analyse.",
            ai_opportunities=[],
        )

    # ── 1. Score tickers ──────────────────────────────────────────────
    ticker_signals = _score_tickers(trades, now)

    # Filter to meaningful signals
    top_tickers = sorted(
        [t for t in ticker_signals.values() if abs(t.net_score) >= min_ticker_score],
        key=lambda t: t.net_score,
        reverse=True,
    )

    # ── 2. Roll up to sectors ─────────────────────────────────────────
    sector_signals = _aggregate_sectors(ticker_signals)

    # ── 3. Watchlist highlights ───────────────────────────────────────
    watchlist_trades = [t for t in trades if t.is_watchlist]
    highlights = _build_watchlist_highlights(watchlist_trades)

    # ── 4. AI narrative ───────────────────────────────────────────────
    ai_narrative, ai_opps = _generate_congress_narrative(
        top_tickers[:15],
        sector_signals,
        highlights,
        provider=provider,
        model=model,
        **provider_kwargs,
    )

    return CongressIntelReport(
        generated_at=now,
        days_analysed=days_back,
        total_trades=len(trades),
        watchlist_trades=len(watchlist_trades),
        top_ticker_signals=top_tickers[:20],
        sector_signals=sector_signals,
        watchlist_highlights=highlights,
        ai_narrative=ai_narrative,
        ai_opportunities=ai_opps,
    )


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def _score_tickers(
    trades: List[CongressTrade],
    now: datetime,
) -> Dict[str, TickerSignal]:
    """Compute net buy/sell scores for each ticker."""
    by_ticker: Dict[str, List[CongressTrade]] = defaultdict(list)
    for t in trades:
        by_ticker[t.ticker].append(t)

    signals: Dict[str, TickerSignal] = {}

    for ticker, ticker_trades in by_ticker.items():
        score         = 0.0
        buy_count     = 0
        sell_count    = 0
        buyers_dem    = set()
        buyers_rep    = set()
        watchlist_buyers = []
        total_min     = 0.0
        total_max     = 0.0
        most_recent   = min(t.transaction_date for t in ticker_trades)

        politician_set: set = set()

        for t in ticker_trades:
            # Age decay
            age_days = max(0, (now - t.transaction_date).days)
            decay    = max(0.1, 1.0 - age_days * RECENCY_DECAY)

            if t.trade_type == "purchase":
                base = PURCHASE_WEIGHT * t.watchlist_weight * decay
                buy_count += 1
                total_min += t.amount_min
                total_max += t.amount_max
                if "D" in t.party:
                    buyers_dem.add(t.politician)
                else:
                    buyers_rep.add(t.politician)
                if t.is_watchlist and t.politician not in watchlist_buyers:
                    watchlist_buyers.append(t.politician)
            elif t.trade_type in ("sale", "sale_partial"):
                base = SALE_WEIGHT * t.watchlist_weight * decay
                sell_count += 1
            else:
                base = 0.0

            score += base

            if t.transaction_date > most_recent:
                most_recent = t.transaction_date
            politician_set.add(t.politician)

        # Bonuses
        bipartisan = bool(buyers_dem and buyers_rep)
        if bipartisan:
            score += BIPARTISAN_BONUS

        extra_traders = max(0, len(politician_set) - 1)
        score += extra_traders * CLUSTER_BONUS

        signals[ticker] = TickerSignal(
            ticker=ticker,
            sector=ticker_trades[0].sector,
            net_score=round(score, 3),
            buy_count=buy_count,
            sell_count=sell_count,
            total_traders=len(politician_set),
            watchlist_buyers=watchlist_buyers,
            bipartisan=bipartisan,
            total_amount_min=total_min,
            total_amount_max=total_max,
            most_recent_trade=most_recent,
            trades=ticker_trades,
        )

    return signals


def _aggregate_sectors(
    ticker_signals: Dict[str, TickerSignal],
) -> Dict[str, SectorSignal]:
    by_sector: Dict[str, List[TickerSignal]] = defaultdict(list)
    for sig in ticker_signals.values():
        by_sector[sig.sector].append(sig)

    sector_signals: Dict[str, SectorSignal] = {}

    for sector, sigs in by_sector.items():
        net     = sum(s.net_score for s in sigs)
        buys    = sum(s.buy_count for s in sigs)
        sells   = sum(s.sell_count for s in sigs)
        top     = sorted(sigs, key=lambda s: s.net_score, reverse=True)[:5]
        wl      = any(s.watchlist_buyers for s in sigs)

        if net >= 3.0:
            label = "Strong Buy"
        elif net >= 1.0:
            label = "Buy"
        elif net <= -3.0:
            label = "Strong Sell"
        elif net <= -1.0:
            label = "Sell"
        else:
            label = "Neutral"

        sector_signals[sector] = SectorSignal(
            sector=sector, net_score=round(net, 3),
            buy_count=buys, sell_count=sells,
            top_tickers=top, signal_label=label,
            watchlist_activity=wl,
        )

    return sector_signals


def _build_watchlist_highlights(
    watchlist_trades: List[CongressTrade],
) -> List[Dict[str, Any]]:
    """Build notable watchlist politician trade summaries."""
    by_politician: Dict[str, List[CongressTrade]] = defaultdict(list)
    for t in watchlist_trades:
        by_politician[t.politician].append(t)

    highlights = []
    for pol, trades in sorted(
        by_politician.items(),
        key=lambda x: sum(1 for t in x[1] if t.trade_type == "purchase"),
        reverse=True,
    ):
        buys  = [t for t in trades if t.trade_type == "purchase"]
        sells = [t for t in trades if t.trade_type in ("sale", "sale_partial")]
        highlights.append({
            "politician":      pol,
            "chamber":         trades[0].chamber,
            "party":           trades[0].party,
            "total_trades":    len(trades),
            "buy_count":       len(buys),
            "sell_count":      len(sells),
            "tickers_bought":  list({t.ticker for t in buys}),
            "tickers_sold":    list({t.ticker for t in sells}),
            "sectors":         list({t.sector for t in trades}),
            "notes":           trades[0].committee_relevance,
            "most_recent":     max(t.transaction_date for t in trades).strftime("%Y-%m-%d"),
        })

    return highlights[:10]


# ---------------------------------------------------------------------------
# AI narrative for congress trades
# ---------------------------------------------------------------------------
def _generate_congress_narrative(
    top_tickers: List[TickerSignal],
    sector_signals: Dict[str, SectorSignal],
    highlights: List[Dict[str, Any]],
    provider: str = "auto",
    model: Optional[str] = None,
    **provider_kwargs,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Generate AI-powered interpretation of congress trading patterns."""
    if not provider_kwargs.get("anthropic_key") and provider == "auto":
        return "AI narrative unavailable — no provider configured.", []

    tickers_block = "\n".join(
        f"  {s.ticker} ({s.sector}): score={s.net_score:+.2f}  "
        f"buys={s.buy_count} sells={s.sell_count}  "
        f"traders={s.total_traders}  "
        f"bipartisan={'YES' if s.bipartisan else 'no'}  "
        f"watchlist={', '.join(s.watchlist_buyers) or 'none'}"
        for s in top_tickers[:12]
    )

    sectors_block = "\n".join(
        f"  {sector}: {sig.signal_label} (score={sig.net_score:+.2f}  "
        f"buys={sig.buy_count} sells={sig.sell_count})"
        for sector, sig in sorted(
            sector_signals.items(), key=lambda x: x[1].net_score, reverse=True
        )
    )

    watchlist_block = "\n".join(
        f"  {h['politician']} ({h['party']}, {h['chamber'].title()}): "
        f"bought {h['tickers_bought']}, sold {h['tickers_sold']}"
        for h in highlights[:6]
    )

    user_prompt = f"""
## Top Congressional Ticker Signals (last 90 days)
{tickers_block}

## Sector-Level Signals
{sectors_block}

## Notable Watchlist Politician Activity
{watchlist_block}

## Task
Analyse these congressional trading patterns and respond with JSON:

{{
  "narrative": "<3 paragraphs: (1) what the patterns suggest, (2) which sectors congress is rotating into/out of and why, (3) what this means for retail investors who want to position alongside smart money>",
  "opportunities": [
    {{
      "ticker": "<ticker>",
      "action": "<specific action — e.g. 'Consider building a position in NVDA — 4 congress members including Pelosi bought in the last 30 days'>",
      "rationale": "<why this congress activity is significant>",
      "urgency": "immediate" | "short_term" | "monitor",
      "confidence": <0.0-1.0>,
      "risks": ["<risk 1>"]
    }}
  ]
}}

Include up to 6 opportunities, ranked by conviction.
Return ONLY the JSON. No markdown.
"""

    try:
        raw = complete(
            system_prompt=CONGRESS_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            provider=provider,
            model=model,
            temperature=0.2,
            max_tokens=1500,
            **provider_kwargs,
        )

        import json, re
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip().rstrip("`").strip()

        data = json.loads(text)
        return data.get("narrative", ""), data.get("opportunities", [])

    except Exception as exc:
        logger.warning("Congress AI narrative failed: %s", exc)
        return "Congress trade analysis complete. See ticker signals above.", []
