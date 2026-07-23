#!/usr/bin/env python3
"""
StockIQ Daily Briefing Updater
Fetches Yahoo Finance screener data (gainers, losers, most_actives),
generates HTML briefing cards + AI analysis column, and pushes to GitHub Pages.
"""

import json, os
import base64
import requests
import yfinance as yf
from datetime import datetime, timezone, timedelta
import traceback
import re

# ── Config ──────────────────────────────────────────────────────
GITHUB_TOKEN = os.environ.get("GH_TOKEN", "")
REPO = "smartlife-calendar/AI-Investment-HQ"
BRANCH = "gh-pages"
FILE_PATH = "index.html"
API_BASE = f"https://api.github.com/repos/{REPO}"
HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}

CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")
CLAUDE_MODEL = "claude-haiku-4-5-20251001"


# ── Market Data Fetch (from data/market_movers.json on GitHub) ──
def fetch_all_data():
    """Read market movers from data/market_movers.json (written by update_data.py).
    
    This ensures the daily briefing and email use the exact same data source.
    """
    gainers = []
    losers = []
    actives = []

    try:
        url = f"{API_BASE}/contents/data/market_movers.json?ref={BRANCH}"
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        movers = json.loads(content)

        def convert(stock):
            """Convert update_data.py format → update_briefing.py format."""
            vol = stock.get("volume", 0) or 0
            vr = stock.get("vr", 0) or 0
            # Reconstruct avgVolume from volume/vr if vr is available
            if vr and vr > 0:
                avg_vol = max(1, int(vol / vr))
            else:
                avg_vol = vol or 1  # if no vr data, assume avg = current vol (ratio ~1)
            return {
                "symbol": stock.get("symbol", ""),
                "name": stock.get("name", stock.get("symbol", "")),
                "price": stock.get("price", 0),
                "change": 0,  # not needed for display
                "changePct": stock.get("change_pct", 0),
                "volume": vol,
                "avgVolume": avg_vol,
                "volRatio": round(vr, 1) if vr else 0,
            }

        gainers = [convert(s) for s in movers.get("gainers", [])]
        losers = [convert(s) for s in movers.get("losers", [])]

        # Inject/override strong_buy into gainers and strong_sell into losers
        # strong_buy/sell have accurate vr data, so they should take priority
        gainer_map = {s["symbol"]: i for i, s in enumerate(gainers)}
        for s in movers.get("strong_buy", []):
            c = convert(s)
            if c["symbol"] in gainer_map:
                gainers[gainer_map[c["symbol"]]] = c  # override with vr data
            else:
                gainers.append(c)

        loser_map = {s["symbol"]: i for i, s in enumerate(losers)}
        for s in movers.get("strong_sell", []):
            c = convert(s)
            if c["symbol"] in loser_map:
                losers[loser_map[c["symbol"]]] = c  # override with vr data
            else:
                losers.append(c)

        # Build actives from most_active (deduplicated)
        seen = set()
        for s in movers.get("most_active", []):
            sym = s.get("symbol", "")
            if sym and sym not in seen:
                seen.add(sym)
                actives.append(convert(s))

        print(f"  ✅ Read from data/market_movers.json ({movers.get('generated_at', '?')})")

    except Exception as e:
        print(f"  ⚠️  Failed to read market_movers.json: {e}")
        print("  Falling back to direct Yahoo Finance fetch...")
        gainers, losers, actives = fetch_screener_fallback()

    return gainers, losers, actives


def fetch_screener_fallback():
    """Fallback: fetch a list of popular tickers directly via yfinance."""
    popular = [
        "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AMD",
        "NFLX", "CRM", "AVGO", "ORCL", "ADBE", "INTC", "QCOM", "MU",
        "COIN", "PLTR", "SOFI", "RIVN", "NIO", "MARA", "RIOT", "SQ",
        "SHOP", "SNOW", "DDOG", "NET", "CRWD", "PANW", "ZS", "FTNT",
        "UBER", "ABNB", "DIS", "BA", "JPM", "GS", "V", "MA",
        "XOM", "CVX", "PFE", "JNJ", "UNH", "LLY", "COST", "WMT",
        "DELL", "SMCI", "ARM", "MRVL", "ON", "ANET", "APP", "RKLB",
    ]
    tickers_data = []
    try:
        tickers = yf.Tickers(" ".join(popular))
        for sym in popular:
            try:
                info = tickers.tickers[sym].fast_info
                price = getattr(info, "last_price", 0) or 0
                prev = getattr(info, "previous_close", 0) or 0
                vol = getattr(info, "last_volume", 0) or 0
                avg_vol = getattr(info, "three_month_average_volume", 1) or 1
                if prev > 0:
                    change = price - prev
                    changePct = (change / prev) * 100
                    tickers_data.append({
                        "symbol": sym, "name": sym,
                        "price": round(price, 2), "change": round(change, 2),
                        "changePct": round(changePct, 2),
                        "volume": vol, "avgVolume": avg_vol,
                    })
            except Exception:
                continue
    except Exception as e:
        print(f"Tickers fallback failed: {e}")

    gainers = sorted(tickers_data, key=lambda x: x["changePct"], reverse=True)[:10]
    losers = sorted(tickers_data, key=lambda x: x["changePct"])[:10]
    actives = sorted(tickers_data, key=lambda x: x["volume"], reverse=True)[:10]
    return gainers, losers, actives


# ── Signal Detection ────────────────────────────────────────────
def detect_signals(gainers, losers, actives=None):
    """
    Strong buy: volume ratio >= 1.5x AND change > +3%
    Strong sell: volume ratio >= 1.5x AND change < -3%
    Scans gainers + losers + actives (deduplicated).
    """
    strong_buy = []
    strong_sell = []
    seen_buy = set()
    seen_sell = set()

    all_stocks = list(gainers) + list(actives or [])
    for stock in all_stocks:
        sym = stock.get("symbol", "")
        if sym in seen_buy:
            continue
        vol_ratio = stock.get("volRatio", 0)
        if not vol_ratio:
            avg_vol = stock.get("avgVolume", 1) or 1
            vol_ratio = stock["volume"] / avg_vol if avg_vol > 0 else 0
        if vol_ratio >= 1.5 and stock["changePct"] > 3:
            strong_buy.append({**stock, "volRatio": round(vol_ratio, 1)})
            seen_buy.add(sym)

    all_sell = list(losers) + list(actives or [])
    for stock in all_sell:
        sym = stock.get("symbol", "")
        if sym in seen_sell:
            continue
        vol_ratio = stock.get("volRatio", 0)
        if not vol_ratio:
            avg_vol = stock.get("avgVolume", 1) or 1
            vol_ratio = stock["volume"] / avg_vol if avg_vol > 0 else 0
        if vol_ratio >= 1.5 and stock["changePct"] < -3:
            strong_sell.append({**stock, "volRatio": round(vol_ratio, 1)})
            seen_sell.add(sym)

    return strong_buy[:5], strong_sell[:5]


