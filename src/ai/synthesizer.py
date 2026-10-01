"""
Narrative synthesis engine.

Takes a batch of articles + market data for a sector and produces:
  1. A sector narrative   — what's really happening and why
  2. Key themes           — 3-5 bullet themes driving the sector
  3. Sentiment rating     — Bullish / Neutral / Bearish + confidence
  4. Risk flags           — headwinds or landmines to watch
"""

import json
import logging
from typing import Any, Dict, List, Optional

from ..news.fetcher import Article
from .providers import complete

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a financial market analyst. "
    "Output ONLY a valid JSON object — no prose, no markdown fences, no explanation. "
    "Every key in the schema is required. Use concise, specific language. "
    "Give a clear directional view; never be vague or hedge excessively."
)


# ---------------------------------------------------------------------------
# Core synthesis function
# ---------------------------------------------------------------------------
def synthesize_sector(
    sector: str,
    articles: List[Article],
    market_data: Dict[str, Any],
    provider: str = "auto",
    model: Optional[str] = None,
    extra_context: str = "",
    **provider_kwargs,
) -> Dict[str, Any]:
    """
    Synthesise news + market data for one sector into a structured narrative.

    Returns a dict with keys:
      sector, narrative, themes, sentiment, confidence, risk_flags,
      top_articles, provider_used
    """
    if not articles:
        logger.warning("No articles for sector '%s' — skipping synthesis", sector)
        return {"sector": sector, "error": "no articles"}

    article_blurbs = _format_articles(articles[:30])  # top 30 to stay in token budget
    market_blurb   = _format_market(market_data)
    extra_block    = f"\n## Alternative Intelligence\n{extra_context}\n" if extra_context else ""

    user_prompt = f"""SECTOR: {sector.upper().replace("_", " ")}

NEWS (most recent first):
{article_blurbs}

MARKET DATA:
{market_blurb}
{extra_block}
TASK: Analyse the sector and return a JSON object with EXACTLY these keys:

{{"narrative":"<2-4 paragraphs: what is happening, why, and what it means for investors>","themes":["<theme 1>","<theme 2>","<theme 3>"],"sentiment":"Bullish","confidence":0.72,"risk_flags":["<risk>","<risk>"],"key_catalysts":["<catalyst>","<catalyst>"],"time_horizon":"short_term","summary_one_liner":"<one punchy sentence>"}}

sentiment must be exactly one of: Bullish | Neutral | Bearish
time_horizon must be exactly one of: immediate | short_term | medium_term
confidence must be a float between 0.0 and 1.0
CRITICAL: output the JSON object only — no markdown, no explanation, no preamble."""

    raw = complete(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        provider=provider,
        model=model,
        temperature=0.15,   # lower = more consistent JSON structure
        max_tokens=1024,    # Haiku is concise; 1024 is ample for this schema
        **provider_kwargs,
    )

    result = _parse_json(raw)
    result["sector"] = sector
    result["article_count"] = len(articles)
    result["top_articles"] = [
        {"title": a.title, "source": a.source, "url": a.url}
        for a in articles[:5]
    ]

    return result


# ---------------------------------------------------------------------------
# Cross-sector macro synthesis
# ---------------------------------------------------------------------------
def synthesize_macro(
    sector_narratives: List[Dict[str, Any]],
    macro_data: Dict[str, Any],
    provider: str = "auto",
    model: Optional[str] = None,
    extra_context: str = "",
    **provider_kwargs,
) -> Dict[str, Any]:
    """
    Roll up individual sector narratives into a top-down market narrative.
    """
    sectors_block = "\n\n".join(
        f"[{n.get('sector', 'unknown').upper()}]\n"
        f"Sentiment: {n.get('sentiment', 'N/A')}  |  "
        f"One-liner: {n.get('summary_one_liner', '')}\n"
        f"Themes: {', '.join(n.get('themes', []))}"
        for n in sector_narratives
        if "error" not in n
    )

    macro_blurb = _format_market(macro_data)
    extra_block = f"\n## Alternative Intelligence (Insider Trades, Options Flow, Sentiment)\n{extra_context}\n" if extra_context else ""

    user_prompt = f"""SECTOR NARRATIVES:
{sectors_block}

MACRO CONTEXT:
{macro_blurb}
{extra_block}
TASK: Write a top-down market narrative tying all sectors together.
Return a JSON object with EXACTLY these keys:

{{"market_narrative":"<2-3 paragraphs: macro picture, inter-sector dynamics, investor implications>","dominant_theme":"<single biggest market theme right now>","rotation_signals":["<e.g. money rotating from tech to energy>"],"overall_sentiment":"Risk-On","macro_risks":["<risk>","<risk>"],"time_horizon":"short_term"}}

overall_sentiment must be exactly one of: Risk-On | Neutral | Risk-Off
time_horizon must be exactly one of: immediate | short_term | medium_term
CRITICAL: output the JSON object only — no markdown, no explanation, no preamble."""

    raw = complete(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        provider=provider,
        model=model,
        temperature=0.15,
        max_tokens=900,
        **provider_kwargs,
    )

    result = _parse_json(raw)
    result["sectors_analysed"] = [n.get("sector") for n in sector_narratives]
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _format_articles(articles: List[Article]) -> str:
    lines = []
    for i, a in enumerate(articles, 1):
        lines.append(
            f"{i}. [{a.source}] {a.title}\n"
            f"   {a.summary[:200]}{'...' if len(a.summary) > 200 else ''}"
        )
    return "\n".join(lines)


def _format_market(market_data: Dict[str, Any]) -> str:
    if not market_data:
        return "No market data available."

    lines = []
    # Sector summary format
    if "etf" in market_data:
        etf = market_data.get("etf") or {}
        momentum = market_data.get("avg_1m_momentum")
        lines.append(
            f"Sector ETF ({etf.get('symbol', '?')}): "
            f"${etf.get('price', '?')}  "
            f"1m: {etf.get('change_1m', '?')}%  "
            f"Momentum: {market_data.get('momentum_label', '?')}"
        )
        for c in market_data.get("top_constituents", []):
            lines.append(
                f"  {c.get('symbol')}: ${c.get('price')}  "
                f"1d: {c.get('change_1d')}%  1m: {c.get('change_1m')}%"
            )
    # Macro format
    else:
        for sym, snap in market_data.items():
            if isinstance(snap, dict):
                lines.append(
                    f"  {snap.get('label', sym)} ({sym}): "
                    f"${snap.get('price')}  "
                    f"1d: {snap.get('change_1d')}%  "
                    f"1m: {snap.get('change_1m')}%"
                )

    return "\n".join(lines) or "Market data unavailable."


def _parse_json(raw: str) -> Dict[str, Any]:
    """Extract JSON from model output even if it includes surrounding text."""
    text = raw.strip()
    # Strip possible markdown code fences
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip().rstrip("`").strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("JSON parse failed, returning raw text: %s", exc)
        return {"raw_response": raw, "parse_error": str(exc)}
