"""HTML report builder — sleek dark theme with Chart.js visuals."""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_SENT_COLOR = {
    "Bullish": "#22c55e", "Risk-On": "#22c55e",
    "Bearish": "#ef4444", "Risk-Off": "#ef4444",
    "Neutral": "#eab308",
}

def _sc(s): return _SENT_COLOR.get(s, "#94a3b8")

# ── CSS ───────────────────────────────────────────────────────────────────────
_CSS = """<style>
:root{--bg:#06090f;--bg2:#0d1117;--surface:rgba(255,255,255,0.035);--border:rgba(255,255,255,0.07);--border2:rgba(255,255,255,0.13);--text:#e6edf3;--muted:#7d8590;--dim:#3d444d;--accent:#3b82f6;--cyan:#22d3ee;--green:#22c55e;--yellow:#eab308;--red:#ef4444;--purple:#a78bfa;--sent:SENTCOLOR;}
*{box-sizing:border-box;margin:0;padding:0}html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--text);font-family:'Inter',system-ui,sans-serif;font-size:14px;line-height:1.6;min-height:100vh;background-image:radial-gradient(ellipse 80% 50% at 50% -20%,rgba(59,130,246,0.08) 0%,transparent 60%),radial-gradient(ellipse 60% 40% at 80% 80%,rgba(139,92,246,0.05) 0%,transparent 50%);}
.nav{position:sticky;top:0;z-index:100;background:rgba(6,9,15,0.88);backdrop-filter:blur(20px);border-bottom:1px solid var(--border);padding:0 40px;display:flex;align-items:center;height:52px;}
.nav-brand{font-size:15px;font-weight:700;color:var(--text);margin-right:32px;}.nav-brand span{background:linear-gradient(135deg,var(--accent),var(--cyan));-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.nav-links{display:flex;gap:2px;flex:1;}.nav-link{color:var(--muted);text-decoration:none;padding:6px 14px;border-radius:6px;font-size:13px;font-weight:500;transition:all .15s;}.nav-link:hover{color:var(--text);background:var(--surface);}
.nav-time{color:var(--dim);font-size:12px;margin-left:auto;}
.page{max-width:1320px;margin:0 auto;padding:36px 40px 60px;}
.hero{margin-bottom:32px;}
.hero-tag{display:inline-flex;align-items:center;gap:6px;background:rgba(59,130,246,0.1);border:1px solid rgba(59,130,246,0.25);color:var(--accent);font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;padding:4px 10px;border-radius:20px;margin-bottom:14px;}
.hero-tag::before{content:'';width:6px;height:6px;border-radius:50%;background:var(--accent);animation:pulse 2s infinite;}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1);}50%{opacity:.5;transform:scale(1.3);}}
.hero h1{font-size:32px;font-weight:800;letter-spacing:-.02em;margin-bottom:6px;}.hero h1 .grad{background:linear-gradient(135deg,var(--accent) 0%,var(--cyan) 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.hero-sub{color:var(--muted);font-size:13px;}
.stats-row{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin-bottom:32px;}
.stat-card{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:18px 20px;transition:border-color .2s,transform .2s;position:relative;overflow:hidden;}
.stat-card::before{content:'';position:absolute;inset:0;background:linear-gradient(135deg,rgba(255,255,255,0.03) 0%,transparent 60%);pointer-events:none;}
.stat-card:hover{border-color:var(--border2);transform:translateY(-2px);}
.stat-label{font-size:11px;color:var(--muted);font-weight:500;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px;}
.stat-value{font-size:26px;font-weight:700;letter-spacing:-.02em;line-height:1;}.stat-sub{font-size:11px;color:var(--dim);margin-top:4px;}
.section-title{display:flex;align-items:center;gap:10px;font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;margin:40px 0 18px;padding-bottom:12px;border-bottom:1px solid var(--border);}
.section-count{margin-left:auto;font-size:11px;color:var(--dim);font-weight:400;text-transform:none;letter-spacing:0;}
.charts-grid{display:grid;grid-template-columns:230px 1fr 1fr;gap:16px;margin-bottom:32px;}
.chart-card{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:20px;}
.chart-title{font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-bottom:16px;}
.sentiment-label{text-align:center;font-size:15px;font-weight:700;margin-top:10px;color:var(--sent);}
.sentiment-sub{text-align:center;font-size:11px;color:var(--dim);margin-top:2px;}
.macro-banner{background:var(--surface);border:1px solid var(--border);border-left:3px solid var(--sent);border-radius:14px;padding:20px 24px;margin-bottom:36px;display:grid;grid-template-columns:160px auto 1fr;gap:20px;align-items:start;}
.mb-meta{display:flex;flex-direction:column;gap:4px;}.mb-label{font-size:10px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;}
.mb-value{font-size:17px;font-weight:700;color:var(--sent);}.mb-theme{font-size:12px;color:var(--muted);margin-top:6px;line-height:1.4;}
.mb-divider{width:1px;background:var(--border);align-self:stretch;}.mb-narrative{font-size:13px;color:var(--muted);line-height:1.75;}
.opp-grid{display:grid;gap:14px;}
.opp-card{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:22px 24px;position:relative;overflow:hidden;transition:border-color .2s,transform .2s;}
.opp-card:hover{border-color:var(--border2);transform:translateY(-1px);}
.opp-topbar{height:2px;position:absolute;top:0;left:0;right:0;}
.opp-row1{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:10px;}
.opp-num{font-size:11px;font-weight:700;color:var(--dim);background:rgba(255,255,255,0.05);border-radius:6px;padding:2px 8px;flex-shrink:0;margin-top:3px;}
.opp-title-wrap{flex:1;}.opp-title{font-size:16px;font-weight:600;color:var(--text);margin-bottom:3px;line-height:1.3;}
.opp-type{font-size:11px;color:var(--muted);font-weight:500;}
.opp-badges{display:flex;gap:6px;flex-shrink:0;align-items:flex-start;}
.opp-summary{font-size:13px;color:var(--muted);margin-bottom:12px;line-height:1.6;}
.opp-action-box{background:rgba(34,197,94,0.06);border:1px solid rgba(34,197,94,0.15);border-radius:8px;padding:10px 14px;font-size:13px;color:#4ade80;margin-bottom:14px;line-height:1.5;}
.opp-action-box strong{color:#86efac;}
.opp-footer{display:flex;align-items:center;gap:16px;flex-wrap:wrap;}
.conf-row{display:flex;align-items:center;gap:8px;flex:1;min-width:180px;}
.conf-lbl{font-size:11px;color:var(--dim);width:68px;flex-shrink:0;}
.conf-track{flex:1;height:4px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden;}
.conf-fill{height:100%;border-radius:2px;}
.conf-pct{font-size:12px;font-weight:600;width:34px;text-align:right;}
.tickers-wrap{display:flex;gap:6px;flex-wrap:wrap;}
code.tk{background:rgba(59,130,246,0.1);border:1px solid rgba(59,130,246,0.2);color:#93c5fd;padding:2px 8px;border-radius:6px;font-size:11px;font-weight:500;}
.badge{display:inline-flex;align-items:center;gap:4px;padding:3px 9px;border-radius:6px;font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;white-space:nowrap;}
.badge::before{content:'';width:5px;height:5px;border-radius:50%;}
.badge-red{background:rgba(239,68,68,.12);color:#fca5a5;border:1px solid rgba(239,68,68,.25);}.badge-red::before{background:#ef4444;}
.badge-amber{background:rgba(234,179,8,.10);color:#fcd34d;border:1px solid rgba(234,179,8,.20);}.badge-amber::before{background:#eab308;}
.badge-slate{background:rgba(255,255,255,.04);color:var(--muted);border:1px solid var(--border);}.badge-slate::before{background:var(--dim);}
.sector-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px;}
.sector-card{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:18px 20px;transition:border-color .2s,transform .2s;}
.sector-card:hover{border-color:var(--border2);transform:translateY(-1px);}
.sc-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;}
.sc-name{font-size:12px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;}
.sc-pill{font-size:10px;font-weight:600;padding:3px 9px;border-radius:20px;}
.sc-oneliner{font-size:13px;font-style:italic;color:var(--text);opacity:.85;margin-bottom:10px;}
.sc-conf-row{display:flex;align-items:center;gap:8px;margin-bottom:10px;}
.sc-conf-lbl{font-size:10px;color:var(--dim);width:64px;}
.sc-conf-track{flex:1;height:3px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden;}
.sc-conf-fill{height:100%;border-radius:2px;}
.sc-conf-pct{font-size:11px;font-weight:600;width:32px;text-align:right;}
.sc-narrative{font-size:12px;color:var(--muted);line-height:1.65;}
.cong-table-wrap{background:var(--surface);border:1px solid var(--border);border-radius:14px;overflow:hidden;margin-bottom:16px;}
.cong-table{width:100%;border-collapse:collapse;font-size:13px;}
.cong-table th{padding:11px 14px;text-align:left;color:var(--dim);font-size:10px;text-transform:uppercase;letter-spacing:.08em;border-bottom:1px solid var(--border);font-weight:600;}
.cong-table td{padding:11px 14px;border-bottom:1px solid rgba(255,255,255,0.03);color:var(--text);}
.cong-table tr:hover td{background:rgba(255,255,255,0.02);}
.watchlist-card{background:var(--surface);border:1px solid var(--border);border-radius:14px;overflow:hidden;margin-bottom:16px;}
.watchlist-hdr{padding:12px 16px;border-bottom:1px solid var(--border);font-size:11px;font-weight:700;color:#fbbf24;text-transform:uppercase;letter-spacing:.08em;}
.watchlist-item{padding:12px 16px;border-bottom:1px solid rgba(255,255,255,0.03);display:flex;align-items:center;gap:16px;}
.wl-name{font-weight:600;font-size:13px;min-width:160px;}.wl-party{font-size:11px;color:var(--dim);}
.cong-charts-row{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:20px;}
.ai-box{background:rgba(59,130,246,0.04);border:1px solid rgba(59,130,246,0.12);border-radius:14px;padding:18px 20px;}
.ai-box p{font-size:13px;color:var(--muted);line-height:1.75;}
.disclaimer{text-align:center;color:var(--dim);font-size:11px;margin-top:60px;padding:20px;border-top:1px solid var(--border);line-height:1.8;}
@keyframes fadeUp{from{opacity:0;transform:translateY(12px);}to{opacity:1;transform:translateY(0);}}
.fade-up{animation:fadeUp .4s ease both;}
</style>"""


