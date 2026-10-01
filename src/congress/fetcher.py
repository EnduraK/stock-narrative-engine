"""
Congress trade fetcher.

Pulls STOCK Act disclosures from the free House & Senate Stock Watcher APIs.
No API key required — data is sourced directly from official gov disclosures.

Uses realistic browser headers + retry/backoff so requests aren't blocked.
Also caches responses locally so re-runs don't hammer the servers.

Returns normalised CongressTrade objects ready for analysis.
"""

import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .sources import (
    HIGH_VALUE_POLITICIANS,
    HOUSE_TRANSACTIONS_URL,
    SENATE_TRANSACTIONS_URL,
    CAPITOLTRADES_API_URL,
    CAPITOLTRADES_API_SENATE,
    STOCKSEAR_HOUSE_URL,
    STOCKSEAR_SENATE_URL,
    HOUSE_S3_FALLBACK,
    SENATE_S3_FALLBACK,
    TICKER_SECTOR_MAP,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Browser-realistic headers — rotate through a small pool so each request
# looks like a slightly different real visitor
# ---------------------------------------------------------------------------
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",

    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",

    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",

    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) "
    "Gecko/20100101 Firefox/124.0",

    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

def _browser_headers(referer: str = "https://house-stock-watcher.com/") -> Dict[str, str]:
    """Return a realistic browser header set with a randomly chosen User-Agent."""
    return {
        "User-Agent":       random.choice(_USER_AGENTS),
        "Accept":           "application/json, text/plain, */*",
        "Accept-Language":  "en-US,en;q=0.9",
        "Accept-Encoding":  "gzip, deflate, br",
        "Referer":          referer,
        "Connection":       "keep-alive",
        "Sec-Fetch-Dest":   "empty",
        "Sec-Fetch-Mode":   "cors",
        "Sec-Fetch-Site":   "same-origin",
        "Cache-Control":    "no-cache",
        "Pragma":           "no-cache",
    }


# ---------------------------------------------------------------------------
# Robust HTTP session with automatic retries and backoff
# ---------------------------------------------------------------------------
def _make_session() -> requests.Session:
    """
    Build a requests Session with:
      - Automatic retries (3x) on 5xx errors and connection failures
      - Exponential backoff between retries
      - Browser-realistic headers already set
    """
    session = requests.Session()

    retry_strategy = Retry(
        total=3,
        backoff_factor=1.5,           # waits 1.5s, 3s, 4.5s between retries
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://",  adapter)
    return session


# ---------------------------------------------------------------------------
# Local disk cache — avoids re-downloading on every run
# ---------------------------------------------------------------------------
CACHE_DIR  = Path(".cache/congress")
CACHE_TTL  = 3600   # seconds — refresh data at most once per hour

def _cache_path(url: str) -> Path:
    slug = hashlib.md5(url.encode()).hexdigest()[:12]
    return CACHE_DIR / f"{slug}.json"

def _read_cache(url: str) -> Optional[Any]:
    p = _cache_path(url)
    if not p.exists():
        return None
    age = time.time() - p.stat().st_mtime
    if age > CACHE_TTL:
        logger.debug("Cache expired for %s", url)
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None

def _write_cache(url: str, data: Any) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _cache_path(url).write_text(json.dumps(data), encoding="utf-8")
    except Exception as exc:
        logger.debug("Cache write failed: %s", exc)


# ---------------------------------------------------------------------------
# Core HTTP fetch with headers + cache + fallback URLs
# ---------------------------------------------------------------------------
def _fetch_json(
    primary_url: str,
    referer: str,
    fallback_urls: Optional[List[str]] = None,
) -> Optional[Any]:
    """
    Fetch JSON from primary_url (with browser headers + retry).
    Falls back to fallback_urls if all retries fail.
    Caches successful responses to disk.
    """
    # Check cache first
    cached = _read_cache(primary_url)
    if cached is not None:
        logger.debug("Cache hit for %s", primary_url)
        return cached

    session = _make_session()
    urls_to_try = [primary_url] + (fallback_urls or [])

    for url in urls_to_try:
        try:
            # Small random delay to mimic human browsing pace
            time.sleep(random.uniform(0.5, 1.5))

            resp = session.get(
                url,
                headers=_browser_headers(referer=referer),
                timeout=30,
            )

            if resp.status_code == 200:
                data = resp.json()
                _write_cache(primary_url, data)
                logger.info("Fetched %d bytes from %s", len(resp.content), url)
                return data

            elif resp.status_code == 403:
                logger.warning(
                    "403 Forbidden on %s — trying next URL or fallback", url
                )
                time.sleep(random.uniform(2.0, 4.0))   # longer pause after 403
                continue

            else:
                logger.warning("HTTP %d from %s", resp.status_code, url)
                continue

        except requests.exceptions.ConnectionError:
            logger.warning("Connection error for %s", url)
            continue
        except requests.exceptions.Timeout:
            logger.warning("Timeout for %s", url)
            continue
        except Exception as exc:
            logger.warning("Unexpected error fetching %s: %s", url, exc)
            continue

    logger.error("All fetch attempts failed for %s", primary_url)
    return None


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class CongressTrade:
    uid: str
    politician: str
    chamber: str                     # "house" | "senate"
    party: str
    ticker: str
    asset_name: str
    trade_type: str                  # "purchase" | "sale" | "sale_partial"
    amount_range: str                # e.g. "$1,001 - $15,000"
    amount_min: float                # parsed lower bound
    amount_max: float                # parsed upper bound
    transaction_date: datetime
    disclosure_date: datetime
    sector: str
    days_to_disclose: int            # lag between trade and disclosure
    is_watchlist: bool               # True if politician is in HIGH_VALUE list
    watchlist_weight: float          # politician weight (1.0 if not on list)
    committee_relevance: str         # notes on committee/sector overlap

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uid":               self.uid,
            "politician":        self.politician,
            "chamber":           self.chamber,
            "party":             self.party,
            "ticker":            self.ticker,
            "asset_name":        self.asset_name,
            "trade_type":        self.trade_type,
            "amount_range":      self.amount_range,
            "amount_min":        self.amount_min,
            "amount_max":        self.amount_max,
            "transaction_date":  self.transaction_date.isoformat(),
            "disclosure_date":   self.disclosure_date.isoformat(),
            "sector":            self.sector,
            "days_to_disclose":  self.days_to_disclose,
            "is_watchlist":      self.is_watchlist,
            "watchlist_weight":  self.watchlist_weight,
            "committee_relevance": self.committee_relevance,
        }