# ── Claude AI Analysis ─────────────────────────────────────────
def get_top_signals(strong_buy, strong_sell):
    """Pick the single strongest buy and sell signal."""
    top_buy = None
    top_sell = None

    if strong_buy:
        # Highest combo of volRatio * changePct
        top_buy = max(strong_buy, key=lambda s: s["volRatio"] * abs(s["changePct"]))
    if strong_sell:
        top_sell = max(strong_sell, key=lambda s: s["volRatio"] * abs(s["changePct"]))

    return top_buy, top_sell


def claude_analyze(top_buy, top_sell):
    """Call Claude API to analyze the top buy/sell signals."""
    tw_tz = timezone(timedelta(hours=8))
    today = datetime.now(tw_tz).strftime("%Y/%m/%d")

    # Build prompt
    stocks_info = []
    if top_buy:
        stocks_info.append(
            f"📈 最強買進：{top_buy['symbol']}（{top_buy['name']}）"
            f" 漲幅 {top_buy['changePct']:+.1f}%，量比 {top_buy['volRatio']}x，"
            f"價格 ${top_buy['price']:.2f}"
        )
    if top_sell:
        stocks_info.append(
            f"📉 最強賣出：{top_sell['symbol']}（{top_sell['name']}）"
            f" 跌幅 {top_sell['changePct']:+.1f}%，量比 {top_sell['volRatio']}x，"
            f"價格 ${top_sell['price']:.2f}"
        )

    if not stocks_info:
        return None

    prompt = f"""今天是 {today}，以下是今日美股市場最強訊號：

{chr(10).join(stocks_info)}

請用繁體中文，以 JSON 格式回應。不要輸出任何 markdown，只輸出純 JSON。
格式如下（每支股票都要分析）：

{{
  "buy": {{
    "trigger": "一句話描述今天為什麼大漲",
    "reasons": ["原因一，具體且有數據支撐", "原因二", "原因三"],
    "beneficiaries": ["SYMBOL1：一句話說明為何連動受惠", "SYMBOL2：說明"],
    "victims": ["SYMBOL1：一句話說明為何連動受害", "SYMBOL2：說明"],
    "conclusion": "一句話總結，包含風險提示"
  }},
  "sell": {{
    "trigger": "一句話描述今天為什麼大跌",
    "reasons": ["原因一", "原因二", "原因三"],
    "beneficiaries": ["SYMBOL1：說明為何受惠", "SYMBOL2：說明"],
    "victims": ["SYMBOL1：說明為何受害", "SYMBOL2：說明"],
    "conclusion": "一句話總結"
  }}
}}

注意：
- 用繁體中文
- 分析要具體，提到相關財報、新聞事件、產業趨勢
- 受惠/受害個股要列出具體的美股代號，2-3支，說明產業鏈或競爭關聯
- 只輸出 JSON，不要任何其他文字、不要 ```json 標記
- 如果只有買進或只有賣出，對應的欄位設為 null"""

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": 2048,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        return data["content"][0]["text"]
    except Exception as e:
        print(f"❌ Claude API error: {e}")
        return None


def parse_claude_json(analysis_text):
    """Parse Claude's JSON response, stripping any markdown fences."""
    text = analysis_text.strip()
    # Remove ```json ... ``` wrapper if present
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    return json.loads(text)


def build_analysis_card(data, symbol, pct, vol_ratio, is_buy=True):
    """Build one analysis card (buy or sell) from structured data."""
    if not data:
        return ""

    sign = "+" if pct >= 0 else ""
    emoji = "📈" if is_buy else "📉"
    border_color = "#10b981" if is_buy else "#ef4444"
    title_color = "#059669" if is_buy else "#dc2626"
    bg = "white" if is_buy else "#fef2f2"

    # Trigger
    trigger = data.get("trigger", "")
    # Reasons
    reasons_html = ""
    for i, r in enumerate(data.get("reasons") or [], 1):
        reasons_html += f'<div style="padding-left:12px;font-size:13px;color:#374151;margin:3px 0;line-height:1.6">{i}. {esc(r)}</div>'
    # Beneficiaries
    benef_html = ""
    for b in (data.get("beneficiaries") or []):
        benef_html += f'<div style="padding-left:12px;font-size:13px;color:#059669;margin:2px 0;line-height:1.6">▲ {esc(b)}</div>'
    # Victims
    victim_html = ""
    for v in (data.get("victims") or []):
        victim_html += f'<div style="padding-left:12px;font-size:13px;color:#dc2626;margin:2px 0;line-height:1.6">▼ {esc(v)}</div>'
    # Conclusion
    conclusion = data.get("conclusion", "")

    return f'''<div style="background:{bg};border-left:4px solid {border_color};border-radius:0 12px 12px 0;padding:20px;margin-bottom:12px">
  <div style="font-size:15px;font-weight:700;color:{title_color};margin-bottom:14px">{emoji} {symbol} {sign}{pct:.1f}%（量比{vol_ratio}x）</div>
  <div style="margin-bottom:10px"><span style="font-weight:600;font-size:13px;color:#1f2937">觸發事件：</span><span style="font-size:13px;color:#374151">{esc(trigger)}</span></div>
  <div style="margin-bottom:6px;font-weight:600;font-size:13px;color:#1f2937">主要原因：</div>{reasons_html}
  <div style="margin-top:10px;margin-bottom:6px;font-weight:600;font-size:13px;color:#059669">受惠個股：</div>{benef_html}
  <div style="margin-top:10px;margin-bottom:6px;font-weight:600;font-size:13px;color:#dc2626">受害個股：</div>{victim_html}
  <div style="margin-top:12px;padding-top:10px;border-top:1px solid #e5e7eb"><span style="font-weight:600;font-size:13px;color:#1f2937">結論：</span><span style="font-size:13px;color:#374151">{esc(conclusion)}</span></div>
</div>'''


def esc(text):
    """Escape HTML and strip any leftover markdown syntax."""
    text = str(text)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Strip leftover markdown: ##, **, *, ---, ``
    text = re.sub(r'#{1,6}\s*', '', text)
    text = re.sub(r'\*{1,2}', '', text)
    text = re.sub(r'`{1,3}', '', text)
    text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)
    return text.strip()


