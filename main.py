#!/usr/bin/env python3
"""
Stock Narrative Engine — Main entry point
=========================================

Usage
-----
  # Run with all defaults (reads .env):
  python main.py

  # Specify sectors:
  python main.py --sectors technology artificial_intelligence crypto

  # Quick mode (RSS only, no market data):
  python main.py --quick

  # Use a specific AI provider:
  python main.py --provider openai

  # Export HTML and open in browser:
  python main.py --html --open

  # Scheduled / headless (no colour output, JSON only):
  python main.py --json-only --no-rich

Full help:
  python main.py --help
"""

import argparse
import logging
import os
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

# ── Allow running from project root without install ──────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

from config import get_config
from src.news.fetcher import fetch_all_news

# ---------------------------------------------------------------------------
# Proxy routing — prefer SOCKS5 over the default HTTP proxy when available,
# because the HTTP proxy (localhost:3128) blocks HTTPS with 403 while the
# SOCKS5 proxy (localhost:1080) allows the Anthropic API endpoint.
# ---------------------------------------------------------------------------
def _configure_proxy() -> None:
    """
    If HTTP_PROXY/HTTPS_PROXY point to localhost:3128 and a SOCKS5 proxy is
    available at localhost:1080, switch all outbound requests to SOCKS5.
    This ensures api.anthropic.com (and any other SOCKS-allowed hosts) are
    reachable even when the HTTP proxy returns 403 Forbidden.
    """
    _SOCKS = "socks5h://localhost:1080"
    _HTTP_BLOCK = "localhost:3128"
    https_proxy = os.environ.get("HTTPS_PROXY", os.environ.get("https_proxy", ""))
    if _HTTP_BLOCK in https_proxy:
        os.environ["HTTP_PROXY"]  = _SOCKS
        os.environ["HTTPS_PROXY"] = _SOCKS
        os.environ["http_proxy"]  = _SOCKS
        os.environ["https_proxy"] = _SOCKS

_configure_proxy()
from src.market.data import get_sector_summary, get_macro_context
from src.ai.synthesizer import synthesize_sector, synthesize_macro
from src.ai.opportunity import detect_opportunities
from src.ai.providers import list_available_providers
from src.congress.fetcher import fetch_all_congress_trades
from src.congress.analyzer import analyse_congress_trades
from src.notifications.notifier import (
    print_report,
    export_json,
    export_html,
    notify_slack,
    notify_email,
    notify_desktop,
    notify_telegram,
)
from src.news.sources import SECTORS
from src.data.sec_edgar import fetch_edgar_intelligence, EdgarReport
from src.data.options_flow import fetch_options_intelligence, OptionsReport
from src.data.sentiment import fetch_sentiment_intelligence, SentimentReport


