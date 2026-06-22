#!/usr/bin/env python3
"""
StockIQ Daily Briefing Updater v2
Features: market speed report + AI event analysis with beneficiary/victim stocks
Runs daily at 01:00 UTC (09:00 Taiwan) via OpenClaw heartbeat
"""
import urllib.request, json, base64, time, re
from datetime import datetime, timezone, timedelta

GH_TOKEN = os.environ.get("GH_TOKEN", "")
REPO = "smartlife-calendar/AI-Investment-HQ"
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
HEADERS_YF = {"User-Agent": UA, "Accept": "*/*", "Referer": "https://finance.yahoo.com/"}

# ── Weekend / holiday check ───────────────────────────────────────────────────
def is_market_day():
    """US market is open Mon-Fri (excluding major holidays). UTC time."""
    now_utc = datetime.now(timezone.utc)
    # US market opens 13:30 UTC; check if today is a trading day
    weekday = now_utc.weekday()  # 0=Mon, 6=Sun
    if weekday >= 5:  # Saturday or Sunday
        return False, now_utc.strftime("%A")
    # Basic holiday check (major US holidays)
    mmdd = now_utc.strftime("%m-%d")
    holidays = {"01-01", "07-04", "12-25", "11-11"}  # New Year, July 4, Christmas, Veterans
    if mmdd in holidays:
        return False, "Holiday"
    return True, "Weekday"

def get_yf(scrId, n=10):
    for base in ["query1", "query2"]:
        try:
            time.sleep(2)
            url = f"https://{base}.finance.yahoo.com/v1/finance/screener/predefined/saved?formatted=false&lang=en-US&region=US&scrIds={scrId}&count={n}"
            resp = urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS_YF), timeout=12)
            q = json.loads(resp.read()).get("finance", {}).get("result", [{}])[0].get("quotes", [])
            if q: return q
        except Exception as e: print(f"  {base}: {e}")
        time.sleep(3)
    return []

def get_news(sym):
    try:
        time.sleep(1)
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={sym}&newsCount=3&quotesCount=0"
        resp = urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS_YF), timeout=8)
        return [n.get("title","") for n in json.loads(resp.read()).get("news",[])[:3]]
    except: return []

def claude(prompt):
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps({"model":"claude-haiku-4-5","max_tokens":500,"messages":[{"role":"user","content":prompt}]}).encode(),
        headers={"Content-Type":"application/json","x-api-key":ANTHROPIC_KEY,"anthropic-version":"2023-06-01"},
        method="POST"
    )
    return json.loads(urllib.request.urlopen(req, timeout=30).read())["content"][0]["text"].strip()

import sys
market_open, day_name = is_market_day()
tw = datetime.now(timezone.utc) + timedelta(hours=8)
ds = tw.strftime("%Y/%m/%d %H:%M")

