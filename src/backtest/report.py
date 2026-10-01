"""
Backtest report generator.

Produces a self-contained HTML report with:
  - Summary stats table (win rate, avg alpha, Sharpe at each horizon)
  - Politician leaderboard with follow scores
  - Sector performance table
  - Party comparison (Democrat vs Republican vs Bipartisan)
  - Best/worst individual trades
  - Inline Chart.js charts — no external dependencies beyond CDN
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Verdict colour mapping
# ---------------------------------------------------------------------------
VERDICT_COLOR = {
    "🔥 Must Follow":    "#22c55e",
    "✅ Worth Following": "#4ade80",
    "👀 Monitor":        "#eab308",
    "⚪ Low Signal":     "#64748b",
}


def export_backtest_html(
    results: Dict[str, Any],
    output_path: str = "reports/backtest.html",
) -> str:
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    summary  = results.get("summary", {})
    by_pol   = results.get("by_politician", [])
    by_sec   = results.get("by_sector", [])
    by_party = results.get("by_party", {})
    best     = results.get("best_trades", [])
    worst    = results.get("worst_trades", [])
    follows  = results.get("follow_scores", [])

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Congress Trade Backtester — {now_str}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<style>
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:#0f172a; color:#e2e8f0; font-family:'Segoe UI',sans-serif; line-height:1.6; padding:24px; }}
h1 {{ font-size:26px; color:#38bdf8; margin-bottom:4px; }}
h2 {{ font-size:18px; color:#94a3b8; margin:28px 0 12px;
      border-bottom:1px solid #334155; padding-bottom:6px; }}
table {{ width:100%; border-collapse:collapse; margin-bottom:20px; }}
th {{ background:#1e293b; color:#94a3b8; padding:10px; text-align:left; font-size:13px; }}
td {{ padding:9px 10px; border-bottom:1px solid #1e293b; font-size:13px; }}
tr:hover td {{ background:#1e293b44; }}
.green {{ color:#22c55e; font-weight:600; }}
.red   {{ color:#ef4444; font-weight:600; }}
.gold  {{ color:#fbbf24; font-weight:600; }}
.dim   {{ color:#64748b; }}
.badge {{ display:inline-block; padding:2px 8px; border-radius:10px;
          font-size:11px; font-weight:600; }}
.card  {{ background:#1e293b; border-radius:8px; padding:16px; margin-bottom:16px; }}
.grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
.chart-box {{ background:#1e293b; border-radius:8px; padding:16px; margin-bottom:20px; }}
</style>
</head>
<body>

<h1>🧪 Congress Trade Backtester</h1>
<p class="dim" style="margin-bottom:24px">{now_str} &nbsp;·&nbsp;
  {results.get('trade_count', 0)} trades analysed</p>

{_summary_section(summary)}
{_follow_scores_section(follows)}
{_party_section(by_party)}
{_politician_section(by_pol)}
{_sector_section(by_sec)}
{_best_worst_section(best, worst)}
{_charts_section(follows, by_sec)}

<p class="dim" style="font-size:12px;margin-top:32px;text-align:center">
  ⚠️ Past performance does not guarantee future results.
  For research purposes only. Not financial advice.
</p>
</body>
</html>"""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    logger.info("Backtest HTML saved to %s", path)
    return str(path)


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------
def _summary_section(summary: Dict) -> str:
    horizons = ["1d", "5d", "1m", "3m", "6m"]
    labels   = {"1d": "1 Day", "5d": "5 Day", "1m": "1 Month",
                "3m": "3 Month", "6m": "6 Month"}

    rows = ""
    for h in horizons:
        data = summary.get(h)
        if not data:
            continue
        alpha    = data.get("avg_alpha_pct")
        wr       = data.get("win_rate_pct", "N/A")
        ret      = data.get("avg_return_pct")
        sharpe   = data.get("sharpe_ratio")
        n        = data.get("sample_size", 0)

        alpha_cls  = "green" if alpha and alpha > 0 else "red"
        ret_cls    = "green" if ret and ret > 0 else "red"

        rows += f"""
        <tr>
          <td><strong>{labels[h]}</strong></td>
          <td class="{ret_cls}">{ret:+.2f}%</td>
          <td class="{alpha_cls}">{alpha:+.2f}%</td>
          <td>{wr}</td>
          <td class="dim">{sharpe if sharpe else '—'}</td>
          <td class="dim">{n}</td>
        </tr>"""

    return f"""
<h2>📊 Overall Performance vs SPY</h2>
<table>
  <thead><tr>
    <th>Horizon</th><th>Avg Return</th><th>Avg Alpha vs SPY</th>
    <th>Win Rate</th><th>Sharpe</th><th>Trades</th>
  </tr></thead>
  <tbody>{rows}</tbody>
</table>"""