# ---------------------------------------------------------------------------
# House trades
# ---------------------------------------------------------------------------
def _normalise_item(item: Dict, chamber: str) -> Dict:
    """
    Normalise a trade record from any source to a consistent internal shape:
      representative/senator, ticker, type, amount, transaction_date,
      disclosure_date, asset_description, party

    Handles three source formats:
      1. CapitolTrades API  — keys: politician, ticker, type, amount, txDate, pubDate, party
      2. Quiver Quant       — keys: Politician, Ticker, Transaction, Amount, Date, Party
      3. House/Senate Stock Watcher (legacy S3) — already in target format
    """
    name_key = "representative" if chamber == "house" else "senator"

    # ── CapitolTrades format ──────────────────────────────────────────
    if "txDate" in item or "pubDate" in item:
        politician = (
            item.get("politician", {}).get("name", "")
            if isinstance(item.get("politician"), dict)
            else item.get("politician", "")
        )
        return {
            name_key:            politician,
            "ticker":            item.get("ticker", ""),
            "type":              item.get("type", ""),
            "amount":            item.get("amount", ""),
            "transaction_date":  item.get("txDate", ""),
            "disclosure_date":   item.get("pubDate", item.get("txDate", "")),
            "asset_description": item.get("assetName", item.get("ticker", "")),
            "party":             item.get("party", "Unknown"),
        }

    # ── Quiver Quant format ───────────────────────────────────────────
    if "Politician" in item:
        return {
            name_key:            item.get("Politician", ""),
            "ticker":            item.get("Ticker", ""),
            "type":              item.get("Transaction", ""),
            "amount":            item.get("Amount", ""),
            "transaction_date":  item.get("Date", ""),
            "disclosure_date":   item.get("Date", ""),
            "asset_description": item.get("Ticker", ""),
            "party":             item.get("Party", "Unknown"),
        }

    # ── StockSear format ──────────────────────────────────────────────
    if "name" in item and "trades" not in item:
        return {
            name_key:            item.get("name", ""),
            "ticker":            item.get("ticker", ""),
            "type":              item.get("transaction", item.get("type", "")),
            "amount":            item.get("amount", ""),
            "transaction_date":  item.get("transactionDate", item.get("date", "")),
            "disclosure_date":   item.get("disclosureDate", item.get("date", "")),
            "asset_description": item.get("assetName", item.get("ticker", "")),
            "party":             item.get("party", "Unknown"),
        }

    # Already in watcher/normalised format
    return item