def generate_daily_column_html(analysis_text, top_buy, top_sell):
    """Convert Claude's JSON analysis into the dailyColumn HTML block."""
    tw_tz = timezone(timedelta(hours=8))
    now_tw = datetime.now(tw_tz)
    timestamp = now_tw.strftime("%Y/%m/%d %H:%M")

    try:
        data = parse_claude_json(analysis_text)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"⚠️  Failed to parse Claude JSON: {e}")
        print(f"    Raw response: {analysis_text[:200]}...")
        return None

    buy_data = data.get("buy")
    sell_data = data.get("sell")

    buy_card = ""
    sell_card = ""

    if buy_data and top_buy:
        buy_card = build_analysis_card(buy_data, top_buy["symbol"], top_buy["changePct"], top_buy["volRatio"], is_buy=True)
    if sell_data and top_sell:
        sell_card = build_analysis_card(sell_data, top_sell["symbol"], top_sell["changePct"], top_sell["volRatio"], is_buy=False)

    cards = buy_card + sell_card
    if not cards:
        return None

    # Return ONLY the innerHTML of #dailyColumn (not the wrapper div itself)
    column_html = f"""<div style="background:white;border-radius:16px;padding:24px;box-shadow:0 1px 3px rgba(0,0,0,0.1);border:1px solid #e5e7eb;margin-bottom:24px">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px">
              <div style="font-size:18px;font-weight:800;color:#1f2937">⚡ 今日事件快速分析</div>
              <span style="color:#9ca3af;font-size:12px">{timestamp}</span>
            </div>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px">
              {cards}
            </div>
            <p style="color:#9ca3af;font-size:11px;margin-top:16px;margin-bottom:0">⚠️ 本分析僅供參考，不構成投資建議｜AI輔助生成｜stockiq.tw</p>
          </div>"""

    return column_html


# ── Briefing HTML Generation ───────────────────────────────────
def make_stock_item(stock, color_class="white"):
    """Generate a clickable stock item div."""
    sym = stock["symbol"]
    pct = stock["changePct"]
    sign = "+" if pct >= 0 else ""
    vol_ratio = stock.get("volRatio", 0)
    vol_text = f" ｜ 量比{vol_ratio}x" if vol_ratio else ""

    return (
        f'<div onclick="document.getElementById(\'tickerInput\').value=\'{sym}\';'
        f"document.getElementById('tickerInput').scrollIntoView({{behavior:'smooth'}})\" "
        f'style="cursor:pointer;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.06);font-size:13px">'
        f'<span style="font-weight:700;color:#c7d2fe">{sym}</span> '
        f'<span style="color:#94a3b8;font-size:12px">${stock["price"]:.2f} '
        f'({sign}{pct:.1f}%){vol_text}</span></div>'
    )


def get_session_label():
    """Return 🌅 早報 or 🌙 晚報 based on current UTC hour."""
    utc_hour = datetime.now(timezone.utc).hour
    # UTC 01:00 run → 早報, UTC 13:00 run → 晚報
    # Allow ±2h window for each
    if utc_hour <= 6:
        return "🌅 早報"
    else:
        return "🌙 晚報"


def generate_briefing_html(gainers, losers, actives, strong_buy, strong_sell):
    """Generate the full Daily Briefing HTML block."""
    tw_tz = timezone(timedelta(hours=8))
    now_tw = datetime.now(tw_tz)
    weekday_map = {0: "一", 1: "二", 2: "三", 3: "四", 4: "五", 5: "六", 6: "日"}
    day_name = weekday_map[now_tw.weekday()]
    is_weekend = now_tw.weekday() >= 5
    session_label = get_session_label()
    timestamp = now_tw.strftime(f"%Y/%m/%d %H:%M") + f" （週{day_name}）"
    if is_weekend:
        timestamp += "（收盤資料）"

    buy_items = "\n".join(make_stock_item(s) for s in strong_buy) if strong_buy else '<div style="color:#94a3b8;font-size:12px;padding:8px 0">今日無強力訊號</div>'
    sell_items = "\n".join(make_stock_item(s) for s in strong_sell) if strong_sell else '<div style="color:#94a3b8;font-size:12px;padding:8px 0">今日無強力訊號</div>'
    gainer_items = "\n".join(make_stock_item(s) for s in gainers[:5])
    loser_items = "\n".join(make_stock_item(s) for s in losers[:5])
    active_items = "\n".join(make_stock_item(s) for s in actives[:5]) if actives else '<div style="color:#94a3b8;font-size:12px;padding:8px 0">無數據</div>'

    # Return ONLY the innerHTML of #topBriefing (not the wrapper div itself)
    html = f"""<div style="background:linear-gradient(135deg,#1e1b4b 0%,#1e3a5f 100%);border-radius:16px;padding:24px;color:white;margin-bottom:24px">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;flex-wrap:wrap;gap:8px">
    <h2 style="font-size:20px;font-weight:800;margin:0">📰 {session_label} 市場速報</h2>
    <span style="color:#818cf8;font-size:12px;background:rgba(255,255,255,0.1);padding:4px 10px;border-radius:20px">{timestamp}</span>
  </div>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px">
    <div style="background:rgba(74,222,128,0.1);border:1px solid rgba(74,222,128,0.2);border-radius:10px;padding:14px">
      <div style="color:#86efac;font-weight:700;margin-bottom:10px;font-size:13px">🚀 強力買進</div>
      {buy_items}
    </div>
    <div style="background:rgba(248,113,113,0.1);border:1px solid rgba(248,113,113,0.2);border-radius:10px;padding:14px">
      <div style="color:#fca5a5;font-weight:700;margin-bottom:10px;font-size:13px">🔴 強力賣出</div>
      {sell_items}
    </div>
    <div style="background:rgba(255,255,255,0.08);border-radius:10px;padding:14px">
      <div style="color:#fde68a;font-weight:700;margin-bottom:10px;font-size:13px">📈 漲幅前5</div>
      {gainer_items}
    </div>
    <div style="background:rgba(255,255,255,0.08);border-radius:10px;padding:14px">
      <div style="color:#fca5a5;font-weight:700;margin-bottom:10px;font-size:13px">📉 跌幅前5</div>
      {loser_items}
    </div>
    <div style="background:rgba(251,146,60,0.1);border:1px solid rgba(251,146,60,0.2);border-radius:10px;padding:14px">
      <div style="color:#fdba74;font-weight:700;margin-bottom:10px;font-size:13px">🔥 熱搜話題股</div>
      {active_items}
    </div>
  </div>
  <p style="color:#4f46e5;font-size:11px;margin-top:14px;margin-bottom:0">📊 Yahoo Finance 數據 ｜ 量比=今日量÷近3月均量 ｜ 點代號直接分析 ｜ stockiq.tw 每日更新</p>
</div>"""

    return html