def _follow_scores_section(follows: List[Dict]) -> str:
    if not follows:
        return ""
    rows = ""
    for f in follows[:15]:
        score   = f.get("follow_score", 0)
        verdict = f.get("verdict", "")
        color   = VERDICT_COLOR.get(verdict, "#64748b")
        party_badge = (
            '<span class="badge" style="background:#1e40af;color:#fff">D</span>'
            if "D" in f.get("party", "")
            else '<span class="badge" style="background:#991b1b;color:#fff">R</span>'
        )
        wl = "⭐" if f.get("is_watchlist") else ""
        rows += f"""
        <tr>
          <td><strong>{f['politician']}</strong> {wl}</td>
          <td>{party_badge} {f['chamber'].title()}</td>
          <td>{f['trade_count']}</td>
          <td>
            <div style="background:#0f172a;border-radius:4px;height:8px;width:120px;display:inline-block;vertical-align:middle">
              <div style="background:{color};width:{score}%;height:8px;border-radius:4px"></div>
            </div>
            <span style="color:{color};margin-left:8px;font-weight:600">{score}</span>
          </td>
          <td style="color:{color}">{verdict}</td>
        </tr>"""

    return f"""
<h2>🏆 Politician Follow Scores</h2>
<p class="dim" style="margin-bottom:10px;font-size:13px">
  Composite score (0–100) based on alpha, win rate, trade size and sample size.
</p>
<table>
  <thead><tr>
    <th>Politician</th><th>Party / Chamber</th>
    <th>Trades</th><th>Follow Score</th><th>Verdict</th>
  </tr></thead>
  <tbody>{rows}</tbody>
</table>"""


def _party_section(by_party: Dict) -> str:
    if not by_party:
        return ""
    cards = ""
    for party, data in by_party.items():
        alpha_1m = data.get("avg_alpha_1m")
        alpha_3m = data.get("avg_alpha_3m")
        wr_1m    = data.get("win_rate_1m")
        color    = "#1e40af" if party == "Democrat" else ("#991b1b" if party == "Republican" else "#854d0e")
        cards += f"""
        <div class="card" style="border-left:4px solid {color}">
          <strong style="font-size:15px">{party}</strong>
          <span class="dim"> — {data.get('trade_count', 0)} trades</span>
          <div style="margin-top:8px">
            <span class="dim">1M Alpha: </span>
            <span class="{'green' if alpha_1m and alpha_1m > 0 else 'red'}">
              {f'{alpha_1m:+.2f}%' if alpha_1m is not None else 'N/A'}
            </span>
            &nbsp;·&nbsp;
            <span class="dim">3M Alpha: </span>
            <span class="{'green' if alpha_3m and alpha_3m > 0 else 'red'}">
              {f'{alpha_3m:+.2f}%' if alpha_3m is not None else 'N/A'}
            </span>
            &nbsp;·&nbsp;
            <span class="dim">Win Rate: </span>
            <span>{f'{wr_1m*100:.1f}%' if wr_1m else 'N/A'}</span>
          </div>
          {'<div style="margin-top:6px;color:#94a3b8;font-size:12px">Tickers: ' + ', '.join(data.get("tickers", [])[:8]) + '</div>' if party == "Bipartisan" else ""}
        </div>"""

    return f"""<h2>🤝 Democrat vs Republican vs Bipartisan</h2>
<div class="grid2">{cards}</div>"""


def _politician_section(by_pol: List[Dict]) -> str:
    if not by_pol:
        return ""
    rows = ""
    for p in by_pol[:20]:
        a1m = p.get("avg_alpha_1m")
        a3m = p.get("avg_alpha_3m")
        wr  = p.get("win_rate_1m")
        rows += f"""
        <tr>
          <td><strong>{'⭐ ' if p.get('is_watchlist') else ''}{p['politician']}</strong></td>
          <td class="dim">{p['chamber'].title()}</td>
          <td>{p['trade_count']}</td>
          <td class="{'green' if a1m and a1m > 0 else 'red'}">{f'{a1m:+.2f}%' if a1m is not None else '—'}</td>
          <td class="{'green' if a3m and a3m > 0 else 'red'}">{f'{a3m:+.2f}%' if a3m is not None else '—'}</td>
          <td>{f'{wr*100:.1f}%' if wr else '—'}</td>
        </tr>"""

    return f"""
<h2>👤 Per-Politician Performance</h2>
<table>
  <thead><tr>
    <th>Politician</th><th>Chamber</th><th>Trades</th>
    <th>Avg Alpha 1M</th><th>Avg Alpha 3M</th><th>Win Rate 1M</th>
  </tr></thead>
  <tbody>{rows}</tbody>
</table>"""