# Backward-compat alias
def _normalise_quiver_item(item: Dict, chamber: str) -> Dict:
    return _normalise_item(item, chamber)


def fetch_house_trades(
    days_back: int = 90,
    tickers: Optional[List[str]] = None,
) -> List[CongressTrade]:
    """Fetch House member trades.

    Source priority:
      1. CapitolTrades API (primary — reliable from cloud IPs, no auth)
      2. StockSear free API (fallback)
      3. House Stock Watcher S3 (last resort — may 403 from VPS)
    """
    raw = _fetch_json(
        primary_url=CAPITOLTRADES_API_URL,
        referer="https://www.capitoltrades.com/",
        fallback_urls=[
            STOCKSEAR_HOUSE_URL,
            HOUSE_S3_FALLBACK,
        ],
    )

    if raw is None:
        logger.warning("House trades unavailable — all sources failed")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    trades = []

    # CapitolTrades wraps results in {"data": [...]} or {"trades": [...]}
    if isinstance(raw, dict):
        rows = raw.get("data") or raw.get("trades") or raw.get("items") or []
    else:
        rows = raw  # bare list

    for item in rows:
        item = _normalise_item(item, "house")
        trade = _parse_house_trade(item, cutoff, tickers)
        if trade:
            trades.append(trade)

    logger.info("House: parsed %d trades (last %d days)", len(trades), days_back)
    return trades


def _parse_house_trade(
    item: Dict,
    cutoff: datetime,
    tickers: Optional[List[str]],
) -> Optional[CongressTrade]:
    try:
        ticker = (item.get("ticker") or "").strip().upper()
        if not ticker or ticker in ("--", "N/A", ""):
            return None
        if tickers and ticker not in tickers:
            return None

        transaction_date = _parse_date(item.get("transaction_date", ""))
        if not transaction_date or transaction_date < cutoff:
            return None

        disclosure_date = _parse_date(item.get("disclosure_date", "")) or transaction_date
        politician = _clean_name(item.get("representative", ""))
        trade_type = (item.get("type") or "").lower()
        amount_str = item.get("amount") or ""
        amount_min, amount_max = _parse_amount(amount_str)

        sector = TICKER_SECTOR_MAP.get(ticker, "macro")
        watchlist_info = _get_watchlist_info(politician)

        return CongressTrade(
            uid=hashlib.md5(f"{politician}{ticker}{transaction_date}".encode()).hexdigest()[:16],
            politician=politician,
            chamber="house",
            party=item.get("party", "Unknown"),
            ticker=ticker,
            asset_name=item.get("asset_description", ticker),
            trade_type=_normalise_type(trade_type),
            amount_range=amount_str,
            amount_min=amount_min,
            amount_max=amount_max,
            transaction_date=transaction_date,
            disclosure_date=disclosure_date,
            sector=sector,
            days_to_disclose=max(0, (disclosure_date - transaction_date).days),
            is_watchlist=watchlist_info["on_list"],
            watchlist_weight=watchlist_info["weight"],
            committee_relevance=watchlist_info["notes"],
        )
    except Exception as exc:
        logger.debug("Failed to parse house trade: %s — %s", item, exc)
        return None


# ---------------------------------------------------------------------------
# Senate trades
# ---------------------------------------------------------------------------
def fetch_senate_trades(
    days_back: int = 90,
    tickers: Optional[List[str]] = None,
) -> List[CongressTrade]:
    """Fetch Senate member trades.

    Source priority:
      1. CapitolTrades API — Senate chamber filter
      2. StockSear free API
      3. Senate Stock Watcher S3 (last resort)
    """
    raw = _fetch_json(
        primary_url=CAPITOLTRADES_API_SENATE,
        referer="https://www.capitoltrades.com/",
        fallback_urls=[
            STOCKSEAR_SENATE_URL,
            SENATE_S3_FALLBACK,
        ],
    )

    if raw is None:
        logger.warning("Senate trades unavailable — all sources failed")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    trades = []

    if isinstance(raw, dict):
        rows = raw.get("data") or raw.get("trades") or raw.get("items") or []
    else:
        rows = raw

    for item in rows:
        item = _normalise_item(item, "senate")
        trade = _parse_senate_trade(item, cutoff, tickers)
        if trade:
            trades.append(trade)

    logger.info("Senate: parsed %d trades (last %d days)", len(trades), days_back)
    return trades


