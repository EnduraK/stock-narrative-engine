"""
Notification & report engine.

Outputs via:
  1. Terminal (rich)   2. JSON export   3. HTML report (charts)
  4. Email (SMTP)      5. Slack webhook 6. Desktop notification
"""
import json, logging, smtplib, textwrap
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from ..ai.opportunity import Opportunity
from .html_builder import build_html

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Terminal output
# ---------------------------------------------------------------------------
def print_report(opportunities, sector_narratives, macro_narrative, congress_report=None, use_rich=True):
    try:
        if use_rich:
            _print_rich(opportunities, sector_narratives, macro_narrative, congress_report)
        else:
            _print_plain(opportunities, sector_narratives, macro_narrative, congress_report)
    except ImportError:
        _print_plain(opportunities, sector_narratives, macro_narrative, congress_report)


def _print_rich(opps, narratives, macro, cr=None):
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich import box
    console = Console()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    console.print(Panel.fit(f"[bold cyan]STOCK NARRATIVE ENGINE[/bold cyan]\n[dim]{now}[/dim]", border_style="cyan"))

    if macro and "error" not in macro:
        sc = {"Risk-On":"green","Neutral":"yellow","Risk-Off":"red"}.get(macro.get("overall_sentiment","Neutral"),"white")
        console.print(Panel(
            f"[bold]Overall Market:[/bold] [{sc}]{macro.get('overall_sentiment')}[/{sc}]\n"
            f"[bold]Dominant Theme:[/bold] {macro.get('dominant_theme','')}\n\n{macro.get('market_narrative','')}",
            title="[bold]MACRO NARRATIVE[/bold]", border_style="blue"))

    for n in narratives:
        if "error" in n: continue
        color = {"Bullish":"green","Bearish":"red","Neutral":"yellow"}.get(n.get("sentiment","Neutral"),"white")
        console.print(Panel(
            f"[bold]Sentiment:[/bold] [{color}]{n.get('sentiment')}[/{color}] ({n.get('confidence',0):.0%})\n"
            f"[bold]One-liner:[/bold] {n.get('summary_one_liner','')}\n\n{n.get('narrative','')[:600]}...",
            title=f"[bold]{n.get('sector','').upper().replace('_',' ')}[/bold]", border_style=color))

    if opps:
        t = Table(title="INVESTMENT OPPORTUNITIES", box=box.ROUNDED, header_style="bold magenta", show_lines=True)
        for col,w in [("#",3),("Type",14),("Title",35),("Action",40),("Tickers",14),("Urgency",10),("Confidence",10)]:
            t.add_column(col, width=w)
        us_map = {"immediate":"bold red","short_term":"yellow","monitor":"dim"}
        for i,opp in enumerate(opps,1):
            us = us_map.get(opp.urgency,"white")
            t.add_row(str(i),opp.type.replace("_","\n"),opp.title,textwrap.fill(opp.action,38),
                      " ".join(opp.tickers[:3]),f"[{us}]{opp.urgency}[/{us}]",f"{opp.confidence:.0%}")
        console.print(t)

    if cr and cr.total_trades > 0:
        ct = Table(title=f"CONGRESSIONAL TRADES ({cr.total_trades} trades, {cr.days_analysed} days)",
                   box=box.ROUNDED, header_style="bold yellow", show_lines=True)
        for col,w in [("Sector",22),("Signal",12),("Buys",6),("Sells",6),("Top Tickers",30)]: ct.add_column(col,width=w)
        lm = {"Strong Buy":"bold green","Buy":"green","Neutral":"yellow","Sell":"red","Strong Sell":"bold red"}
        for sector,sig in sorted(cr.sector_signals.items(),key=lambda x:x[1].net_score,reverse=True):
            ls = lm.get(sig.signal_label,"white")
            ct.add_row(sector.replace("_"," ").title(),f"[{ls}]{sig.signal_label}[/{ls}]",
                       str(sig.buy_count),str(sig.sell_count),
                       ", ".join(t.ticker for t in sig.top_tickers[:4] if t.net_score>0))
        console.print(ct)
        if cr.watchlist_highlights:
            wl = []
            for h in cr.watchlist_highlights[:5]:
                wl.append(f"  [bold]{h['politician']}[/bold] ({h['party']}, {h['chamber'].title()})  "
                           f"[green]▲ {', '.join(h['tickers_bought'][:4]) or '—'}[/green]  "
                           f"[red]▼ {', '.join(h['tickers_sold'][:4]) or '—'}[/red]")
            console.print(Panel("\n".join(wl),title="[bold yellow]Watchlist Politician Activity[/bold yellow]",border_style="yellow"))
        if cr.ai_narrative:
            console.print(Panel(cr.ai_narrative[:700]+"...",title="[bold]Congress Trade Interpretation[/bold]",border_style="yellow"))
    console.rule("[dim]End of Report[/dim]")


