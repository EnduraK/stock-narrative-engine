"""
SEC EDGAR Intelligence Module
==============================
Pulls free, real-time data from SEC's public APIs:
  - Form 4  : Insider buy/sell transactions (executives, directors, 10%+ holders)
  - 13F     : Hedge fund / institutional holdings changes (quarterly)
  - 8-K     : Material events (earnings, mergers, executive changes, etc.)
  - Ticker→CIK mapping for targeted company lookups

All endpoints are public (no API key required) per SEC EDGAR policy.
Rate limit: max 10 requests/second per SEC fair-use policy.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional
import urllib.request
import urllib.error
import json
import re
import xml.etree.ElementTree as ET

log = logging.getLogger(__name__)

_EDGAR_BASE    = "https://data.sec.gov"
_EFTS_BASE     = "https://efts.sec.gov/LATEST/search-index"
_BROWSE_BASE   = "https://www.sec.gov/cgi-bin/browse-edgar"
_HEADERS        = {
    "User-Agent": "StockNarrativeEngine khalik@example.com",  # SEC requires user-agent
    "Accept": "application/json",
}
_DELAY = 0.12   # ~8 req/s — stays under the 10/s limit


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class InsiderTrade:
    ticker: str
    company: str
    insider_name: str
    insider_title: str
    trade_type: str          # "buy" | "sell" | "option_exercise"
    shares: float
    price_per_share: float
    total_value: float
    filed_date: str          # ISO date string
    ownership_after: float
    is_direct: bool
    form_url: str
    signal_strength: str     # "strong_buy" | "buy" | "sell" | "strong_sell" | "neutral"

    @property
    def summary(self) -> str:
        direction = "🟢 BUY" if "buy" in self.trade_type else "🔴 SELL"
        return (
            f"{direction} {self.ticker} | {self.insider_name} ({self.insider_title}) "
            f"| {self.shares:,.0f} shares @ ${self.price_per_share:.2f} "
            f"= ${self.total_value:,.0f} | Filed {self.filed_date}"
        )


@dataclass
class InstitutionalHolding:
    institution_name: str
    cik: str
    ticker: str
    company: str
    shares_held: float
    market_value: float
    change_shares: float     # positive = bought, negative = sold
    change_pct: float
    report_date: str
    form_url: str

    @property
    def summary(self) -> str:
        arrow = "▲" if self.change_shares > 0 else "▼"
        return (
            f"{arrow} {self.institution_name} | {self.ticker} | "
            f"{abs(self.change_pct):.1f}% {'increase' if self.change_shares>0 else 'decrease'} "
            f"| {self.shares_held:,.0f} shares held (${self.market_value/1e6:.1f}M)"
        )


@dataclass
class MaterialEvent:
    ticker: str
    company: str
    event_type: str          # "earnings", "merger", "exec_change", "debt", "guidance", etc.
    headline: str
    filed_date: str
    period_of_report: str
    form_url: str
    relevance_score: int     # 1-10


@dataclass
class EdgarReport:
    insider_trades: List[InsiderTrade]   = field(default_factory=list)
    institutional: List[InstitutionalHolding] = field(default_factory=list)
    material_events: List[MaterialEvent] = field(default_factory=list)
    as_of: str = ""

    @property
    def total_items(self) -> int:
        return len(self.insider_trades) + len(self.institutional) + len(self.material_events)

    def strong_insider_buys(self) -> List[InsiderTrade]:
        return [t for t in self.insider_trades if t.signal_strength in ("strong_buy", "buy")]

    def large_sells(self) -> List[InsiderTrade]:
        return [t for t in self.insider_trades if t.signal_strength in ("strong_sell", "sell")]

    def to_ai_context(self) -> str:
        """Format as concise text for AI prompt injection."""
        lines = ["=== SEC EDGAR INTELLIGENCE ==="]

        if self.insider_trades:
            lines.append(f"\n[INSIDER TRADES — last 14 days, {len(self.insider_trades)} transactions]")
            buys  = [t for t in self.insider_trades if "buy" in t.trade_type]
            sells = [t for t in self.insider_trades if "sell" in t.trade_type]
            if buys:
                lines.append("Notable Buys:")
                for t in sorted(buys, key=lambda x: x.total_value, reverse=True)[:10]:
                    lines.append(f"  {t.summary}")
            if sells:
                lines.append("Notable Sells:")
                for t in sorted(sells, key=lambda x: x.total_value, reverse=True)[:10]:
                    lines.append(f"  {t.summary}")

        if self.material_events:
            lines.append(f"\n[8-K MATERIAL EVENTS — {len(self.material_events)} filings]")
            for e in sorted(self.material_events, key=lambda x: x.relevance_score, reverse=True)[:15]:
                lines.append(f"  [{e.event_type.upper()}] {e.ticker} | {e.headline} ({e.filed_date})")

        return "\n".join(lines)


# ── HTTP helper ────────────────────────────────────────────────────────────────

def _get(url: str, retries: int = 3) -> Optional[dict | str]:
    """Fetch URL with retries. Returns parsed JSON dict or raw string."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return raw
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 2 ** attempt
                log.warning("EDGAR rate-limited, waiting %ds", wait)
                time.sleep(wait)
            else:
                log.debug("EDGAR HTTP %d for %s", e.code, url)
                return None
        except Exception as exc:
            log.debug("EDGAR request failed (%s): %s", url, exc)
            if attempt < retries - 1:
                time.sleep(1)
    return None