# ── GitHub Push ─────────────────────────────────────────────────
def find_div_end(html: str, start_pos: int) -> int:
    """Find the matching </div> for the first <div found at or after start_pos."""
    i = html.find("<div", start_pos)
    if i == -1:
        return -1
    depth = 0
    while i < len(html):
        if html[i:i+4] == "<div":
            depth += 1
            i = html.find(">", i) + 1
        elif html[i:i+6] == "</div>":
            depth -= 1
            if depth == 0:
                return i + 6
            i += 6
        else:
            i += 1
    return -1


def push_to_github(content: str, sha: str, path: str = FILE_PATH, message: str = None):
    """Push a file to GitHub."""
    tw_tz = timezone(timedelta(hours=8))
    now_tw = datetime.now(tw_tz)
    if not message:
        message = f"📰 Daily briefing + AI analysis {now_tw.strftime('%Y/%m/%d %H:%M')} (auto)"

    url = f"{API_BASE}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "sha": sha,
        "branch": BRANCH,
    }
    r = requests.put(url, headers=HEADERS, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


_pending_files = {}  # path -> content for batch commit

def create_or_update_file(path: str, content: str, message: str):
    """Queue file for batch commit instead of pushing individually."""
    global _pending_files
    _pending_files[path] = content
    return {"queued": path}

def batch_commit_all(message: str):
    """Push all queued files as a single commit using Git Trees API."""
    global _pending_files
    if not _pending_files:
        return None
    try:
        # 1. Get current ref
        r = requests.get(f"{API_BASE}/git/ref/heads/{BRANCH}", headers=HEADERS, timeout=10)
        r.raise_for_status()
        base_sha = r.json()["object"]["sha"]
        # 2. Get base tree
        r2 = requests.get(f"{API_BASE}/git/commits/{base_sha}", headers=HEADERS, timeout=10)
        r2.raise_for_status()
        base_tree = r2.json()["tree"]["sha"]
        # 3. Create blobs
        entries = []
        for path, content in _pending_files.items():
            blob_r = requests.post(f"{API_BASE}/git/blobs", headers=HEADERS, json={
                "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                "encoding": "base64"
            }, timeout=15)
            blob_r.raise_for_status()
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob_r.json()["sha"]})
        # 4. Create tree
        tree_r = requests.post(f"{API_BASE}/git/trees", headers=HEADERS, json={
            "base_tree": base_tree, "tree": entries
        }, timeout=15)
        tree_r.raise_for_status()
        # 5. Create commit
        commit_r = requests.post(f"{API_BASE}/git/commits", headers=HEADERS, json={
            "message": message, "tree": tree_r.json()["sha"], "parents": [base_sha]
        }, timeout=15)
        commit_r.raise_for_status()
        # 6. Update ref
        ref_r = requests.patch(f"{API_BASE}/git/refs/heads/{BRANCH}", headers=HEADERS, json={
            "sha": commit_r.json()["sha"]
        }, timeout=10)
        ref_r.raise_for_status()
        sha = commit_r.json()["sha"][:7]
        count = len(_pending_files)
        _pending_files = {}
        return sha, count
    except Exception as e:
        print(f"  ⚠️  Batch commit failed: {e}, pushing individually...")
        for path, content in _pending_files.items():
            try:
                url = f"{API_BASE}/contents/{path}"
                sha = None
                try:
                    gr = requests.get(url, headers=HEADERS, params={"ref": BRANCH}, timeout=10)
                    if gr.status_code == 200:
                        sha = gr.json().get("sha")
                except Exception:
                    pass
                payload = {"message": f"Update {path}", "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"), "branch": BRANCH}
                if sha:
                    payload["sha"] = sha
                requests.put(url, headers=HEADERS, json=payload, timeout=30).raise_for_status()
            except Exception as e2:
                print(f"  ⚠️  {path}: {e2}")
        _pending_files = {}
        return None


# ── Yahoo Finance News ──────────────────────────────────────────
def fetch_yahoo_news(count: int = 5):
    """Fetch top financial news from Yahoo Finance RSS feed."""
    news = []
    try:
        # Use RSS feed for S&P 500, Dow Jones, Nasdaq
        url = "https://feeds.finance.yahoo.com/rss/2.0/headline"
        params = {"s": "^GSPC,^DJI,^IXIC", "region": "US", "lang": "en-US"}
        r = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        r.raise_for_status()

        # Parse RSS XML
        titles = re.findall(r'<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>', r.text)
        descriptions = re.findall(r'<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>', r.text)
        links = re.findall(r'<link>(https?://[^<]+)</link>', r.text)
        pub_dates = re.findall(r'<pubDate>(.*?)</pubDate>', r.text)

        # Skip the first title/description (channel-level)
        seen_titles = set()
        for i in range(len(titles)):
            title = titles[i].strip()
            if not title or title.startswith("Yahoo") or title in seen_titles:
                continue
            seen_titles.add(title)
            desc = descriptions[i].strip() if i < len(descriptions) else ""
            # Unescape HTML entities
            desc = desc.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
            title = title.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            link = links[i] if i < len(links) else ""
            pub = pub_dates[i - 1] if i > 0 and (i - 1) < len(pub_dates) else ""
            news.append({
                "title": title,
                "description": desc[:300],
                "link": link,
                "pubDate": pub,
            })
            if len(news) >= count:
                break
    except Exception as e:
        print(f"⚠️  Failed to fetch Yahoo Finance news: {e}")

    # Fallback: try search API
    if not news:
        try:
            url = "https://query1.finance.yahoo.com/v1/finance/search"
            params = {"q": "stock market today", "newsCount": count, "lang": "en-US"}
            r = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            for n in r.json().get("news", [])[:count]:
                news.append({
                    "title": n.get("title", ""),
                    "description": "",
                    "link": n.get("link", ""),
                    "pubDate": "",
                })
        except Exception:
            pass

    return news


def claude_summarize_news(news_items):
    """Use Claude to summarize news into a Chinese digest (~200 words)."""
    news_text = "\n".join(
        f"{i+1}. {n['title']}\n   {n['description'][:200]}"
        for i, n in enumerate(news_items)
    )

    prompt = f"""以下是今日美股相關的5則英文財金新聞，請用繁體中文整理成一篇約200字的新聞摘要。

{news_text}

要求：
- 用繁體中文
- 約200字，簡潔精煉
- 按重要性排序，最重要的放前面
- 提到具體股票代號時用括號標注（如 NVDA）
- 不要用 markdown 格式，純文字段落
- 直接輸出摘要，不要開頭語"""

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": 512,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"]
    except Exception as e:
        print(f"❌ Claude news summary error: {e}")
        return None