def _print_plain(opps, narratives, macro, cr=None):
    sep = "="*70
    print(sep, "STOCK NARRATIVE ENGINE", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), sep, sep="\n")
    if macro and "error" not in macro:
        print(f"\n[MACRO] {macro.get('overall_sentiment')} | {macro.get('dominant_theme')}")
    for n in narratives:
        if "error" not in n:
            print(f"\n[{n.get('sector','').upper()}] {n.get('sentiment')} — {n.get('summary_one_liner','')}")
    print("\nTOP OPPORTUNITIES:")
    for i,opp in enumerate(opps,1):
        print(f"\n  {i}. [{opp.urgency.upper()}] {opp.title}")
        print(f"     Action: {opp.action}")
        print(f"     Tickers: {', '.join(opp.tickers)}")
        print(f"     Confidence: {opp.confidence:.0%}")
    if cr and cr.total_trades > 0:
        print(f"\nCONGRESS TRADES ({cr.total_trades} trades):")
        for sector,sig in sorted(cr.sector_signals.items(),key=lambda x:x[1].net_score,reverse=True):
            print(f"  {sector}: {sig.signal_label} (buys={sig.buy_count}, sells={sig.sell_count})")


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------
def export_json(opportunities, sector_narratives, macro_narrative, congress_report=None, output_path="report.json"):
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "macro": macro_narrative,
        "sectors": sector_narratives,
        "opportunities": [o.to_dict() for o in opportunities],
        "congress": congress_report.to_dict() if congress_report else None,
    }
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))
    logger.info("JSON report saved to %s", path)
    return str(path)


# ---------------------------------------------------------------------------
# HTML export
# ---------------------------------------------------------------------------
def export_html(opportunities, sector_narratives, macro_narrative, congress_report=None, output_path="report.html"):
    html = build_html(opportunities, sector_narratives, macro_narrative, congress_report)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    logger.info("HTML report saved to %s", path)
    return str(path)


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------
def notify_slack(opportunities, macro_narrative, webhook_url):
    if not webhook_url: return False
    blocks = [
        {"type":"header","text":{"type":"plain_text","text":"Stock Narrative Engine Report"}},
        {"type":"section","text":{"type":"mrkdwn","text":f"*Market:* {macro_narrative.get('overall_sentiment','?')} | *Theme:* {macro_narrative.get('dominant_theme','?')}"}},
        {"type":"divider"},
    ]
    for opp in opportunities[:3]:
        blocks.append({"type":"section","text":{"type":"mrkdwn",
            "text":f"*{opp.title}*\n{opp.action}\nTickers: `{'` `'.join(opp.tickers)}`  |  Confidence: {opp.confidence:.0%}  |  Urgency: {opp.urgency}"}})
    try:
        requests.post(webhook_url, json={"blocks":blocks}, timeout=10).raise_for_status()
        logger.info("Slack notification sent"); return True
    except Exception as exc:
        logger.warning("Slack notification failed: %s", exc); return False


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Email section builders — each wrapped by caller in try/except
# ---------------------------------------------------------------------------

