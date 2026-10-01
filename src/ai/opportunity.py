"""
Opportunity detection engine.

Analyses sector narratives + market data to identify:
  - Immediate trade opportunities (entry signals)
  - Emerging macro trends worth positioning for
  - Sectors with unusual momentum divergence
  - Specific ticker recommendations with rationale
  - Congress trade signals (STOCK Act disclosures)

Each opportunity is tagged by type, urgency and evidence strength.
"""

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .providers import complete

logger = logging.getLogger(__name__)

# Kept short intentionally — every token in the system prompt is a token
# not available for the JSON response.
OPPORTUNITY_SYSTEM_PROMPT = (
    "You are a hedge fund portfolio manager. "
    "Output ONLY a valid JSON array of investment opportunities. "
    "No prose, no markdown fences, no explanation — raw JSON only. "
    "All string values must be concise (under 120 chars). "
    "For research purposes only; not financial advice."
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Opportunity:
    id: str
    type: str                      # "equity_long", "equity_short", "sector_rotation",
                                   # "thematic", "macro_hedge", "watchlist"
    title: str
    summary: str
    action: str                    # e.g. "Consider buying NVDA on pullbacks"
    tickers: List[str]             # specific tickers involved
    sector: str
    urgency: str                   # "immediate", "short_term", "monitor"
    confidence: float              # 0.0–1.0
    catalysts: List[str]
    risks: List[str]
    evidence_sources: List[str]    # article titles / data points supporting this
    time_horizon: str              # "days", "weeks", "months"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Core detection function
# ---------------------------------------------------------------------------
def detect_opportunities(
    sector_narratives: List[Dict[str, Any]],
    macro_narrative: Dict[str, Any],
    sector_market_data: Dict[str, Any],   # keyed by sector
    congress_report: Optional[Any] = None,  # CongressIntelReport or None
    provider: str = "auto",
    model: Optional[str] = None,
    max_opportunities: int = 10,
    extra_context: str = "",
    **provider_kwargs,
) -> List[Opportunity]:
    """
    Cross-reference all sector narratives + macro view to surface
    actionable opportunities.

    Returns a list of Opportunity objects sorted by confidence × urgency.
    """
    # Build a rich context block for the AI
    sectors_block  = _format_sector_narratives(sector_narratives)
    macro_block    = _format_macro(macro_narrative)
    market_block   = _format_market_summary(sector_market_data)
    congress_block = _format_congress(congress_report)

    extra_block = f"ALTERNATIVE INTELLIGENCE:\n{extra_context}\n\n" if extra_context else ""

    user_prompt = (
        f"MACRO: {macro_block}\n\n"
        f"SECTORS:\n{sectors_block}\n\n"
        f"MARKET MOMENTUM:\n{market_block}\n\n"
        f"CONGRESS SIGNALS:\n{congress_block}\n\n"
        f"{extra_block}"
        f"Return a JSON array of the top {max_opportunities} opportunities. "
        f"Each object must have exactly these keys — keep every string under 100 chars:\n"
        f'{{"id":"opp_1","type":"equity_long|equity_short|sector_rotation|thematic|macro_hedge|watchlist",'
        f'"title":"...","summary":"...","action":"...","tickers":["TICK"],'
        f'"sector":"...","urgency":"immediate|short_term|monitor","confidence":0.0,'
        f'"catalysts":["..."],"risks":["..."],"evidence_sources":["..."],"time_horizon":"days|weeks|months"}}\n'
        f"Rank highest confidence×urgency first. Raw JSON array only."
    )

    raw = complete(
        system_prompt=OPPORTUNITY_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        provider=provider,
        model=model,
        temperature=0.2,
        max_tokens=4096,
        **provider_kwargs,
    )

    raw_list = _parse_json_list(raw)
    opportunities = []
    for item in raw_list:
        try:
            opp = Opportunity(
                id=item.get("id", f"opp_{len(opportunities)+1}"),
                type=item.get("type", "watchlist"),
                title=item.get("title", ""),
                summary=item.get("summary", ""),
                action=item.get("action", ""),
                tickers=item.get("tickers", []),
                sector=item.get("sector", "macro"),
                urgency=item.get("urgency", "monitor"),
                confidence=float(item.get("confidence", 0.5)),
                catalysts=item.get("catalysts", []),
                risks=item.get("risks", []),
                evidence_sources=item.get("evidence_sources", []),
                time_horizon=item.get("time_horizon", "weeks"),
            )
            opportunities.append(opp)
        except Exception as exc:
            logger.warning("Failed to parse opportunity item: %s — %s", item, exc)

    # Sort: immediate + high confidence first
    urgency_rank = {"immediate": 3, "short_term": 2, "monitor": 1}
    opportunities.sort(
        key=lambda o: (urgency_rank.get(o.urgency, 0) * o.confidence),
        reverse=True,
    )

    logger.info("Detected %d opportunities", len(opportunities))
    return opportunities[:max_opportunities]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _format_sector_narratives(narratives: List[Dict[str, Any]]) -> str:
    lines = []
    for n in narratives:
        if "error" in n:
            continue
        lines.append(
            f"### {n.get('sector', '?').upper()}\n"
            f"Sentiment: {n.get('sentiment')}  (confidence: {n.get('confidence')})\n"
            f"One-liner: {n.get('summary_one_liner', '')}\n"
            f"Themes: {', '.join(n.get('themes', []))}\n"
            f"Catalysts: {', '.join(n.get('key_catalysts', []))}\n"
            f"Risks: {', '.join(n.get('risk_flags', []))}"
        )
    return "\n\n".join(lines)


def _format_macro(macro: Dict[str, Any]) -> str:
    if not macro:
        return "No macro narrative available."
    return (
        f"Overall Market: {macro.get('overall_sentiment', 'unknown')}\n"
        f"Dominant Theme: {macro.get('dominant_theme', '')}\n"
        f"Rotation Signals: {', '.join(macro.get('rotation_signals', []))}\n"
        f"Macro Risks: {', '.join(macro.get('macro_risks', []))}"
    )


def _format_market_summary(sector_market_data: Dict[str, Any]) -> str:
    lines = []
    for sector, data in sector_market_data.items():
        if not isinstance(data, dict):
            continue
        momentum = data.get("momentum_label", "unknown")
        avg_1m   = data.get("avg_1m_momentum")
        etf      = (data.get("etf") or {}).get("symbol", "?")
        lines.append(f"  {sector}: momentum={momentum}  avg_1m={avg_1m}%  ETF={etf}")
    return "\n".join(lines) or "No market data."


def _format_congress(congress_report: Optional[Any]) -> str:
    """Format CongressIntelReport for inclusion in the AI prompt."""
    if not congress_report:
        return "No congressional trading data available."
    try:
        lines = [
            f"Analysed {congress_report.total_trades} trades "
            f"({congress_report.watchlist_trades} from high-value watchlist politicians)\n"
        ]
        # Sector signals
        lines.append("Sector signals from congress activity:")
        for sector, sig in sorted(
            congress_report.sector_signals.items(),
            key=lambda x: x[1].net_score, reverse=True
        ):
            lines.append(
                f"  {sector}: {sig.signal_label}  "
                f"(score={sig.net_score:+.2f}, buys={sig.buy_count}, sells={sig.sell_count})"
            )
        # Top ticker signals
        lines.append("\nTop ticker buy signals:")
        for sig in congress_report.top_ticker_signals[:8]:
            if sig.net_score > 0:
                lines.append(
                    f"  {sig.ticker} ({sig.sector}): score={sig.net_score:+.2f}  "
                    f"{sig.total_traders} politicians  "
                    f"bipartisan={'YES' if sig.bipartisan else 'no'}  "
                    f"watchlist buyers: {', '.join(sig.watchlist_buyers) or 'none'}"
                )
        # Watchlist highlights
        if congress_report.watchlist_highlights:
            lines.append("\nNotable watchlist politician trades:")
            for h in congress_report.watchlist_highlights[:5]:
                lines.append(
                    f"  {h['politician']} ({h['party']}): "
                    f"bought {h['tickers_bought']}, sold {h['tickers_sold']}"
                )
        return "\n".join(lines)
    except Exception:
        return "Congress data parsing error."


def _parse_json_list(raw: str) -> List[Dict[str, Any]]:
    """
    Parse the model's output into a list of dicts.

    Attempt order:
      1. Direct json.loads  — works when output is clean
      2. _repair_json       — fixes truncated / malformed output
      3. Regex object sweep — pulls any complete {...} objects from debris
    """
    text = _strip_fences(raw)

    # ── 1. Clean parse ────────────────────────────────────────────────
    try:
        parsed = json.loads(text)
        return _ensure_list(parsed)
    except json.JSONDecodeError:
        pass

    # ── 2. Repair then parse ──────────────────────────────────────────
    repaired = _repair_json(text)
    if repaired:
        try:
            parsed = json.loads(repaired)
            logger.info("JSON recovered via repair function")
            return _ensure_list(parsed)
        except json.JSONDecodeError as exc:
            logger.warning("Repair attempt still invalid: %s", exc)

    # ── 3. Regex sweep for complete objects ───────────────────────────
    salvaged = _salvage_objects(text)
    if salvaged:
        logger.info("Salvaged %d partial objects via regex sweep", len(salvaged))
        return salvaged

    logger.warning("All JSON recovery strategies failed — returning empty list")
    return []


# ---------------------------------------------------------------------------
# JSON repair helpers
# ---------------------------------------------------------------------------

def _strip_fences(text: str) -> str:
    """Remove markdown code fences and leading/trailing whitespace."""
    text = text.strip()
    if text.startswith("```"):
        # grab the content between the first and last fence
        inner = re.split(r"```(?:json)?", text)
        text = inner[1] if len(inner) > 1 else inner[0]
    return text.strip().rstrip("`").strip()


def _ensure_list(parsed: Any) -> List[Dict[str, Any]]:
    if isinstance(parsed, list):
        return [p for p in parsed if isinstance(p, dict)]
    if isinstance(parsed, dict):
        return parsed.get("opportunities") or [parsed]
    return []


def _repair_json(text: str) -> str:
    """
    Attempt to close off a truncated JSON string/array/object so it
    becomes parseable.  Handles the most common model truncation patterns:

      • Unterminated string  →  close the string
      • Trailing comma       →  remove before closing bracket
      • Unclosed object(s)   →  add missing } braces
      • Unclosed array       →  add missing ]
    """
    if not text:
        return text

    # ── Step 1: find where the JSON structure starts ──────────────────
    start = 0
    for i, ch in enumerate(text):
        if ch in ("[", "{"):
            start = i
            break
    text = text[start:]

    # ── Step 2: close an unterminated string ──────────────────────────
    # Count unescaped double-quotes; odd count means we're inside a string
    in_string = False
    escaped   = False
    for ch in text:
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string

    if in_string:
        # Truncated mid-string — close it, then strip any partial key/value
        text = text.rstrip()
        # Remove incomplete trailing fragment (partial word after last quote)
        text = re.sub(r',\s*"[^"]*$', '', text)   # partial key at end
        text += '"'                                 # close the string

    # ── Step 3: remove trailing commas before closing tokens ──────────
    text = re.sub(r',\s*([}\]])', r'\1', text)

    # ── Step 4: balance braces and brackets ───────────────────────────
    opens  = text.count('{') - text.count('}')
    arrays = text.count('[') - text.count(']')

    # Close any open objects first, then array
    text = text.rstrip().rstrip(',')
    text += '}' * max(0, opens)
    text += ']' * max(0, arrays)

    return text


def _salvage_objects(text: str) -> List[Dict[str, Any]]:
    """
    Last-resort: use regex to extract every complete {...} JSON object
    from the raw text, ignoring surrounding debris.
    """
    results = []
    # Match top-level objects (non-greedy, handles nested braces up to depth 3)
    pattern = re.compile(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\}', re.DOTALL)
    for match in pattern.finditer(text):
        candidate = match.group(0)
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict) and obj:
                results.append(obj)
        except json.JSONDecodeError:
            continue
    return results
