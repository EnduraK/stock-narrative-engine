"""
Multi-source news fetcher.

Pulls articles from:
  1. RSS feeds            — free, no key needed
  2. NewsAPI              — free tier (100 req/day)  → set NEWSAPI_KEY
  3. Finnhub              — free tier               → set FINNHUB_KEY
  4. Alpha Vantage        — free tier               → set ALPHA_VANTAGE_KEY

All results are normalised into a common Article dataclass.
"""

import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import feedparser
import requests

from .sources import (
    ALPHA_VANTAGE_NEWS_URL,
    ALPHA_VANTAGE_TICKERS_BY_SECTOR,
    FINNHUB_CATEGORIES,
    FINNHUB_NEWS_URL,
    NEWSAPI_ENDPOINTS,
    NEWSAPI_QUERIES,
    RSS_SOURCES,
    SECTORS,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Normalised article dataclass
# ---------------------------------------------------------------------------
@dataclass
class Article:
    uid: str                          # deterministic hash of url+title
    title: str
    summary: str
    url: str
    source: str
    published_at: datetime
    sectors: List[str] = field(default_factory=list)
    sentiment_hint: Optional[str] = None   # filled later by AI layer
    relevance_score: float = 0.0

    @staticmethod
    def _make_uid(url: str, title: str) -> str:
        raw = f"{url}:{title}"
        return hashlib.md5(raw.encode()).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uid": self.uid,
            "title": self.title,
            "summary": self.summary,
            "url": self.url,
            "source": self.source,
            "published_at": self.published_at.isoformat(),
            "sectors": self.sectors,
            "relevance_score": self.relevance_score,
        }


# ---------------------------------------------------------------------------
# RSS fetcher
# ---------------------------------------------------------------------------
def fetch_rss(
    sectors: Optional[List[str]] = None,
    max_per_feed: int = 15,
) -> List[Article]:
    """Fetch articles from all registered RSS feeds."""
    articles: List[Article] = []
    sources = RSS_SOURCES

    if sectors:
        # Include feeds tagged with any requested sector, plus generic feeds
        sources = [
            s for s in RSS_SOURCES
            if not s.sectors or any(sec in s.sectors for sec in sectors)
        ]

    for src in sources:
        try:
            feed = feedparser.parse(src.url)
            for entry in feed.entries[:max_per_feed]:
                title   = getattr(entry, "title", "").strip()
                summary = getattr(entry, "summary", "")
                url     = getattr(entry, "link", "")

                if not title or not url:
                    continue

                # Parse publish date
                published_at = datetime.now(timezone.utc)
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        published_at = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    except Exception:
                        pass

                art = Article(
                    uid=Article._make_uid(url, title),
                    title=title,
                    summary=_clean_html(summary)[:500],
                    url=url,
                    source=src.name,
                    published_at=published_at,
                    sectors=src.sectors.copy(),
                    relevance_score=src.weight,
                )
                articles.append(art)

        except Exception as exc:
            logger.warning("RSS fetch failed for %s: %s", src.name, exc)

    logger.info("RSS: fetched %d articles from %d feeds", len(articles), len(sources))
    return articles