def _build_sentiment_section(sentiment_report, options_report):
    # ── Fear & Greed + Options flow ────────────────────────────────────
    sentiment_section = ""
    if sentiment_report:
        fg = sentiment_report.fear_greed
        fg_score = fg.score if fg else None
        fg_label = fg.label if fg else "—"
        fg_prev  = fg.prev_week if fg else None

        if fg_score is not None:
            gauge_color = ("#ef4444" if fg_score <= 25 else
                           "#f97316" if fg_score <= 45 else
                           "#eab308" if fg_score <= 55 else
                           "#84cc16" if fg_score <= 75 else "#22c55e")
            pct_bar = int(fg_score)
            week_delta = ""
            if fg_prev is not None:
                delta = fg_score - fg_prev
                arrow = "▲" if delta > 0 else "▼"
                clr   = "#22c55e" if delta > 0 else "#ef4444"
                week_delta = f'<span style="color:{clr};font-size:11px;margin-left:8px">{arrow} {abs(delta):.0f} vs last week</span>'

            # Top ticker sentiments
            ticker_rows = ""
            for ts in (sentiment_report.ticker_sentiments or [])[:6]:
                sc = "#22c55e" if ts.score > 0.2 else "#ef4444" if ts.score < -0.2 else "#eab308"
                trend_tag = " 🔥" if ts.trending else ""
                ticker_rows += (
                    f'<div style="display:flex;justify-content:space-between;padding:4px 0;'
                    f'border-bottom:1px solid rgba(255,255,255,0.04)">'
                    f'<span style="font-family:monospace;color:#93c5fd;font-size:12px">{ts.ticker}{trend_tag}</span>'
                    f'<span style="font-size:12px;color:{sc};font-weight:600">{ts.label} ({ts.score:+.2f})</span>'
                    f'<span style="font-size:11px;color:#475569">{ts.mention_count} mentions</span>'
                    f'</div>'
                )

            options_mini = ""
            if options_report and options_report.market_pc_ratio:
                pc = options_report.market_pc_ratio
                pc_clr = "#ef4444" if pc > 1.2 else "#22c55e" if pc < 0.8 else "#eab308"
                unusual = options_report.total_unusual or 0
                options_mini = (
                    f'<div style="margin-top:12px;padding-top:10px;border-top:1px solid rgba(255,255,255,0.06)">'
                    f'<div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.07em;margin-bottom:6px">⚡ Options Flow</div>'
                    f'<div style="display:flex;gap:20px">'
                    f'<div><div style="font-size:11px;color:#64748b">Put/Call Ratio</div>'
                    f'<div style="font-size:18px;font-weight:700;color:{pc_clr}">{pc:.2f}</div></div>'
                    f'<div><div style="font-size:11px;color:#64748b">Unusual Contracts</div>'
                    f'<div style="font-size:18px;font-weight:700;color:#e2e8f0">{unusual}</div></div>'
                    f'</div></div>'
                )

            sentiment_section = f"""
  <div style="background:#1e293b;border:1px solid rgba(255,255,255,0.07);border-radius:12px;padding:16px 20px;margin-bottom:16px">
    <div style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.1em;margin-bottom:12px">📊 Market Psychology</div>
    <div style="display:flex;align-items:center;gap:16px;margin-bottom:12px">
      <div>
        <div style="font-size:11px;color:#64748b;margin-bottom:4px">Fear &amp; Greed Index</div>
        <div style="font-size:28px;font-weight:800;color:{gauge_color}">{fg_score}</div>
        <div style="font-size:13px;color:{gauge_color};font-weight:600">{fg_label}{week_delta}</div>
      </div>
      <div style="flex:1">
        <div style="background:#0f172a;border-radius:4px;height:8px;overflow:hidden">
          <div style="background:linear-gradient(90deg,#ef4444,#f97316,#eab308,#84cc16,#22c55e);width:100%;height:100%"></div>
        </div>
        <div style="position:relative;margin-top:2px">
          <span style="position:absolute;left:{pct_bar}%;transform:translateX(-50%);font-size:10px;color:{gauge_color}">▲</span>
        </div>
      </div>
    </div>
    {f'<div style="margin-top:8px">{ticker_rows}</div>' if ticker_rows else ''}
    {options_mini}
  </div>"""
    return sentiment_section


