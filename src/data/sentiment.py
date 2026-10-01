"""
Social Sentiment & Market Psychology Module
=============================================
Aggregates crowd intelligence from free public sources:
  - Reddit (r/wallstreetbets, r/investing, r/stocks) — via public JSON API
  - StockTwits                                        — public symbol stream API
  - CNN Fear & Greed Index                            — public endpoint
  - Google Trends proxy                               — via RSS

No API keys required for any of these sources.

Produces:
  - Per-ticker sentiment scores (-1.0 to +1.0)
  - Trending tickers (momentum)
  - Fear & Greed reading with historical context
  - Contrarian signal flags (peak euphoria / max fear)
"""

from __future__ import annotations

import logging
import re
import time
import json
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Dict, Tuple
from collections import defaultdict

log = logging.getLogger(__name__)

_HEADERS_REDDIT = {
    "User-Agent": "StockNarrativeEngine/1.0 (research bot)",
    "Accept": "application/json",
}
_HEADERS_WEB = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/html, */*",
}


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class TickerSentiment:
    ticker: str
    score: float             # -1.0 (extreme bearish) to +1.0 (extreme bullish)
    mention_count: int
    bullish_count: int
    bearish_count: int
    source: str              # "reddit" | "stocktwits" | "combined"
    trending: bool           # unusually high mention velocity
    as_of: str

    @property
    def label(self) -> str:
        if self.score >  0.5: return "STRONGLY BULLISH"
        if self.score >  0.2: return "BULLISH"
        if self.score > -0.2: return "NEUTRAL"
        if self.score > -0.5: return "BEARISH"
        return "STRONGLY BEARISH"

    @property
    def summary(self) -> str:
        trend_tag = " 🔥TRENDING" if self.trending else ""
        return (
            f"{self.ticker}{trend_tag}: {self.label} ({self.score:+.2f}) "
            f"| {self.mention_count} mentions "
            f"[{self.bullish_count}↑ {self.bearish_count}↓] via {self.source}"
        )


@dataclass
class FearGreedReading:
    score: int               # 0-100
    label: str               # "Extreme Fear" | "Fear" | "Neutral" | "Greed" | "Extreme Greed"
    prev_close: Optional[int]
    prev_week: Optional[int]
    prev_month: Optional[int]
    prev_year: Optional[int]
    as_of: str
    source: str

    @property
    def contrarian_signal(self) -> str:
        if self.score <= 20:
            return "BUY_SIGNAL: Extreme Fear historically precedes rallies"
        if self.score >= 80:
            return "SELL_SIGNAL: Extreme Greed historically precedes corrections"
        if self.score <= 35:
            return "MILD_BUY: Fear present, cautious accumulation zone"
        if self.score >= 65:
            return "MILD_SELL: Greed present, watch for reversal"
        return "NEUTRAL: No strong contrarian signal"

    @property
    def summary(self) -> str:
        change = ""
        if self.prev_week is not None:
            delta = self.score - self.prev_week
            change = f" (vs {self.prev_week} last week, {'+' if delta>=0 else ''}{delta})"
        return (
            f"Fear & Greed: {self.score}/100 — {self.label}{change} "
            f"→ {self.contrarian_signal}"
        )


@dataclass
class SentimentReport:
    ticker_sentiments: List[TickerSentiment]    = field(default_factory=list)
    fear_greed: Optional[FearGreedReading]      = None
    trending_tickers: List[str]                 = field(default_factory=list)
    reddit_posts_analysed: int                  = 0
    stocktwits_analysed: int                    = 0
    as_of: str                                  = ""

    def top_bullish(self, n: int = 5) -> List[TickerSentiment]:
        return sorted(
            [s for s in self.ticker_sentiments if s.mention_count >= 3],
            key=lambda x: x.score, reverse=True,
        )[:n]

    def top_bearish(self, n: int = 5) -> List[TickerSentiment]:
        return sorted(
            [s for s in self.ticker_sentiments if s.mention_count >= 3],
            key=lambda x: x.score,
        )[:n]

    def to_ai_context(self) -> str:
        lines = ["=== SOCIAL SENTIMENT & MARKET PSYCHOLOGY ==="]

        if self.fear_greed:
            lines.append(f"\n{self.fear_greed.summary}")

        if self.trending_tickers:
            lines.append(f"\nTrending tickers: {', '.join(self.trending_tickers[:10])}")

        bullish = self.top_bullish(8)
        if bullish:
            lines.append(f"\n[TOP BULLISH SENTIMENT]")
            for s in bullish:
                lines.append(f"  {s.summary}")

        bearish = self.top_bearish(5)
        if bearish:
            lines.append(f"\n[TOP BEARISH SENTIMENT]")
            for s in bearish:
                lines.append(f"  {s.summary}")

        lines.append(
            f"\nData: {self.reddit_posts_analysed} Reddit posts + "
            f"{self.stocktwits_analysed} StockTwits messages analysed"
        )
        return "\n".join(lines)


# ── Sentiment scoring helpers ─────────────────────────────────────────────────

_BULLISH_WORDS = {
    "moon", "rocket", "buy", "calls", "bullish", "long", "yolo", "pump", "up",
    "gains", "profit", "rally", "squeeze", "growth", "beats", "beat", "strong",
    "undervalued", "buy the dip", "breakout", "hold", "hodl", "accumulate",
    "all-time high", "ath", "surge", "soaring", "bullrun", "bull", "green",
}
_BEARISH_WORDS = {
    "puts", "bearish", "short", "sell", "dump", "crash", "drop", "fall",
    "overvalued", "bubble", "red", "down", "loss", "plunge", "tank", "tanks",
    "collapse", "fraud", "miss", "disappointing", "weak", "recession",
    "bear", "correction", "breakdown", "resistance", "selling", "sold",
}

def _score_text(text: str) -> Tuple[float, bool, bool]:
    """Returns (score, is_bullish, is_bearish) for a piece of text."""
    words  = set(re.findall(r'\b\w+\b', text.lower()))
    bull_n = len(words & _BULLISH_WORDS)
    bear_n = len(words & _BEARISH_WORDS)
    total  = bull_n + bear_n
    if total == 0:
        return 0.0, False, False
    score = (bull_n - bear_n) / total
    return score, bull_n > bear_n, bear_n > bull_n


# ── Ticker extractor ──────────────────────────────────────────────────────────

_TICKER_RE = re.compile(r'\b\$?([A-Z]{1,5})\b')
_STOP_WORDS = {
    "I", "A", "AN", "THE", "AND", "OR", "BUT", "FOR", "IN", "ON", "AT",
    "TO", "OF", "IS", "IT", "BE", "DO", "GO", "NO", "SO", "UP", "US",
    "WE", "MY", "BY", "AS", "IF", "PM", "AM", "CEO", "CFO", "COO",
    "IPO", "ETF", "SEC", "FED", "IMF", "ECB", "GDP", "CPI", "PPI",
    "IMO", "imo", "EOD", "EOW", "EOM", "AH", "DD", "OC", "OP",
    "YOLO", "FOMO", "FUD", "WSB", "ATH", "ATL", "OTM", "ITM",
    "QQQ", "SPY", "SPX", "VIX", "DXY",  # keep these separately
}

def _extract_tickers(text: str) -> List[str]:
    found = _TICKER_RE.findall(text.upper())
    return [t for t in found if t not in _STOP_WORDS and 1 < len(t) <= 5]


# ── CNN Fear & Greed ──────────────────────────────────────────────────────────

def _label_fg(s: int) -> str:
    if s <= 25: return "Extreme Fear"
    if s <= 44: return "Fear"
    if s <= 55: return "Neutral"
    if s <= 75: return "Greed"
    return "Extreme Greed"


def fetch_fear_greed() -> Optional[FearGreedReading]:
    """
    Fetch Fear & Greed Index.
    Primary:  alternative.me (crypto-weighted, but broadly correlated with equity sentiment)
    Fallback: CNN dataviz endpoint (sometimes blocks servers)
    """
    # ── Primary: alternative.me (always works, no bot detection) ─────
    try:
        url = "https://api.alternative.me/fng/?limit=8&format=json"
        req = urllib.request.Request(url, headers=_HEADERS_WEB)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        entries = data.get("data", [])
        if not entries:
            raise ValueError("empty data")

        current   = entries[0]
        score     = int(current.get("value", 50))
        label     = current.get("value_classification", _label_fg(score))

        # entries are newest-first; find prev close, week, month
        prev_cls = int(entries[1]["value"]) if len(entries) > 1 else None
        prev_wk  = int(entries[7]["value"]) if len(entries) > 7 else None

        reading = FearGreedReading(
            score=score,
            label=label,
            prev_close=prev_cls,
            prev_week=prev_wk,
            prev_month=None,
            prev_year=None,
            as_of=datetime.now(timezone.utc).isoformat(),
            source="Alternative.me Fear & Greed (crypto-weighted proxy)",
        )
        log.info("Fear & Greed: %d (%s)", score, label)
        return reading

    except Exception as exc:
        log.debug("alternative.me F&G failed: %s", exc)

    # ── Fallback: CNN endpoint ─────────────────────────────────────────
    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        req = urllib.request.Request(url, headers=_HEADERS_WEB)
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode())

        fg    = data.get("fear_and_greed", {})
        score = int(float(fg.get("score", 50)))
        reading = FearGreedReading(
            score=score,
            label=fg.get("rating", _label_fg(score)),
            prev_close=None, prev_week=None, prev_month=None, prev_year=None,
            as_of=datetime.now(timezone.utc).isoformat(),
            source="CNN Fear & Greed",
        )
        return reading
    except Exception as exc:
        log.debug("CNN F&G fallback failed: %s", exc)

    return None


# ── Reddit ────────────────────────────────────────────────────────────────────

_REDDIT_SUBS = [
    "wallstreetbets", "investing", "stocks", "options",
    "SecurityAnalysis", "StockMarket", "Economics",
]

def _fetch_reddit_posts(subreddit: str, limit: int = 50) -> List[dict]:
    """Fetch hot posts from a subreddit via public JSON API."""
    url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}&raw_json=1"
    try:
        req = urllib.request.Request(url, headers=_HEADERS_REDDIT)
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode())
        posts = data.get("data", {}).get("children", [])
        return [p["data"] for p in posts if "data" in p]
    except Exception as exc:
        log.debug("Reddit r/%s fetch failed: %s", subreddit, exc)
        return []


def fetch_reddit_sentiment(
    tickers: Optional[List[str]] = None,
    max_posts_per_sub: int = 50,
) -> Tuple[Dict[str, TickerSentiment], int]:
    """
    Fetch Reddit sentiment. Returns (ticker→TickerSentiment dict, total_posts).
    """
    scores:   Dict[str, List[float]] = defaultdict(list)
    bulls:    Dict[str, int]         = defaultdict(int)
    bears:    Dict[str, int]         = defaultdict(int)
    mentions: Dict[str, int]         = defaultdict(int)
    total_posts = 0

    for sub in _REDDIT_SUBS:
        posts = _fetch_reddit_posts(sub, max_posts_per_sub)
        total_posts += len(posts)
        for post in posts:
            text = f"{post.get('title', '')} {post.get('selftext', '')}"
            tickers_found = _extract_tickers(text)
            if not tickers_found:
                continue
            score, is_bull, is_bear = _score_text(text)
            upvotes = int(post.get("score", 0))
            weight  = max(1, min(upvotes, 1000)) / 1000  # cap weight at 1.0

            for t in set(tickers_found):
                if tickers and t not in tickers:
                    continue
                mentions[t] += 1
                scores[t].append(score * weight)
                if is_bull: bulls[t] += 1
                if is_bear: bears[t] += 1
        time.sleep(0.5)

    results: Dict[str, TickerSentiment] = {}
    now = datetime.now(timezone.utc).isoformat()
    for ticker, sc_list in scores.items():
        avg_score = sum(sc_list) / len(sc_list) if sc_list else 0.0
        results[ticker] = TickerSentiment(
            ticker=ticker,
            score=round(avg_score, 3),
            mention_count=mentions[ticker],
            bullish_count=bulls[ticker],
            bearish_count=bears[ticker],
            source="reddit",
            trending=mentions[ticker] >= 10,
            as_of=now,
        )

    log.info("Reddit: %d posts → %d tickers mentioned", total_posts, len(results))
    return results, total_posts


# ── StockTwits ────────────────────────────────────────────────────────────────

_ST_TRENDING_URL = "https://api.stocktwits.com/api/2/trending/symbols.json"

def fetch_stocktwits_trending() -> List[str]:
    """Fetch currently trending tickers on StockTwits (no auth needed)."""
    try:
        req = urllib.request.Request(_ST_TRENDING_URL, headers=_HEADERS_WEB)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        symbols = data.get("symbols", [])
        tickers = [s["symbol"] for s in symbols if "symbol" in s]
        log.info("StockTwits trending: %s", ", ".join(tickers[:10]))
        return tickers
    except Exception as exc:
        log.debug("StockTwits trending failed: %s", exc)
        return []


def fetch_stocktwits_sentiment(
    tickers: List[str],
) -> Tuple[Dict[str, TickerSentiment], int]:
    """
    Fetch per-ticker sentiment from StockTwits public stream API.
    """
    results: Dict[str, TickerSentiment] = {}
    total = 0
    now = datetime.now(timezone.utc).isoformat()

    for ticker in tickers[:15]:  # cap to avoid rate limits
        url = f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
        try:
            req = urllib.request.Request(url, headers=_HEADERS_WEB)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
        except Exception as exc:
            log.debug("StockTwits %s failed: %s", ticker, exc)
            time.sleep(0.5)
            continue

        messages = data.get("messages", [])
        total += len(messages)
        bull_c = bear_c = 0
        score_sum = 0.0

        for msg in messages:
            sentiment = (msg.get("entities", {}).get("sentiment") or {})
            basic = sentiment.get("basic", "")
            if basic == "Bullish":
                bull_c += 1
                score_sum += 1.0
            elif basic == "Bearish":
                bear_c += 1
                score_sum -= 1.0
            else:
                # Fallback: score the text
                s, is_b, is_be = _score_text(msg.get("body", ""))
                score_sum += s

        n = len(messages)
        if n > 0:
            avg = score_sum / n
            results[ticker] = TickerSentiment(
                ticker=ticker,
                score=round(avg, 3),
                mention_count=n,
                bullish_count=bull_c,
                bearish_count=bear_c,
                source="stocktwits",
                trending=bull_c + bear_c > n * 0.5,  # >50% with explicit sentiment
                as_of=now,
            )
        time.sleep(0.4)

    log.info("StockTwits: %d messages across %d tickers", total, len(results))
    return results, total


# ── Merge sentiment sources ────────────────────────────────────────────────────

def _merge_sentiments(
    reddit: Dict[str, TickerSentiment],
    stocktwits: Dict[str, TickerSentiment],
) -> List[TickerSentiment]:
    """Merge Reddit + StockTwits, weighting by mention count."""
    all_tickers = set(reddit) | set(stocktwits)
    merged = []
    now = datetime.now(timezone.utc).isoformat()

    for ticker in all_tickers:
        r = reddit.get(ticker)
        s = stocktwits.get(ticker)

        if r and s:
            total_m = r.mention_count + s.mention_count
            w_r = r.mention_count / total_m
            w_s = s.mention_count / total_m
            merged.append(TickerSentiment(
                ticker=ticker,
                score=round(r.score * w_r + s.score * w_s, 3),
                mention_count=total_m,
                bullish_count=r.bullish_count + s.bullish_count,
                bearish_count=r.bearish_count + s.bearish_count,
                source="combined",
                trending=r.trending or s.trending,
                as_of=now,
            ))
        elif r:
            merged.append(r)
        elif s:
            merged.append(s)

    return sorted(merged, key=lambda x: x.mention_count, reverse=True)


# ── Main entrypoint ────────────────────────────────────────────────────────────

def fetch_sentiment_intelligence(
    tickers: Optional[List[str]] = None,
) -> SentimentReport:
    """
    Main entrypoint: fetch all sentiment data and return a unified report.
    """
    log.info("Fetching social sentiment intelligence...")
    report = SentimentReport(as_of=datetime.now(timezone.utc).isoformat())

    # Fear & Greed
    try:
        report.fear_greed = fetch_fear_greed()
    except Exception as exc:
        log.warning("Fear & Greed failed: %s", exc)

    # Reddit
    try:
        reddit_data, n_posts = fetch_reddit_sentiment(tickers=tickers)
        report.reddit_posts_analysed = n_posts
    except Exception as exc:
        log.warning("Reddit sentiment failed: %s", exc)
        reddit_data = {}

    # StockTwits trending (get the list first, then sentiment for those tickers)
    st_tickers = tickers or []
    try:
        trending = fetch_stocktwits_trending()
        report.trending_tickers = trending[:10]
        if not tickers:
            # Add trending tickers to sentiment watch list
            st_tickers = list(set(trending[:15]))
    except Exception as exc:
        log.warning("StockTwits trending failed: %s", exc)

    try:
        st_data, n_st = fetch_stocktwits_sentiment(st_tickers or list(reddit_data.keys())[:15])
        report.stocktwits_analysed = n_st
    except Exception as exc:
        log.warning("StockTwits sentiment failed: %s", exc)
        st_data = {}

    # Merge sources
    report.ticker_sentiments = _merge_sentiments(reddit_data, st_data)

    log.info(
        "Sentiment: %d tickers, F&G=%s, trending=%s",
        len(report.ticker_sentiments),
        report.fear_greed.score if report.fear_greed else "N/A",
        ", ".join(report.trending_tickers[:5]),
    )
    return report