def _parse_senate_trade(
    item: Dict,
    cutoff: datetime,
    tickers: Optional[List[str]],
) -> Optional[CongressTrade]:
    try:
        ticker = (item.get("ticker") or "").strip().upper()
        if not ticker or ticker in ("--", "N/A", ""):
            return None
        if tickers and ticker not in tickers:
            return None

        transaction_date = _parse_date(item.get("transaction_date", ""))
        if not transaction_date or transaction_date < cutoff:
            return None

        disclosure_date = _parse_date(item.get("disclosure_date", "")) or transaction_date
        politician = _clean_name(item.get("senator", ""))
        trade_type = (item.get("type") or "").lower()
        amount_str = item.get("amount") or ""
        amount_min, amount_max = _parse_amount(amount_str)

        sector = TICKER_SECTOR_MAP.get(ticker, "macro")
        watchlist_info = _get_watchlist_info(politician)

        return CongressTrade(
            uid=hashlib.md5(f"{politician}{ticker}{transaction_date}".encode()).hexdigest()[:16],
            politician=politician,
            chamber="senate",
            party=item.get("party", "Unknown"),
            ticker=ticker,
            asset_name=item.get("asset_description", ticker),
            trade_type=_normalise_type(trade_type),
            amount_range=amount_str,
            amount_min=amount_min,
            amount_max=amount_max,
            transaction_date=transaction_date,
            disclosure_date=disclosure_date,
            sector=sector,
            days_to_disclose=max(0, (disclosure_date - transaction_date).days),
            is_watchlist=watchlist_info["on_list"],
            watchlist_weight=watchlist_info["weight"],
            committee_relevance=watchlist_info["notes"],
        )
    except Exception as exc:
        logger.debug("Failed to parse senate trade: %s — %s", item, exc)
        return None


# ---------------------------------------------------------------------------
# Combined fetch
# ---------------------------------------------------------------------------
def fetch_all_congress_trades(
    days_back: int = 90,
    tickers: Optional[List[str]] = None,
    watchlist_only: bool = False,
) -> List[CongressTrade]:
    """
    Fetch and merge House + Senate trades.

    days_back       — how many days of history to pull
    tickers         — filter to specific tickers (None = all)
    watchlist_only  — only return trades by HIGH_VALUE_POLITICIANS
    """
    trades = fetch_house_trades(days_back=days_back, tickers=tickers)

    # Small human-like pause between the two requests
    time.sleep(random.uniform(1.0, 2.5))

    trades += fetch_senate_trades(days_back=days_back, tickers=tickers)

    if watchlist_only:
        trades = [t for t in trades if t.is_watchlist]

    # Sort: most recent transaction first
    trades.sort(key=lambda t: t.transaction_date, reverse=True)

    logger.info(
        "Total congress trades: %d (%s)",
        len(trades),
        "watchlist only" if watchlist_only else "all members",
    )
    return trades


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_date(s: str) -> Optional[datetime]:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _parse_amount(s: str) -> tuple:
    """Parse '$1,001 - $15,000' → (1001.0, 15000.0)."""
    import re
    nums = re.findall(r"[\d,]+", s.replace("$", ""))
    vals = [float(n.replace(",", "")) for n in nums if n]
    if len(vals) >= 2:
        return vals[0], vals[1]
    if len(vals) == 1:
        return vals[0], vals[0]
    return 0.0, 0.0


def _normalise_type(raw: str) -> str:
    raw = raw.lower()
    if "purchase" in raw or "buy" in raw:
        return "purchase"
    if "sale_partial" in raw or "partial" in raw:
        return "sale_partial"
    if "sale" in raw or "sell" in raw:
        return "sale"
    return raw


def _clean_name(name: str) -> str:
    import re
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"\s*\(.*?\)", "", name).strip()
    return name


def _get_watchlist_info(politician: str) -> Dict[str, Any]:
    for key, info in HIGH_VALUE_POLITICIANS.items():
        if key.lower() in politician.lower() or politician.lower() in key.lower():
            return {
                "on_list": True,
                "weight": info["weight"],
                "notes": info.get("notes", ""),
            }
    return {"on_list": False, "weight": 1.0, "notes": ""}