if not market_open:
    # Weekend / holiday: push a "non-trading day" message instead of fetching data
    print(f"Non-trading day ({day_name}), pushing 非交易日 briefing...")
    weekend_briefing = (
        f'<div style="background:linear-gradient(135deg,#1e1b4b,#1e3a5f);border-radius:16px;padding:24px;color:white;margin-bottom:24px">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;flex-wrap:wrap;gap:8px">'
        f'<h2 style="font-size:20px;font-weight:800;margin:0">📅 非交易日</h2>'
        f'<span style="color:#818cf8;font-size:12px;background:rgba(255,255,255,0.1);padding:4px 10px;border-radius:20px">{ds}（{day_name}）</span>'
        f'</div>'
        f'<div style="background:rgba(255,255,255,0.08);border-radius:12px;padding:20px;text-align:center">'
        f'<div style="font-size:40px;margin-bottom:12px">😴</div>'
        f'<div style="font-size:16px;font-weight:700;margin-bottom:8px">美股今日休市</div>'
        f'<div style="font-size:13px;color:#a5b4fc;line-height:1.6">'
        f'下一個交易日速報將於開市前自動更新<br>'
        f'台灣時間週一–週五 <strong style="color:#4ade80">09:30</strong> 更新早報</div>'
        f'</div>'
        f'<p style="color:#4f46e5;font-size:11px;margin-top:14px;margin-bottom:0">📊 Yahoo Finance｜stockiq.tw</p></div>'
    )
    # Only update topBriefing, leave dailyColumn as-is
    ghr = urllib.request.Request(f"https://api.github.com/repos/{REPO}/contents/frontend/index.html", headers={"Authorization":f"token {GH_TOKEN}","Accept":"application/vnd.github.v3+json"})
    ghd = json.loads(urllib.request.urlopen(ghr).read())
    html = base64.b64decode(ghd["content"]).decode("utf-8")
    # Use surgical replace
    def replace_div_inner(html, div_id, new_inner):
        pattern = f'id="{div_id}"'
        pos = html.find(pattern)
        if pos < 0: return html
        tag_end = html.find('>', pos) + 1
        depth = 1
        i = tag_end
        while i < len(html) and depth > 0:
            if html[i:i+4] == '<div': depth += 1
            elif html[i:i+6] == '</div>': depth -= 1
            if depth > 0: i += 1
        return html[:tag_end] + new_inner + html[i:]
    # Fetch weekend news (markets closed but news still flows)
    print("Fetching weekend news headlines...")
    weekend_news_html = ""
    try:
        news_url = "https://query1.finance.yahoo.com/v1/finance/search?q=stock+market&newsCount=8&quotesCount=0"
        r_news = urllib.request.urlopen(urllib.request.Request(news_url, headers=HEADERS_YF), timeout=10)
        news_list = json.loads(r_news.read()).get("news", [])
        if news_list:
            news_rows = "".join(
                f'<div style="padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.08)">'
                f'<a href="{n.get("link","#")}" target="_blank" rel="noopener" '
                f'style="color:#a5b4fc;font-size:12px;text-decoration:none;line-height:1.5">'
                f'{n.get("title","")}</a>'
                f'<span style="color:#4f46e5;font-size:10px;margin-left:6px">{n.get("publisher","")}</span>'
                f'</div>'
                for n in news_list[:6]
            )
            weekend_news_html = (
                f'<div style="background:rgba(255,255,255,0.06);border-radius:10px;padding:14px;margin-top:14px">'
                f'<div style="color:#fde68a;font-weight:700;font-size:13px;margin-bottom:10px">🌐 週末財金新聞</div>'
                f'{news_rows}'
                f'</div>'
            )
            print(f"  Got {len(news_list)} news items")
    except Exception as e:
        print(f"  News fetch failed: {e}")

    # Embed news in the weekend briefing
    weekend_briefing_with_news = weekend_briefing.replace(
        f'<p style="color:#4f46e5;font-size:11px;margin-top:14px;margin-bottom:0">📊 Yahoo Finance｜stockiq.tw</p></div>',
        weekend_news_html + f'<p style="color:#4f46e5;font-size:11px;margin-top:14px;margin-bottom:0">📊 Yahoo Finance｜stockiq.tw</p></div>'
    )

    html = replace_div_inner(html, "topBriefing", weekend_briefing_with_news)
    enc = base64.b64encode(html.encode()).decode()
    urllib.request.urlopen(urllib.request.Request(f"https://api.github.com/repos/{REPO}/contents/frontend/index.html",data=json.dumps({"message":f"非交易日 {ds}","sha":ghd["sha"],"content":enc}).encode(),headers={"Authorization":f"token {GH_TOKEN}","Content-Type":"application/json","Accept":"application/vnd.github.v3+json"},method="PUT"))
    ghp=json.loads(urllib.request.urlopen(urllib.request.Request(f"https://api.github.com/repos/{REPO}/contents/index.html?ref=gh-pages",headers={"Authorization":f"token {GH_TOKEN}","Accept":"application/vnd.github.v3+json"})).read())
    urllib.request.urlopen(urllib.request.Request(f"https://api.github.com/repos/{REPO}/contents/index.html",data=json.dumps({"message":f"非交易日 {ds}","sha":ghp["sha"],"content":enc,"branch":"gh-pages"}).encode(),headers={"Authorization":f"token {GH_TOKEN}","Content-Type":"application/json","Accept":"application/vnd.github.v3+json"},method="PUT"))
    print(f"✅ Synced gh-pages — 非交易日 + 週末新聞 {ds}")
    sys.exit(0)

print("Fetching data...")
gainers = get_yf("day_gainers", 10)
losers = get_yf("day_losers", 10)
actives = get_yf("most_actives", 25)
if not gainers: print("No Yahoo Finance data"); exit(0)

strong_buy, strong_sell = [], []
for q in actives:
    vol = q.get("regularMarketVolume", 0)
    avg = q.get("averageDailyVolume3Month") or 1
    pct = q.get("regularMarketChangePercent", 0)
    vr = vol/avg
    if vr >= 1.5:
        if pct > 3: strong_buy.append({**q, "vr": round(vr,1)})
        elif pct < -3: strong_sell.append({**q, "vr": round(vr,1)})