# ── News Page HTML ──────────────────────────────────────────────
PAGE_STYLE = """<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, sans-serif; background: #f8fafc; color: #1e293b; line-height: 1.8; }
.nav { background: #1e1b4b; padding: 12px 24px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; }
.nav a { color: #a5b4fc; text-decoration: none; font-size: 14px; padding: 4px 10px; border-radius: 6px; }
.nav .logo { color: white; font-weight: 800; font-size: 18px; text-decoration: none; }
.nav .logo span { color: #818cf8; }
.container { max-width: 900px; margin: 0 auto; padding: 32px 20px; }
h1 { font-size: 28px; font-weight: 800; color: #1e1b4b; margin-bottom: 8px; }
h2 { font-size: 20px; font-weight: 700; color: #1e1b4b; margin: 32px 0 10px; border-bottom: 2px solid #e2e8f0; padding-bottom: 6px; }
p { margin-bottom: 14px; color: #475569; }
.tag { display: inline-block; background: #ede9fe; color: #6d28d9; font-size: 12px; padding: 2px 8px; border-radius: 10px; margin-bottom: 12px; }
.card { background: white; border-radius: 10px; padding: 18px 22px; margin: 14px 0; border-left: 4px solid #4f46e5; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.breadcrumb { color: #94a3b8; font-size: 13px; margin-bottom: 20px; }
.breadcrumb a { color: #6366f1; text-decoration: none; }
.btn { display: inline-block; background: #4f46e5; color: white; padding: 10px 20px; border-radius: 8px; text-decoration: none; font-weight: 600; margin: 4px; }
.footer { background: #1e1b4b; color: #94a3b8; text-align: center; padding: 24px; margin-top: 48px; font-size: 13px; }
.news-item { background: white; border-radius: 10px; padding: 16px 20px; margin: 12px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.06); border: 1px solid #e2e8f0; }
.news-item h3 { font-size: 15px; font-weight: 600; color: #1e1b4b; margin-bottom: 6px; }
.news-item h3 a { color: #4f46e5; text-decoration: none; }
.news-item p { font-size: 13px; color: #64748b; margin-bottom: 4px; }
.summary-box { background: linear-gradient(135deg, #eff6ff, #f0fdf4); border: 1px solid #bfdbfe; border-radius: 12px; padding: 20px 24px; margin: 20px 0; }
.summary-box p { color: #1e293b; font-size: 14px; line-height: 1.8; }
</style>"""

PAGE_NAV = """<nav class="nav">
  <a href="/" class="logo">Stock<span>IQ</span>.TW</a>
  <div style="display:flex;gap:4px;flex-wrap:wrap">
    <a href="/">🔍 分析工具</a><a href="/learn/">📚 投資教學</a>
    <a href="/daily/">📰 市場日報</a><a href="/news/">🌐 財金新聞</a>
  </div>
</nav>"""

PAGE_FOOTER = """<div class="footer">
  <p>© 2026 StockIQ.TW — AI 美股多框架分析平台</p>
  <p style="margin-top:8px">⚠️ 本網站資訊僅供參考，不構成投資建議。</p>
  <p style="margin-top:8px"><a href="/" style="color:#818cf8">返回分析工具</a></p>
</div>"""


def generate_news_page(news_items, summary):
    """Generate the /news/index.html page with today's news."""
    tw_tz = timezone(timedelta(hours=8))
    now_tw = datetime.now(tw_tz)
    date_str = now_tw.strftime("%Y/%m/%d %H:%M")

    summary_html = ""
    if summary:
        summary_html = f"""
  <div class="summary-box">
    <p style="font-weight:700;color:#1e1b4b;margin-bottom:8px">🤖 AI 新聞摘要（{date_str} 更新）</p>
    <p>{esc(summary)}</p>
  </div>"""

    news_html = ""
    for n in news_items:
        title = esc(n["title"])
        desc = esc(n.get("description", ""))
        link = n.get("link", "#")
        pub = n.get("pubDate", "")
        news_html += f"""
  <div class="news-item">
    <h3><a href="{link}" target="_blank" rel="noopener">{title}</a></h3>
    <p>{desc}</p>
    <p style="font-size:11px;color:#94a3b8">{pub}</p>
  </div>"""

    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="icon" type="image/png" href="/logo.png">
<meta name="description" content="美股財金新聞精選與AI摘要 - {now_tw.strftime('%Y/%m/%d')}更新">
<title>財金新聞 | StockIQ.TW</title>
{PAGE_STYLE}
</head><body>
{PAGE_NAV}
<div class="container">
  <div class="breadcrumb"><a href="/">首頁</a> › 財金新聞</div>
  <span class="tag">🌐 財金新聞</span>
  <h1>美股財金新聞</h1>
  <p>每日自動更新，整合 Yahoo Finance 最新美股相關新聞，並由 AI 整理中文摘要。最後更新：{date_str}</p>
  {summary_html}
  <h2>📰 今日新聞（{now_tw.strftime('%Y/%m/%d')}）</h2>
  {news_html}
  <div style="margin-top:24px">
    <a href="/" class="btn">🔍 前往 AI 分析工具 →</a>
    <a href="/daily/" class="btn">📰 市場日報 →</a>
  </div>
