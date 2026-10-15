#!/usr/bin/env python3
"""
StockIQ Weekly Report Generator
Runs every Saturday — generates a comprehensive weekly summary
"""
import os, sys, json, base64, urllib.request
from datetime import datetime, timedelta, timezone
from collections import defaultdict

GH_TOKEN = os.environ.get("GH_TOKEN", "")
REPO = "smartlife-calendar/AI-Investment-HQ"
BRANCH = "gh-pages"
GH_HEADERS = {"Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github.v3+json"}
API = f"https://api.github.com/repos/{REPO}"

SB_URL = os.environ.get("SUPABASE_URL", "https://kggwnlevbxghmqpieoet.supabase.co")
SB_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
SB_HEADERS = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}"}

TW_TZ = timezone(timedelta(hours=8))


def gh_get_json(path):
    """Get JSON file from gh-pages."""
    try:
        url = f"{API}/contents/{path}?ref={BRANCH}"
        req = urllib.request.Request(url, headers=GH_HEADERS)
        d = json.loads(urllib.request.urlopen(req, timeout=15).read())
        return json.loads(base64.b64decode(d["content"]).decode()), d.get("sha")
    except:
        return None, None


def gh_put(path, data, msg):
    """Push JSON file to gh-pages."""
    content = json.dumps(data, ensure_ascii=False)
    encoded = base64.b64encode(content.encode()).decode()
    
    # Get existing SHA
    sha = None
    try:
        url = f"{API}/contents/{path}?ref={BRANCH}"
        req = urllib.request.Request(url, headers=GH_HEADERS)
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
        sha = d.get("sha")
    except:
        pass
    
    payload = {"message": msg, "content": encoded, "branch": BRANCH}
    if sha:
        payload["sha"] = sha
    
    req = urllib.request.Request(
        f"{API}/contents/{path}",
        data=json.dumps(payload).encode(),
        headers={**GH_HEADERS, "Content-Type": "application/json"},
        method="PUT"
    )
    r = json.loads(urllib.request.urlopen(req, timeout=30).read())
    return r.get("commit", {}).get("sha", "?")[:7]