tb = (strong_buy or gainers)[0]
ts = (strong_sell or losers)[0]
bs, ss = tb.get("symbol","?"), ts.get("symbol","?")
bp = round(tb.get("regularMarketChangePercent",0),2)
sp = round(ts.get("regularMarketChangePercent",0),2)
bvr = tb.get("vr","?"); svr = ts.get("vr","?")

print(f"Buy: {bs} {bp:+.1f}%, Sell: {ss} {sp:+.1f}%")
bn = get_news(bs); sn = get_news(ss)

print("Generating AI analysis...")
analysis = claude(
    f"今日美股事件分析（繁體中文，詳細）：\n"
    f"📈 強力買進：{bs} {bp:+.1f}% 量比{bvr}x 新聞：{'; '.join(bn[:2])}\n"
    f"📉 強力賣出：{ss} {sp:+.1f}% 量比{svr}x 新聞：{'; '.join(sn[:2])}\n\n"
    "請依序分析兩支股票（先買進再賣出），每支包含：\n"
    "(1) 觸發事件（1句話）\n"
    "(2) 主要原因（3點，每點20字）\n"
    "(3) 受惠個股：2-3支可能連動上漲的相關股，說明關聯\n"
    "(4) 受害個股：2-3支可能連動下跌的競爭股，說明關聯\n"
    "(5) 結論（1句話）\n"
    "總共250字，格式清楚。"
)

# Split analysis
mid = analysis.find(ss) if ss in analysis else len(analysis)//2
buy_a = analysis[:mid].strip()
sell_a = analysis[mid:].strip() if mid < len(analysis) else analysis

tw = datetime.now(timezone.utc) + timedelta(hours=8)
ds = tw.strftime("%Y/%m/%d %H:%M")

def row(q, c):
    s=q.get("symbol",""); p=q.get("regularMarketChangePercent",0); vr=q.get("vr","")
    vs=f'<span style="color:#f97316;font-size:10px"> {vr}x</span>' if vr else ""
    oc=f"document.getElementById(\'tickerInput\').value=\'{s}\';document.getElementById(\'tickerInput\').scrollIntoView({{behavior:\'smooth\'}})"
    return f'<div onclick="{oc}" style="display:flex;justify-content:space-between;padding:4px 0;cursor:pointer;border-bottom:1px solid rgba(255,255,255,0.08)"><span style="font-weight:700;color:#a5b4fc">{s}</span><span style="color:{c}">{("+" if p>0 else "")}{p:.1f}%{vs}</span></div>'

bh="".join(row(q,"#4ade80") for q in strong_buy[:5]) or "<p style=\'color:#818cf8;font-size:11px;margin:0\'>今日無強力買進訊號</p>"
sh="".join(row(q,"#f87171") for q in strong_sell[:5]) or "<p style=\'color:#818cf8;font-size:11px;margin:0\'>今日無強力賣出訊號</p>"
gh="".join(row(q,"#4ade80") for q in gainers[:5])
lh="".join(row(q,"#f87171") for q in losers[:5])

briefing = (
    f'<div style="background:linear-gradient(135deg,#1e1b4b,#1e3a5f);border-radius:16px;padding:24px;color:white;margin-bottom:24px">'
    f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;flex-wrap:wrap;gap:8px"><h2 style="font-size:20px;font-weight:800;margin:0">📰 今日市場速報</h2><span style="color:#818cf8;font-size:12px;background:rgba(255,255,255,0.1);padding:4px 10px;border-radius:20px">{ds}</span></div>'
    f'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px">'
    f'<div style="background:rgba(74,222,128,0.1);border:1px solid rgba(74,222,128,0.2);border-radius:10px;padding:14px"><div style="color:#86efac;font-weight:700;margin-bottom:10px;font-size:13px">🚀 強力買進</div>{bh}</div>'
    f'<div style="background:rgba(248,113,113,0.1);border:1px solid rgba(248,113,113,0.2);border-radius:10px;padding:14px"><div style="color:#fca5a5;font-weight:700;margin-bottom:10px;font-size:13px">🔴 強力賣出</div>{sh}</div>'
    f'<div style="background:rgba(255,255,255,0.08);border-radius:10px;padding:14px"><div style="color:#fde68a;font-weight:700;margin-bottom:10px;font-size:13px">📈 漲幅前5</div>{gh}</div>'
    f'<div style="background:rgba(255,255,255,0.08);border-radius:10px;padding:14px"><div style="color:#fca5a5;font-weight:700;margin-bottom:10px;font-size:13px">📉 跌幅前5</div>{lh}</div></div>'
    f'<p style="color:#4f46e5;font-size:11px;margin-top:14px;margin-bottom:0">📊 Yahoo Finance｜點代號直接分析｜stockiq.tw</p></div>'
)