def _build_congress_section(congress_report):
    # ── Congressional trades ───────────────────────────────────────────
    congress_section = ""
    if congress_report and congress_report.total_trades > 0:
        sector_rows = ""
        sig_colors = {
            "Strong Buy":"#22c55e","Buy":"#86efac",
            "Neutral":"#eab308",
            "Sell":"#fca5a5","Strong Sell":"#ef4444",
        }
        for sector, sig in sorted(
            congress_report.sector_signals.items(),
            key=lambda x: abs(x[1].net_score), reverse=True
        )[:6]:
            sc = sig_colors.get(sig.signal_label, "#94a3b8")
            top_tickers = ", ".join(
                f'<span style="font-family:monospace;color:#93c5fd">{t.ticker}</span>'
                for t in (sig.top_tickers or [])[:4] if t.net_score > 0
            ) or "—"
            sector_rows += (
                f'<tr>'
                f'<td style="padding:6px 8px;font-size:12px;color:#cbd5e1">{sector.replace("_"," ").title()}</td>'
                f'<td style="padding:6px 8px;font-size:12px;font-weight:700;color:{sc}">{sig.signal_label}</td>'
                f'<td style="padding:6px 8px;font-size:12px;color:#22c55e">{sig.buy_count}↑</td>'
                f'<td style="padding:6px 8px;font-size:12px;color:#ef4444">{sig.sell_count}↓</td>'
                f'<td style="padding:6px 8px;font-size:12px">{top_tickers}</td>'
                f'</tr>'
            )

        watchlist_html = ""
        for h in (congress_report.watchlist_highlights or [])[:4]:
            party_color = "#3b82f6" if h.get("party","") == "Democrat" else "#ef4444"
            bought = ", ".join(h.get("tickers_bought", [])[:3]) or "—"
            sold   = ", ".join(h.get("tickers_sold",   [])[:3]) or "—"
            watchlist_html += (
                f'<div style="padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.04)">'
                f'<span style="font-size:12px;font-weight:600;color:#e2e8f0">{h.get("politician","")}</span>'
                f'<span style="font-size:11px;color:{party_color};margin-left:6px">({h.get("party","")}, {h.get("chamber","").title()})</span>'
                f'<div style="margin-top:4px;font-size:12px">'
                f'<span style="color:#22c55e">▲ {bought}</span>'
                f'<span style="color:#ef4444;margin-left:12px">▼ {sold}</span>'
                f'</div></div>'
            )

        ai_blurb = ""
        if congress_report.ai_narrative:
            snippet = congress_report.ai_narrative[:300]
            ai_blurb = (
                f'<div style="margin-top:12px;padding:10px 12px;background:#0f172a;border-radius:8px;'
                f'font-size:12px;color:#94a3b8;line-height:1.6">{snippet}…</div>'
            )

        congress_section = f"""
  <div style="background:#1e293b;border:1px solid rgba(255,255,255,0.07);border-radius:12px;padding:16px 20px;margin-bottom:16px">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
      <div style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.1em">🏛️ Congressional Trades</div>
      <span style="font-size:11px;color:#475569">{congress_report.total_trades} trades · {congress_report.days_analysed}d</span>
    </div>
    <table style="width:100%;border-collapse:collapse">
      <tr style="border-bottom:1px solid rgba(255,255,255,0.08)">
        <th style="padding:4px 8px;font-size:10px;color:#475569;text-align:left;font-weight:600">SECTOR</th>
        <th style="padding:4px 8px;font-size:10px;color:#475569;text-align:left;font-weight:600">SIGNAL</th>
        <th style="padding:4px 8px;font-size:10px;color:#475569;text-align:left;font-weight:600">BUY</th>
        <th style="padding:4px 8px;font-size:10px;color:#475569;text-align:left;font-weight:600">SELL</th>
        <th style="padding:4px 8px;font-size:10px;color:#475569;text-align:left;font-weight:600">TOP TICKERS</th>
      </tr>
      {sector_rows}
    </table>
    {f'<div style="margin-top:12px;padding-top:10px;border-top:1px solid rgba(255,255,255,0.06)"><div style="font-size:11px;color:#64748b;margin-bottom:6px;font-weight:600">WATCHLIST POLITICIANS</div>{watchlist_html}</div>' if watchlist_html else ''}
    {ai_blurb}
  </div>"""
    return congress_section