# ---------------------------------------------------------------------------
# CLI argument parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Stock Narrative Engine — AI-powered market intelligence",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--sectors", nargs="+", metavar="SECTOR",
        choices=SECTORS + ["all"],
        default=None,
        help=f"Sectors to analyse. Choices: {', '.join(SECTORS)}",
    )
    p.add_argument(
        "--provider", default=None,
        choices=["auto", "anthropic", "openai", "gemini", "ollama"],
        help="AI provider to use (default: auto-detect from available keys)",
    )
    p.add_argument("--model",    default=None, help="Override the AI model")
    p.add_argument("--quick",    action="store_true", help="RSS only, skip market data")
    p.add_argument("--html",     action="store_true", help="Export HTML report")
    p.add_argument("--open",     action="store_true", help="Open HTML report in browser")
    p.add_argument("--json-only", action="store_true", help="Skip terminal output, export JSON only")
    p.add_argument("--no-rich",  action="store_true", help="Plain text terminal output")
    p.add_argument("--output-dir", default=None, help="Directory for output files")
    p.add_argument("--max-opps", type=int, default=None, help="Maximum opportunities to surface")
    p.add_argument("--verbose",  action="store_true", help="Debug logging")
    p.add_argument("--list-providers", action="store_true", help="Show available AI providers and exit")
    p.add_argument("--no-congress",    action="store_true", help="Skip congressional trade analysis")
    p.add_argument("--congress-days",  type=int, default=90, help="Days of congress trade history to pull (default: 90)")
    p.add_argument("--watchlist-only", action="store_true", help="Only analyse trades from high-value watchlist politicians")
    p.add_argument("--no-edgar",       action="store_true", help="Skip SEC EDGAR intelligence (insider trades, 8-K)")
    p.add_argument("--no-options",     action="store_true", help="Skip options flow analysis")
    p.add_argument("--no-sentiment",   action="store_true", help="Skip social sentiment analysis")
    p.add_argument("--edgar-days",     type=int, default=14, help="Days of EDGAR history to pull (default: 14)")
    return p


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def run(cfg, args) -> int:
    """
    Full pipeline:
      1. Fetch news
      2. Fetch market data
      3. Synthesise sector narratives
      4. Synthesise macro narrative
      5. Detect opportunities
      6. Output / notify
    """

    sectors = args.sectors or cfg.sectors or SECTORS
    if "all" in sectors:
        sectors = SECTORS

    provider = args.provider or cfg.ai_provider
    model    = args.model    or (cfg.ai_model or None)
    max_opps = args.max_opps or cfg.max_opportunities
    output_dir = args.output_dir or cfg.output_dir
    quick    = args.quick

    log.info("Starting Stock Narrative Engine")
    log.info("Sectors: %s", sectors)
    log.info("Provider: %s", provider)

    # ── Step 1: Fetch news ──────────────────────────────────────────────
    log.info("Fetching news from all sources...")
    articles = fetch_all_news(
        sectors=sectors,
        newsapi_key=cfg.newsapi_key if cfg.fetch_newsapi else "",
        finnhub_key=cfg.finnhub_key if cfg.fetch_finnhub else "",
        alpha_vantage_key=cfg.alpha_vantage_key if cfg.fetch_alpha_vantage else "",
        max_total=cfg.max_articles_total,
    )
    log.info("Fetched %d articles total", len(articles))

    if not articles:
        log.warning(
            "No articles fetched (network/API issue). "
            "Continuing with market data only — AI narratives will reflect limited inputs."
        )

    # ── Step 1b: Congress trade intelligence ──────────────────────────
    congress_report = None
    if not args.no_congress:
        log.info("Fetching congressional trade disclosures (STOCK Act)...")
        try:
            congress_trades = fetch_all_congress_trades(
                days_back=args.congress_days,
                watchlist_only=args.watchlist_only,
            )
            if congress_trades:
                log.info("Analysing %d congress trades...", len(congress_trades))
                congress_report = analyse_congress_trades(
                    trades=congress_trades,
                    days_back=args.congress_days,
                    provider=provider,
                    model=model,
                    **cfg.provider_kwargs(),
                )
                log.info(
                    "Congress: %d trades analysed, %d watchlist",
                    congress_report.total_trades,
                    congress_report.watchlist_trades,
                )
            else:
                log.warning("No congress trades fetched (network or data issue)")
        except Exception as exc:
            log.warning("Congress trade fetch failed: %s", exc)

    # ── Step 1c: SEC EDGAR intelligence ───────────────────────────────
    edgar_report: Optional[EdgarReport] = None
    if not args.no_edgar and not quick:
        log.info("Fetching SEC EDGAR intelligence (insider trades, 8-K)...")
        try:
            edgar_report = fetch_edgar_intelligence(days_back=args.edgar_days)
            log.info(
                "EDGAR: %d insider trades, %d material events",
                len(edgar_report.insider_trades), len(edgar_report.material_events),
            )
        except Exception as exc:
            log.warning("SEC EDGAR fetch failed: %s", exc)

    # ── Step 1d: Options flow intelligence ────────────────────────────
    options_report: Optional[OptionsReport] = None
    if not args.no_options and not quick:
        log.info("Fetching options flow intelligence...")
        try:
            options_report = fetch_options_intelligence()
            log.info(
                "Options: %d unusual contracts, market P/C=%.2f",
                options_report.total_unusual,
                options_report.market_pc_ratio or 0,
            )
        except Exception as exc:
            log.warning("Options flow fetch failed: %s", exc)

    # ── Step 1e: Social sentiment intelligence ─────────────────────────
    sentiment_report: Optional[SentimentReport] = None
    if not args.no_sentiment and not quick:
        log.info("Fetching social sentiment intelligence...")
        try:
            sentiment_report = fetch_sentiment_intelligence()
            log.info(
                "Sentiment: %d tickers, F&G=%s",
                len(sentiment_report.ticker_sentiments),
                sentiment_report.fear_greed.score if sentiment_report.fear_greed else "N/A",
            )
        except Exception as exc:
            log.warning("Sentiment fetch failed: %s", exc)

    # ── Step 2: Market data ────────────────────────────────────────────
    sector_market_data: dict = {}
    macro_data: dict = {}

    if not quick:
        log.info("Fetching market data...")
        for sector in sectors:
            try:
                sector_market_data[sector] = get_sector_summary(
                    sector, top_n=cfg.market_top_n_tickers
                )
            except Exception as exc:
                log.warning("Market data failed for %s: %s", sector, exc)
                sector_market_data[sector] = {}

        if cfg.fetch_macro_context:
            try:
                macro_data = get_macro_context()
            except Exception as exc:
                log.warning("Macro context failed: %s", exc)

    # ── Build supplemental AI context from new intelligence sources ───
    extra_context_parts = []
    if edgar_report and edgar_report.total_items > 0:
        extra_context_parts.append(edgar_report.to_ai_context())
    if options_report and options_report.total_unusual > 0:
        extra_context_parts.append(options_report.to_ai_context())
    if sentiment_report:
        extra_context_parts.append(sentiment_report.to_ai_context())
    extra_context = "\n\n".join(extra_context_parts)

    # ── Step 3: Sector narratives ──────────────────────────────────────
    log.info("Synthesising sector narratives (AI)...")
    sector_narratives = []
    provider_kwargs   = cfg.provider_kwargs()

    for sector in sectors:
        sector_articles = [
            a for a in articles
            if not a.sectors or sector in a.sectors
        ]
        # If sector filter yields nothing, use all articles (better than empty)
        if not sector_articles:
            sector_articles = articles

        log.info("  Sector %s: %d articles", sector, len(sector_articles))
        narrative = synthesize_sector(
            sector=sector,
            articles=sector_articles,
            market_data=sector_market_data.get(sector, {}),
            provider=provider,
            model=model,
            extra_context=extra_context,
            **provider_kwargs,
        )
        sector_narratives.append(narrative)

    # ── Step 4: Macro narrative ────────────────────────────────────────
    log.info("Synthesising macro narrative (AI)...")
    macro_narrative = synthesize_macro(
        sector_narratives=sector_narratives,
        macro_data=macro_data,
        provider=provider,
        model=model,
        extra_context=extra_context,
        **provider_kwargs,
    )

    # ── Step 5: Opportunity detection ──────────────────────────────────
    log.info("Detecting opportunities (AI)...")
    opportunities = detect_opportunities(
        sector_narratives=sector_narratives,
        macro_narrative=macro_narrative,
        sector_market_data=sector_market_data,
        congress_report=congress_report,
        provider=provider,
        model=model,
        max_opportunities=max_opps,
        extra_context=extra_context,
        **provider_kwargs,
    )

    # ── Step 6: Output ─────────────────────────────────────────────────
    stem      = cfg.report_stem()
    out_path  = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    if not args.json_only:
        print_report(
            opportunities=opportunities,
            sector_narratives=sector_narratives,
            macro_narrative=macro_narrative,
            congress_report=congress_report,
            use_rich=not args.no_rich,
        )

    if cfg.export_json:
        json_file = export_json(
            opportunities, sector_narratives, macro_narrative,
            congress_report=congress_report,
            output_path=str(out_path / f"report_{stem}.json"),
        )
        log.info("JSON report: %s", json_file)

    html_file = None
    if cfg.export_html or args.html or args.open:
        html_file = export_html(
            opportunities, sector_narratives, macro_narrative,
            congress_report=congress_report,
            output_path=str(out_path / f"report_{stem}.html"),
        )
        log.info("HTML report: %s", html_file)
        if args.open or cfg.open_html_in_browser:
            webbrowser.open(f"file://{Path(html_file).resolve()}")

    # ── Notifications ──────────────────────────────────────────────────
    if cfg.slack_webhook_url:
        notify_slack(opportunities, macro_narrative, cfg.slack_webhook_url)

    if cfg.email_to:
        notify_email(
            opportunities, macro_narrative,
            to_email=cfg.email_to,
            smtp_host=cfg.smtp_host,
            smtp_port=cfg.smtp_port,
            smtp_user=cfg.smtp_user,
            smtp_password=cfg.smtp_password,
            resend_api_key=cfg.resend_api_key or None,
            congress_report=congress_report,
            edgar_report=edgar_report,
            sentiment_report=sentiment_report,
            options_report=options_report,
        )

    if cfg.telegram_bot_token and cfg.telegram_chat_id:
        notify_telegram(
            opportunities, macro_narrative,
            bot_token=cfg.telegram_bot_token,
            chat_id=cfg.telegram_chat_id,
            congress_report=congress_report,
        )

    if cfg.desktop_notify and opportunities:
        top = opportunities[0]
        notify_desktop(
            title="Stock Narrative Engine",
            message=f"[{top.urgency.upper()}] {top.title} — {top.action[:100]}",
        )

    log.info("Done. %d opportunities surfaced.", len(opportunities))
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = build_parser()
    args   = parser.parse_args()
    cfg    = get_config()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else getattr(logging, cfg.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger("main")

    if args.list_providers:
        available = list_available_providers(**cfg.provider_kwargs())
        print("Available AI providers:", ", ".join(available) if available else "none detected")
        sys.exit(0)

    if not cfg.has_any_ai_key():
        # Check if Ollama is running
        available = list_available_providers(**cfg.provider_kwargs())
        if not available:
            print(
                "\n⚠️  No AI provider found!\n"
                "Set at least one of these in your .env:\n"
                "  ANTHROPIC_API_KEY   → get free at console.anthropic.com\n"
                "  OPENAI_API_KEY      → get at platform.openai.com\n"
                "  GEMINI_API_KEY      → get at aistudio.google.com\n"
                "Or start Ollama locally: https://ollama.ai\n"
            )
            sys.exit(1)

    sys.exit(run(cfg, args))
else:
    # Allow importing as module without executing
    log = logging.getLogger("main")