def _build_js(dv, sl, sc, sco, ol, oc, cl, cb, cs):
    d = json.dumps
    return (
        "<script>\n"
        "Chart.defaults.color='#7d8590';\n"
        "Chart.defaults.borderColor='rgba(255,255,255,0.06)';\n"
        "Chart.defaults.font.family='Inter,system-ui,sans-serif';\n"

        # donut
        "(function(){"
        "var ctx=document.getElementById('sentimentChart');if(!ctx)return;"
        "new Chart(ctx,{type:'doughnut',data:{labels:['Risk-On','Neutral','Risk-Off'],"
        "datasets:[{data:" + d(dv) + ","
        "backgroundColor:['rgba(34,197,94,.8)','rgba(234,179,8,.8)','rgba(239,68,68,.8)'],"
        "borderWidth:0,hoverOffset:6,borderRadius:4}]},"
        "options:{cutout:'76%',animation:{animateRotate:true,duration:800},"
        "plugins:{legend:{position:'bottom',labels:{font:{size:11,weight:'500'},boxWidth:10,padding:10}}}}});"
        "})();\n"

        # sector bar
        "(function(){"
        "var labels=" + d(sl) + ",conf=" + d(sc) + ",colors=" + d(sco) + ";"
        "var ctx=document.getElementById('sectorChart');if(!ctx||!labels.length)return;"
        "new Chart(ctx,{type:'bar',data:{labels:labels,datasets:[{label:'Confidence %',data:conf,"
        "backgroundColor:colors.map(function(c){return c+'55';}),borderColor:colors,"
        "borderWidth:1,borderRadius:5,borderSkipped:false}]},"
        "options:{indexAxis:'y',animation:{duration:700},plugins:{legend:{display:false}},"
        "scales:{x:{min:0,max:100,grid:{color:'rgba(255,255,255,0.04)'},"
        "ticks:{callback:function(v){return v+'%';},font:{size:11}}},"
        "y:{grid:{display:false},ticks:{font:{size:11,weight:'500'}}}}}});"
        "})();\n"

        # opp bar
        "(function(){"
        "var labels=" + d(ol) + ",conf=" + d(oc) + ";"
        "var ctx=document.getElementById('oppChart');if(!ctx||!labels.length)return;"
        "var colors=conf.map(function(v){return v>=70?'#22c55e':v>=45?'#eab308':'#ef4444';});"
        "new Chart(ctx,{type:'bar',data:{labels:labels,datasets:[{label:'Confidence',data:conf,"
        "backgroundColor:colors.map(function(c){return c+'55';}),borderColor:colors,"
        "borderWidth:1,borderRadius:5,borderSkipped:false}]},"
        "options:{indexAxis:'y',animation:{duration:700},plugins:{legend:{display:false}},"
        "scales:{x:{min:0,max:100,grid:{color:'rgba(255,255,255,0.04)'},"
        "ticks:{callback:function(v){return v+'%';},font:{size:11}}},"
        "y:{grid:{display:false},ticks:{font:{size:11}}}}}});"
        "})();\n"

        # cong buy/sell
        "(function(){"
        "var labels=" + d(cl) + ",buys=" + d(cb) + ",sells=" + d(cs) + ";"
        "var ctx=document.getElementById('congBarChart');if(!ctx||!labels.length)return;"
        "new Chart(ctx,{type:'bar',data:{labels:labels,datasets:["
        "{label:'Buys',data:buys,backgroundColor:'rgba(34,197,94,0.4)',borderColor:'#22c55e',borderWidth:1,borderRadius:4},"
        "{label:'Sells',data:sells,backgroundColor:'rgba(239,68,68,0.4)',borderColor:'#ef4444',borderWidth:1,borderRadius:4}]},"
        "options:{plugins:{legend:{labels:{font:{size:11,weight:'500'},boxWidth:10}}},"
        "scales:{x:{grid:{display:false}},y:{grid:{color:'rgba(255,255,255,0.04)'},ticks:{stepSize:1}}}}});"
        "})();\n"

        # cong net
        "(function(){"
        "var labels=" + d(cl) + ",buys=" + d(cb) + ",sells=" + d(cs) + ";"
        "var ctx=document.getElementById('congNetChart');if(!ctx||!labels.length)return;"
        "var net=buys.map(function(b,i){return b-sells[i];});"
        "var colors=net.map(function(v){return v>0?'rgba(34,197,94,0.5)':v<0?'rgba(239,68,68,0.5)':'rgba(234,179,8,0.5)';});"
        "var borders=net.map(function(v){return v>0?'#22c55e':v<0?'#ef4444':'#eab308';});"
        "new Chart(ctx,{type:'bar',data:{labels:labels,datasets:[{label:'Net (Buys-Sells)',data:net,"
        "backgroundColor:colors,borderColor:borders,borderWidth:1,borderRadius:4}]},"
        "options:{plugins:{legend:{labels:{font:{size:11,weight:'500'},boxWidth:10}}},"
        "scales:{x:{grid:{display:false}},y:{grid:{color:'rgba(255,255,255,0.04)'}}}}}});"
        "})();\n"

        # bar animations
        "document.querySelectorAll('.conf-fill,.sc-conf-fill').forEach(function(el){"
        "var w=el.style.width;el.style.width='0';"
        "requestAnimationFrame(function(){el.style.transition='width .8s cubic-bezier(.4,0,.2,1)';el.style.width=w;});"
        "});\n"
        "</script>"
    )