column = (
    f'<div style="background:white;border-radius:16px;padding:24px;box-shadow:0 1px 3px rgba(0,0,0,0.1);border:1px solid #e5e7eb">'
    f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;flex-wrap:wrap;gap:8px"><h2 style="font-size:18px;font-weight:800;margin:0;color:#1e293b">📋 今日事件分析專欄</h2><span style="color:#6b7280;font-size:12px;background:#f3f4f6;padding:4px 10px;border-radius:20px">{ds}</span></div>'
    f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">'
    f'<div style="background:#f0fdf4;border-left:4px solid #22c55e;border-radius:0 8px 8px 0;padding:16px"><div style="font-weight:700;color:#15803d;margin-bottom:8px;font-size:14px">📈 {bs} {bp:+.1f}%（量比{bvr}x）</div><div style="font-size:12px;color:#374151;line-height:1.7;white-space:pre-line">{buy_a}</div></div>'
    f'<div style="background:#fef2f2;border-left:4px solid #ef4444;border-radius:0 8px 8px 0;padding:16px"><div style="font-weight:700;color:#dc2626;margin-bottom:8px;font-size:14px">📉 {ss} {sp:+.1f}%（量比{svr}x）</div><div style="font-size:12px;color:#374151;line-height:1.7;white-space:pre-line">{sell_a}</div></div></div>'
    f'<p style="color:#9ca3af;font-size:11px;margin-top:16px;margin-bottom:0">⚠️ 僅供參考，不構成投資建議｜AI生成｜stockiq.tw</p></div>'
)

ghr = urllib.request.Request(f"https://api.github.com/repos/{REPO}/contents/frontend/index.html", headers={"Authorization":f"token {GH_TOKEN}","Accept":"application/vnd.github.v3+json"})
ghd = json.loads(urllib.request.urlopen(ghr).read())
html = base64.b64decode(ghd["content"]).decode("utf-8")
html = re.sub(r"        <!-- Daily Column.*?</div>\s*\n\s*\n","",html,flags=re.DOTALL)
html = re.sub(r"        <!-- Daily Briefing.*?</div>\s*\n\s*\n","",html,flags=re.DOTALL)
od = "        <!-- Product Info + Policies (for payment platform review) -->"
ns = f"        <!-- Daily Column: {ds} -->\n        <div class=\"max-w-5xl mx-auto mt-4 px-4\" id=\"dailyColumn\">{column}</div>\n\n        <!-- Daily Briefing: {ds} -->\n        <div class=\"max-w-5xl mx-auto mt-4 px-4\" id=\"topBriefing\">{briefing}</div>\n\n        <!-- Product Info + Policies (for payment platform review) -->"
html = html.replace(od, ns)
enc = base64.b64encode(html.encode()).decode()
urllib.request.urlopen(urllib.request.Request(f"https://api.github.com/repos/{REPO}/contents/frontend/index.html",data=json.dumps({"message":f"Briefing {ds}","sha":ghd["sha"],"content":enc}).encode(),headers={"Authorization":f"token {GH_TOKEN}","Content-Type":"application/json","Accept":"application/vnd.github.v3+json"},method="PUT"))
ghp=json.loads(urllib.request.urlopen(urllib.request.Request(f"https://api.github.com/repos/{REPO}/contents/index.html?ref=gh-pages",headers={"Authorization":f"token {GH_TOKEN}","Accept":"application/vnd.github.v3+json"})).read())
urllib.request.urlopen(urllib.request.Request(f"https://api.github.com/repos/{REPO}/contents/index.html",data=json.dumps({"message":f"Sync {ds}","sha":ghp["sha"],"content":enc,"branch":"gh-pages"}).encode(),headers={"Authorization":f"token {GH_TOKEN}","Content-Type":"application/json","Accept":"application/vnd.github.v3+json"},method="PUT"))
print(f"✅ Synced gh-pages — {ds}")
print(f"  Buy: {bs} {bp:+.1f}% | Sell: {ss} {sp:+.1f}%")