def _sector_section(by_sec: List[Dict]) -> str:
    if not by_sec:
        return ""
    rows = ""
    for s in by_sec:
        a1m = s.get("avg_alpha_1m")
        a3m = s.get("avg_alpha_3m")
        wr  = s.get("win_rate_1m")
        rows += f"""
        <tr>
          <td><strong>{s['sector'].replace('_',' ').title()}</strong></td>
          <td>{s['trade_count']}</td>
          <td class="{'green' if a1m and a1m > 0 else 'red'}">{f'{a1m:+.2f}%' if a1m is not None else '—'}</td>
          <td class="{'green' if a3m and a3m > 0 else 'red'}">{f'{a3m:+.2f}%' if a3m is not None else '—'}</td>
          <td>{f'{wr*100:.1f}%' if wr else '—'}</td>
        </tr>"""

    return f"""
<h2>🏭 Sector Performance</h2>
<table>
  <thead><tr>
    <th>Sector</th><th>Trades</th>
    <th>Avg Alpha 1M</th><th>Avg Alpha 3M</th><th>Win Rate 1M</th>
  </tr></thead>
  <tbody>{rows}</tbody>
</table>"""


def _best_worst_section(best: List[Dict], worst: List[Dict]) -> str:
    def trade_rows(trades):
        rows = ""
        for t in trades:
            a1m = t.get("alpha_1m")
            a3m = t.get("alpha_3m")
            rows += f"""
            <tr>
              <td><strong>{t['politician']}</strong></td>
              <td style="color:#38bdf8"><strong>{t['ticker']}</strong></td>
              <td class="dim">{t['disclosure_date']}</td>
              <td class="dim">{t.get('amount_range','')}</td>
              <td class="{'green' if a1m and a1m > 0 else 'red'}">{f'{a1m:+.2f}%' if a1m is not None else '—'}</td>
              <td class="{'green' if a3m and a3m > 0 else 'red'}">{f'{a3m:+.2f}%' if a3m is not None else '—'}</td>
            </tr>"""
        return rows

    return f"""
<h2>🎯 Best Individual Trades</h2>
<table>
  <thead><tr>
    <th>Politician</th><th>Ticker</th><th>Disclosure</th>
    <th>Amount</th><th>Alpha 1M</th><th>Alpha 3M</th>
  </tr></thead>
  <tbody>{trade_rows(best)}</tbody>
</table>

<h2>⚠️ Worst Individual Trades</h2>
<table>
  <thead><tr>
    <th>Politician</th><th>Ticker</th><th>Disclosure</th>
    <th>Amount</th><th>Alpha 1M</th><th>Alpha 3M</th>
  </tr></thead>
  <tbody>{trade_rows(worst)}</tbody>
</table>"""


def _charts_section(follows: List[Dict], by_sec: List[Dict]) -> str:
    # Follow score bar chart data
    pol_labels = json.dumps([f["politician"].split()[-1] for f in follows[:10]])
    pol_scores = json.dumps([f["follow_score"] for f in follows[:10]])
    pol_colors = json.dumps([VERDICT_COLOR.get(f.get("verdict", ""), "#64748b") for f in follows[:10]])

    # Sector alpha bar chart data
    sec_labels  = json.dumps([s["sector"].replace("_", " ").title() for s in by_sec[:10]])
    sec_alphas  = json.dumps([s.get("avg_alpha_1m", 0) or 0 for s in by_sec[:10]])
    sec_colors  = json.dumps(["#22c55e" if (s.get("avg_alpha_1m") or 0) > 0 else "#ef4444" for s in by_sec[:10]])

    return f"""
<h2>📈 Charts</h2>
<div class="grid2">
  <div class="chart-box">
    <p style="color:#94a3b8;font-size:13px;margin-bottom:12px">Follow Scores — Top 10 Politicians</p>
    <canvas id="followChart" height="220"></canvas>
  </div>
  <div class="chart-box">
    <p style="color:#94a3b8;font-size:13px;margin-bottom:12px">Avg 1-Month Alpha by Sector</p>
    <canvas id="sectorChart" height="220"></canvas>
  </div>
</div>

<script>
new Chart(document.getElementById('followChart'), {{
  type: 'bar',
  data: {{
    labels: {pol_labels},
    datasets: [{{
      label: 'Follow Score',
      data: {pol_scores},
      backgroundColor: {pol_colors},
      borderRadius: 4,
    }}]
  }},
  options: {{
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#1e293b' }} }},
      y: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#1e293b' }}, max: 100 }}
    }}
  }}
}});

new Chart(document.getElementById('sectorChart'), {{
  type: 'bar',
  data: {{
    labels: {sec_labels},
    datasets: [{{
      label: 'Avg Alpha 1M (%)',
      data: {sec_alphas},
      backgroundColor: {sec_colors},
      borderRadius: 4,
    }}]
  }},
  options: {{
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color: '#94a3b8', font: {{ size: 10 }} }}, grid: {{ color: '#1e293b' }} }},
      y: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#1e293b' }} }}
    }}
  }}
}});
</script>"""