# ---------------------------------------------------------------------------
# NewsAPI fetcher
# ---------------------------------------------------------------------------
def fetch_newsapi(
    api_key: str,
    sectors: Optional[List[str]] = None,
    max_per_sector: int = 10,
) -> List[Article]:
    """Fetch articles from NewsAPI.org (requires free API key)."""
    if not api_key:
        logger.debug("NewsAPI key not set — skipping")
        return []

    articles: List[Article] = []
    target_sectors = sectors or list(NEWSAPI_QUERIES.keys())

    for sector in target_sectors:
        query = NEWSAPI_QUERIES.get(sector)
        if not query:
            continue

        params = {
            "q":        query,
            "language": "en",
            "sortBy":   "publishedAt",
            "pageSize": max_per_sector,
            "apiKey":   api_key,
        }

        try:
            resp = requests.get(
                NEWSAPI_ENDPOINTS["everything"],
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            for item in data.get("articles", []):
                title   = (item.get("title") or "").strip()
                url     = item.get("url", "")
                summary = item.get("description") or item.get("content") or ""

                if not title or not url or title == "[Removed]":
                    continue

                published_at = datetime.now(timezone.utc)
                raw_date = item.get("publishedAt")
                if raw_date:
                    try:
                        published_at = datetime.fromisoformat(
                            raw_date.replace("Z", "+00:00")
                        )
                    except Exception:
                        pass

                art = Article(
                    uid=Article._make_uid(url, title),
                    title=title,
                    summary=summary[:500],
                    url=url,
                    source=item.get("source", {}).get("name", "NewsAPI"),
                    published_at=published_at,
                    sectors=[sector],
                    relevance_score=1.1,
                )
                articles.append(art)

            time.sleep(0.3)   # be polite to free tier

        except Exception as exc:
            logger.warning("NewsAPI failed for sector '%s': %s", sector, exc)

    logger.info("NewsAPI: fetched %d articles", len(articles))
    return articles


# ---------------------------------------------------------------------------
# Finnhub fetcher
# ---------------------------------------------------------------------------
def fetch_finnhub(
    api_key: str,
    sectors: Optional[List[str]] = None,
) -> List[Article]:
    """Fetch market news from Finnhub (requires free API key)."""
    if not api_key:
        logger.debug("Finnhub key not set — skipping")
        return []

    articles: List[Article] = []

    for category in FINNHUB_CATEGORIES:
        try:
            resp = requests.get(
                FINNHUB_NEWS_URL,
                params={"category": category, "token": api_key},
                timeout=10,
            )
            resp.raise_for_status()
            for item in resp.json():
                title   = (item.get("headline") or "").strip()
                url     = item.get("url", "")
                summary = item.get("summary") or ""

                if not title or not url:
                    continue

                published_at = datetime.fromtimestamp(
                    item.get("datetime", time.time()), tz=timezone.utc
                )

                art = Article(
                    uid=Article._make_uid(url, title),
                    title=title,
                    summary=summary[:500],
                    url=url,
                    source=item.get("source", "Finnhub"),
                    published_at=published_at,
                    sectors=_finnhub_category_to_sectors(category),
                    relevance_score=1.15,
                )
                articles.append(art)

            time.sleep(0.3)

        except Exception as exc:
            logger.warning("Finnhub failed for category '%s': %s", category, exc)

    logger.info("Finnhub: fetched %d articles", len(articles))
    return articles


# ---------------------------------------------------------------------------
# Alpha Vantage news fetcher
# ---------------------------------------------------------------------------
def fetch_alpha_vantage(
    api_key: str,
    sectors: Optional[List[str]] = None,
    max_per_sector: int = 10,
) -> List[Article]:
    """Fetch news & sentiment from Alpha Vantage (requires free API key)."""
    if not api_key:
        logger.debug("Alpha Vantage key not set — skipping")
        return []

    articles: List[Article] = []
    target_sectors = sectors or list(ALPHA_VANTAGE_TICKERS_BY_SECTOR.keys())

    for sector in target_sectors:
        tickers = ALPHA_VANTAGE_TICKERS_BY_SECTOR.get(sector, [])
        if not tickers:
            continue

        tickers_str = ",".join(tickers[:3])   # keep under free-tier limits

        try:
            resp = requests.get(
                ALPHA_VANTAGE_NEWS_URL,
                params={
                    "function":    "NEWS_SENTIMENT",
                    "tickers":     tickers_str,
                    "limit":       max_per_sector,
                    "apikey":      api_key,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            for item in data.get("feed", []):
                title   = (item.get("title") or "").strip()
                url     = item.get("url", "")
                summary = item.get("summary") or ""

                if not title or not url:
                    continue

                # Alpha Vantage provides a sentiment label
                sentiment = item.get("overall_sentiment_label", "Neutral")

                published_at = datetime.now(timezone.utc)
                raw_date = item.get("time_published", "")
                if raw_date:
                    try:
                        published_at = datetime.strptime(
                            raw_date, "%Y%m%dT%H%M%S"
                        ).replace(tzinfo=timezone.utc)
                    except Exception:
                        pass

                art = Article(
                    uid=Article._make_uid(url, title),
                    title=title,
                    summary=summary[:500],
                    url=url,
                    source=item.get("source", "Alpha Vantage"),
                    published_at=published_at,
                    sectors=[sector],
                    sentiment_hint=sentiment,
                    relevance_score=1.2,
                )
                articles.append(art)

            time.sleep(0.5)   # Alpha Vantage free tier is strict

        except Exception as exc:
            logger.warning("Alpha Vantage failed for sector '%s': %s", sector, exc)

    logger.info("Alpha Vantage: fetched %d articles", len(articles))
    return articles


# ---------------------------------------------------------------------------
# Unified fetch function
# ---------------------------------------------------------------------------
def fetch_all_news(
    sectors: Optional[List[str]] = None,
    newsapi_key: str = "",
    finnhub_key: str = "",
    alpha_vantage_key: str = "",
    max_total: int = 200,
    deduplicate: bool = True,
) -> List[Article]:
    """
    Aggregate news from all configured sources.

    Returns a deduplicated, recency-sorted list of Article objects.
    """
    all_articles: List[Article] = []

    all_articles.extend(fetch_rss(sectors=sectors))
    all_articles.extend(fetch_newsapi(newsapi_key, sectors=sectors))
    all_articles.extend(fetch_finnhub(finnhub_key, sectors=sectors))
    all_articles.extend(fetch_alpha_vantage(alpha_vantage_key, sectors=sectors))

    if deduplicate:
        seen_uids: set = set()
        unique: List[Article] = []
        for art in all_articles:
            if art.uid not in seen_uids:
                seen_uids.add(art.uid)
                unique.append(art)
        all_articles = unique

    # Sort: most recent first, then by source weight
    all_articles.sort(
        key=lambda a: (a.published_at, a.relevance_score),
        reverse=True,
    )

    logger.info(
        "Total articles fetched: %d (capped at %d)", len(all_articles), max_total
    )
    return all_articles[:max_total]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _clean_html(text: str) -> str:
    """Very lightweight HTML strip (no extra deps)."""
    import re
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _finnhub_category_to_sectors(category: str) -> List[str]:
    mapping = {
        "general": ["macro"],
        "forex":   ["financial_services", "macro"],
        "crypto":  ["crypto"],
        "merger":  ["financial_services"],
    }
    return mapping.get(category, ["macro"])