def _congress_html(cr):
    if not cr or cr.total_trades == 0:
        return '<p style="color:var(--dim);padding:8px 0">No congressional trading data available for this period.</p>'
    lc = {"Strong Buy":"#22c55e","Buy":"#4ade80","Neutral":"#eab308","Sell":"#f87171","Strong Sell":"#ef4444"}
    rows = []
    for sector, sig in sorted(cr.sector_signals.items(), key=lambda x: x[1].net_score, reverse=True):
        color = lc.get(sig.signal_label, "#94a3b8")
        top_t = ", ".join(t.ticker for t in sig.top_tickers[:4] if t.net_score > 0) or "—"
        rows.append(
            "<tr><td>" + sector.replace("_"," ").title() + "</td>"
            + '<td style="color:' + color + ';font-weight:700">' + sig.signal_label + "</td>"
            + '<td style="color:#4ade80">' + str(sig.buy_count) + "</td>"
            + '<td style="color:#f87171">' + str(sig.sell_count) + "</td>"
            + '<td style="color:#38bdf8">' + top_t + "</td></tr>"
        )
    wl = []
    for h in cr.watchlist_highlights[:5]:
        bought = " ".join('<code class="tk">' + t + "</code>" for t in h["tickers_bought"][:4]) or "—"
        sold   = " ".join('<code class="tk" style="color:#fca5a5;border-color:rgba(239,68,68,.2);background:rgba(239,68,68,.08)">' + t + "</code>" for t in h["tickers_sold"][:4]) or "—"
        wl.append(
            '<div class="watchlist-item">'
            '<div><div class="wl-name">' + h["politician"] + '</div>'
            '<div class="wl-party">' + h["party"] + " \u00b7 " + h["chamber"].title() + '</div></div>'
            '<div><div style="font-size:12px;color:#4ade80;margin-bottom:4px">&#x25B2; Bought: ' + bought + '</div>'
            '<div style="font-size:12px;color:#f87171">&#x25BC; Sold: ' + sold + '</div></div>'
            '</div>'
        )
    ai_html = ""
    if cr.ai_narrative:
        ai_html = '<div class="ai-box" style="margin-top:12px"><p>' + cr.ai_narrative[:700] + "&#8230;</p></div>"
    wl_content = "\n".join(wl) if wl else '<div style="padding:14px 16px;color:var(--dim);font-size:13px">No watchlist politician trades in this period.</div>'
    return (
        '<p style="color:var(--muted);font-size:12px;margin-bottom:14px">'
        + '<strong style="color:var(--text)">' + str(cr.total_trades) + '</strong> trades analysed &middot; '
        + '<strong style="color:var(--text)">' + str(cr.watchlist_trades) + '</strong> from watchlist politicians &middot; '
        + 'last <strong style="color:var(--text)">' + str(cr.days_analysed) + '</strong> days</p>'
        + '<div class="cong-table-wrap"><table class="cong-table">'
        + '<thead><tr><th>Sector</th><th>Signal</th><th>Buys</th><th>Sells</th><th>Top Tickers</th></tr></thead>'
        + '<tbody>' + "\n".join(rows) + '</tbody></table></div>'
        + '<div class="watchlist-card"><div class="watchlist-hdr">&#x1F441; Watchlist Politician Activity</div>'
        + wl_content + '</div>' + ai_html
    )