def _build_edgar_section(edgar_report):
    # ── EDGAR insider trades ───────────────────────────────────────────
    edgar_section = ""
    if edgar_report and edgar_report.total_items > 0:
        trade_rows = ""
        for t in (edgar_report.insider_trades or [])[:8]:
            direction = "buy" in (t.trade_type or "").lower()
            clr = "#22c55e" if direction else "#ef4444"
            icon = "▲" if direction else "▼"
            val = f"${t.total_value:,.0f}" if t.total_value else "—"
            sig_colors_e = {"strong_buy":"#22c55e","buy":"#86efac","sell":"#fca5a5","strong_sell":"#ef4444"}
            sig_clr = sig_colors_e.get(t.signal_strength, "#94a3b8")
            trade_rows += (
                f'<tr>'
                f'<td style="padding:5px 8px;font-family:monospace;color:#93c5fd;font-size:12px">{t.ticker}</td>'
                f'<td style="padding:5px 8px;font-size:11px;color:#94a3b8">{t.insider_title[:22]}</td>'
                f'<td style="padding:5px 8px;font-size:12px;font-weight:700;color:{clr}">{icon} {t.trade_type.upper()[:4]}</td>'
                f'<td style="padding:5px 8px;font-size:12px;color:{sig_clr};font-weight:600">{val}</td>'
                f'<td style="padding:5px 8px;font-size:11px;color:#475569">{t.filed_date[:10]}</td>'
                f'</tr>'
            )

        events_html = ""
        for ev in (edgar_report.material_events or [])[:3]:
            ev_ticker = ev.get("ticker", "") if isinstance(ev, dict) else getattr(ev, "ticker", "")
            ev_desc   = ev.get("description", "") if isinstance(ev, dict) else getattr(ev, "description", "")
            events_html += (
                f'<div style="padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.04);font-size:12px">'
                f'<span style="font-family:monospace;color:#93c5fd">{ev_ticker}</span>'
                f'<span style="color:#94a3b8;margin-left:8px">{str(ev_desc)[:80]}</span>'
                f'</div>'
            )

        edgar_section = f"""
  <div style="background:#1e293b;border:1px solid rgba(255,255,255,0.07);border-radius:12px;padding:16px 20px;margin-bottom:16px">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
      <div style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.1em">📋 SEC EDGAR — Insider Activity</div>
      <span style="font-size:11px;color:#475569">{len(edgar_report.insider_trades or [])} filings</span>
    </div>
    <table style="width:100%;border-collapse:collapse">
      <tr style="border-bottom:1px solid rgba(255,255,255,0.08)">
        <th style="padding:4px 8px;font-size:10px;color:#475569;text-align:left">TICKER</th>
        <th style="padding:4px 8px;font-size:10px;color:#475569;text-align:left">INSIDER</th>
        <th style="padding:4px 8px;font-size:10px;color:#475569;text-align:left">TYPE</th>
        <th style="padding:4px 8px;font-size:10px;color:#475569;text-align:left">VALUE</th>
        <th style="padding:4px 8px;font-size:10px;color:#475569;text-align:left">FILED</th>
      </tr>
      {trade_rows}
    </table>
    {f'<div style="margin-top:10px;padding-top:10px;border-top:1px solid rgba(255,255,255,0.06)"><div style="font-size:11px;color:#64748b;margin-bottom:4px;font-weight:600">MATERIAL EVENTS (8-K)</div>{events_html}</div>' if events_html else ''}
  </div>"""
    return edgar_section