def fetch_supabase_signals(days=7):
    """Fetch recent signals from Supabase."""
    since = (datetime.now(TW_TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
    signals = []
    offset = 0
    while True:
        try:
            url = f"{SB_URL}/rest/v1/accumulation_signals?select=date,symbol,score,direction,price,phase&date=gte.{since}&order=date.desc&limit=1000&offset={offset}"
            req = urllib.request.Request(url, headers=SB_HEADERS)
            batch = json.loads(urllib.request.urlopen(req, timeout=15).read())
            if not batch:
                break
            signals.extend(batch)
            offset += 1000
            if len(batch) < 1000:
                break
        except Exception as e:
            print(f"  ⚠️ Supabase error: {e}")
            break
    return signals


def save_pe_snapshot(alpha_data, date_str):
    """Save daily PE snapshot to pe_history.json."""
    print("📸 Saving PE snapshot...")
    history, sha = gh_get_json("data/pe_history.json")
    if not history:
        history = {"snapshots": {}}
    
    # Build today's snapshot
    today_snap = {}
    for sym, data in alpha_data.items():
        a = data.get("alpha", {})
        v = data.get("valuation", {})
        if not a.get("forward_pe"):
            continue
        today_snap[sym] = {
            "fpe": round(a["forward_pe"], 1) if a.get("forward_pe") else None,
            "tpe": round(a["trailing_pe"], 1) if a.get("trailing_pe") else None,
            "gap": a.get("pe_gap_pct"),
            "sector": v.get("sector", ""),
            "industry": a.get("industry", ""),
            "baseline": v.get("sector_pe_used"),
            "price": data.get("price"),
            "score": data.get("score"),
            "phase": data.get("phase"),
            "cls": data.get("classification"),
        }
    
    history["snapshots"][date_str] = today_snap
    
    # Keep only last 90 days
    all_dates = sorted(history["snapshots"].keys())
    if len(all_dates) > 90:
        for old_date in all_dates[:-90]:
            del history["snapshots"][old_date]
    
    history["last_updated"] = datetime.now(TW_TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    
    commit = gh_put("data/pe_history.json", history, f"PE snapshot {date_str}")
    print(f"  ✅ PE snapshot saved ({len(today_snap)} stocks) → {commit}")
    return history


def fetch_macro_data():
    """Fetch macro indicators: VIX, SPY, signals regime, sector flows, events, paper trading."""
    macro = {}
    
    # 1. Signals regime
    try:
        signals, _ = gh_get_json("data/signals.json")
        if signals:
            regime = signals.get("market_regime", {})
            macro["regime"] = regime.get("regime", "NEUTRAL")
            macro["spy_vs_200d"] = regime.get("spy_above_200d_pct")
            macro["vix"] = regime.get("vix")
            macro["fear_greed"] = regime.get("fear_greed")
            macro["composite_score"] = regime.get("composite_score")
            # Count signals
            sigs = signals.get("signals", [])
            macro["total_buy"] = len([s for s in sigs if s.get("action") in ("BUY", "SCALE_IN")])
            macro["total_sell"] = len([s for s in sigs if s.get("action") == "SELL"])
            macro["total_hold"] = len([s for s in sigs if s.get("action") == "HOLD"])
    except Exception as e:
        print(f"  ⚠️ Signals: {e}")
    
    # 2. Sector flow alerts
    try:
        alerts, _ = gh_get_json("data/sector_flow_alerts.json")
        if alerts:
            macro["sector_alerts"] = {}
            for market in ["us", "tw"]:
                macro["sector_alerts"][market] = {}
                for etf, data in (alerts.get(market, {}) or {}).items():
                    if isinstance(data, dict) and data.get("status"):
                        macro["sector_alerts"][market][etf] = {
                            "name": data.get("name", etf),
                            "status": data.get("status", ""),
                            "avg_5d": data.get("avg_5d_m", 0),
                            "avg_20d": data.get("avg_20d_m", 0),
                        }
    except Exception as e:
        print(f"  ⚠️ Sector alerts: {e}")
    
    # 3. Sector flow weekly performance
    try:
        flow_hist, _ = gh_get_json("data/sector_flow_history.json")
        if flow_hist:
            macro["sector_weekly"] = {"us": {}, "tw": {}}
            for market in ["us", "tw"]:
                for etf, rows in (flow_hist.get(market, {}) or {}).items():
                    if len(rows) >= 5:
                        last5 = rows[-5:]
                        first_close = rows[-6]["close"] if len(rows) >= 6 else last5[0]["close"]
                        last_close = last5[-1]["close"]
                        if first_close and first_close > 0:
                            week_ret = round((last_close - first_close) / first_close * 100, 2)
                            week_flow = round(sum(r.get("flow_m", 0) or 0 for r in last5), 1)
                            macro["sector_weekly"][market][etf] = {
                                "name": rows[-1].get("name", etf) if isinstance(rows[-1], dict) else etf,
                                "return_pct": week_ret,
                                "flow_m": week_flow,
                                "close": last_close,
                            }
    except Exception as e:
        print(f"  ⚠️ Sector flow: {e}")
    
    # 4. Event calendar
    try:
        events, _ = gh_get_json("data/event_calendar.json")
        if events:
            now = datetime.now(TW_TZ)
            upcoming = []
            for evt in events.get("events", []):
                evt_date = evt.get("date", "")
                if evt_date >= now.strftime("%Y-%m-%d"):
                    days_until = (datetime.strptime(evt_date, "%Y-%m-%d") - datetime.strptime(now.strftime("%Y-%m-%d"), "%Y-%m-%d")).days
                    if days_until <= 30:
                        upcoming.append({
                            "date": evt_date,
                            "name": evt.get("name", ""),
                            "type": evt.get("type", ""),
                            "days_until": days_until,
                            "impact": evt.get("impact", ""),
                        })
            macro["upcoming_events"] = sorted(upcoming, key=lambda x: x["date"])[:10]
    except Exception as e:
        print(f"  ⚠️ Events: {e}")
    
    # 5. Paper trading performance
    try:
        paper, _ = gh_get_json("data/paper_portfolio.json")
        if paper:
            stats = paper.get("stats", {})
            macro["paper"] = {
                "nav": stats.get("nav", 30000),
                "return_pct": stats.get("nav_return_pct", 0),
                "positions": len(paper.get("positions", {})),
                "total_trades": stats.get("total_trades", 0),
                "win_rate": stats.get("win_rate", 0),
                "cash": stats.get("cash", 30000),
                "holdings": {},
            }
            for sym, pos in paper.get("positions", {}).items():
                macro["paper"]["holdings"][sym] = {
                    "entry": pos.get("entry_price", 0),
                    "current": pos.get("current_price", 0),
                    "return_pct": pos.get("current_return", 0),
                    "shares": pos.get("shares", 0),
                }
    except Exception as e:
        print(f"  ⚠️ Paper trading: {e}")
    
    return macro


def generate_weekly_report(alpha_data, pe_history, signals_7d):
    """Generate weekly analysis report."""
    now = datetime.now(TW_TZ)
    week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
    week_end = now.strftime("%Y-%m-%d")
    
    print(f"\n📋 Generating weekly report ({week_start} → {week_end})...")
    
    # Fetch macro data
    print("  📡 Fetching macro data...")
    macro = fetch_macro_data()
    
    # ── 1. Sector PE trends ──
    snapshots = pe_history.get("snapshots", {})
    dates = sorted(snapshots.keys())
    
    sector_trends = defaultdict(lambda: {"current": [], "prev": []})
    
    # Current week vs last week
    current_dates = [d for d in dates if d >= week_start]
    prev_start = (now - timedelta(days=now.weekday() + 7)).strftime("%Y-%m-%d")
    prev_dates = [d for d in dates if prev_start <= d < week_start]
    
    for d in current_dates[-1:]:  # Use latest day
        for sym, snap in snapshots.get(d, {}).items():
            sector = snap.get("industry") if snap.get("industry") in ["Semiconductors"] else snap.get("sector", "Other")
            if snap.get("fpe"):
                sector_trends[sector]["current"].append(snap["fpe"])
    
    for d in prev_dates[-1:]:
        for sym, snap in snapshots.get(d, {}).items():
            sector = snap.get("industry") if snap.get("industry") in ["Semiconductors"] else snap.get("sector", "Other")
            if snap.get("fpe"):
                sector_trends[sector]["prev"].append(snap["fpe"])
    
    # ── 2. Signal analysis ──
    new_bulls = [s for s in signals_7d if s["direction"] == "bullish" and s["score"] >= 7]
    new_bears = [s for s in signals_7d if s["direction"] == "bearish"]
    
    # Group signals by symbol, track score changes
    by_symbol = defaultdict(list)
    for s in signals_7d:
        by_symbol[s["symbol"]].append(s)
    
    # ── 3. PE movers ──
    pe_movers = []
    if len(dates) >= 2:
        latest = snapshots.get(dates[-1], {})
        earliest_week = dates[max(0, len(dates)-6)]  # ~5 trading days ago
        prev = snapshots.get(earliest_week, {})
        
        for sym in latest:
            if sym in prev and latest[sym].get("fpe") and prev[sym].get("fpe"):
                old_pe = prev[sym]["fpe"]
                new_pe = latest[sym]["fpe"]
                if old_pe > 0:
                    change = ((new_pe / old_pe) - 1) * 100
                    if abs(change) > 5:  # >5% PE change in a week
                        pe_movers.append({
                            "symbol": sym,
                            "old_pe": old_pe,
                            "new_pe": new_pe,
                            "change_pct": round(change, 1),
                            "sector": latest[sym].get("sector", ""),
                            "price": latest[sym].get("price"),
                        })
        
        pe_movers.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
    
    # ── 4. Build report ──
    report = {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "week": f"{week_start} → {week_end}",
        "summary": {
            "total_bull_signals": len(new_bulls),
            "total_bear_signals": len(new_bears),
            "unique_stocks_tracked": len(by_symbol),
            "pe_data_days": len(current_dates),
        },
        "sector_pe_trends": {},
        "pe_movers_top10": pe_movers[:10],
        "signal_summary": {
            "new_high_score": sorted(new_bulls, key=lambda s: s["score"], reverse=True)[:10],
        },
    }
    
    for sector, data in sorted(sector_trends.items()):
        if len(data["current"]) < 2:
            continue
        curr_avg = sum(data["current"]) / len(data["current"])
        prev_avg = sum(data["prev"]) / len(data["prev"]) if data["prev"] else curr_avg
        change = ((curr_avg / prev_avg) - 1) * 100 if prev_avg > 0 else 0
        report["sector_pe_trends"][sector] = {
            "current_avg_pe": round(curr_avg, 1),
            "prev_week_avg_pe": round(prev_avg, 1),
            "change_pct": round(change, 1),
            "stock_count": len(data["current"]),
        }
    
    # Add macro data
    report["macro"] = macro
    
    return report


def generate_weekly_html(report, alpha_data):
    """Generate weekly report HTML with macro + events + sector + paper trading."""
    now = datetime.now(TW_TZ)
    date_str = now.strftime("%Y-%m-%d")
    week_display = report.get("week", "")
    macro = report.get("macro", {})
    
    # Extract macro values
    regime = macro.get("regime", "NEUTRAL")
    regime_map = {"STRONG_BULL": ("🐂","#16a34a"), "BULL": ("🐂","#22c55e"), "NEUTRAL": ("➡️","#94a3b8"), "CAUTION": ("⚠️","#f59e0b"), "BEAR": ("🐻","#dc2626")}
    regime_emoji, regime_color = regime_map.get(regime, ("➡️","#94a3b8"))
    vix = macro.get("vix", "—")
    spy_pct = macro.get("spy_vs_200d", "—")
    fg = macro.get("fear_greed", "—")
    comp = macro.get("composite_score", "—")
    paper = macro.get("paper", {})
    paper_nav = paper.get("nav", 30000)
    paper_ret = paper.get("return_pct", 0)
    paper_rc = "#22c55e" if paper_ret >= 0 else "#ef4444"
    
    parts = []
    
    # HEAD
    parts.append(f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>StockIQ 週報 — {week_display}</title>
<meta name="description" content="StockIQ 週報 {week_display}：宏觀趨勢、板塊資金流向、事件行事曆、模擬操作追蹤。">
<link rel="canonical" href="https://stockiq.tw/weekly/{date_str}.html">
<link rel="icon" href="/favicon.png">
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 800px; margin: 0 auto; padding: 16px; background: #f8fafc; color: #1e293b; }}
.nav {{ background: #1e1b4b; padding: 12px 20px; text-align: center; margin: -16px -16px 20px; }}
.nav a {{ color: #a5b4fc; text-decoration: none; font-size: 13px; margin: 0 12px; }}
.nav .brand {{ color: white; font-weight: 800; font-size: 18px; margin-right: 20px; }}
.card {{ background: white; border-radius: 12px; border: 1px solid #e2e8f0; padding: 16px; margin-bottom: 16px; }}
.card h2 {{ margin: 0 0 12px; font-size: 16px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th {{ background: #f1f5f9; padding: 8px; text-align: left; }}
td {{ padding: 6px 8px; border-bottom: 1px solid #f1f5f9; }}
.tag {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; }}
.up {{ background: #dcfce7; color: #16a34a; }}
.dn {{ background: #fee2e2; color: #dc2626; }}
.neutral {{ background: #f1f5f9; color: #64748b; }}
a {{ color: #4f46e5; text-decoration: none; }}
.kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr)); gap: 8px; text-align: center; }}
.kpi {{ border-radius: 8px; padding: 10px; }}
.kpi .val {{ font-size: 20px; font-weight: 800; }}
.kpi .lab {{ font-size: 10px; color: #64748b; margin-top: 2px; }}
footer {{ text-align: center; padding: 20px; color: #94a3b8; font-size: 11px; }}
footer a {{ color: #f59e0b; font-weight: 700; }}
</style></head><body>
<nav class="nav">
<a href="/" class="brand">📊 StockIQ</a>
<a href="/about.html">關於</a>
<a href="/methodology.html">方法論</a>
<a href="/blog/">Blog</a>
<a href="/weekly/">週報</a>
</nav>
<div style="text-align:center;margin-bottom:20px">
<h1 style="font-size:22px;margin:0">📊 StockIQ 週報</h1>
<p style="color:#64748b;margin:4px 0">{week_display}</p>
</div>""")
    
    # 1. MACRO OVERVIEW
    ret_sign = "+" if paper_ret >= 0 else ""
    parts.append(f"""
<div class="card" style="border-color:{regime_color}">
<h2>{regime_emoji} 宏觀總覽</h2>
<div class="kpi-grid">
<div class="kpi" style="background:#eff6ff"><div class="val" style="color:{regime_color}">{regime}</div><div class="lab">市場狀態</div></div>
<div class="kpi" style="background:#fefce8"><div class="val" style="color:#92400e">{vix}</div><div class="lab">VIX</div></div>
<div class="kpi" style="background:#f0fdf4"><div class="val" style="color:#16a34a">{spy_pct}%</div><div class="lab">SPY vs 200MA</div></div>
<div class="kpi" style="background:#fef2f2"><div class="val" style="color:#dc2626">{fg}</div><div class="lab">恐懼指數</div></div>
<div class="kpi" style="background:#f5f3ff"><div class="val" style="color:#7c3aed">{comp}</div><div class="lab">綜合/100</div></div>
</div>
<div style="margin-top:10px;font-size:12px;color:#64748b">
<strong>訊號：</strong>買入 {macro.get("total_buy",0)} · 賣出 {macro.get("total_sell",0)} · 持有 {macro.get("total_hold",0)}
</div></div>""")
    
    # 2. PAPER TRADING
    parts.append(f"""
<div class="card">
<h2>💰 模擬操作 v4</h2>
<div class="kpi-grid">
<div class="kpi" style="background:#f8fafc"><div class="val" style="color:{paper_rc}">${paper_nav:,.0f}</div><div class="lab">淨值</div></div>
<div class="kpi" style="background:#f8fafc"><div class="val" style="color:{paper_rc}">{ret_sign}{paper_ret:.2f}%</div><div class="lab">報酬率</div></div>
<div class="kpi" style="background:#f8fafc"><div class="val">{paper.get("positions",0)}/10</div><div class="lab">持倉</div></div>
<div class="kpi" style="background:#f8fafc"><div class="val">{paper.get("win_rate",0)}%</div><div class="lab">勝率</div></div>
</div>""")
    
    holdings = paper.get("holdings", {})
    if holdings:
        parts.append("<table style=\"margin-top:10px\"><thead><tr><th>股票</th><th style=\"text-align:right\">進場</th><th style=\"text-align:right\">現價</th><th style=\"text-align:right\">損益</th></tr></thead><tbody>")
        for sym, h in sorted(holdings.items(), key=lambda x: x[1].get("return_pct", 0), reverse=True):
            ret = h.get("return_pct", 0)
            rc = "up" if ret > 0 else "dn" if ret < 0 else "neutral"
            rs = "+" if ret > 0 else ""
            parts.append(f"<tr><td style=\"font-weight:600\">{sym}</td><td style=\"text-align:right\">${h.get('entry',0):.2f}</td><td style=\"text-align:right\">${h.get('current',0):.2f}</td><td style=\"text-align:right\"><span class=\"tag {rc}\">{rs}{ret:.1f}%</span></td></tr>")
        parts.append("</tbody></table>")
    parts.append("</div>")
    
    # 3. SECTOR FLOWS
    sector_weekly = macro.get("sector_weekly", {})
    sector_alerts = macro.get("sector_alerts", {})
    
    for market, label, flag in [("us", "美股", "🇺🇸"), ("tw", "台股", "🇹🇼")]:
        flows = sector_weekly.get(market, {})
        alerts_m = sector_alerts.get(market, {})
        if not flows:
            continue
        
        parts.append(f"<div class=\"card\"><h2>{flag} {label}板塊資金流（本週）</h2>")
        
        accel = [(e, a) for e, a in alerts_m.items() if "加速" in a.get("status", "")]
        if accel:
            parts.append("<div style=\"margin-bottom:10px;display:flex;gap:6px;flex-wrap:wrap\">")
            for etf, a in accel:
                is_in = "流入" in a["status"]
                bg = "#dcfce7" if is_in else "#fee2e2"
                parts.append(f"<span style=\"background:{bg};padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600\">{a['status']} {a['name']}</span>")
            parts.append("</div>")
        
        parts.append("<table><thead><tr><th>板塊</th><th style=\"text-align:right\">週報酬</th><th style=\"text-align:right\">5日資金流</th></tr></thead><tbody>")
        for etf, data in sorted(flows.items(), key=lambda x: x[1].get("return_pct", 0), reverse=True):
            ret = data.get("return_pct", 0)
            flow = data.get("flow_m", 0)
            rc = "up" if ret > 0 else "dn"
            fc = "up" if flow > 0 else "dn" if flow < 0 else "neutral"
            name = alerts_m.get(etf, {}).get("name", etf)
            rs = "+" if ret > 0 else ""
            fs = "+" if flow > 0 else ""
            parts.append(f"<tr><td style=\"font-weight:600\">{name}</td><td style=\"text-align:right\"><span class=\"tag {rc}\">{rs}{ret:.1f}%</span></td><td style=\"text-align:right\"><span class=\"tag {fc}\">{fs}{flow:.0f}M</span></td></tr>")
        parts.append("</tbody></table></div>")
    
    # 4. EVENTS
    events = macro.get("upcoming_events", [])
    if events:
        parts.append("<div class=\"card\" style=\"border-color:#f59e0b\"><h2>🗓️ 未來 30 天重大事件</h2>")
        type_icons = {"election": "🗳️", "fomc": "🏦", "opex": "📊", "cpi": "📈", "earnings": "📋"}
        for evt in events:
            days = evt.get("days_until", 0)
            urgency = "#dc2626" if days <= 3 else "#f59e0b" if days <= 7 else "#94a3b8"
            icon = type_icons.get(evt.get("type", ""), "📅")
            parts.append(f"<div style=\"display:flex;gap:12px;padding:8px 0;border-bottom:1px solid #f1f5f9;font-size:13px;align-items:center\"><div style=\"min-width:60px;text-align:center;color:{urgency};font-weight:700\">{days}天</div><div>{icon} <strong>{evt.get('name','')}</strong><br><span style=\"font-size:11px;color:#94a3b8\">{evt.get('date','')} · {evt.get('impact','')}</span></div></div>")
        parts.append("</div>")
    
    # 5. SIGNAL SUMMARY
    parts.append(f"""
<div class="card">
<h2>📈 訊號摘要</h2>
<div class="kpi-grid">
<div class="kpi" style="background:#eff6ff"><div class="val" style="color:#4f46e5">{report["summary"]["total_bull_signals"]}</div><div class="lab">多頭訊號</div></div>
<div class="kpi" style="background:#fef2f2"><div class="val" style="color:#dc2626">{report["summary"]["total_bear_signals"]}</div><div class="lab">空頭訊號</div></div>
<div class="kpi" style="background:#f0fdf4"><div class="val" style="color:#16a34a">{report["summary"]["unique_stocks_tracked"]}</div><div class="lab">追蹤個股</div></div>
</div></div>""")
    
    # 6. PE TRENDS (original)
    parts.append("""<div class="card"><h2>📊 板塊 PE 趨勢（週變化）</h2>
<table><thead><tr><th>板塊</th><th style="text-align:right">本週 PE</th><th style="text-align:right">上週 PE</th><th style="text-align:right">變化</th><th style="text-align:right">股數</th></tr></thead><tbody>""")
    
    for sector, data in sorted(report.get("sector_pe_trends", {}).items(), key=lambda x: abs(x[1].get("change_pct", 0)), reverse=True):
        change = data.get("change_pct", 0)
        cc = "up" if change > 2 else "dn" if change < -2 else "neutral"
        cs = f"+{change:.1f}%" if change > 0 else f"{change:.1f}%"
        parts.append(f"<tr><td style=\"font-weight:600\">{sector}</td><td style=\"text-align:right\">{data['current_avg_pe']:.1f}x</td><td style=\"text-align:right;color:#94a3b8\">{data['prev_week_avg_pe']:.1f}x</td><td style=\"text-align:right\"><span class=\"tag {cc}\">{cs}</span></td><td style=\"text-align:right;color:#94a3b8\">{data['stock_count']}</td></tr>")
    
    parts.append("</tbody></table></div>")
    
    # PE Movers
    movers = report.get("pe_movers_top10", [])
    if movers:
        parts.append("""<div class="card"><h2>🔍 PE 大幅異動（週變化 &gt;5%）</h2>
<table><thead><tr><th>股票</th><th>板塊</th><th style="text-align:right">上週PE</th><th style="text-align:right">本週PE</th><th style="text-align:right">變化</th></tr></thead><tbody>""")
        for m in movers:
            cc = "up" if m["change_pct"] > 0 else "dn"
            parts.append(f"<tr><td style=\"font-weight:600\">{m['symbol']}</td><td style=\"font-size:11px;color:#64748b\">{m['sector']}</td><td style=\"text-align:right\">{m['old_pe']:.1f}x</td><td style=\"text-align:right\">{m['new_pe']:.1f}x</td><td style=\"text-align:right\"><span class=\"tag {cc}\">{m['change_pct']:+.1f}%</span></td></tr>")
        parts.append("</tbody></table></div>")
    
    # Cyclical breakout
    alpha_json, _ = gh_get_json("data/alpha.json")
    cyclical = (alpha_json or {}).get("cyclical_breakout", [])
    if cyclical:
        parts.append("""<div class="card" style="border-color:#f59e0b"><h2>🔄 景氣循環脫離偵測</h2>
<table><thead><tr><th>股票</th><th>板塊</th><th style="text-align:right">FwdPE</th><th style="text-align:right">基準PE</th><th style="text-align:right">擴張</th><th>狀態</th></tr></thead><tbody>""")
        for b in cyclical:
            fpe = b.get("forward_pe") or b.get("fwd_pe", 0)
            baseline = b.get("sector_baseline_pe") or b.get("breakout_pe", 0)
            expansion = b.get("pe_expansion", fpe/baseline if baseline else 0)
            status = "🚀 確認突破" if b.get("breakout_confirmed") else "👀 觀察中"
            parts.append(f"<tr><td style=\"font-weight:600\">{b['symbol']}</td><td style=\"font-size:11px\">{b.get('sector','')}</td><td style=\"text-align:right\">{fpe:.1f}x</td><td style=\"text-align:right;color:#94a3b8\">{baseline}x</td><td style=\"text-align:right;font-weight:600;color:#f59e0b\">{expansion:.1f}x</td><td style=\"font-size:11px\">{status}</td></tr>")
        parts.append("</tbody></table></div>")
    
    # FOOTER
    parts.append(f"""
<footer>
<p>StockIQ 週報 · {date_str} · <a href="https://stockiq.tw">stockiq.tw</a></p>
<p>資料來源：Yahoo Finance, SEC EDGAR · 分析僅供參考，不構成投資建議</p>
<p style="margin-top:8px"><a href="https://buymeacoffee.com/SmartLifeCalendar">☕ 請我喝杯咖啡 — 支持免費開發</a></p>
</footer></body></html>""")
    
    return "\n".join(parts)



def main():
    now = datetime.now(TW_TZ)
    date_str = now.strftime("%Y-%m-%d")
    print(f"📋 StockIQ Weekly Report — {date_str}")
    
    # 1. Load alpha data
    print("\n📥 Loading alpha data...")
    alpha_data, _ = gh_get_json("data/alpha.json")
    if not alpha_data:
        print("  ❌ No alpha data found")
        return
    stocks = alpha_data.get("stocks", {})
    print(f"  ✅ {len(stocks)} stocks")
    
    # 2. Save PE snapshot
    pe_history = save_pe_snapshot(stocks, date_str)
    
    # 3. Fetch signals
    print("\n📥 Fetching 7-day signals...")
    signals = fetch_supabase_signals(7)
    print(f"  ✅ {len(signals)} signals")
    
    # 4. Generate report data
    report = generate_weekly_report(stocks, pe_history, signals)
    
    # 5. Push report JSON
    commit = gh_put("data/weekly_report.json", report, f"Weekly report {date_str}")
    print(f"  ✅ weekly_report.json → {commit}")
    
    # 6. Generate HTML
    html = generate_weekly_html(report, stocks)
    
    # 7. Push weekly HTML
    week_num = now.isocalendar()[1]
    html_path = f"weekly/{date_str}.html"
    commit2 = gh_put(html_path, None, f"Weekly report HTML {date_str}")
    # Actually push raw HTML
    encoded = base64.b64encode(html.encode()).decode()
    sha = None
    try:
        url = f"{API}/contents/{html_path}?ref={BRANCH}"
        req = urllib.request.Request(url, headers=GH_HEADERS)
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
        sha = d.get("sha")
    except:
        pass
    payload = {"message": f"Weekly report {date_str}", "content": encoded, "branch": BRANCH}
    if sha:
        payload["sha"] = sha
    req = urllib.request.Request(
        f"{API}/contents/{html_path}",
        data=json.dumps(payload).encode(),
        headers={**GH_HEADERS, "Content-Type": "application/json"},
        method="PUT"
    )
    r = json.loads(urllib.request.urlopen(req, timeout=30).read())
    print(f"  ✅ {html_path} → {r.get('commit',{}).get('sha','?')[:7]}")
    
    # 8. Summary
    summary = report.get("summary", {})
    trends = report.get("sector_pe_trends", {})
    movers = report.get("pe_movers_top10", [])
    
    print(f"\n{'='*50}")
    print(f"📊 週報摘要")
    print(f"  多頭訊號: {summary.get('total_bull_signals', 0)}")
    print(f"  空頭訊號: {summary.get('total_bear_signals', 0)}")
    print(f"  PE 異動最大板塊:")
    for sector, data in sorted(trends.items(), key=lambda x: abs(x[1].get("change_pct", 0)), reverse=True)[:3]:
        print(f"    {sector}: {data['change_pct']:+.1f}%")
    if movers:
        print(f"  PE 異動最大個股:")
        for m in movers[:5]:
            print(f"    {m['symbol']}: {m['old_pe']:.1f}→{m['new_pe']:.1f} ({m['change_pct']:+.1f}%)")
    
    print(f"\n🌐 週報已發布: https://stockiq.tw/{html_path}")
    print("✅ Done!")


if __name__ == "__main__":
    main()