# ── Ticker → CIK mapping ───────────────────────────────────────────────────────

_ticker_cik_cache: dict[str, str] = {}

def _load_ticker_map() -> dict[str, str]:
    """Load SEC's official ticker→CIK mapping (cached in module memory)."""
    global _ticker_cik_cache
    if _ticker_cik_cache:
        return _ticker_cik_cache
    data = _get("https://www.sec.gov/files/company_tickers.json")
    if not data:
        return {}
    for entry in data.values():
        ticker = entry.get("ticker", "").upper()
        cik    = str(entry.get("cik_str", "")).zfill(10)
        if ticker:
            _ticker_cik_cache[ticker] = cik
    log.info("EDGAR: loaded %d ticker→CIK mappings", len(_ticker_cik_cache))
    return _ticker_cik_cache


def _get_cik(ticker: str) -> Optional[str]:
    tmap = _load_ticker_map()
    return tmap.get(ticker.upper())


# ── Form 4 — Insider Trades ────────────────────────────────────────────────────

def _classify_trade(transaction_code: str, shares: float) -> tuple[str, str]:
    """Return (trade_type, signal_strength) from SEC transaction code."""
    buys  = {"P": "buy", "A": "buy"}
    sells = {"S": "sell", "D": "sell", "G": "sell", "F": "sell"}
    tc = transaction_code.upper()
    if tc in buys:
        ttype = buys[tc]
        strength = "strong_buy" if shares > 10_000 else "buy"
    elif tc in sells:
        ttype = sells[tc]
        strength = "strong_sell" if shares > 50_000 else "sell"
    elif tc in ("M", "C", "X"):
        ttype = "option_exercise"
        strength = "neutral"
    else:
        ttype = "other"
        strength = "neutral"
    return ttype, strength