# ---------------------------------------------------------------------------
def notify_email(
    opportunities, macro_narrative, to_email,
    smtp_host, smtp_port, smtp_user, smtp_password,
    use_tls=True, resend_api_key=None,
    congress_report=None, edgar_report=None,
    sentiment_report=None, options_report=None,
):
    if not to_email: return False
    if not resend_api_key and not all([smtp_host, smtp_user, smtp_password]):
        return False

    now       = datetime.now(timezone.utc)
    date_str  = now.strftime("%B %d, %Y")
    sentiment = macro_narrative.get("overall_sentiment", "—")
    theme     = macro_narrative.get("dominant_theme", "—")
    narrative = macro_narrative.get("market_narrative", "")[:400]

    sent_color = {"Risk-On":"#22c55e","Bullish":"#22c55e",
                  "Risk-Off":"#ef4444","Bearish":"#ef4444",
                  "Neutral":"#eab308"}.get(sentiment, "#94a3b8")

    urgency_labels = {"immediate":"🔴 IMMEDIATE","short_term":"🟡 SHORT TERM","monitor":"⚪ MONITOR"}
    urgency_colors = {"immediate":"#7f1d1d","short_term":"#78350f","monitor":"#1e293b"}
    urgency_text   = {"immediate":"#fca5a5","short_term":"#fcd34d","monitor":"#94a3b8"}

    imm = sum(1 for o in opportunities if o.urgency == "immediate")
    st  = sum(1 for o in opportunities if o.urgency == "short_term")
    subj_tag = f"🔴{imm} urgent" if imm else f"🟡{st} short-term" if st else f"{len(opportunities)} signals"
    subject = f"📈 {sentiment.upper()} | {subj_tag} | {date_str}"

    # ── Opportunity cards (ALL of them) ───────────────────────────────
    opp_cards_html = ""
    for i, opp in enumerate(opportunities, 1):
        tickers_html = "  ".join(
            f'<span style="background:#1e3a5f;color:#93c5fd;padding:2px 8px;border-radius:4px;'
            f'font-size:12px;font-family:monospace">{t}</span>'
            for t in opp.tickers[:5]
        )
        badge_bg  = urgency_colors.get(opp.urgency, "#1e293b")
        badge_txt = urgency_text.get(opp.urgency, "#94a3b8")
        badge_lbl = urgency_labels.get(opp.urgency, opp.urgency.upper())
        conf_pct  = int(opp.confidence * 100)
        conf_clr  = "#22c55e" if conf_pct >= 70 else "#eab308" if conf_pct >= 45 else "#ef4444"
        opp_cards_html += f"""
        <div style="background:#1e293b;border-radius:12px;padding:16px 20px;margin-bottom:12px;border-left:3px solid {conf_clr}">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;gap:10px">
            <span style="font-size:13px;font-weight:700;color:#e2e8f0;line-height:1.3;flex:1">{i}. {opp.title}</span>
            <span style="background:{badge_bg};color:{badge_txt};font-size:10px;font-weight:700;padding:3px 8px;border-radius:5px;white-space:nowrap;flex-shrink:0">{badge_lbl}</span>
          </div>
          <div style="background:#0f172a;border-radius:8px;padding:9px 12px;margin-bottom:9px">
            <span style="font-size:12px;color:#86efac;font-weight:600">▶ </span>
            <span style="font-size:12px;color:#cbd5e1">{opp.action}</span>
          </div>
          <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
            <div>{tickers_html or '<span style="color:#475569;font-size:12px">—</span>'}</div>
            <span style="font-size:12px;color:{conf_clr};font-weight:700">{conf_pct}% confidence</span>
          </div>
        </div>"""
    if not opp_cards_html:
        opp_cards_html = '<p style="color:#475569;font-size:13px;padding:10px 0">No opportunities detected in this run.</p>'

    # ── Fear & Greed + Options flow ────────────────────────────────────
    try:
        sentiment_section = _build_sentiment_section(sentiment_report, options_report)
    except Exception as _exc:
        logger.warning("Sentiment section failed: %s", _exc)
        sentiment_section = ""

    # ── Congressional trades ───────────────────────────────────────────
    try:
        congress_section = _build_congress_section(congress_report)
    except Exception as _exc:
        logger.warning("Congress section failed: %s", _exc)
        congress_section = ""

    # ── EDGAR insider trades ───────────────────────────────────────────
    try:
        edgar_section = _build_edgar_section(edgar_report)
    except Exception as _exc:
        logger.warning("Edgar section failed: %s", _exc)
        edgar_section = ""

    # ── Assemble HTML ──────────────────────────────────────────────────
    html_body = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Market Report</title></head>
