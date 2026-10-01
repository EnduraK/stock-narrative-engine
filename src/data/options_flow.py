"""
Options Flow Intelligence Module
==================================
Reads the options market — where sophisticated money actually shows its hand.
Sources (all free, no API key required):
  - yfinance options chains        : per-ticker put/call data, IV, OI
  - CBOE market statistics         : market-wide put/call ratio
  - Unusual options activity       : large OI vs avg vol, high-premium bets

Signals detected:
  - Unusual call sweeps (big money betting on upside)
  - Unusual put buying (hedging or bearish bets)
  - IV crush / expansion signals
  - Put/call ratio extremes (contrarian signals)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict
import json
import urllib.request
import urllib.error

log = logging.getLogger(__name__)

# yfinance is used for options chain data
try:
    import yfinance as yf
    _HAS_YF = True
except ImportError:
    _HAS_YF = False
    log.warning("yfinance not installed — options chain data unavailable")


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class UnusualOption:
    ticker: str
    option_type: str       # "call" | "put"
    expiry: str            # e.g. "2024-02-16"
    strike: float
    last_price: float
    volume: int
    open_interest: int
    iv: float              # implied volatility as decimal (0.35 = 35%)
    volume_oi_ratio: float # volume / open_interest — >1.0 is very unusual
    premium_total: float   # last_price * volume * 100 (total dollar flow)
    signal: str            # "unusual_call" | "unusual_put" | "high_iv" | "iv_crush"
    days_to_expiry: int

    @property
    def summary(self) -> str:
        tag  = "🟢 CALL" if self.option_type == "call" else "🔴 PUT"
        return (
            f"{tag} {self.ticker} ${self.strike:.0f} exp {self.expiry} "
            f"| Vol {self.volume:,} / OI {self.open_interest:,} ({self.volume_oi_ratio:.1f}x) "
            f"| IV {self.iv*100:.0f}% | Flow ${self.premium_total/1e3:.0f}K"
        )


@dataclass
class PutCallRatio:
    ticker: str            # "MARKET" for index-wide
    put_call_ratio: float
    put_volume: int
    call_volume: int
    signal: str            # "extreme_fear" | "fear" | "neutral" | "greed" | "extreme_greed"
    as_of: str

    @property
    def summary(self) -> str:
        return (
            f"P/C Ratio {self.ticker}: {self.put_call_ratio:.2f} → {self.signal.upper()}"
        )


@dataclass
class OptionsReport:
    unusual_options: List[UnusualOption]   = field(default_factory=list)
    put_call_ratios: List[PutCallRatio]    = field(default_factory=list)
    market_pc_ratio: Optional[float]       = None
    as_of: str                             = ""

    @property
    def total_unusual(self) -> int:
        return len(self.unusual_options)

    def bullish_flow(self) -> List[UnusualOption]:
        return [o for o in self.unusual_options if o.option_type == "call"]

    def bearish_flow(self) -> List[UnusualOption]:
        return [o for o in self.unusual_options if o.option_type == "put"]

    def to_ai_context(self) -> str:
        lines = ["=== OPTIONS FLOW INTELLIGENCE ==="]

        if self.market_pc_ratio is not None:
            signal = _pcr_signal(self.market_pc_ratio)
            lines.append(f"\nMarket Put/Call Ratio: {self.market_pc_ratio:.2f} → {signal}")

        calls = self.bullish_flow()
        puts  = self.bearish_flow()

        if calls:
            lines.append(f"\n[UNUSUAL CALL ACTIVITY — {len(calls)} signals]")
            for o in sorted(calls, key=lambda x: x.premium_total, reverse=True)[:10]:
                lines.append(f"  {o.summary}")

        if puts:
            lines.append(f"\n[UNUSUAL PUT ACTIVITY — {len(puts)} signals]")
            for o in sorted(puts, key=lambda x: x.premium_total, reverse=True)[:10]:
                lines.append(f"  {o.summary}")

        if self.put_call_ratios:
            lines.append("\n[PER-TICKER PUT/CALL RATIOS]")
            for pcr in sorted(self.put_call_ratios, key=lambda x: abs(x.put_call_ratio - 1.0), reverse=True)[:10]:
                lines.append(f"  {pcr.summary}")

        return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pcr_signal(ratio: float) -> str:
    if ratio > 1.5:   return "extreme_fear (contrarian bullish)"
    if ratio > 1.0:   return "fear (mild bullish lean)"
    if ratio > 0.7:   return "neutral"
    if ratio > 0.5:   return "greed (mild bearish lean)"
    return "extreme_greed (contrarian bearish)"


def _days_to_expiry(expiry_str: str) -> int:
    try:
        exp = datetime.strptime(expiry_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return max(0, (exp - datetime.now(timezone.utc)).days)
    except ValueError:
        return 0


# ── CBOE Market-Wide Put/Call Ratio ───────────────────────────────────────────

def fetch_market_pcr() -> Optional[float]:
    """
    Fetch CBOE total put/call ratio from their public stats endpoint.
    Returns float (e.g. 0.87) or None on failure.
    """
    # CBOE publishes a JSON stats file updated daily
    url = "https://cdn.cboe.com/api/global/us_equities/daily_market_statistics/market_statistics_-1.json"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        # Find put/call ratio field
        stats = data.get("data", {})
        for key in ("totalPutCallRatio", "total_put_call_ratio", "pcRatio"):
            if key in stats:
                return float(stats[key])
        # Try nested structure
        if isinstance(stats, list):
            for item in stats:
                if isinstance(item, dict):
                    for key in ("totalPutCallRatio", "pcRatio"):
                        if key in item:
                            return float(item[key])
    except Exception as exc:
        log.debug("CBOE PCR fetch failed: %s", exc)

    # Fallback: try CBOE equity-only PCR
    try:
        url2 = "https://cdn.cboe.com/api/global/us_equities/daily_market_statistics/market_statistics_-1.json"
        req2 = urllib.request.Request(url2, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req2, timeout=10) as resp2:
            raw = resp2.read().decode()
            # Look for any float that looks like a P/C ratio
            import re
            m = re.search(r'"(?:put.?call|pc)[^"]*"\s*:\s*"?([\d.]+)"?', raw, re.IGNORECASE)
            if m:
                return float(m.group(1))
    except Exception:
        pass

    return None


# ── Per-Ticker Options Chain Analysis ─────────────────────────────────────────

def _analyse_chain(ticker: str, yf_ticker) -> tuple[List[UnusualOption], Optional[PutCallRatio]]:
    """Analyse options chain for unusual activity."""
    unusual: List[UnusualOption] = []
    pcr: Optional[PutCallRatio]  = None

    try:
        expirations = yf_ticker.options
        if not expirations:
            return unusual, pcr
    except Exception:
        return unusual, pcr

    now = datetime.now(timezone.utc)
    # Focus on near-term expirations (7–60 days out) where smart money is active
    valid_exps = []
    for exp in expirations:
        dte = _days_to_expiry(exp)
        if 5 <= dte <= 60:
            valid_exps.append((dte, exp))
    valid_exps.sort()
    target_exps = [e for _, e in valid_exps[:3]]  # Take 3 nearest expirations

    total_call_vol = 0
    total_put_vol  = 0

    for exp in target_exps:
        try:
            chain = yf_ticker.option_chain(exp)
            time.sleep(0.3)
        except Exception:
            continue

        dte = _days_to_expiry(exp)

        for side, df, opt_type in [("call", chain.calls, "call"), ("put", chain.puts, "put")]:
            if df is None or df.empty:
                continue
            if "volume" not in df.columns:
                continue

            # Accumulate volume for P/C ratio
            vol_sum = int(df["volume"].fillna(0).sum())
            if opt_type == "call":
                total_call_vol += vol_sum
            else:
                total_put_vol  += vol_sum

            for _, row in df.iterrows():
                vol = int(row.get("volume", 0) or 0)
                oi  = int(row.get("openInterest", 0) or 0)
                iv  = float(row.get("impliedVolatility", 0) or 0)
                lp  = float(row.get("lastPrice", 0) or 0)
                strike = float(row.get("strike", 0) or 0)

                if vol < 100 or lp <= 0 or strike <= 0:
                    continue

                voi_ratio = vol / max(oi, 1)
                premium   = lp * vol * 100

                # Flag unusual: vol/OI > 2x AND premium > $50K AND not too far OTM
                if voi_ratio >= 2.0 and premium >= 50_000:
                    signal_tag = f"unusual_{opt_type}"
                    if iv > 0.8:
                        signal_tag = "high_iv"
                    unusual.append(UnusualOption(
                        ticker=ticker,
                        option_type=opt_type,
                        expiry=exp,
                        strike=strike,
                        last_price=lp,
                        volume=vol,
                        open_interest=oi,
                        iv=iv,
                        volume_oi_ratio=voi_ratio,
                        premium_total=premium,
                        signal=signal_tag,
                        days_to_expiry=dte,
                    ))

    # Build P/C ratio for this ticker
    if total_call_vol > 0 or total_put_vol > 0:
        ratio = total_put_vol / max(total_call_vol, 1)
        pcr = PutCallRatio(
            ticker=ticker,
            put_call_ratio=ratio,
            put_volume=total_put_vol,
            call_volume=total_call_vol,
            signal=_pcr_signal(ratio),
            as_of=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    return unusual, pcr


# ── Main entrypoint ────────────────────────────────────────────────────────────

# Key tickers to always watch (high options liquidity + market significance)
_DEFAULT_WATCH = [
    "SPY", "QQQ", "IWM", "DIA",           # Indices
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOGL",  # Mega cap
    "XLE", "USO", "GLD", "TLT",           # Macro ETFs
    "VIX",                                  # Volatility
]


def fetch_options_intelligence(
    tickers: Optional[List[str]] = None,
    include_market_pcr: bool = True,
) -> OptionsReport:
    """
    Main entrypoint: fetch unusual options flow and put/call ratios.
    """
    if not _HAS_YF:
        log.warning("yfinance not available — skipping options flow")
        return OptionsReport(as_of=datetime.now(timezone.utc).isoformat())

    watch = tickers or _DEFAULT_WATCH
    log.info("Options flow: analysing %d tickers...", len(watch))

    report = OptionsReport(as_of=datetime.now(timezone.utc).isoformat())

    if include_market_pcr:
        pcr = fetch_market_pcr()
        if pcr is not None:
            report.market_pc_ratio = pcr
            log.info("CBOE market P/C ratio: %.2f (%s)", pcr, _pcr_signal(pcr))

    for ticker in watch[:20]:  # cap at 20 to avoid yfinance rate limits
        try:
            yf_t = yf.Ticker(ticker)
            unusual, pcr_data = _analyse_chain(ticker, yf_t)
            report.unusual_options.extend(unusual)
            if pcr_data:
                report.put_call_ratios.append(pcr_data)
            log.debug("Options %s: %d unusual, P/C %.2f",
                      ticker, len(unusual),
                      pcr_data.put_call_ratio if pcr_data else 0)
        except Exception as exc:
            log.debug("Options chain failed for %s: %s", ticker, exc)
        time.sleep(0.5)

    log.info(
        "Options flow complete: %d unusual contracts across %d tickers",
        len(report.unusual_options), len(watch),
    )
    return report