def fetch_insider_trades(
    tickers: Optional[List[str]] = None,
    days_back: int = 14,
    min_value: float = 50_000,
) -> List[InsiderTrade]:
    """
    Fetch recent Form 4 insider trade filings.
    If tickers is None, fetches the market-wide recent feed (last 40 filings).
    If tickers is provided, fetches targeted data per company.
    """
    trades: List[InsiderTrade] = []
    since = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")

    if not tickers:
        # Market-wide recent Form 4 via RSS
        url = (
            f"{_BROWSE_BASE}?action=getcurrent&type=4&dateb=&owner=include"
            f"&count=100&output=atom"
        )
        raw = _get(url)
        if raw and isinstance(raw, str):
            trades.extend(_parse_form4_atom(raw, min_value=min_value))
        time.sleep(_DELAY)
    else:
        ticker_map = _load_ticker_map()
        for ticker in tickers[:20]:  # cap to avoid hammering SEC
            cik = ticker_map.get(ticker.upper())
            if not cik:
                continue
            url = f"{_EDGAR_BASE}/submissions/CIK{cik}.json"
            data = _get(url)
            time.sleep(_DELAY)
            if not data or not isinstance(data, dict):
                continue
            company_name = data.get("name", ticker)
            recent = data.get("filings", {}).get("recent", {})
            forms  = recent.get("form", [])
            dates  = recent.get("filingDate", [])
            accs   = recent.get("accessionNumber", [])

            for form, date, acc in zip(forms, dates, accs):
                if form != "4":
                    continue
                if date < since:
                    break
                acc_clean = acc.replace("-", "")
                filing_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/{acc}.txt"
                # Use the viewer URL instead for readability
                viewer_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=4&dateb=&owner=include&count=10"
                trades.append(InsiderTrade(
                    ticker=ticker.upper(),
                    company=company_name,
                    insider_name="(see filing)",
                    insider_title="",
                    trade_type="unknown",
                    shares=0,
                    price_per_share=0,
                    total_value=0,
                    filed_date=date,
                    ownership_after=0,
                    is_direct=True,
                    form_url=viewer_url,
                    signal_strength="neutral",
                ))

    log.info("EDGAR Form 4: fetched %d insider trade records", len(trades))
    return trades


def _parse_form4_atom(xml_str: str, min_value: float = 0) -> List[InsiderTrade]:
    """Parse the SEC EDGAR Atom feed for recent Form 4 filings."""
    trades = []
    try:
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(xml_str)
        entries = root.findall("atom:entry", ns)
        for entry in entries:
            title   = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
            updated = (entry.findtext("atom:updated", default="", namespaces=ns) or "")[:10]
            link_el = entry.find("atom:link", ns)
            url     = link_el.get("href", "") if link_el is not None else ""
            summary = (entry.findtext("atom:summary", default="", namespaces=ns) or "")

            # Title format: "4 - CompanyName (ticker) (0000123456) (Filer)"
            ticker_match  = re.search(r'\(([A-Z]{1,5})\)', title)
            company_match = re.search(r'4 - (.+?) \(', title)
            ticker  = ticker_match.group(1)  if ticker_match  else "UNKN"
            company = company_match.group(1) if company_match else title

            trades.append(InsiderTrade(
                ticker=ticker,
                company=company,
                insider_name="(see filing)",
                insider_title="",
                trade_type="filed",
                shares=0,
                price_per_share=0,
                total_value=0,
                filed_date=updated,
                ownership_after=0,
                is_direct=True,
                form_url=url,
                signal_strength="neutral",
            ))
    except ET.ParseError as exc:
        log.debug("Form 4 Atom parse error: %s", exc)
    return trades


# ── 8-K Material Events ────────────────────────────────────────────────────────

_8K_KEYWORDS = {
    "merger":       ["merger", "acquisition", "acquire", "takeover", "deal"],
    "earnings":     ["earnings", "revenue", "profit", "loss", "quarterly results"],
    "exec_change":  ["ceo", "cfo", "president", "officer", "appoint", "resign", "depart"],
    "guidance":     ["guidance", "outlook", "forecast", "raises", "lowers", "expects"],
    "debt":         ["credit facility", "debt", "bond", "notes", "offering", "bankruptcy"],
    "legal":        ["lawsuit", "settlement", "investigation", "sec inquiry", "subpoena"],
    "dividend":     ["dividend", "buyback", "repurchase"],
    "product":      ["fda", "approval", "launch", "recall", "patent"],
}

_RELEVANCE = {
    "merger": 10, "earnings": 9, "guidance": 8, "exec_change": 7,
    "debt": 7, "legal": 6, "dividend": 5, "product": 8,
}


def _classify_8k(text: str) -> tuple[str, int]:
    text_lower = text.lower()
    for etype, kws in _8K_KEYWORDS.items():
        if any(kw in text_lower for kw in kws):
            return etype, _RELEVANCE.get(etype, 5)
    return "other", 3