<body style="margin:0;padding:0;background:#0f172a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif">
<div style="max-width:620px;margin:0 auto;padding:20px 16px">

  <!-- Header -->
  <div style="background:linear-gradient(135deg,#1e293b,#0f172a);border:1px solid rgba(255,255,255,0.08);border-radius:16px;padding:24px;margin-bottom:16px;text-align:center">
    <div style="font-size:11px;font-weight:600;color:#3b82f6;text-transform:uppercase;letter-spacing:.1em;margin-bottom:8px">Stock Narrative Engine</div>
    <div style="font-size:24px;font-weight:800;color:#e2e8f0;margin-bottom:4px">{date_str}</div>
    <div style="font-size:13px;color:#64748b">Daily Market Intelligence Brief</div>
  </div>

  <!-- Sentiment band -->
  <div style="background:#1e293b;border:1px solid rgba(255,255,255,0.07);border-left:4px solid {sent_color};border-radius:12px;padding:16px 20px;margin-bottom:16px">
    <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px">Market Sentiment</div>
    <div style="font-size:22px;font-weight:800;color:{sent_color};margin-bottom:4px">{sentiment}</div>
    <div style="font-size:13px;color:#94a3b8;font-weight:500;margin-bottom:8px">{theme}</div>
    <div style="font-size:12px;color:#64748b;line-height:1.65">{narrative}{'…' if len(macro_narrative.get('market_narrative',''))>400 else ''}</div>
  </div>

  <!-- Opportunities -->
  <div style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.1em;margin:20px 0 12px">
    🎯 Investment Opportunities ({len(opportunities)} detected)
  </div>
  {opp_cards_html}

  <!-- Sentiment / Fear & Greed / Options -->
  {sentiment_section}

  <!-- Congressional trades -->
  {congress_section}

  <!-- EDGAR insider activity -->
  {edgar_section}

  <!-- Footer -->
  <div style="text-align:center;padding:16px 0;border-top:1px solid rgba(255,255,255,0.06);margin-top:8px">
    <div style="font-size:11px;color:#334155;line-height:1.7">
      For research purposes only. Not financial advice.<br>
      Always consult a licensed financial advisor before making investment decisions.
    </div>
  </div>