def build_html(opportunities, sector_narratives, macro_narrative, congress_report=None):
    now_str           = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    overall_sentiment = macro_narrative.get("overall_sentiment", "Neutral")
    sc_color          = _sc(overall_sentiment)
    valid             = [n for n in sector_narratives if "error" not in n]

    sl  = [n.get("sector","").replace("_"," ").title() for n in valid]
    scf = [round(n.get("confidence",0)*100,1) for n in valid]
    sco = [_sc(n.get("sentiment","")) for n in valid]
    ol  = [o.title[:30]+("…" if len(o.title)>30 else "") for o in opportunities]
    oc  = [round(o.confidence*100,1) for o in opportunities]
    urg = {"immediate":0,"short_term":0,"monitor":0}
    for o in opportunities: urg[o.urgency] = urg.get(o.urgency,0)+1
    dv  = {"Risk-On":[1,0,0],"Neutral":[0,1,0],"Risk-Off":[0,0,1]}.get(overall_sentiment,[0,1,0])
    cl,cb,cs = [],[],[]
    if congress_report and congress_report.total_trades>0:
        for s,sig in sorted(congress_report.sector_signals.items(),key=lambda x:x[1].net_score,reverse=True):
            cl.append(s.replace("_"," ").title()); cb.append(sig.buy_count); cs.append(sig.sell_count)

    # opp cards
    badge_map = {"immediate":'<span class="badge badge-red">Immediate</span>',
                 "short_term":'<span class="badge badge-amber">Short Term</span>',
                 "monitor":'<span class="badge badge-slate">Monitor</span>'}
    opp_cards = []
    for i,opp in enumerate(opportunities):
        pct = int(opp.confidence*100)
        bc  = "#22c55e" if pct>=70 else "#eab308" if pct>=45 else "#ef4444"
        ot  = opp.type.replace("_"," ").title() if hasattr(opp,"type") else ""
        tks = " ".join('<code class="tk">'+t+"</code>" for t in opp.tickers) or '<span style="color:var(--dim);font-size:12px">No specific tickers</span>'
        opp_cards.append(
            '<div class="opp-card fade-up">'
            '<div class="opp-topbar" style="background:linear-gradient(90deg,'+bc+',transparent)"></div>'
            '<div class="opp-row1">'
            '<span class="opp-num">#'+str(i+1)+'</span>'
            '<div class="opp-title-wrap"><div class="opp-title">'+opp.title+'</div><div class="opp-type">'+ot+'</div></div>'
            '<div class="opp-badges">'+badge_map.get(opp.urgency,"")+'</div></div>'
            '<p class="opp-summary">'+(opp.summary or "")+'</p>'
            '<div class="opp-action-box"><strong>Action:</strong> '+opp.action+'</div>'
            '<div class="opp-footer">'
            '<div class="conf-row"><span class="conf-lbl">Confidence</span>'
            '<div class="conf-track"><div class="conf-fill" style="width:'+str(pct)+'%;background:'+bc+'"></div></div>'
            '<span class="conf-pct" style="color:'+bc+'">'+str(pct)+'%</span></div>'
            '<div class="tickers-wrap">'+tks+'</div></div></div>'
        )

    # sector cards
    sec_cards = []
    for n in valid:
        c    = _sc(n.get("sentiment",""))
        cp   = int(n.get("confidence",0)*100)
        sent = n.get("sentiment","")
        sec_cards.append(
            '<div class="sector-card fade-up">'
            '<div class="sc-head"><span class="sc-name" style="color:'+c+'">'+n.get("sector","").upper().replace("_"," ")+'</span>'
            '<span class="sc-pill" style="background:'+c+'18;color:'+c+';border:1px solid '+c+'30">'+sent+'</span></div>'
            '<p class="sc-oneliner">'+n.get("summary_one_liner","")+'</p>'
            '<div class="sc-conf-row"><span class="sc-conf-lbl">Confidence</span>'
            '<div class="sc-conf-track"><div class="sc-conf-fill" style="width:'+str(cp)+'%;background:'+c+'"></div></div>'
            '<span class="sc-conf-pct" style="color:'+c+'">'+str(cp)+'%</span></div>'
            '<p class="sc-narrative">'+n.get("narrative","")[:420]+'&#8230;</p></div>'
        )

    cong_charts = (
        '<div class="cong-charts-row">'
        '<div class="chart-card"><div class="chart-title">Buy vs Sell by Sector</div><canvas id="congBarChart" height="220"></canvas></div>'
        '<div class="chart-card"><div class="chart-title">Net Congressional Sentiment</div><canvas id="congNetChart" height="220"></canvas></div>'
        '</div>'
    ) if cl else ""

    dom_theme = macro_narrative.get("dominant_theme","—")
    mk_narr   = macro_narrative.get("market_narrative","No macro narrative available.")
    css       = _CSS.replace("SENTCOLOR", sc_color)

    opp_html = "\n".join(opp_cards) if opp_cards else '<p style="color:var(--dim);padding:20px 0">No opportunities detected.</p>'
    sec_html = "\n".join(sec_cards) if sec_cards else '<p style="color:var(--dim)">No sector data available.</p>'

    html = (
        '<!DOCTYPE html><html lang="en"><head>'
        '<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Stock Narrative Engine \u2014 ' + now_str + '</title>'
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">'
        '<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>'
        + css +
        '</head><body>'

        # NAV
        '<nav class="nav">'
        '<div class="nav-brand">&#x1F4C8;&nbsp;<span>Narrative Engine</span></div>'
        '<div class="nav-links">'
        '<a href="#overview" class="nav-link">Overview</a>'
        '<a href="#opportunities" class="nav-link">Opportunities</a>'
        '<a href="#sectors" class="nav-link">Sectors</a>'
        '<a href="#congress" class="nav-link">Congress</a>'
        '</div><span class="nav-time">' + now_str + '</span></nav>'

        '<div class="page">'

        # HERO
        '<div class="hero" id="overview">'
        '<div class="hero-tag">Live Market Intelligence</div>'
        '<h1>Stock <span class="grad">Narrative Engine</span></h1>'
        '<p class="hero-sub">AI-powered market analysis &middot; ' + now_str + ' &middot; Research purposes only</p>'
        '</div>'

        # STATS
        '<div class="stats-row">'
        '<div class="stat-card fade-up"><div class="stat-label">Market Sentiment</div><div class="stat-value" style="color:var(--sent)">'+overall_sentiment+'</div><div class="stat-sub">Overall bias</div></div>'
        '<div class="stat-card fade-up"><div class="stat-label">Opportunities</div><div class="stat-value" style="color:var(--cyan)">'+str(len(opportunities))+'</div><div class="stat-sub">Detected this run</div></div>'
        '<div class="stat-card fade-up"><div class="stat-label">Sectors Covered</div><div class="stat-value" style="color:var(--purple)">'+str(len(valid))+'</div><div class="stat-sub">With AI narrative</div></div>'
        '<div class="stat-card fade-up"><div class="stat-label">Immediate Alerts</div><div class="stat-value" style="color:var(--red)">'+str(urg.get("immediate",0))+'</div><div class="stat-sub">Action required now</div></div>'
        '<div class="stat-card fade-up"><div class="stat-label">Short-Term Signals</div><div class="stat-value" style="color:var(--yellow)">'+str(urg.get("short_term",0))+'</div><div class="stat-sub">Near-term window</div></div>'
        '</div>'

        # CHARTS
        '<div class="charts-grid">'
        '<div class="chart-card"><div class="chart-title">Market Mode</div><canvas id="sentimentChart" height="190"></canvas>'
        '<div class="sentiment-label">'+overall_sentiment+'</div><div class="sentiment-sub">'+dom_theme[:45]+'</div></div>'
        '<div class="chart-card"><div class="chart-title">Sector Confidence &amp; Sentiment</div><canvas id="sectorChart" height="190"></canvas></div>'
        '<div class="chart-card"><div class="chart-title">Opportunity Confidence Scores</div><canvas id="oppChart" height="190"></canvas></div>'
        '</div>'

        # MACRO BANNER
        '<div class="macro-banner">'
        '<div class="mb-meta"><span class="mb-label">Sentiment</span><span class="mb-value">'+overall_sentiment+'</span><span class="mb-theme">'+dom_theme+'</span></div>'
        '<div class="mb-divider"></div>'
        '<p class="mb-narrative">'+mk_narr+'</p>'
        '</div>'

        # OPPORTUNITIES
        '<div class="section-title" id="opportunities"><span>&#x1F3AF;</span> Investment Opportunities<span class="section-count">'+str(len(opportunities))+' detected</span></div>'
        '<div class="opp-grid">'+opp_html+'</div>'

        # SECTORS
        '<div class="section-title" id="sectors"><span>&#x1F4CA;</span> Sector Narratives<span class="section-count">'+str(len(valid))+' sectors</span></div>'
        '<div class="sector-grid">'+sec_html+'</div>'

        # CONGRESS
        '<div class="section-title" id="congress"><span>&#x1F3DB;</span> Congressional Trading Intelligence</div>'
        + _congress_html(congress_report)
        + cong_charts

        # DISCLAIMER
        + '<div class="disclaimer"><strong>Research &amp; educational purposes only.</strong><br>'
        'This report is AI-generated from public data sources and does not constitute financial advice.<br>'
        'Always conduct your own due diligence and consult a licensed financial advisor before making any investment decision.</div>'
        '</div>'

        + _build_js(dv, sl, scf, sco, ol, oc, cl, cb, cs)
        + '</body></html>'
    )
    return html