</div>
{PAGE_FOOTER}
</body></html>"""


# ── Daily Archive Page ──────────────────────────────────────────
def generate_daily_archive(briefing_html, column_html, gainers, losers, actives, strong_buy, strong_sell, news_items, news_summary):
    """Generate /daily/YYYY-MM-DD.html archive page."""
    tw_tz = timezone(timedelta(hours=8))
    now_tw = datetime.now(tw_tz)
    date_str = now_tw.strftime("%Y-%m-%d")
    date_display = now_tw.strftime("%Y年%m月%d日")
    weekday_map = {0: "一", 1: "二", 2: "三", 3: "四", 4: "五", 5: "六", 6: "日"}
    day_name = weekday_map[now_tw.weekday()]

    # Build market data section
    def stock_row(s, emoji=""):
        pct = s["changePct"]
        sign = "+" if pct >= 0 else ""
        vol_ratio = s.get("volRatio", 0)
        vr_text = f" (量比{vol_ratio}x)" if vol_ratio else ""
        color = "#059669" if pct >= 0 else "#dc2626"
        return f'<div style="padding:6px 0;border-bottom:1px solid #f1f5f9;font-size:13px">{emoji}<strong>{s["symbol"]}</strong> ${s["price"]:.2f} <span style="color:{color}">{sign}{pct:.1f}%</span>{vr_text}</div>'

    buy_rows = "".join(stock_row(s, "🚀 ") for s in strong_buy) if strong_buy else "<p style='color:#94a3b8;font-size:13px'>今日無強力買進訊號</p>"
    sell_rows = "".join(stock_row(s, "🔴 ") for s in strong_sell) if strong_sell else "<p style='color:#94a3b8;font-size:13px'>今日無強力賣出訊號</p>"
    gainer_rows = "".join(stock_row(s) for s in gainers[:5])
    loser_rows = "".join(stock_row(s) for s in losers[:5])
    active_rows = "".join(stock_row(s, "🔥 ") for s in actives[:5]) if actives else ""

    # News section
    news_section = ""
    if news_items:
        news_list = ""
        for n in news_items:
            title = esc(n["title"])
            link = n.get("link", "#")
            news_list += f'<li><a href="{link}" target="_blank" rel="noopener" style="color:#4f46e5;text-decoration:none">{title}</a></li>'
        news_section = f"""
  <h2>🌐 今日財金新聞</h2>
  <ul style="padding-left:20px;margin-bottom:14px">{news_list}</ul>"""
        if news_summary:
            news_section += f"""
  <div class="summary-box">
    <p style="font-weight:600;margin-bottom:6px">AI 新聞摘要</p>
    <p>{esc(news_summary)}</p>
  </div>"""

    # Column (AI analysis) - inject if available
    column_section = ""
    if column_html:
        # Extract just the inner content from the column HTML
        column_section = f"""
  <h2>⚡ 事件快速分析</h2>
  <div style="margin:14px 0">{column_html}</div>"""

    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="icon" type="image/png" href="/logo.png">
<meta name="description" content="StockIQ 美股市場速報 {date_display} - 強力買賣訊號、事件分析、財金新聞">
<title>{date_display} 市場速報 | StockIQ.TW</title>
{PAGE_STYLE}
</head><body>
{PAGE_NAV}
<div class="container">
  <div class="breadcrumb"><a href="/">首頁</a> › <a href="/daily/">市場日報</a> › {date_display}</div>
  <span class="tag">📰 市場日報</span>
  <h1>{date_display}（週{day_name}）美股市場速報</h1>

  <h2>🚀 強力買進訊號</h2>
  <div class="card">{buy_rows}</div>

  <h2>🔴 強力賣出訊號</h2>
  <div class="card">{sell_rows}</div>

  <h2>📈 漲幅前5</h2>
  <div class="card">{gainer_rows}</div>

  <h2>📉 跌幅前5</h2>
  <div class="card">{loser_rows}</div>

  <h2>🔥 熱搜話題股</h2>
  <div class="card">{active_rows}</div>

  {column_section}
  {news_section}

  <div style="margin-top:24px">
    <a href="/" class="btn">🔍 前往 AI 分析工具 →</a>
    <a href="/daily/" class="btn">📰 市場日報首頁 →</a>
  </div>
</div>
{PAGE_FOOTER}
</body></html>""", date_str


def update_daily_index(date_str, date_display):
    """Regenerate /daily/index.html with past 30 days calendar grid."""
    tw_tz = timezone(timedelta(hours=8))
    now_tw = datetime.now(tw_tz)

    try:
        # 1. Scan which daily files exist in the repo
        url = f"{API_BASE}/contents/daily"
        r = requests.get(url, headers=HEADERS, params={"ref": BRANCH}, timeout=15)
        existing_dates = set()
        if r.status_code == 200:
            for item in r.json():
                name = item.get("name", "")
                m = re.match(r'^(\d{4}-\d{2}-\d{2})\.html$', name)
                if m:
                    existing_dates.add(m.group(1))

        # Today should be in the set (we just created it)
        existing_dates.add(date_str)

        # 2. Build past 30 days list
        days_html = ""
        weekday_map = {0: "一", 1: "二", 2: "三", 3: "四", 4: "五", 5: "六", 6: "日"}
        for i in range(30):
            d = now_tw - timedelta(days=i)
            ds = d.strftime("%Y-%m-%d")
            dd = d.strftime("%m/%d")
            dn = weekday_map[d.weekday()]
            is_weekend = d.weekday() >= 5

            if ds in existing_dates:
                days_html += f'''
    <a href="/daily/{ds}.html" style="display:flex;justify-content:space-between;align-items:center;padding:12px 16px;background:white;border-radius:8px;margin:6px 0;text-decoration:none;color:#1e293b;border:1px solid #e2e8f0;box-shadow:0 1px 2px rgba(0,0,0,0.04);transition:all 0.2s">
      <span style="font-weight:600">{dd}（{dn}）</span>
      <span style="font-size:12px;color:#059669;font-weight:600">✅ 查看日報 →</span>
    </a>'''
            else:
                label = "週末" if is_weekend else "無資料"
                days_html += f'''
    <div style="display:flex;justify-content:space-between;align-items:center;padding:12px 16px;background:#f8fafc;border-radius:8px;margin:6px 0;color:#cbd5e1;border:1px solid #f1f5f9">
      <span>{dd}（{dn}）</span>
      <span style="font-size:12px">{label}</span>
    </div>'''

        # 3. Build full page
        page = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="icon" type="image/png" href="/logo.png">
<meta name="description" content="StockIQ 每日美股市場速報，強力買進訊號、板塊資金動向、今日大漲大跌個股分析">
<title>每日美股市場速報 | StockIQ.TW</title>
{PAGE_STYLE}
</head><body>
{PAGE_NAV}
<div class="container">
  <div class="breadcrumb"><a href="/">首頁</a> › 市場日報</div>
  <span class="tag">📰 每日速報</span>
  <h1>每日美股市場速報</h1>
  <p>每個交易日台灣時間早上 9:00 自動更新。包含強力買進/賣出訊號、AI 事件分析、財金新聞摘要。</p>

  <div class="card">
    <h3>📅 今日速報 {date_display}</h3>
    <p>查看今日完整市場速報：</p>
    <a href="/" class="btn">🔍 主頁速報 →</a>
    <a href="/daily/{date_str}.html" class="btn" style="background:#059669">📄 完整日報 →</a>
  </div>

  <h2>📂 過去 30 天日報</h2>
  <div style="margin:14px 0">
    {days_html}
  </div>

  <h2>速報指標說明</h2>
  <div class="card">
    <p><strong>量比（Volume Ratio）</strong>= 今日成交量 ÷ 近三個月日均成交量。量比 &gt; 1.5 代表交易活躍度明顯高於平常。</p>
    <p><strong>強力買進</strong>：量比 ≥ 1.5 且漲幅 &gt; 3%（機構資金主動買進訊號）</p>
    <p><strong>強力賣出</strong>：量比 ≥ 1.5 且跌幅 &gt; 3%（機構資金主動出貨訊號）</p>
  </div>

  <a href="/" class="btn">🔍 前往分析工具 →</a>
  <a href="/news/" class="btn">🌐 財金新聞 →</a>