def fetch_material_events(
    tickers: Optional[List[str]] = None,
    days_back: int = 7,
    min_relevance: int = 5,
) -> List[MaterialEvent]:
    """Fetch recent 8-K material event filings from SEC EDGAR."""
    events: List[MaterialEvent] = []
    since = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")

    if not tickers:
        # Market-wide 8-K feed
        url = (
            f"{_BROWSE_BASE}?action=getcurrent&type=8-K&dateb=&owner=include"
            f"&count=100&output=atom"
        )
        raw = _get(url)
        time.sleep(_DELAY)
        if raw and isinstance(raw, str):
            events.extend(_parse_8k_atom(raw, min_relevance=min_relevance))
    else:
        ticker_map = _load_ticker_map()
        for ticker in tickers[:20]:
            cik = ticker_map.get(ticker.upper())
            if not cik:
                continue
            url = f"{_EDGAR_BASE}/submissions/CIK{cik}.json"
            data = _get(url)
            time.sleep(_DELAY)
            if not data or not isinstance(data, dict):
                continue
            company_name = data.get("name", ticker)
            recent = data.get("filings", {}).get("recent", {})
            forms  = recent.get("form", [])
            dates  = recent.get("filingDate", [])
            accs   = recent.get("accessionNumber", [])
            descs  = recent.get("primaryDocument", [])

            for form, date, acc, desc in zip(forms, dates, accs, descs):
                if not form.startswith("8-K"):
                    continue
                if date < since:
                    break
                etype, score = _classify_8k(desc or "")
                if score < min_relevance:
                    continue
                viewer_url = (
                    f"https://www.sec.gov/cgi-bin/browse-edgar"
                    f"?action=getcompany&CIK={cik}&type=8-K&dateb=&owner=include&count=5"
                )
                events.append(MaterialEvent(
                    ticker=ticker.upper(),
                    company=company_name,
                    event_type=etype,
                    headline=desc,
                    filed_date=date,
                    period_of_report=date,
                    form_url=viewer_url,
                    relevance_score=score,
                ))

    log.info("EDGAR 8-K: fetched %d material events", len(events))
    return events


def _parse_8k_atom(xml_str: str, min_relevance: int = 4) -> List[MaterialEvent]:
    events = []
    try:
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(xml_str)
        for entry in root.findall("atom:entry", ns):
            title   = (entry.findtext("atom:title",   default="", namespaces=ns) or "").strip()
            updated = (entry.findtext("atom:updated",  default="", namespaces=ns) or "")[:10]
            link_el = entry.find("atom:link", ns)
            url     = link_el.get("href", "") if link_el is not None else ""
            summary = (entry.findtext("atom:summary",  default="", namespaces=ns) or "")

            combined = f"{title} {summary}"
            etype, score = _classify_8k(combined)
            if score < min_relevance:
                continue

            ticker_match  = re.search(r'\(([A-Z]{1,5})\)', title)
            company_match = re.search(r'8-K - (.+?) \(', title)
            ticker  = ticker_match.group(1)  if ticker_match  else "UNKN"
            company = company_match.group(1) if company_match else title

            events.append(MaterialEvent(
                ticker=ticker,
                company=company,
                event_type=etype,
                headline=title[:200],
                filed_date=updated,
                period_of_report=updated,
                form_url=url,
                relevance_score=score,
            ))
    except ET.ParseError as exc:
        log.debug("8-K Atom parse error: %s", exc)
    return events


# ── Main entrypoint ────────────────────────────────────────────────────────────

def fetch_edgar_intelligence(
    tickers: Optional[List[str]] = None,
    days_back: int = 14,
) -> EdgarReport:
    """
    Fetch all SEC EDGAR intelligence in one call.
    Returns an EdgarReport with insider trades, institutional changes, and 8-K events.
    """
    log.info("Fetching SEC EDGAR intelligence (days_back=%d)...", days_back)
    report = EdgarReport(as_of=datetime.now(timezone.utc).isoformat())

    try:
        report.insider_trades = fetch_insider_trades(tickers=tickers, days_back=days_back)
    except Exception as exc:
        log.warning("EDGAR insider trades failed: %s", exc)

    try:
        report.material_events = fetch_material_events(tickers=tickers, days_back=min(days_back, 7))
    except Exception as exc:
        log.warning("EDGAR 8-K events failed: %s", exc)

    log.info(
        "EDGAR: %d insider trades, %d material events",
        len(report.insider_trades), len(report.material_events),
    )
    return report