</div>
</body></html>"""

    # ── Plain text fallback ────────────────────────────────────────────
    plain_lines = [
        f"STOCK NARRATIVE ENGINE — {date_str}",
        f"Market: {sentiment} | Theme: {theme}", "",
    ]
    for i, opp in enumerate(opportunities, 1):
        plain_lines += [
            f"{i}. [{urgency_labels.get(opp.urgency, opp.urgency)}] {opp.title}",
            f"   Action: {opp.action}",
            f"   Tickers: {', '.join(opp.tickers)}  |  Confidence: {int(opp.confidence*100)}%", "",
        ]
    if sentiment_report and sentiment_report.fear_greed:
        fg = sentiment_report.fear_greed
        plain_lines += [f"Fear & Greed: {fg.score} ({fg.label})", ""]
    if congress_report and congress_report.total_trades > 0:
        plain_lines += [f"Congressional Trades: {congress_report.total_trades} trades analysed", ""]
    if edgar_report and edgar_report.total_items > 0:
        plain_lines += [f"EDGAR Insider Filings: {edgar_report.total_items} items", ""]
    plain_lines += ["For research purposes only. Not financial advice."]

    # ── Send ───────────────────────────────────────────────────────────
    # Path 1: Resend API (preferred when key available)
    if resend_api_key:
        try:
            resp = requests.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {resend_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": "Stock Narrative Engine <onboarding@resend.dev>",
                    "to": [to_email],
                    "subject": subject,
                    "html": html_body,
                    "text": "\n".join(plain_lines),
                },
                timeout=20,
            )
            resp.raise_for_status()
            logger.info("Email sent via Resend to %s (id=%s)", to_email, resp.json().get("id"))
            return True
        except Exception as exc:
            logger.warning("Resend send failed: %s — falling back to SMTP", exc)

    # Path 2: SMTP
    if not all([smtp_host, smtp_user, smtp_password]):
        logger.warning("No SMTP credentials and Resend failed — email not sent")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"]    = smtp_user
    msg["To"]      = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText("\n".join(plain_lines), "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        cls = smtplib.SMTP_SSL if use_tls and smtp_port == 465 else smtplib.SMTP
        with cls(smtp_host, smtp_port) as s:
            if use_tls and smtp_port != 465: s.starttls()
            s.login(smtp_user, smtp_password)
            s.sendmail(smtp_user, to_email, msg.as_string())
        logger.info("Email sent via SMTP to %s", to_email)
        return True
    except Exception as exc:
        logger.warning("SMTP send failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Desktop
# ---------------------------------------------------------------------------
def notify_desktop(title, message):
    try:
        from plyer import notification
        notification.notify(title=title,message=message[:256],app_name="Stock Narrative Engine",timeout=10)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
def notify_telegram(opportunities, macro_narrative, bot_token, chat_id, congress_report=None):
    """Send a brief digest to a Telegram chat via Bot API."""
    try:
        import requests as _req

        top_opps = opportunities[:5]
        lines = ["📊 *Stock Narrative Engine*\n"]

        if macro_narrative:
            sentiment = getattr(macro_narrative, "overall_sentiment", "")
            if sentiment:
                lines.append(f"Macro: *{sentiment}*")

        if top_opps:
            lines.append("\n🎯 *Top Opportunities:*")
            for opp in top_opps:
                urgency = getattr(opp, "urgency", "").upper()
                title = getattr(opp, "title", "")
                action = getattr(opp, "action", "")[:120]
                lines.append(f"[{urgency}] *{title}*\n{action}")

        if congress_report and getattr(congress_report, "total_trades", 0) > 0:
            lines.append(f"\n🏛 Congress: {congress_report.total_trades} trades tracked")

        text = "\n".join(lines)
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        resp = _req.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=10)
        if resp.ok:
            logger.info("Telegram notification sent to chat %s", chat_id)
            return True
        else:
            ning("Telegram send failed (HTTP %s): %s", resp.status_code, resp.text)
            return False
    except Exception as exc:
        logger.warning("Telegram notification error: %s", exc)
        return False