</div>
{PAGE_FOOTER}
</body></html>"""

        create_or_update_file("daily/index.html", page,
            f"📰 Update daily index {date_str} (auto)")
        print(f"  ✅ daily/index.html updated (30-day calendar)")
    except Exception as e:
        print(f"  ⚠️  Failed to update daily/index.html: {e}")
        traceback.print_exc()


# ── Sector Flow JSON ─────────────────────────────────────────────
SECTOR_ETFS = {
    "XLK": {"name": "科技", "en": "Technology"},
    "XLF": {"name": "金融", "en": "Financials"},
    "XLV": {"name": "醫療保健", "en": "Healthcare"},
    "XLE": {"name": "能源", "en": "Energy"},
    "XLI": {"name": "工業", "en": "Industrials"},
    "XLY": {"name": "非必需消費", "en": "Consumer Discretionary"},
    "XLP": {"name": "必需消費", "en": "Consumer Staples"},
    "XLB": {"name": "原物料", "en": "Materials"},
    "XLRE": {"name": "房地產", "en": "Real Estate"},
    "XLU": {"name": "公用事業", "en": "Utilities"},
    "XLC": {"name": "通訊服務", "en": "Communication Services"},
}


def fetch_sector_flow():
    """Read sector data from data/macro.json (written by update_data.py).
    
    Uses the same data source as the website and email for consistency.
    """
    sectors = []
    try:
        url = f"{API_BASE}/contents/data/macro.json?ref={BRANCH}"
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        macro = json.loads(content)

        for s in macro.get("broad_sectors", []):
            etf = s.get("etf", "")
            if etf not in SECTOR_ETFS:
                continue
            meta = SECTOR_ETFS[etf]
            sectors.append({
                "symbol": etf,
                "sector_zh": meta["name"],
                "sector_en": meta["en"],
                "price": s.get("current", 0),
                "change_pct": s.get("change_1d", 0),
                "volume": 0,
                "avg_volume": 0,
                "vol_ratio": 0,
            })
        print(f"  ✅ Read sector data from data/macro.json")
    except Exception as e:
        print(f"  ⚠️  Failed to read macro.json: {e}, falling back to yfinance")
        # Fallback to direct yfinance
        try:
            symbols = list(SECTOR_ETFS.keys())
            tickers = yf.Tickers(" ".join(symbols))
            for sym in symbols:
                try:
                    info = tickers.tickers[sym].fast_info
                    price = getattr(info, "last_price", 0) or 0
                    prev = getattr(info, "previous_close", 0) or 0
                    vol = getattr(info, "last_volume", 0) or 0
                    avg_vol = getattr(info, "three_month_average_volume", 1) or 1
                    if prev > 0:
                        change_pct = round((price - prev) / prev * 100, 2)
                        vol_ratio = round(vol / avg_vol, 2) if avg_vol > 0 else 0
                        meta = SECTOR_ETFS[sym]
                        sectors.append({
                            "symbol": sym, "sector_zh": meta["name"], "sector_en": meta["en"],
                            "price": round(price, 2), "change_pct": change_pct,
                            "volume": vol, "avg_volume": round(avg_vol), "vol_ratio": vol_ratio,
                        })
                except Exception:
                    continue
        except Exception as e2:
            print(f"  ⚠️  Fallback also failed: {e2}")

    sectors.sort(key=lambda x: x["change_pct"], reverse=True)
    return sectors


def save_sector_flow_json(date_str):
    """Save sector flow data to data/sector-flow-YYYY-MM-DD.json."""
    print("📊 Fetching sector ETF data...")
    sectors = fetch_sector_flow()
    print(f"  Sectors: {len(sectors)}")

    if not sectors:
        print("  ⚠️  No sector data, skipping")
        return

    # Show top/bottom
    for s in sectors[:3]:
        print(f"    📈 {s['symbol']} ({s['sector_zh']}): {s['change_pct']:+.2f}%")
    for s in sectors[-2:]:
        print(f"    📉 {s['symbol']} ({s['sector_zh']}): {s['change_pct']:+.2f}%")

    tw_tz = timezone(timedelta(hours=8))
    now_tw = datetime.now(tw_tz)

    # Classify: inflow (>0.3%), outflow (<-0.3%), neutral
    inflow = [s for s in sectors if s["change_pct"] > 0.3]
    outflow = [s for s in sectors if s["change_pct"] < -0.3]
    neutral = [s for s in sectors if -0.3 <= s["change_pct"] <= 0.3]

    payload = {
        "date": date_str,
        "generated_at": now_tw.isoformat(),
        "sector_count": len(sectors),
        "summary": {
            "inflow_count": len(inflow),
            "outflow_count": len(outflow),
            "neutral_count": len(neutral),
            "top_sector": sectors[0]["sector_zh"] if sectors else None,
            "bottom_sector": sectors[-1]["sector_zh"] if sectors else None,
        },
        "sectors": sectors,
    }

    content = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        create_or_update_file(
            f"data/sector-flow-{date_str}.json",
            content,
            f"📊 Sector flow data {date_str} (auto)")
        print(f"  ✅ data/sector-flow-{date_str}.json saved")
    except Exception as e:
        print(f"  ⚠️  Failed to push sector flow JSON: {e}")


# ── Smart Money JSON ─────────────────────────────────────────────
def save_smart_money_json(gainers, losers, actives, date_str):
    """Save stocks with vol_ratio >= 2x to data/smart-money-YYYY-MM-DD.json."""
    tw_tz = timezone(timedelta(hours=8))
    now_tw = datetime.now(tw_tz)

    # Collect all unique stocks from all lists
    all_stocks = {}
    for stock in gainers + losers + actives:
        sym = stock.get("symbol", "")
        if sym and sym not in all_stocks:
            all_stocks[sym] = stock

    # Filter: vol_ratio >= 2x
    smart_money = []
    for stock in all_stocks.values():
        avg_vol = stock.get("avgVolume", 1) or 1
        vol_ratio = round(stock["volume"] / avg_vol, 2) if avg_vol > 0 else 0
        if vol_ratio >= 2.0:
            smart_money.append({
                "symbol": stock["symbol"],
                "name": stock.get("name", stock["symbol"]),
                "price": round(stock.get("price", 0), 2),
                "change_pct": round(stock.get("changePct", 0), 2),
                "vol_ratio": vol_ratio,
                "volume": stock.get("volume", 0),
                "avg_volume": stock.get("avgVolume", 0),
            })

    # Sort by vol_ratio descending
    smart_money.sort(key=lambda x: x["vol_ratio"], reverse=True)

    payload = {
        "date": date_str,
        "generated_at": now_tw.isoformat(),
        "filter": "vol_ratio >= 2.0",
        "count": len(smart_money),
        "stocks": smart_money,
    }

    content = json.dumps(payload, ensure_ascii=False, indent=2)

    try:
        create_or_update_file(
            f"data/smart-money-{date_str}.json",
            content,
            f"📊 Smart money data {date_str} (auto)")
        print(f"  ✅ data/smart-money-{date_str}.json ({len(smart_money)} stocks)")
    except Exception as e:
        print(f"  ⚠️  Failed to push smart money JSON: {e}")


# ── Main ────────────────────────────────────────────────────────
def main():
    print("🚀 StockIQ Daily Briefing + AI Analysis Updater")
    print("=" * 50)

    # 1. Fetch market data
    print("📊 Fetching Yahoo Finance data...")
    gainers, losers, actives = fetch_all_data()
    print(f"  Gainers: {len(gainers)}, Losers: {len(losers)}, Actives: {len(actives)}")

    if not gainers and not losers:
        print("⚠️  No market data available (market may be closed).")
        print("Done (no update needed)")
        return

    # 2. Detect signals
    print("🔍 Detecting strong signals...")
    strong_buy, strong_sell = detect_signals(gainers, losers, actives)
    print(f"  Strong Buy: {len(strong_buy)}, Strong Sell: {len(strong_sell)}")

    for s in strong_buy:
        print(f"    🚀 {s['symbol']}: {s['changePct']:+.1f}% vol_ratio={s['volRatio']}x")
    for s in strong_sell:
        print(f"    🔴 {s['symbol']}: {s['changePct']:+.1f}% vol_ratio={s['volRatio']}x")

    # 3. Generate briefing HTML
    print("🎨 Generating briefing HTML...")
    briefing_html = generate_briefing_html(gainers, losers, actives, strong_buy, strong_sell)

    # 4. AI Analysis via Claude
    column_html = None
    top_buy, top_sell = get_top_signals(strong_buy, strong_sell)

    if top_buy or top_sell:
        print(f"🤖 Calling Claude AI for analysis...")
        if top_buy:
            print(f"    Top Buy: {top_buy['symbol']} {top_buy['changePct']:+.1f}% (vol {top_buy['volRatio']}x)")
        if top_sell:
            print(f"    Top Sell: {top_sell['symbol']} {top_sell['changePct']:+.1f}% (vol {top_sell['volRatio']}x)")

        analysis = claude_analyze(top_buy, top_sell)
        if analysis:
            print("✅ Claude analysis received")
            column_html = generate_daily_column_html(analysis, top_buy, top_sell)
        else:
            print("⚠️  Claude analysis failed, skipping daily column")
    else:
        print("ℹ️  No strong signals today, skipping AI analysis")

    # 5. Fetch Yahoo Finance news
    print("📰 Fetching Yahoo Finance news...")
    news_items = fetch_yahoo_news(5)
    print(f"  News articles: {len(news_items)}")
    for n in news_items[:3]:
        print(f"    📄 {n['title'][:60]}...")

    # 6. Summarize news with Claude
    news_summary = None
    if news_items:
        print("🤖 Summarizing news with Claude...")
        news_summary = claude_summarize_news(news_items)
        if news_summary:
            print(f"  ✅ Summary: {news_summary[:80]}...")
        else:
            print("  ⚠️  News summary failed")

    # ── SCOPE: daily/, news/, data/ + index.html (only topBriefing & dailyColumn divs) ──
    # DO NOT modify learn/, sitemap.xml or any structural pages.

    tw_tz = timezone(timedelta(hours=8))
    now_tw = datetime.now(tw_tz)
    date_str = now_tw.strftime("%Y-%m-%d")
    date_display = now_tw.strftime("%Y年%m月%d日")

    # NOTE: topBriefing + dailyColumn updates REMOVED (2026-07-20)
    # Reason: content duplicates daily/YYYY-MM-DD.html which loadDailyReport() loads
    # index.html no longer shows topBriefing; daily reports are the single source of truth
    print("ℹ️  Skipping index.html update (content served via daily/ archive)")

    # ── Batch push: collect all files, then push as a single commit ──
    print("📦 Preparing batch commit...")
    batch_files = {}  # path -> content

    # 7. Generate and push /news/index.html
    if news_items:
        print("📤 Pushing /news/index.html...")
        news_page = generate_news_page(news_items, news_summary)
        try:
            create_or_update_file("news/index.html", news_page,
                f"📰 News update {now_tw.strftime('%Y/%m/%d %H:%M')} (auto)")
            print(f"  ✅ news/index.html updated")
        except Exception as e:
            print(f"  ⚠️  Failed to push news page: {e}")

    # 9. Generate and push /daily/YYYY-MM-DD.html
    print("📤 Generating daily archive...")
    daily_html, date_str = generate_daily_archive(
        briefing_html, column_html, gainers, losers, actives,
        strong_buy, strong_sell, news_items, news_summary)
    try:
        create_or_update_file(f"daily/{date_str}.html", daily_html,
            f"📰 Daily archive {date_str} (auto)")
        print(f"  ✅ daily/{date_str}.html created")
    except Exception as e:
        print(f"  ⚠️  Failed to push daily archive: {e}")

    # 10. Update daily/index.html (30-day calendar)
    print("📤 Updating daily/index.html...")
    update_daily_index(date_str, date_display)

    # 11. Generate smart money JSON (vol_ratio >= 2x)
    print("📤 Generating smart money JSON...")
    save_smart_money_json(gainers, losers, actives, date_str)

    # 12. Generate sector flow JSON
    print("📤 Generating sector flow JSON...")
    save_sector_flow_json(date_str)

    # Batch commit all queued files (news, daily archive, daily index, smart money, sector flow)
    print(f"\n📦 Pushing {len(_pending_files)} files in single commit...")
    result = batch_commit_all(f"📰 Daily update {now_tw.strftime('%Y/%m/%d %H:%M')} (auto)")
    if result:
        sha, count = result
        print(f"  ✅ Single commit: {sha} ({count} files)")

    print(f"\n🌐 All done! Site will update at https://stockiq.tw in ~1 min")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ Error: {e}")
        traceback.print_exc()
        raise
