import os
#!/usr/bin/env python3
"""
StockIQ Data Preloader v1.1
Fetches: sector/macro data + market movers + accumulation scan + earnings calendar
Saves to data/ directory on GitHub → frontend loads instantly without waiting for Railway API

Run: python3 scripts/update_data.py
"""
import urllib.request, json, base64, time, sys, os
from datetime import datetime, timezone, timedelta
from collections import defaultdict

GH_TOKEN = os.environ.get("GH_TOKEN", "")
REPO = "smartlife-calendar/AI-Investment-HQ"
RAILWAY_API = "https://ai-investment-hq-production.up.railway.app"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
YF_HEADERS = {"User-Agent": UA, "Accept": "*/*", "Referer": "https://finance.yahoo.com/"}

SUPABASE_URL = "https://kggwnlevbxghmqpieoet.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
SB_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates",
}

# ─── GitHub helpers ───────────────────────────────────────────────────────────

def gh_get(path, branch="gh-pages"):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/contents/{path}?ref={branch}",
        headers={"Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    )
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
        return d.get("sha"), base64.b64decode(d["content"]).decode("utf-8")
    except Exception:
        return None, None

def gh_put(path, content_str, msg, branch="gh-pages"):
    """Queue file for batch commit (or push individually as fallback)."""
    global _pending_files
    _pending_files[path] = content_str
    return f"(queued:{path[:20]})"

_pending_files = {}  # path -> content_str

def gh_batch_commit(msg, branch="gh-pages"):
    """Push all queued files as a single commit using Git Trees API."""
    global _pending_files
    if not _pending_files:
        return None
    api = f"https://api.github.com/repos/{REPO}"
    hdrs = {"Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github.v3+json", "Content-Type": "application/json"}

    def _api(method, url, data=None):
        req = urllib.request.Request(url, data=json.dumps(data).encode() if data else None, headers=hdrs, method=method)
        return json.loads(urllib.request.urlopen(req, timeout=20).read())

    try:
        # 1. Get current ref
        ref = _api("GET", f"{api}/git/ref/heads/{branch}")
        base_sha = ref["object"]["sha"]
        # 2. Get base tree
        commit = _api("GET", f"{api}/git/commits/{base_sha}")
        base_tree = commit["tree"]["sha"]
        # 3. Create blobs + tree entries
        entries = []
        for path, content in _pending_files.items():
            blob = _api("POST", f"{api}/git/blobs", {
                "content": base64.b64encode(content.encode()).decode(), "encoding": "base64"
            })
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        # 4. Create tree
        tree = _api("POST", f"{api}/git/trees", {"base_tree": base_tree, "tree": entries})
        # 5. Create commit
        new_commit = _api("POST", f"{api}/git/commits", {
            "message": msg, "tree": tree["sha"], "parents": [base_sha]
        })
        # 6. Update ref
        _api("PATCH", f"{api}/git/refs/heads/{branch}", {"sha": new_commit["sha"]})
        sha_short = new_commit["sha"][:7]
        count = len(_pending_files)
        _pending_files = {}
        return sha_short, count
    except Exception as e:
        print(f"  ⚠️  Batch commit failed: {e}, falling back to individual pushes")
        # Fallback: push one by one
        for path, content in _pending_files.items():
            try:
                sha_old, _ = gh_get(path, branch)
                payload = {"message": f"Update {path}", "content": base64.b64encode(content.encode()).decode(), "branch": branch}
                if sha_old:
                    payload["sha"] = sha_old
                req = urllib.request.Request(f"{api}/contents/{path}", data=json.dumps(payload).encode(), headers=hdrs, method="PUT")
                urllib.request.urlopen(req, timeout=15)
            except Exception as e2:
                print(f"  ⚠️  Fallback push {path} failed: {e2}")
        _pending_files = {}
        return None, 0

def sync_to_main(path, content_str, msg):
    """Also push to main/data/ for Railway bot reference."""
    main_path = f"data/{path.split('/')[-1]}"
    sha, _ = gh_get(main_path, "main")
    payload = {"message": msg, "content": base64.b64encode(content_str.encode()).decode(), "branch": "main"}
    if sha:
        payload["sha"] = sha
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/contents/{main_path}",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github.v3+json", "Content-Type": "application/json"},
        method="PUT"
    )
    try:
        urllib.request.urlopen(req, timeout=15)
        return True
    except:
        return False

# ─── Yahoo Finance helpers ─────────────────────────────────────────────────────

def yf_screener(scrId, n=10):
    for base in ["query1", "query2"]:
        try:
            time.sleep(1.5)
            url = f"https://{base}.finance.yahoo.com/v1/finance/screener/predefined/saved?formatted=false&lang=en-US&region=US&scrIds={scrId}&count={n}"
            resp = urllib.request.urlopen(urllib.request.Request(url, headers=YF_HEADERS), timeout=12)
            q = json.loads(resp.read()).get("finance", {}).get("result", [{}])[0].get("quotes", [])
            if q:
                return q
        except Exception as e:
            print(f"    {base}/{scrId}: {e}")
        time.sleep(2)
    return []

def yf_chart(ticker, interval="1wk", range_="52wk"):
    for base in ["query1", "query2"]:
        try:
            time.sleep(0.5)
            url = f"https://{base}.finance.yahoo.com/v8/finance/chart/{ticker}?interval={interval}&range={range_}"
            resp = urllib.request.urlopen(urllib.request.Request(url, headers=YF_HEADERS), timeout=10)
            result = json.loads(resp.read()).get("chart", {}).get("result", [None])[0]
            if result:
                return result
        except:
            pass
    return None

def compute_52w(ticker):
    result = yf_chart(ticker)
    if not result:
        return {}
    meta = result.get("meta", {})
    closes = [c for c in result.get("indicators", {}).get("quote", [{}])[0].get("close", []) if c]
    timestamps = result.get("timestamp", [])
    if not closes or len(closes) < 2:
        return {}
    perf_52w = (closes[-1] - closes[0]) / closes[0] * 100
    wow = []
    for i in range(max(1, len(closes)-8), len(closes)):
        if closes[i-1]:
            w = (closes[i] - closes[i-1]) / closes[i-1] * 100
            dt = datetime.fromtimestamp(timestamps[i]).strftime("%m/%d") if i < len(timestamps) else ""
            wow.append([dt, round(closes[i], 2), round(w, 1)])
    recent4 = closes[-5:-1] if len(closes) >= 5 else closes
    prior4 = closes[-9:-5] if len(closes) >= 9 else []
    momentum = "N/A"
    if recent4 and prior4 and prior4[0]:
        rg = (recent4[-1] - recent4[0]) / recent4[0] * 100
        pg = (prior4[-1] - prior4[0]) / prior4[0] * 100
        if abs(rg) > abs(pg) * 1.2:
            momentum = "📈 加速" if rg > 0 else "📉 加速下跌"
        elif abs(rg) < abs(pg) * 0.8:
            momentum = "📉 趨緩" if rg > 0 else "📈 跌勢趨緩"
        else:
            momentum = "➡️ 穩定"
    # Fetch daily data for accurate 1-day change + volume + fund flow
    change_1d = 0
    volume_1d = 0
    avg_volume = 0
    fund_flow = 0  # estimated net fund flow in USD
    try:
        daily = yf_chart(ticker, "1d", "5d")
        if daily:
            d_closes = [c for c in daily.get("indicators", {}).get("quote", [{}])[0].get("close", []) if c]
            d_volumes = [v for v in daily.get("indicators", {}).get("quote", [{}])[0].get("volume", []) if v]
            if len(d_closes) >= 2:
                change_1d = round((d_closes[-1] - d_closes[-2]) / d_closes[-2] * 100, 2)
            if d_volumes:
                volume_1d = d_volumes[-1] if d_volumes else 0
                avg_volume = round(sum(d_volumes) / len(d_volumes)) if d_volumes else 0
                # Net fund flow estimate: (volume - avg) * price * direction
                # Positive = more buying, Negative = more selling
                if d_closes and volume_1d:
                    # Fund flow = total dollar volume × direction (positive=up day, negative=down day)
                    direction = 1 if change_1d > 0 else -1 if change_1d < 0 else 0
                    fund_flow = round(volume_1d * d_closes[-1] * direction)
    except Exception:
        pass
    return {
        "current": round(closes[-1], 2),
        "change_1d": change_1d,
        "volume_1d": volume_1d,
        "avg_volume_5d": avg_volume,
        "fund_flow": fund_flow,
        "perf_52w": round(perf_52w, 1),
        "flow": "🟢流入" if perf_52w > 10 else "🔴流出" if perf_52w < -10 else "⚪中性",
        "momentum": momentum,
        "wow": wow[-8:],
    }

# ─── Sector definitions (same as macro_fetcher.py) ────────────────────────────

BROAD_SECTORS = [
    ("XLK", "科技 Tech"), ("XLF", "金融 Finance"), ("XLE", "能源 Energy"),
    ("XLV", "醫療 Health"), ("XLI", "工業 Industrial"), ("XLB", "原材料 Materials"),
    ("XLU", "公用事業 Utilities"), ("XLRE", "房地產 RE"), ("XLY", "非必需消費 Cyclical"),
    ("XLP", "必需消費 Staples"), ("XLC", "通訊 Comm"),
]

SUB_SECTORS = {
    "科技": [("SOXX", "半導體"), ("SMH", "半導體設備"), ("BOTZ", "機器人/AI"), ("AIQ", "AI廣泛"), ("WCLD", "雲端"), ("IGV", "軟體")],
    "國防/太空": [("ITA", "國防"), ("UFO", "太空")],
    "醫療": [("IBB", "生技"), ("XPH", "製藥")],
    "金融": [("KBE", "銀行"), ("KRE", "區域銀行")],
    "能源": [("ICLN", "清潔能源"), ("UNG", "天然氣")],
    "消費": [("XRT", "零售"), ("ARKK", "創新成長")],
    "商品": [("GLD", "黃金"), ("SLV", "白銀"), ("PDBC", "大宗商品")],
}

MACRO_TICKERS = [
    ("^TNX", "10年債殖利率"), ("DX-Y.NYB", "美元指數 DXY"),
    ("GC=F", "黃金 Gold"), ("CL=F", "原油WTI"),
    ("^VIX", "VIX 恐慌指數"), ("^GSPC", "S&P 500"), ("^IXIC", "NASDAQ"),
]

INDICES = [
    ("^GSPC", "S&P 500"), ("^IXIC", "NASDAQ"), ("^DJI", "DOW"),
    ("^VIX", "VIX"), ("^TNX", "10Y Bond"), ("DX-Y.NYB", "DXY"),
]

# ─── Accumulation scan ────────────────────────────────────────────────────────

SCAN_TICKERS = [
    # S&P 500 Top 50 (by market cap)
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AVGO","JPM","LLY",
    "V","XOM","UNH","MA","JNJ","PG","HD","ABBV","WMT","BAC",
    "NFLX","CRM","CVX","ORCL","KO","PEP","ACN","MCD","COST","ADBE",
    "TMO","CSCO","ABT","LIN","NKE","DHR","AMGN","TXN","NEE","PM",
    "BMY","RTX","UNP","HON","COP","QCOM","INTU","MS","GS","PLTR",
    # Nasdaq 100 additions
    "AMD","LRCX","KLAC","MRVL","CDNS","SNPS","FTNT","PANW","CRWD","DDOG",
    "ZS","OKTA","NET","SNOW","MDB","MNST","PCAR","PAYX","FAST","ODFL",
    "CSGP","VRSK","IDXX","WDAY","PYPL","EBAY","TEAM","TTD","DOCU","ZM",
    "ABNB","DASH","RIVN","LCID","HOOD","MSTR","COIN","INTC","AMAT","MU",
    # Semis / Storage
    "ON","WOLF","SWKS","MCHP","STM","ASML","TER","ARM","SMCI","BTDR","SNDK",
    # Space/Defense
    "RDW","RKLB","ASTS","SATL","LUNR","ACHR","JOBY","LMT","NOC","GD","BA",
    # Quantum
    "IONQ","RGTI","QUBT","QBTS","ARQQ",
    # Crypto/Web3
    "MARA","RIOT","CLSK","SQ","CIFR","BTBT","SOUN","BBAI",
    # Biotech
    "RXRX","HIMS","CRSP","BEAM","EDIT","PACB","MRNA","BNTX","NVAX","BFLY",
    # EV/Energy
    "NIO","FSLR","ENPH","PLUG","BLNK","CHPT","SEDG","CRNC",
    # Cybersecurity
    "S","TENB","QLYS","CYBR",
    # Social/SaaS
    "RBLX","LYFT","PINS","SNAP","U",
    # ETFs
    "SOXX","ARKK","WCLD","BOTZ","UFO","ICLN","XLK","XLF","XLE",
]

def scan_accumulation(ticker, direction="bullish"):
    """
    Signal detection v5: data-driven momentum + breakout system.
    
    Based on feature correlation analysis (1,795 signals):
    - price_range 15-35% sweet spot (+0.13 correlation, strongest factor)
    - Higher range position = better (momentum > value)
    - CNN greed > fear for buying (momentum market)
    - OBV, VIX, phase detection: zero/negative correlation → removed from scoring
    
    BULLISH score (normalized 0-10):
      Momentum confirmed (0-3): price in upper range + above MA20
      Volume expansion (0-2): recent volume > prior
      Volatility sweet spot (0-2): range 15-35% = ideal
      Breakout signal (0-2): price crossing MA20 with volume
      Market alignment (0-1): CNN F&G > 30 (not extreme fear)
    
    BEARISH: keeps distribution gate + evidence-based scoring.
    """
    try:
        result = yf_chart(ticker, "1d", "1y")
        if not result:
            return None
        quote = result.get("indicators", {}).get("quote", [{}])[0]
        closes_raw = quote.get("close", [])
        volumes_raw = quote.get("volume", [])
        opens_raw = quote.get("open", [])

        data_pts = [(c, v, o) for c, v, o in zip(closes_raw, volumes_raw, opens_raw or closes_raw) if c and v]
        if len(data_pts) < 60:
            return None

        data_pts = data_pts[-126:]
        closes = [x[0] for x in data_pts]
        volumes = [x[1] for x in data_pts]
        opens = [x[2] if x[2] else x[0] for x in data_pts]
        n = len(closes)
        current = closes[-1]

        avg_dollar_vol = sum(v * c for v, c in zip(volumes[-20:], closes[-20:])) / 20
        if avg_dollar_vol < 5_000_000:
            return None

        # ── Common calculations ──────────────────────────────────────────
        vol_recent_20 = sum(volumes[-20:]) / 20
        vol_prior_40 = sum(volumes[-60:-20]) / 40 if n >= 60 else sum(volumes[:n-20]) / max(1, n-20)
        vol_ratio = vol_recent_20 / vol_prior_40 if vol_prior_40 > 0 else 1.0

        price_min = min(closes)
        price_max = max(closes)
        price_range_pct = (price_max - price_min) / price_min * 100 if price_min > 0 else 100
        range_pos = (current - price_min) / (price_max - price_min) * 100 if price_max > price_min else 50

        change_3m = (closes[-1] - closes[-65]) / closes[-65] * 100 if n >= 65 else 0
        change_1d = (closes[-1] - closes[-2]) / closes[-2] * 100 if n >= 2 else 0
        change_1m = (closes[-1] - closes[-22]) / closes[-22] * 100 if n >= 22 else 0
        change_2w = (closes[-1] - closes[-10]) / closes[-10] * 100 if n >= 10 else 0

        # MAs
        def sma(data, p):
            return sum(data[-p:]) / p if len(data) >= p else None
        ma10, ma20, ma50 = sma(closes, 10), sma(closes, 20), sma(closes, 50)

        # OBV (keep for bearish)
        obv_series = [0]
        for i in range(1, n):
            delta = volumes[i] if closes[i] > closes[i-1] else -volumes[i] if closes[i] < closes[i-1] else 0
            obv_series.append(obv_series[-1] + delta)
        obv_20d = obv_series[-1] - obv_series[-20] if len(obv_series) >= 20 else 0
        price_20d = (closes[-1] - closes[-20]) / closes[-20] * 100 if n >= 20 else 0

        down_vol = sum(volumes[i] for i in range(n-10, n) if i > 0 and closes[i] < closes[i-1])
        up_vol = sum(volumes[i] for i in range(n-10, n) if i > 0 and closes[i] >= closes[i-1])
        dist_ratio = down_vol / up_vol if up_vol > 0 else 1.0

        # Volume score (common to both directions)
        vol_score = 2 if vol_ratio > 1.4 else 1 if vol_ratio > 1.1 else 0

        # ── BULLISH v5: Momentum + Breakout ──────────────────────────────
        if direction == "bullish":
            # 1. Momentum confirmed (0-3): in upper range + above MA20
            mom_score = 0
            if range_pos > 60: mom_score += 2
            elif range_pos > 40: mom_score += 1
            if current > (ma20 or current * 0.99): mom_score += 1

            # 2. Volume expansion (0-2) — uses common vol_score

            # 3. Volatility sweet spot (0-2): 15-35% range
            if 15 <= price_range_pct <= 35:
                vol_sweet = 2  # Best zone (corr +0.13)
            elif 10 <= price_range_pct <= 50:
                vol_sweet = 1
            else:
                vol_sweet = 0

            # 4. Breakout signal (0-2): price just crossed above MA20 + volume
            breakout = 0
            if ma20 and n >= 3:
                was_below = closes[-3] < ma20 or closes[-2] < ma20
                now_above = current > ma20
                if was_below and now_above and vol_ratio > 1.1:
                    breakout = 2  # Fresh breakout with volume
                elif now_above and change_2w > 2:
                    breakout = 1  # Sustained above MA20

            # 5. Trend alignment (0-1)
            trend_ok = 1 if ma10 and ma20 and ma10 > ma20 else 0

            raw = mom_score + vol_score + vol_sweet + breakout + trend_ok
            # Max: 3+2+2+2+1 = 10, already on 0-10 scale
            score = max(0, min(10, raw))

            if score >= 7:
                signal = "🔥 強勢突破"
                action = "🟢 動能確認，可考慮進場"
            elif score >= 5:
                signal = "📈 動能上升"
                action = "🟡 趨勢形成中，持續觀察"
            else:
                return None

            # Phase label based on momentum stage
            if breakout >= 2:
                phase = 3; phase_label = "突破確認"
            elif mom_score >= 2 and vol_score >= 1:
                phase = 2; phase_label = "動能累積"
            else:
                phase = 1; phase_label = "趨勢萌芽"

            action_detail = f"區間位置{range_pos:.0f}% · 量比{vol_ratio:.1f}x · {'突破MA20' if breakout >= 2 else '趨勢向上'}"

            consec = 0
            for i in range(n-1, max(n-15, 0), -1):
                if closes[i] >= opens[i] and volumes[i] > vol_recent_20 * 0.9:
                    consec += 1
                else:
                    break

            score_comp = vol_sweet
            pos_score = mom_score
            obv_score = breakout
            mom_s = trend_ok

        # ── BEARISH: keep evidence-based ─────────────────────────────────
        else:
            if not (obv_20d < 0 or dist_ratio > 1.2):
                return None

            pos = 2 if range_pos > 80 else 1 if range_pos > 65 else 0
            trend = 2 if change_3m > 40 else 1 if change_3m > 20 else 0 if change_3m > 5 else -1
            obv = 2 if obv_20d < 0 and price_20d > -3 else 1 if obv_20d < 0 else 0
            dist = 2 if dist_ratio > 1.5 else 1 if dist_ratio > 1.2 else 0

            ma_cross_bear = 0
            if ma10 and ma20 and ma50:
                if ma10 < ma20 < ma50: ma_cross_bear = 2
                elif ma10 < ma50: ma_cross_bear = 1

            raw = vol_score + pos + trend + obv + dist + ma_cross_bear
            # Max: 2+2+2+2+2+2 = 12
            score = max(0, min(10, round(raw * 10 / 12)))
            
            if score >= 7:
                signal = "🔻 強出貨"
                action = "🔴 建議減碼"
            elif score >= 5:
                signal = "⚠️ 出貨中"
                action = "🟠 注意風險"
            else:
                return None

            phase = 0; phase_label = ""
            action_detail = f"OBV{'↓' if obv_20d < 0 else '→'} · 下跌量比{dist_ratio:.1f}x"
            consec = 0
            score_comp = 0
            pos_score = pos
            obv_score = obv
            mom_s = 0
            vol_score = vol_score

        # ── Sector resonance ─────────────────────────────────────────────
        SECTOR_MAP = {
            "AAPL":"XLK","MSFT":"XLK","NVDA":"XLK","AMD":"XLK","AVGO":"XLK","INTC":"XLK",
            "QCOM":"XLK","TXN":"XLK","AMAT":"XLK","LRCX":"XLK","KLAC":"XLK","MRVL":"XLK",
            "ASML":"XLK","MU":"XLK","ADBE":"XLK","CRM":"XLK","ORCL":"XLK","CSCO":"XLK",
            "SMCI":"XLK","ARM":"XLK","CDNS":"XLK","SNPS":"XLK","STM":"XLK","ON":"XLK",
            "WOLF":"XLK","SWKS":"XLK","MCHP":"XLK","TER":"XLK","BTDR":"XLK","DELL":"XLK",
            "INTU":"XLK","WDAY":"XLK","SNOW":"XLK","DDOG":"XLK","NET":"XLK","TTD":"XLK",
            "CRWD":"XLK","PANW":"XLK","ZS":"XLK","OKTA":"XLK","FTNT":"XLK","S":"XLK",
            "TENB":"XLK","QLYS":"XLK","CYBR":"XLK",
            "GOOGL":"XLC","META":"XLC","NFLX":"XLC",
            "TSLA":"XLY","AMZN":"XLY","HD":"XLY","MCD":"XLY","NKE":"XLY","COST":"XLY",
            "ABNB":"XLY","DASH":"XLY","RIVN":"XLY","LCID":"XLY","RBLX":"XLY","LYFT":"XLY",
            "PEP":"XLP","KO":"XLP","PG":"XLP","WMT":"XLP",
            "LLY":"XLV","UNH":"XLV","JNJ":"XLV","ABBV":"XLV","TMO":"XLV","ABT":"XLV",
            "DHR":"XLV","AMGN":"XLV","BMY":"XLV","MRNA":"XLV","BNTX":"XLV",
            "RXRX":"XLV","HIMS":"XLV","CRSP":"XLV","BEAM":"XLV","NVAX":"XLV",
            "JPM":"XLF","BAC":"XLF","V":"XLF","MA":"XLF","GS":"XLF","MS":"XLF",
            "PYPL":"XLF","COIN":"XLF","HOOD":"XLF","MSTR":"XLF","SQ":"XLF",
            "XOM":"XLE","CVX":"XLE","COP":"XLE","FSLR":"XLE","ENPH":"XLE",
            "HON":"XLI","UNP":"XLI","BA":"XLI","RTX":"XLI","LMT":"XLI","NOC":"XLI","GD":"XLI",
            "RDW":"XLI","RKLB":"XLI","ASTS":"XLI","LUNR":"XLI","ACHR":"XLI","JOBY":"XLI",
            "LIN":"XLB","NEE":"XLU",
        }
        sector_etf = SECTOR_MAP.get(ticker, "")
        sector_flow = ""
        sector_resonance = "N/A"
        if sector_etf:
            try:
                _, macro_str = gh_get("data/macro.json")
                if macro_str:
                    for s in json.loads(macro_str).get("broad_sectors", []):
                        if s.get("etf") == sector_etf:
                            sector_flow = s.get("flow", "")
                            break
            except: pass
            if direction == "bullish":
                sector_resonance = "✅ 順勢" if "流入" in sector_flow else "⚠️ 逆勢" if "流出" in sector_flow else "➖ 中性"
            else:
                sector_resonance = "✅ 順勢" if "流出" in sector_flow else "⚠️ 逆勢" if "流入" in sector_flow else "➖ 中性"

        # Smart price levels
        if direction == "bullish" and ma20 and ma50:
            # Entry: current price (or MA20 on pullback)
            entry = round(min(current, ma20 * 1.01), 2)  # slightly above MA20
            # Stop loss: lower of MA50 or recent 20-day low
            recent_low = min(closes[-20:]) if n >= 20 else min(closes[-10:])
            stop_candidates = [x for x in [ma50 * 0.98, recent_low * 0.98] if x < entry]
            stop = round(max(stop_candidates) if stop_candidates else entry * 0.95, 2)  # must be below entry
            stop_pct = round((stop / entry - 1) * 100, 1)
            # Target 1: recent 20-day high (resistance)
            recent_high = max(closes[-20:]) if n >= 20 else max(closes[-10:])
            t1 = round(recent_high * 1.02, 2)  # slightly above resistance
            t1_pct = round((t1 / entry - 1) * 100, 1)
            # Target 2: 6-month high
            t2_raw = round(price_max * 1.02, 2)
            t2 = max(t2_raw, round(t1 * 1.05, 2))  # T2 must be above T1
            t2_pct = round((t2 / entry - 1) * 100, 1)
            # Risk/Reward ratio
            risk = abs(entry - stop)
            reward = t1 - entry
            rr = round(reward / risk, 1) if risk > 0 else 0
            # Momentum health: is volume still expanding or fading?
            vol_last_5 = sum(volumes[-5:]) / 5
            vol_prev_5 = sum(volumes[-10:-5]) / 5 if n >= 10 else vol_last_5
            mom_health = "強" if vol_last_5 > vol_prev_5 * 1.1 else "穩" if vol_last_5 > vol_prev_5 * 0.9 else "弱"
        else:
            entry = round(current, 2)
            stop = round(current * 1.05, 2)  # bearish: stop above
            stop_pct = 5.0
            recent_low = min(closes[-20:]) if n >= 20 else min(closes)
            t1 = round(recent_low, 2)
            t1_pct = round((t1 / current - 1) * 100, 1)
            t2 = round(recent_low * 0.9, 2)
            t2_pct = round((t2 / current - 1) * 100, 1)
            rr = 0
            mom_health = ""

        return {
            "symbol": ticker, "direction": direction,
            "score": score, "score_max": 10,
            "price": round(current, 2),
            "change_1d": round(change_1d, 2),
            "change_1m": round(change_1m, 1),
            "vol_ratio": round(vol_ratio, 2),
            "price_range_pct": round(price_range_pct, 1),
            "range_position_pct": round(range_pos, 1),
            "consec_days": consec,
            "signal": signal, "action": action, "action_detail": action_detail,
            "score_vol": vol_score, "score_comp": score_comp,
            "score_pos": pos_score, "score_obv": obv_score, "score_mom": mom_s,
            "change_3m": round(change_3m, 1),
            "phase": phase, "phase_label": phase_label,
            "sector_etf": sector_etf, "sector_flow": sector_flow,
            "sector_resonance": sector_resonance,
            "entry_price": entry,
            "stop_loss": stop,
            "stop_pct": stop_pct,
            "target_1": t1,
            "target_1_pct": t1_pct,
            "target_2": t2,
            "target_2_pct": t2_pct,
            "risk_reward": rr,
            "mom_health": mom_health,
        }
    except Exception:
        pass
    return None

# ─── Main ─────────────────────────────────────────────────────────────────────


# ─── Market Context (VIX, CNN F&G, Composite) ─────────────────────────────────

def collect_market_context():
    """Collect VIX, CNN Fear & Greed, sector flows, and compute composite sentiment."""
    import math
    ctx = {}
    
    # 1. VIX
    try:
        vix_data = yf_chart("^VIX", "1d", "1y")
        if vix_data:
            vix_closes = [c for c in vix_data["indicators"]["quote"][0]["close"] if c]
            ctx["vix"] = round(vix_closes[-1], 2)
            ctx["vix_200sma"] = round(sum(vix_closes[-200:]) / min(200, len(vix_closes)), 2)
            ctx["vix_zone"] = "低位(<15)" if ctx["vix"] < 15 else "正常(15-20)" if ctx["vix"] < 20 else "偏高(20-30)" if ctx["vix"] < 30 else "恐慌(>30)"
            # VIX score: low VIX = greed, high = fear (inverted, 0-100)
            ctx["vix_score"] = max(0, min(100, 100 - (ctx["vix"] - 12) * (90 / 18)))
    except Exception as e:
        print(f"  VIX failed: {e}")
    
    # 2. CNN Fear & Greed
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            headers={"User-Agent": UA, "Accept": "application/json", "Referer": "https://edition.cnn.com/markets/fear-and-greed"}
        )
        r = urllib.request.urlopen(req, timeout=10)
        fg = json.loads(r.read()).get("fear_and_greed", {})
        ctx["cnn_fg_score"] = round(fg.get("score", 50), 1)
        ctx["cnn_fg_rating"] = fg.get("rating", "neutral")
        ctx["cnn_fg_prev_week"] = round(fg.get("previous_1_week", 50), 1)
    except Exception as e:
        print(f"  CNN F&G failed: {e}")
        ctx["cnn_fg_score"] = 50
        ctx["cnn_fg_rating"] = "neutral"
    
    # 3. SPY vs 200 SMA
    try:
        spy_data = yf_chart("SPY", "1d", "1y")
        if spy_data:
            spy_closes = [c for c in spy_data["indicators"]["quote"][0]["close"] if c]
            spy_200 = sum(spy_closes[-200:]) / min(200, len(spy_closes))
            ctx["spy_vs_200sma"] = round((spy_closes[-1] / spy_200 - 1) * 100, 2)
            spy_52w = max(spy_closes)
            ctx["spy_from_52w_high"] = round((spy_closes[-1] / spy_52w - 1) * 100, 2)
            ctx["spy_score"] = max(0, min(100, 50 + ctx["spy_vs_200sma"] * 5))
            ctx["high_score"] = max(0, min(100, 100 + ctx["spy_from_52w_high"] * 5))
            # Momentum
            spy_20d = (spy_closes[-1] - spy_closes[-20]) / spy_closes[-20] * 100
            ctx["mom_score"] = max(0, min(100, 50 + spy_20d * 5))
    except Exception as e:
        print(f"  SPY failed: {e}")
    
    # 4. Safe Haven: TLT vs SPY relative
    try:
        tlt_data = yf_chart("TLT", "1d", "3mo")
        spy_data2 = yf_chart("SPY", "1d", "3mo")
        if tlt_data and spy_data2:
            tlt_c = [c for c in tlt_data["indicators"]["quote"][0]["close"] if c]
            spy_c = [c for c in spy_data2["indicators"]["quote"][0]["close"] if c]
            spy_1m = (spy_c[-1] - spy_c[-22]) / spy_c[-22] * 100
            tlt_1m = (tlt_c[-1] - tlt_c[-22]) / tlt_c[-22] * 100
            ctx["haven_score"] = max(0, min(100, 50 + (spy_1m - tlt_1m) * 5))
    except:
        ctx["haven_score"] = 50
    
    # 5. Composite
    scores = [
        ctx.get("vix_score", 50),
        ctx.get("spy_score", 50),
        ctx.get("high_score", 50),
        ctx.get("haven_score", 50),
        ctx.get("mom_score", 50),
    ]
    ctx["composite_score"] = round(sum(scores) / len(scores), 1)
    if ctx["composite_score"] > 80: ctx["composite_label"] = "極度貪婪"
    elif ctx["composite_score"] > 60: ctx["composite_label"] = "貪婪"
    elif ctx["composite_score"] > 40: ctx["composite_label"] = "中性"
    elif ctx["composite_score"] > 20: ctx["composite_label"] = "恐懼"
    else: ctx["composite_label"] = "極度恐懼"
    
    return ctx


def save_market_context(ctx, today_date):
    """Save market context to Supabase and data/market_context.json."""
    # Save to Supabase
    try:
        row = {
            "date": today_date,
            "vix": ctx.get("vix"),
            "vix_zone": ctx.get("vix_zone"),
            "cnn_fg_score": ctx.get("cnn_fg_score"),
            "cnn_fg_rating": ctx.get("cnn_fg_rating"),
            "spy_vs_200sma": ctx.get("spy_vs_200sma"),
            "spy_from_52w_high": ctx.get("spy_from_52w_high"),
            "composite_score": ctx.get("composite_score"),
            "composite_label": ctx.get("composite_label"),
        }
        req = urllib.request.Request(
            f"{SUPABASE_URL}/rest/v1/market_context?on_conflict=date",
            data=json.dumps([row]).encode(),
            headers={**SB_HEADERS, "Prefer": "resolution=merge-duplicates,return=minimal"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=15)
        print(f"  ✅ Saved market context to Supabase")
    except Exception as e:
        print(f"  ⚠️ Supabase save failed: {e}")
    
    # Save to JSON
    ctx_json = json.dumps(ctx, ensure_ascii=False, indent=2)
    sha = gh_put("data/market_context.json", ctx_json, f"Update market_context.json")
    print(f"  ✅ data/market_context.json → {sha}")
    
    return ctx



def fetch_alpha_data(tickers):
    """
    Fetch 3-layer quantitative framework data for each ticker:
    1. Narrative (EPS revisions, earnings growth)
    2. Alpha (target price upside, forward PE, analyst consensus)
    3. Positioning (put/call ratio, IV skew, short interest)
    
    Returns dict: {ticker: {narrative: {}, alpha: {}, positioning: {}}}
    """
    import yfinance as yf
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    def _fetch_one(ticker):
        try:
            t = yf.Ticker(ticker)
            info = t.info
            price = getattr(t.fast_info, 'last_price', None)
            if not price or price <= 0:
                return ticker, None
            
            result = {"symbol": ticker}
            
            # ── 1. Narrative Layer ──
            # EPS revision trend (current vs 90 days ago)
            eps_revision_pct = None
            eps_up_30d = 0
            eps_dn_30d = 0
            try:
                et = t.eps_trend
                if et is not None and not et.empty:
                    # Use full year (0y) row
                    row = et.iloc[2] if len(et) > 2 else et.iloc[0]
                    curr = row.get('current', 0) or 0
                    ago90 = row.get('90daysAgo', 0) or 0
                    if ago90 and curr and ago90 != 0:
                        eps_revision_pct = round((curr / ago90 - 1) * 100, 1)
            except Exception:
                pass
            
            try:
                er = t.eps_revisions
                if er is not None and not er.empty:
                    eps_up_30d = int(er.iloc[0].get('upLast30days', 0) or 0)
                    eps_dn_30d = int(er.iloc[0].get('downLast30days', 0) or 0)
            except Exception:
                pass
            
            earnings_growth = info.get('earningsGrowth')  # YoY
            revenue_growth = info.get('revenueGrowth')
            
            # Narrative verdict
            narrative = "intact"  # default
            if eps_revision_pct is not None:
                if eps_revision_pct < -5:
                    narrative = "weakening"
                elif eps_revision_pct < -15:
                    narrative = "broken"
            if eps_dn_30d > eps_up_30d * 2:
                narrative = "weakening" if narrative == "intact" else "broken"
            
            result["narrative"] = {
                "eps_revision_pct": eps_revision_pct,
                "eps_up_30d": eps_up_30d,
                "eps_dn_30d": eps_dn_30d,
                "earnings_growth": round(earnings_growth * 100, 1) if earnings_growth else None,
                "revenue_growth": round(revenue_growth * 100, 1) if revenue_growth else None,
                "verdict": narrative,
            }
            
            # ── 2. Alpha Layer ──
            target_mean = info.get('targetMeanPrice', 0) or 0
            target_high = info.get('targetHighPrice', 0) or 0
            target_low = info.get('targetLowPrice', 0) or 0
            forward_pe = info.get('forwardPE', 0) or 0
            trailing_pe = info.get('trailingPE', 0) or 0
            peg = info.get('pegRatio')
            rec_key = info.get('recommendationKey', 'none')
            rec_mean = info.get('recommendationMean', 0) or 0  # 1=strongBuy, 5=strongSell
            n_analysts = info.get('numberOfAnalystOpinions', 0) or 0
            
            upside_pct = round((target_mean / price - 1) * 100, 1) if target_mean and price else 0
            
            result["alpha"] = {
                "target_mean": round(target_mean, 2) if target_mean else None,
                "target_high": round(target_high, 2) if target_high else None,
                "target_low": round(target_low, 2) if target_low else None,
                "upside_pct": upside_pct,
                "forward_pe": round(forward_pe, 1) if forward_pe else None,
                "trailing_pe": round(trailing_pe, 1) if trailing_pe else None,
                "peg_ratio": round(peg, 2) if peg else None,
                "recommendation": rec_key,
                "rec_score": round(rec_mean, 1),
                "n_analysts": n_analysts,
            }
            
            # ── 3. Positioning Layer (Options) ──
            pc_ratio_vol = None
            pc_ratio_oi = None
            iv_skew = None
            max_pain = None
            try:
                dates = t.options
                if dates:
                    # Use nearest monthly expiry (skip weeklies < 7 days out)
                    from datetime import datetime
                    today = datetime.now()
                    target_date = None
                    for d in dates:
                        exp = datetime.strptime(d, "%Y-%m-%d")
                        days_out = (exp - today).days
                        if 7 <= days_out <= 45:
                            target_date = d
                            break
                    if not target_date and dates:
                        target_date = dates[min(1, len(dates)-1)]
                    
                    if target_date:
                        chain = t.option_chain(target_date)
                        calls = chain.calls
                        puts = chain.puts
                        
                        c_vol = calls['volume'].sum() or 0
                        p_vol = puts['volume'].sum() or 0
                        c_oi = calls['openInterest'].sum() or 0
                        p_oi = puts['openInterest'].sum() or 0
                        
                        if c_vol > 0:
                            pc_ratio_vol = round(p_vol / c_vol, 2)
                        if c_oi > 0:
                            pc_ratio_oi = round(p_oi / c_oi, 2)
                        
                        # IV Skew (ATM put IV - call IV)
                        try:
                            atm_c = calls.iloc[(calls['strike'] - price).abs().argsort()[:3]]
                            atm_p = puts.iloc[(puts['strike'] - price).abs().argsort()[:3]]
                            avg_c_iv = atm_c['impliedVolatility'].mean()
                            avg_p_iv = atm_p['impliedVolatility'].mean()
                            if avg_c_iv > 0:
                                iv_skew = round((avg_p_iv - avg_c_iv) * 100, 1)
                        except Exception:
                            pass
                        
                        # Max Pain (strike where total OI loss for option holders is maximized)
                        try:
                            all_strikes = sorted(set(calls['strike'].tolist() + puts['strike'].tolist()))
                            min_loss = float('inf')
                            mp = 0
                            for s in all_strikes:
                                c_loss = calls.apply(lambda r: max(0, s - r['strike']) * r['openInterest'], axis=1).sum()
                                p_loss = puts.apply(lambda r: max(0, r['strike'] - s) * r['openInterest'], axis=1).sum()
                                total = c_loss + p_loss
                                if total < min_loss:
                                    min_loss = total
                                    mp = s
                            max_pain = round(mp, 2)
                        except Exception:
                            pass
            except Exception:
                pass
            
            # Short interest
            short_ratio = info.get('shortRatio')
            short_pct = info.get('shortPercentOfFloat')
            
            # Positioning verdict
            pos_verdict = "neutral"
            if pc_ratio_oi is not None:
                if pc_ratio_oi > 1.5:
                    pos_verdict = "hedged"  # heavy put protection
                elif pc_ratio_oi < 0.5:
                    pos_verdict = "crowded_long"  # dangerous
            if short_pct and short_pct > 0.1:
                pos_verdict = "high_short"
            
            result["positioning"] = {
                "pc_ratio_vol": pc_ratio_vol,
                "pc_ratio_oi": pc_ratio_oi,
                "iv_skew": iv_skew,
                "max_pain": max_pain,
                "short_ratio": round(short_ratio, 1) if short_ratio else None,
                "short_pct_float": round(short_pct * 100, 1) if short_pct else None,
                "verdict": pos_verdict,
            }
            
            # ── 4. Classification (4-quadrant matrix) ──
            # Type 1: 雙重轉弱 (narrative broken + alpha low) → 清倉
            # Type 2: 敘事尚存、相對轉弱 (narrative ok, alpha low) → 減碼  
            # Type 3: 敘事+Alpha高、結構極差 (good story, crowded) → 持有等待
            # Type 4: 最佳加碼區 (narrative ok, alpha high, deleveraged) → 加碼
            
            n_ok = narrative in ("intact",)
            a_high = upside_pct > 15
            p_ok = pos_verdict in ("neutral", "hedged")
            
            if not n_ok and not a_high:
                classification = "type1_exit"
            elif n_ok and not a_high:
                classification = "type2_reduce"
            elif n_ok and a_high and not p_ok:
                classification = "type3_hold"
            elif n_ok and a_high and p_ok:
                classification = "type4_accumulate"
            else:
                classification = "type2_reduce"
            
            result["classification"] = classification
            
            # ── 5. Expected Return Score ──
            # ER = Upside × Probability × (1/Time) − Downside
            prob = 0.5  # base
            if narrative == "intact": prob += 0.2
            elif narrative == "broken": prob -= 0.3
            if eps_up_30d > eps_dn_30d: prob += 0.1
            if rec_key in ("buy", "strong_buy"): prob += 0.1
            prob = max(0.05, min(0.95, prob))
            
            downside_pct = abs(upside_pct * 0.5) if upside_pct < 0 else max(5, abs(target_low / price - 1) * 100) if target_low and price else 10
            
            # Time factor: crowded = slower recovery
            time_factor = 1.0
            if pos_verdict == "crowded_long": time_factor = 0.5
            elif pos_verdict == "high_short": time_factor = 0.7
            
            er_score = round(upside_pct * prob * time_factor - downside_pct * (1 - prob), 1)
            result["expected_return"] = er_score
            result["price"] = round(price, 2)
            
            # ── 6. Multi-Model Valuation ──
            SECTOR_PE = {
                'Technology': 30, 'Communication Services': 22, 'Consumer Cyclical': 25,
                'Healthcare': 18, 'Financial Services': 14, 'Energy': 12,
                'Industrials': 20, 'Consumer Defensive': 24, 'Basic Materials': 18,
                'Real Estate': 35, 'Utilities': 18,
            }
            fwd_eps_val = info.get('forwardEps')
            div_rate_val = info.get('dividendRate', 0) or 0
            sector_name = info.get('sector', '')
            sect_pe = SECTOR_PE.get(sector_name, 22)
            
            valuation = {"analyst": round(target_mean, 0) if target_mean else None}
            
            if fwd_eps_val and fwd_eps_val > 0:
                valuation["sector_pe"] = round(fwd_eps_val * sect_pe, 0)
                valuation["pe_low"] = round(fwd_eps_val * sect_pe * 0.8, 0)
                valuation["pe_high"] = round(fwd_eps_val * sect_pe * 1.2, 0)
                valuation["fwd_eps"] = round(fwd_eps_val, 2)
                valuation["sector"] = sector_name
                valuation["sector_pe_used"] = sect_pe
            
            if div_rate_val > 0 and price > 0:
                try:
                    div_yield = div_rate_val / price
                    # Use sector-appropriate growth: high-yield stocks grow slower
                    g = 0.04 if div_yield > 0.03 else 0.06 if div_yield > 0.015 else 0.08
                    r = 0.10  # required return 10%
                    if r > g:
                        valuation["ddm"] = round(div_rate_val * (1 + g) / (r - g), 0)
                except:
                    pass
            
            # ── v2 Probability-Weighted Composite ──
            # Replace simple average with confidence-weighted models
            weighted_models = []
            
            # Model 1: Analyst (-10% optimism haircut)
            if target_mean and target_mean > 0 and n_analysts > 0:
                adj = target_mean * 0.90
                conf = min(1.0, n_analysts / 20)
                weighted_models.append((adj, conf, "analyst"))
                valuation["analyst_adj"] = round(adj, 0)
            
            # Model 2: Sector PE (FPE -12% discount, reduced weight for growth stocks)
            if fwd_eps_val and fwd_eps_val > 0:
                adj_eps = fwd_eps_val * 0.88
                val_sect = adj_eps * sect_pe
                conf = 0.8
                if forward_pe and forward_pe > sect_pe * 2:
                    conf = 0.3  # growth premium not captured by sector PE
                weighted_models.append((val_sect, conf, "sector_pe"))
                valuation["sector_pe_adj"] = round(val_sect, 0)
            
            # Model 3: PEG Fair Value (replaces DDM for all stocks)
            eg = info.get('earningsGrowth')
            if fwd_eps_val and fwd_eps_val > 0 and eg and 0.03 < eg < 1.0:
                eg_pct = min(eg * 100, 50)  # cap growth at 50%
                fair_peg = 1.2 if sector_name in ('Technology', 'Communication Services', 'Consumer Cyclical') else 1.8
                peg_pe = max(12, min(eg_pct * fair_peg, 40))  # PE 12-40x
                val_peg = (fwd_eps_val * 0.88) * peg_pe
                conf = 0.5
                actual_peg = info.get('pegRatio')
                if actual_peg and (actual_peg > 2.0 or actual_peg < 0.8):
                    conf = 0.7  # strong mispricing signal
                weighted_models.append((val_peg, conf, "peg"))
                valuation["peg_fair"] = round(val_peg, 0)
                valuation["peg_pe_used"] = round(peg_pe, 1)
            
            if weighted_models:
                total_w = sum(w for _, w, _ in weighted_models)
                composite = sum(v * w for v, w, _ in weighted_models) / total_w
                valuation["composite"] = round(composite, 0)
                valuation["composite_upside"] = round((composite / price - 1) * 100, 1)
                valuation["model_count"] = len(weighted_models)
            
            result["valuation"] = valuation
            
            return ticker, result
        except Exception as e:
            return ticker, None
    
    results = {}
    print(f"  Fetching alpha data for {len(tickers)} tickers (8 threads)...")
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_fetch_one, t): t for t in tickers}
        done = 0
        for f in as_completed(futures):
            done += 1
            ticker, data = f.result()
            if data:
                results[ticker] = data
            if done % 20 == 0:
                print(f"    {done}/{len(tickers)} done...")
    
    print(f"  ✅ Alpha data fetched for {len(results)}/{len(tickers)} tickers")
    return results


def send_daily_email(tw, bull_signals, bear_signals, mkt_ctx, news_items=None, movers_data=None, macro_data=None, alpha_data=None, signal_changes=None):
    """Send daily smart money email summary with sector flow + market movers + alpha framework + signal alerts."""
    RESEND_KEY = os.environ.get("RESEND_API_KEY", "re_h6P4QM47_N47rSLhCs3qEeZkQUq5fkvaU")
    TO_EMAIL = "smartlifecalendar@gmail.com"
    
    if not RESEND_KEY:
        print("  No RESEND_API_KEY set, skipping email")
        return
    
    date_str = tw.strftime("%Y/%m/%d")
    day_name = ["週一","週二","週三","週四","週五","週六","週日"][tw.weekday()]
    
    # Market context
    vix = mkt_ctx.get("vix", "?") if mkt_ctx else "?"
    cnn = mkt_ctx.get("cnn_fg_score", "?") if mkt_ctx else "?"
    composite = mkt_ctx.get("composite_score", "?") if mkt_ctx else "?"
    spy_200 = mkt_ctx.get("spy_vs_200sma", "?") if mkt_ctx else "?"
    
    # Bull/bear regime
    if isinstance(spy_200, (int, float)):
        regime = "🐂 牛市" if spy_200 > 5 else "🐂 觀望" if spy_200 > 0 else "🐻 警告" if spy_200 > -5 else "🐻 熊市"
    else:
        regime = "?"
    
    # ── Build sector flow HTML (from macro_data broad_sectors, same source as website) ──
    sector_html = ""
    sectors = []
    if macro_data and macro_data.get("broad_sectors"):
        for s in macro_data["broad_sectors"]:
            sectors.append({
                "symbol": s.get("etf", ""),
                "sector_zh": s.get("name", "").split(" ")[0],
                "change_pct": s.get("change_1d", 0),
                "fund_flow": s.get("fund_flow", 0),
                "volume_1d": s.get("volume_1d", 0),
            })
        sectors.sort(key=lambda x: x["change_pct"], reverse=True)
    
    if sectors:
        def fmt_flow(val):
            """Format fund flow to human readable (e.g., +1.2B, -340M)."""
            if abs(val) >= 1e9:
                return f"{val/1e9:+.1f}B"
            elif abs(val) >= 1e6:
                return f"{val/1e6:+.0f}M"
            elif abs(val) >= 1e3:
                return f"{val/1e3:+.0f}K"
            return f"{val:+.0f}" if val else "-"

        sector_rows = ""
        for s in sectors:
            etf = s.get("symbol", "")
            name = s.get("sector_zh", "")
            daily_chg = s.get("change_pct", 0)
            ff = s.get("fund_flow", 0)
            color = "#16a34a" if daily_chg > 0 else "#dc2626" if daily_chg < 0 else "#64748b"
            fc = "#16a34a" if ff > 0 else "#dc2626" if ff < 0 else "#64748b"
            icon = "🟢" if daily_chg > 0.3 else "🔴" if daily_chg < -0.3 else "⚪"
            sector_rows += f"""
            <tr>
                <td style="padding:6px 10px;font-weight:600">{icon} {etf}</td>
                <td style="padding:6px 10px">{name}</td>
                <td style="padding:6px 10px;text-align:right;color:{color};font-weight:700">{daily_chg:+.2f}%</td>
                <td style="padding:6px 10px;text-align:right;color:{fc};font-weight:600;font-size:12px">{fmt_flow(ff)}</td>
            </tr>"""
        
        inflow = sum(1 for s in sectors if s.get("change_pct", 0) > 0.3)
        outflow = sum(1 for s in sectors if s.get("change_pct", 0) < -0.3)
        top_sector = sectors[0]["sector_zh"] if sectors else "?"
        bot_sector = sectors[-1]["sector_zh"] if sectors else "?"
        total_flow = sum(s.get("fund_flow", 0) for s in sectors)
        sector_html = f"""
        <div style="background:white;padding:16px 24px;border:1px solid #e2e8f0;border-top:none">
            <h2 style="font-size:16px;color:#1e293b;margin:0 0 4px">🏭 今日板塊資金流動</h2>
            <p style="color:#64748b;font-size:12px;margin:0 0 12px">流入 {inflow} 個 · 流出 {outflow} 個 · 淨流動 {fmt_flow(total_flow)} · 最強：{top_sector} · 最弱：{bot_sector}</p>
            <table style="width:100%;border-collapse:collapse;font-size:13px">
                <tr style="background:#f8fafc">
                    <th style="padding:6px 10px;text-align:left">板塊</th>
                    <th style="padding:6px 10px;text-align:left">名稱</th>
                    <th style="padding:6px 10px;text-align:right">今日漲跌</th>
                    <th style="padding:6px 10px;text-align:right">資金流</th>
                </tr>
                {sector_rows}
            </table>
        </div>"""

    # ── Build market movers HTML ──
    movers_html = ""
    if movers_data:
        def _movers_rows(stocks, limit=5):
            rows = ""
            for s in (stocks or [])[:limit]:
                sym = s.get("symbol", "")
                price = s.get("price", 0)
                pct = s.get("change_pct", 0)
                color = "#16a34a" if pct > 0 else "#dc2626"
                vr = s.get("vr", "")
                vr_str = f" · 量比{vr}x" if vr else ""
                rows += f'<tr><td style="padding:5px 10px;font-weight:700">{sym}</td><td style="padding:5px 10px;text-align:right">${price}</td><td style="padding:5px 10px;text-align:right;color:{color};font-weight:700">{pct:+.2f}%</td><td style="padding:5px 10px;font-size:11px;color:#64748b">{s.get("name","")}{vr_str}</td></tr>'
            return rows
        
        gainers = movers_data.get("gainers", [])
        losers = movers_data.get("losers", [])
        strong_buy = movers_data.get("strong_buy", [])
        strong_sell = movers_data.get("strong_sell", [])
        
        sections = ""
        if strong_buy:
            sections += f'<h3 style="font-size:14px;color:#16a34a;margin:16px 0 8px">🚀 強力買進訊號</h3><table style="width:100%;border-collapse:collapse;font-size:13px">{_movers_rows(strong_buy, 5)}</table>'
        if strong_sell:
            sections += f'<h3 style="font-size:14px;color:#dc2626;margin:16px 0 8px">🔴 強力賣出訊號</h3><table style="width:100%;border-collapse:collapse;font-size:13px">{_movers_rows(strong_sell, 5)}</table>'
        sections += f'<h3 style="font-size:14px;color:#f59e0b;margin:16px 0 8px">📈 漲幅前5</h3><table style="width:100%;border-collapse:collapse;font-size:13px">{_movers_rows(gainers, 5)}</table>'
        sections += f'<h3 style="font-size:14px;color:#ef4444;margin:16px 0 8px">📉 跌幅前5</h3><table style="width:100%;border-collapse:collapse;font-size:13px">{_movers_rows(losers, 5)}</table>'
        
        movers_html = f"""
        <div style="background:white;padding:16px 24px;border:1px solid #e2e8f0;border-top:none">
            <h2 style="font-size:16px;color:#1e293b;margin:0 0 4px">📊 今日市場速報</h2>
            <p style="color:#64748b;font-size:12px;margin:0 0 8px">漲跌幅排行 + 異常量能訊號</p>
            {sections}
        </div>"""

    # Build news HTML
    news_html = ""
    if news_items:
        news_rows = ""
        for n in (news_items or [])[:8]:
            t = n.get("title", "").replace('"', '&quot;')
            u = n.get("url", "#")
            p = n.get("publisher", "")
            news_rows += '<div style="padding:8px 0;border-bottom:1px solid #f1f5f9"><a href="' + u + '" style="color:#4f46e5;font-size:13px;text-decoration:none;line-height:1.6">' + t + '</a> <span style="color:#94a3b8;font-size:11px">' + p + '</span></div>'
        news_html = '<div style="background:white;padding:16px 24px;border:1px solid #e2e8f0;border-top:none"><h2 style="font-size:16px;color:#1e293b;margin:0 0 12px">🌐 今日財金新聞</h2>' + news_rows + '</div>'

    # Build HTML email — bull/bear tables
    bull_top = sorted(bull_signals, key=lambda x: x.get("score", 0), reverse=True)[:10]
    bear_top = sorted(bear_signals, key=lambda x: x.get("score", 0), reverse=True)[:5]
    
    bull_rows = ""
    for s in bull_top:
        color = "#16a34a" if s.get("score", 0) >= 7 else "#2563eb"
        trans = s.get("transition", "")
        mom = s.get("momentum_change", "")
        bull_rows += f"""
        <tr>
            <td style="padding:8px 12px;font-weight:700;color:{color}">{s.get("symbol","")}</td>
            <td style="padding:8px 12px;text-align:center">{s.get("score","")}/10</td>
            <td style="padding:8px 12px">{s.get("signal","")}</td>
            <td style="padding:8px 12px;text-align:right">${s.get("price","")}</td>
            <td style="padding:8px 12px;font-size:11px">{trans} {mom}</td>
            <td style="padding:8px 12px;font-size:11px">{s.get("action","")}</td>
        </tr>"""
    
    bear_rows = ""
    for s in bear_top:
        bear_rows += f"""
        <tr>
            <td style="padding:8px 12px;font-weight:700;color:#dc2626">{s.get("symbol","")}</td>
            <td style="padding:8px 12px;text-align:center">{s.get("score","")}/10</td>
            <td style="padding:8px 12px">{s.get("signal","")}</td>
            <td style="padding:8px 12px;text-align:right">${s.get("price","")}</td>
        </tr>"""
    
    # ── Build Alpha Framework HTML ──
    def _build_valuation_table(type4_list, type1_list, all_alpha):
        """Build multi-model valuation comparison HTML for email."""
        # Combine type4 + type1 for valuation display
        stocks_to_show = type4_list[:6] + type1_list[:4]
        if not stocks_to_show:
            return ""
        
        rows = ""
        for d in stocks_to_show:
            v = d.get("valuation", {})
            a = d.get("alpha", {})
            price = d.get("price", 0)
            sym = d.get("symbol", "?")
            cls = d.get("classification", "?")
            
            analyst = v.get("analyst_adj") or v.get("analyst")
            sect_pe = v.get("sector_pe_adj") or v.get("sector_pe")
            peg_fair = v.get("peg_fair")
            composite = v.get("composite")
            comp_upside = v.get("composite_upside")
            
            cls_icon = {"type4_accumulate": "🟢", "type3_hold": "🟡", "type2_reduce": "🟠", "type1_exit": "🔴"}.get(cls, "")
            cls_color = {"type4_accumulate": "#16a34a", "type1_exit": "#dc2626"}.get(cls, "#64748b")
            
            def _fmt(val):
                if val is None: return "—"
                return f"${val:,.0f}"
            
            comp_str = ""
            if comp_upside is not None:
                comp_color = "#16a34a" if comp_upside > 10 else "#dc2626" if comp_upside < -10 else "#a16207"
                comp_str = f'<span style="color:{comp_color};font-weight:700">{comp_upside:+.0f}%</span>'
            
            rows += f'''<tr style="border-bottom:1px solid #f1f5f9">
                <td style="padding:5px 6px;font-weight:700;color:{cls_color}">{cls_icon} {sym}</td>
                <td style="padding:5px 6px;text-align:right">${price:,.0f}</td>
                <td style="padding:5px 6px;text-align:right">{_fmt(analyst)}</td>
                <td style="padding:5px 6px;text-align:right">{_fmt(sect_pe)}</td>
                <td style="padding:5px 6px;text-align:right">{_fmt(peg_fair)}</td>
                <td style="padding:5px 6px;text-align:right">{_fmt(composite)}</td>
                <td style="padding:5px 6px;text-align:center">{comp_str}</td>
            </tr>'''
        
        return f'''
            <h3 style="font-size:14px;color:#4f46e5;margin:16px 0 6px">📊 多模型估值比較</h3>
            <p style="color:#94a3b8;font-size:10px;margin:0 0 6px">分析師(-10%) · 板塊PE(FPE-12%) · PEG估值 · 加權綜合</p>
            <table style="width:100%;border-collapse:collapse;font-size:11px">
                <tr style="background:#f8fafc">
                    <th style="padding:5px 6px;text-align:left">代號</th>
                    <th style="padding:5px 6px;text-align:right">現價</th>
                    <th style="padding:5px 6px;text-align:right">分析師</th>
                    <th style="padding:5px 6px;text-align:right">板塊PE</th>
                    <th style="padding:5px 6px;text-align:right">PEG</th>
                    <th style="padding:5px 6px;text-align:right">綜合</th>
                    <th style="padding:5px 6px;text-align:center">空間</th>
                </tr>
                {rows}
            </table>'''

    alpha_html = ""
    if alpha_data:
        ranked = sorted(alpha_data.values(), key=lambda x: x.get("expected_return", 0), reverse=True)
        from collections import Counter
        cc = Counter(d.get("classification", "?") for d in alpha_data.values())
        
        # Type 4 accumulate (best buys)
        type4 = [d for d in ranked if d.get("classification") == "type4_accumulate"][:8]
        # Type 1 exit (sell now)
        type1 = [d for d in reversed(ranked) if d.get("classification") == "type1_exit"][:5]
        # Narrative alerts (EPS being revised down)
        narrative_alerts = [d for d in alpha_data.values() 
                          if d.get("narrative", {}).get("verdict") in ("broken", "weakening")
                          and d.get("narrative", {}).get("eps_revision_pct") is not None
                          and d["narrative"]["eps_revision_pct"] < -10]
        narrative_alerts.sort(key=lambda x: x["narrative"]["eps_revision_pct"])
        
        def _pc_icon(pc):
            if pc is None: return "—"
            if pc > 1.5: return f"🛡️{pc:.1f}"
            if pc < 0.5: return f"⚠️{pc:.1f}"
            return f"{pc:.1f}"
        
        def _class_label(c):
            return {"type4_accumulate": "🟢加碼", "type3_hold": "🟡持有", "type2_reduce": "🟠減碼", "type1_exit": "🔴清倉"}.get(c, "?")
        
        def _narr_icon(v):
            return {"intact": "✅", "weakening": "⚠️", "broken": "❌"}.get(v, "?")
        
        # Build type4 rows
        t4_rows = ""
        for d in type4:
            n = d.get("narrative", {})
            a = d.get("alpha", {})
            p = d.get("positioning", {})
            eps_rev = n.get("eps_revision_pct")
            eps_str = f"{eps_rev:+.1f}%" if eps_rev is not None else "—"
            t4_rows += f'<tr><td style="padding:5px 8px;font-weight:700;color:#16a34a">{d["symbol"]}</td><td style="padding:5px 8px;text-align:right;font-weight:700;color:#16a34a">{d["expected_return"]:+.1f}</td><td style="padding:5px 8px;text-align:right">{a.get("upside_pct",0):+.1f}%</td><td style="padding:5px 8px;text-align:center">{eps_str}</td><td style="padding:5px 8px;text-align:center">{_pc_icon(p.get("pc_ratio_oi"))}</td><td style="padding:5px 8px;text-align:center;font-size:11px">{a.get("recommendation","?")}</td></tr>'
        
        # Build type1 rows
        t1_rows = ""
        for d in type1:
            n = d.get("narrative", {})
            a = d.get("alpha", {})
            eps_rev = n.get("eps_revision_pct")
            eps_str = f"{eps_rev:+.1f}%" if eps_rev is not None else "—"
            t1_rows += f'<tr><td style="padding:5px 8px;font-weight:700;color:#dc2626">{d["symbol"]}</td><td style="padding:5px 8px;text-align:right;color:#dc2626">{d["expected_return"]:+.1f}</td><td style="padding:5px 8px;text-align:right">{a.get("upside_pct",0):+.1f}%</td><td style="padding:5px 8px;text-align:center">{eps_str}</td><td style="padding:5px 8px;text-align:center">{_narr_icon(n.get("verdict"))}</td></tr>'
        
        alpha_html = f"""
        <div style="background:white;padding:16px 24px;border:1px solid #e2e8f0;border-top:none">
            <h2 style="font-size:16px;color:#1e293b;margin:0 0 4px">🔬 Alpha 框架分析</h2>
            <p style="color:#64748b;font-size:12px;margin:0 0 12px">三層量化：敘事(EPS修正) × Alpha(預期回報) × 部位結構(選擇權) · 共 {len(alpha_data)} 支</p>
            <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap">
                <span style="background:#dcfce7;color:#16a34a;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:700">🟢 加碼 {cc.get('type4_accumulate',0)}</span>
                <span style="background:#fef9c3;color:#a16207;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:700">🟡 持有 {cc.get('type3_hold',0)}</span>
                <span style="background:#fed7aa;color:#c2410c;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:700">🟠 減碼 {cc.get('type2_reduce',0)}</span>
                <span style="background:#fee2e2;color:#dc2626;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:700">🔴 清倉 {cc.get('type1_exit',0)}</span>
            </div>
            
            <h3 style="font-size:14px;color:#16a34a;margin:12px 0 6px">🎯 最佳加碼 Top {len(type4)}</h3>
            <table style="width:100%;border-collapse:collapse;font-size:12px">
                <tr style="background:#f0fdf4"><th style="padding:5px 8px;text-align:left">代號</th><th style="padding:5px 8px;text-align:right">ER</th><th style="padding:5px 8px;text-align:right">上行空間</th><th style="padding:5px 8px;text-align:center">EPS修正</th><th style="padding:5px 8px;text-align:center">P/C</th><th style="padding:5px 8px;text-align:center">評級</th></tr>
                {t4_rows}
            </table>
            
            {"<h3 style='font-size:14px;color:#dc2626;margin:12px 0 6px'>⚠️ 清倉警報</h3><table style='width:100%;border-collapse:collapse;font-size:12px'><tr style='background:#fef2f2'><th style='padding:5px 8px;text-align:left'>代號</th><th style='padding:5px 8px;text-align:right'>ER</th><th style='padding:5px 8px;text-align:right'>上行空間</th><th style='padding:5px 8px;text-align:center'>EPS修正</th><th style='padding:5px 8px;text-align:center'>敘事</th></tr>" + t1_rows + "</table>" if type1 else ""}
            
            {_build_valuation_table(type4, type1, alpha_data)}
        </div>"""
    
    # ── Build Signal Alert HTML (lost signals + targets) ──
    signal_alert_html = ""
    if signal_changes:
        lost = signal_changes.get("lost", [])
        new_sigs = signal_changes.get("new", [])
        targets = signal_changes.get("targets", [])
        
        parts = []
        
        # Exit alerts (signal lost) - fetch entry dates from Supabase
        if lost:
            import requests as _req
            _sb_h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
            for s in lost:
                try:
                    r_h = _req.get(f"{SUPABASE_URL}/rest/v1/accumulation_signals",
                        headers=_sb_h,
                        params={"select": "date", "symbol": f"eq.{s['symbol']}", 
                                "direction": "eq.bullish", "order": "date.asc", "limit": 1}, timeout=5)
                    h = r_h.json()
                    s["first_date"] = h[0]["date"] if h else "?"
                except Exception:
                    s["first_date"] = "?"
            
            lost_rows = ""
            for s in sorted(lost, key=lambda x: x.get("prev_score", 0), reverse=True):
                lost_rows += f'<tr><td style="padding:5px 8px;font-weight:700;color:#dc2626">{s["symbol"]}</td><td style="padding:5px 8px;text-align:center">{s.get("prev_score","?")}/10</td><td style="padding:5px 8px;text-align:right">${s.get("prev_price","?")}</td><td style="padding:5px 8px;text-align:center;font-size:11px">{s.get("first_date","?")}</td></tr>'
            parts.append(f"""
                <h3 style="font-size:14px;color:#dc2626;margin:0 0 6px">🚨 訊號消失 — 建議出場（{len(lost)} 支）</h3>
                <p style="color:#64748b;font-size:11px;margin:0 0 8px">昨天有吸籌訊號，今天消失。回測顯示及時出場可避免平均 -2% 虧損。</p>
                <table style="width:100%;border-collapse:collapse;font-size:12px">
                    <tr style="background:#fef2f2"><th style="padding:5px 8px;text-align:left">代號</th><th style="padding:5px 8px;text-align:center">昨日分數</th><th style="padding:5px 8px;text-align:right">昨日價格</th><th style="padding:5px 8px;text-align:center">首次出現</th></tr>
                    {lost_rows}
                </table>""")
        
        # New entry signals
        if new_sigs:
            new_rows = ""
            for s in sorted(new_sigs, key=lambda x: x.get("score", 0), reverse=True):
                new_rows += f'<tr><td style="padding:5px 8px;font-weight:700;color:#16a34a">{s["symbol"]}</td><td style="padding:5px 8px;text-align:center">{s.get("score","?")}/10</td><td style="padding:5px 8px;text-align:right">${s.get("price","?")}</td><td style="padding:5px 8px;text-align:right;color:#16a34a;font-weight:700">${round(s["price"]*1.15,2) if s.get("price") else "?"}</td></tr>'
            parts.append(f"""
                <h3 style="font-size:14px;color:#16a34a;margin:16px 0 6px">🆕 新訊號 — 觀察名單（{len(new_sigs)} 支）</h3>
                <table style="width:100%;border-collapse:collapse;font-size:12px">
                    <tr style="background:#f0fdf4"><th style="padding:5px 8px;text-align:left">代號</th><th style="padding:5px 8px;text-align:center">分數</th><th style="padding:5px 8px;text-align:right">現價</th><th style="padding:5px 8px;text-align:right">+15%目標</th></tr>
                    {new_rows}
                </table>""")
        
        # Targets tracking (only show score >= 7 and consec >= 5)
        tracked = [t for t in targets if t.get("score", 0) >= 7 and t.get("consec_days", 0) >= 5]
        if tracked:
            hit = [t for t in tracked if t["hit_target"]]
            approaching = [t for t in tracked if not t["hit_target"] and t["gain_pct"] >= 10]
            
            target_rows = ""
            for t in tracked[:15]:
                color = "#16a34a" if t["hit_target"] else "#f59e0b" if t["gain_pct"] >= 10 else "#1e293b"
                status = "✅達標→移動停利" if t["hit_target"] else f'{t["gain_pct"]:+.1f}%'
                phase_str = ""
                # Find phase from accum_results
                for ar in bull_signals:
                    if ar.get("symbol") == t["symbol"]:
                        ph = ar.get("phase", 0)
                        phase_str = {1: "P1觀望", 2: "P2動能", 3: "P3突破"}.get(ph, "")
                        break
                target_rows += f'<tr><td style="padding:4px 8px;font-weight:700">{t["symbol"]}</td><td style="padding:4px 8px;text-align:center;font-size:11px">{t.get("entry_date","?")}</td><td style="padding:4px 8px;text-align:right">${t["entry_price"]}</td><td style="padding:4px 8px;text-align:right;font-weight:700;color:#16a34a">${t["target_15"]}</td><td style="padding:4px 8px;text-align:right">${t["current_price"]}</td><td style="padding:4px 8px;text-align:center;color:{color};font-weight:700;font-size:11px">{status}</td><td style="padding:4px 8px;text-align:center;font-size:11px">{phase_str}</td></tr>'
            
            parts.append(f"""
                <h3 style="font-size:14px;color:#f59e0b;margin:16px 0 6px">🎯 目標價追蹤（{len(hit)}/{len(tracked)} 已達 +15%）</h3>
                <p style="color:#64748b;font-size:11px;margin:0 0 8px">從首次出現訊號日計算 +15% 目標。P3突破 = 最佳進場點，達標後建議移動停利。</p>
                <table style="width:100%;border-collapse:collapse;font-size:12px">
                    <tr style="background:#fffbeb"><th style="padding:4px 8px;text-align:left">代號</th><th style="padding:4px 8px;text-align:center">訊號日</th><th style="padding:4px 8px;text-align:right">訊號價</th><th style="padding:4px 8px;text-align:right">+15%目標</th><th style="padding:4px 8px;text-align:right">現價</th><th style="padding:4px 8px;text-align:center">損益</th><th style="padding:4px 8px;text-align:center">階段</th></tr>
                    {target_rows}
                </table>""")
        
        if parts:
            signal_alert_html = '<div style="background:white;padding:16px 24px;border:1px solid #e2e8f0;border-top:none"><h2 style="font-size:16px;color:#1e293b;margin:0 0 12px">⚡ 交易訊號警報</h2>' + ''.join(parts) + '</div>'
    
    html_body = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:600px;margin:0 auto;background:#f8fafc">
        <div style="background:linear-gradient(135deg,#1e1b4b,#1e3a5f);padding:20px 24px;color:white;border-radius:12px 12px 0 0">
            <h1 style="margin:0;font-size:20px">💡 StockIQ 每日市場日報</h1>
            <p style="margin:4px 0 0;color:#818cf8;font-size:13px">{date_str} {day_name} · 板塊流動 + 金流密碼 + 市場速報</p>
        </div>
        
        <div style="background:white;padding:16px 24px;border:1px solid #e2e8f0">
            <div style="display:flex;justify-content:space-between;align-items:center;padding:12px 0;border-bottom:1px solid #f1f5f9">
                <span style="font-size:24px">{regime.split()[0]}</span>
                <div>
                    <strong style="color:{'#16a34a' if '牛' in regime else '#dc2626'}">{regime}</strong>
                    <span style="color:#64748b;font-size:12px;margin-left:12px">VIX {vix} · CNN {cnn} · 綜合 {composite}/100</span>
                </div>
            </div>
        </div>
        
        {sector_html}
        
        {movers_html}
        
        <div style="background:white;padding:16px 24px;border:1px solid #e2e8f0;border-top:none">
            <h2 style="font-size:16px;color:#16a34a;margin:0 0 12px">📈 吸籌偵測 Top 10（共 {len(bull_signals)} 支）</h2>
            <table style="width:100%;border-collapse:collapse;font-size:13px">
                <tr style="background:#f8fafc">
                    <th style="padding:8px 12px;text-align:left">代號</th>
                    <th style="padding:8px 12px">分數</th>
                    <th style="padding:8px 12px;text-align:left">訊號</th>
                    <th style="padding:8px 12px;text-align:right">價格</th>
                    <th style="padding:8px 12px;text-align:left">動態</th>
                    <th style="padding:8px 12px;text-align:left">建議</th>
                </tr>
                {bull_rows}
            </table>
        </div>
        
        {"<div style='background:white;padding:16px 24px;border:1px solid #e2e8f0;border-top:none'><h2 style='font-size:16px;color:#dc2626;margin:0 0 12px'>📉 出貨偵測 Top 5（共 " + str(len(bear_signals)) + " 支）</h2><table style='width:100%;border-collapse:collapse;font-size:13px'><tr style='background:#f8fafc'><th style='padding:8px 12px;text-align:left'>代號</th><th style='padding:8px 12px'>分數</th><th style='padding:8px 12px;text-align:left'>訊號</th><th style='padding:8px 12px;text-align:right'>價格</th></tr>" + bear_rows + "</table></div>" if bear_signals else ""}
        
        {signal_alert_html}
        
        {news_html}
        
        {alpha_html}
        
        <div style="background:#fefce8;padding:12px 24px;font-size:11px;color:#92400e;border:1px solid #e2e8f0;border-top:none;border-radius:0 0 12px 12px">
            ⚠️ 僅供參考，不構成投資建議。過去績效不代表未來表現。
            <br><a href="https://stockiq.tw" style="color:#4f46e5">stockiq.tw</a> · 
            <a href="https://stockiq.tw/?tab=smart" style="color:#4f46e5">查看完整金流密碼</a> ·
            <a href="https://stockiq.tw/daily/" style="color:#4f46e5">每日速報存檔</a>
        </div>
    </div>
    """
    
    payload = json.dumps({
        "from": "StockIQ 每日市場日報 <report@stockiq.tw>",
        "to": [TO_EMAIL],
        "subject": f"{regime} StockIQ 市場日報 {date_str} · 吸籌 {len(bull_signals)} 支 · 出貨 {len(bear_signals)} 支",
        "html": html_body,
    }).encode()
    
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={"Authorization": f"Bearer {RESEND_KEY}", "Content-Type": "application/json", "User-Agent": "StockIQ/5.2"}
    )
    r = urllib.request.urlopen(req, timeout=15)
    result = json.loads(r.read())
    print(f"  ✅ Email sent: {result.get('id', '?')}")


def run():
    tw = datetime.now(timezone.utc) + timedelta(hours=8)
    now_str = tw.strftime("%Y-%m-%dT%H:%M:%S+08:00")
    print(f"🔄 StockIQ Data Preloader — {tw.strftime('%Y/%m/%d %H:%M')} TW")


    # ── 0. Market Context ─────────────────────────────────────────────────
    print("\n🎯 Collecting market context...")
    market_ctx = collect_market_context()
    print(f"  VIX: {market_ctx.get('vix', '?')} ({market_ctx.get('vix_zone', '?')})")
    print(f"  CNN F&G: {market_ctx.get('cnn_fg_score', '?')} ({market_ctx.get('cnn_fg_rating', '?')})")
    print(f"  Composite: {market_ctx.get('composite_score', '?')}/100 ({market_ctx.get('composite_label', '?')})")
    save_market_context(market_ctx, tw.strftime("%Y-%m-%d"))

    # ── 1. Macro + sectors ────────────────────────────────────────────────────
    print("\n📊 Fetching macro + sector data...")
    macro_result = {
        "generated_at": now_str,
        "from_cache": False,
        "macro": [],
        "broad_sectors": [],
        "sub_sectors": {},
        "summary": {},
    }

    # Parallel fetch macro + sectors
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    def _fetch_macro(args):
        ticker, name, kind = args
        time.sleep(0.05)
        data = compute_52w(ticker)
        return ticker, name, kind, data
    
    all_macro_items = [(t, n, "macro") for t, n in MACRO_TICKERS] + [(e, n, "sector") for e, n in BROAD_SECTORS]
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        for ticker, name, kind, data in executor.map(_fetch_macro, all_macro_items):
            if data:
                if kind == "macro":
                    macro_result["macro"].append({"name": name, "ticker": ticker, **data})
                else:
                    macro_result["broad_sectors"].append({"name": name, "etf": ticker, **data})
                print(f"  {ticker} {data.get('perf_52w',0):+.1f}%")

    macro_result["broad_sectors"].sort(key=lambda x: x["perf_52w"], reverse=True)

    # Parallel sub-sector fetch
    all_sub_items = [(etf, name, group) for group, etfs in SUB_SECTORS.items() for etf, name in etfs]
    sub_results = defaultdict(list)
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        def _fetch_sub(args):
            etf, name, group = args
            time.sleep(0.05)
            data = compute_52w(etf)
            return etf, name, group, data
        for etf, name, group, data in executor.map(_fetch_sub, all_sub_items):
            if data:
                sub_results[group].append({"name": name, "etf": etf, **data, "wow": data.get("wow", [])[-4:]})
                print(f"  {etf} {data.get('perf_52w',0):+.1f}%")
    
    for group in sub_results:
        sub_results[group].sort(key=lambda x: x["perf_52w"], reverse=True)
        macro_result["sub_sectors"][group] = sub_results[group]

    top3 = macro_result["broad_sectors"][:3]
    bot3 = macro_result["broad_sectors"][-3:]
    macro_result["summary"] = {
        "top_inflow": [(s["name"], s["perf_52w"]) for s in top3],
        "top_outflow": [(s["name"], s["perf_52w"]) for s in bot3],
    }

    macro_json = json.dumps(macro_result, ensure_ascii=False, indent=2)
    sha = gh_put("data/macro.json", macro_json, f"Update macro.json {tw.strftime('%Y/%m/%d %H:%M')}")
    print(f"  ✅ data/macro.json → {sha}")

    # ── 1b. Generate daily_flows.json (consumed by index.html 板塊資金 widget) ──
    SECTOR_MCAP_B = {"XLK": 680, "XLF": 165, "XLV": 195, "XLE": 90, "XLI": 145, "XLY": 185,
                     "XLP": 85, "XLB": 45, "XLRE": 35, "XLU": 65, "XLC": 130}
    daily_flows_sectors = []
    for s in sorted(macro_result.get("broad_sectors", []), key=lambda x: x.get("change_1d", 0), reverse=True):
        etf = s.get("etf", "")
        chg = s.get("change_1d", 0)
        vol = s.get("volume_1d", 0)
        price = s.get("current", 0)
        avg_vol = s.get("avg_volume_5d", 0)
        vol_ratio = round(vol / avg_vol, 2) if avg_vol > 0 else 0
        mcap = SECTOR_MCAP_B.get(etf, 50)
        # dollar_flow_b = volume × price in billions × direction
        dollar_flow_raw = vol * price / 1e9
        direction = 1 if chg > 0.3 else -1 if chg < -0.3 else 0
        dollar_flow_b = round(dollar_flow_raw * (1 if chg > 0 else -1), 1) if chg != 0 else 0
        flow_label = "🟢 流入" if chg > 0.3 else "🔴 流出" if chg < -0.3 else "⚪ 持平"
        daily_flows_sectors.append({
            "etf": etf, "name": s.get("name", ""),
            "price": price, "daily_chg": chg,
            "vol_ratio": vol_ratio, "flow": flow_label,
            "mcap_b": mcap, "dollar_flow_b": dollar_flow_b,
        })
    total_in = round(sum(s["dollar_flow_b"] for s in daily_flows_sectors if s["dollar_flow_b"] > 0), 1)
    total_out = round(sum(s["dollar_flow_b"] for s in daily_flows_sectors if s["dollar_flow_b"] < 0), 1)
    daily_flows = {
        "date": tw.strftime("%Y-%m-%d"),
        "generated_at": tw.isoformat(),
        "sectors": daily_flows_sectors,
        "net_flow_b": round(total_in + total_out, 1),
        "total_in_b": total_in,
        "total_out_b": total_out,
    }
    df_sha = gh_put("data/daily_flows.json", json.dumps(daily_flows, ensure_ascii=False, indent=2),
                     f"Update daily_flows.json {tw.strftime('%Y/%m/%d %H:%M')}")
    print(f"  ✅ data/daily_flows.json → {df_sha}")

    # ── 2. Market movers ─────────────────────────────────────────────────────
    print("\n📈 Fetching market movers...")
    gainers = yf_screener("day_gainers", 10)
    losers = yf_screener("day_losers", 10)
    actives = yf_screener("most_actives", 25)
    print(f"  gainers: {len(gainers)}, losers: {len(losers)}, actives: {len(actives)}")

    strong_buy, strong_sell = [], []
    for q in actives:
        vol = q.get("regularMarketVolume", 0)
        avg = q.get("averageDailyVolume3Month") or 1
        pct = q.get("regularMarketChangePercent", 0)
        vr = round(vol / avg, 1)
        if vol / avg >= 1.5:
            if pct > 3:
                strong_buy.append({**q, "vr": vr})
            elif pct < -3:
                strong_sell.append({**q, "vr": vr})

    def fmt_stock(q):
        return {
            "symbol": q.get("symbol", ""),
            "name": q.get("shortName", q.get("symbol", "")),
            "price": round(q.get("regularMarketPrice", 0), 2),
            "change_pct": round(q.get("regularMarketChangePercent", 0), 2),
            "volume": q.get("regularMarketVolume", 0),
            "vr": q.get("vr", ""),
        }

    movers_data = {
        "generated_at": now_str,
        "gainers": [fmt_stock(q) for q in gainers[:10]],
        "losers": [fmt_stock(q) for q in losers[:10]],
        "most_active": [fmt_stock(q) for q in actives[:15]],
        "strong_buy": [fmt_stock(q) for q in strong_buy[:5]],
        "strong_sell": [fmt_stock(q) for q in strong_sell[:5]],
    }

    movers_json = json.dumps(movers_data, ensure_ascii=False, indent=2)
    sha = gh_put("data/market_movers.json", movers_json, f"Update market_movers.json {tw.strftime('%Y/%m/%d %H:%M')}")
    print(f"  ✅ data/market_movers.json → {sha}")

    # ── 3. Indices ────────────────────────────────────────────────────────────
    print("\n🌐 Fetching indices...")
    indices_data = {}
    for ticker, name in INDICES:
        result = yf_chart(ticker, "1d", "5d")
        if result:
            closes = [c for c in result.get("indicators", {}).get("quote", [{}])[0].get("close", []) if c]
            if len(closes) >= 2:
                pct = (closes[-1] - closes[-2]) / closes[-2] * 100
                indices_data[ticker] = {"name": name, "price": round(closes[-1], 2), "pct": round(pct, 2)}
                print(f"  {ticker}: {closes[-1]:.2f} ({pct:+.2f}%)")

    indices_json = json.dumps({"generated_at": now_str, "indices": indices_data}, ensure_ascii=False, indent=2)
    sha = gh_put("data/indices.json", indices_json, f"Update indices.json {tw.strftime('%Y/%m/%d %H:%M')}")
    print(f"  ✅ data/indices.json → {sha}")

    # ── 4. Accumulation scan ──────────────────────────────────────────────────
    print(f"\n🔍 Accumulation scan ({len(SCAN_TICKERS)} tickers)...")
    accum_results = []
    # Load market context for signal adjustment
    market_sentiment = market_ctx.get("composite_score", 50) if market_ctx else 50
    cnn_fg = market_ctx.get("cnn_fg_score", 50) if market_ctx else 50
    vix_val = market_ctx.get("vix", 16) if market_ctx else 16
    
    # Parallel scan using ThreadPoolExecutor (~15s vs ~120s sequential)
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    def _scan_one(ticker):
        time.sleep(0.05)
        bull = scan_accumulation(ticker, direction="bullish")
        bear = scan_accumulation(ticker, direction="bearish")
        return ticker, bull, bear
    
    bearish_results = []
    print(f"  Parallel scanning {len(SCAN_TICKERS)} tickers (8 threads)...")
    scan_start = time.time()
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_scan_one, t): t for t in SCAN_TICKERS}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                _, bull, bear = future.result(timeout=30)
                
                # Market context adjustment
                if bull:
                    if cnn_fg < 25 or vix_val > 25:
                        bull["score"] = min(10, bull["score"] + 1)
                        bull["signal"] = "🔥 強吸籌" if bull["score"] >= 7 else "📈 吸籌中"
                    elif cnn_fg > 75 and vix_val < 14:
                        bull["score"] = max(0, bull["score"] - 1)
                        if bull["score"] < 5: bull = None
                if bear:
                    if cnn_fg > 70 or vix_val < 14:
                        bear["score"] = min(10, bear["score"] + 1)
                        bear["signal"] = "🔻 強出貨" if bear["score"] >= 7 else "⚠️ 出貨中"
                    elif cnn_fg < 20:
                        bear["score"] = max(0, bear["score"] - 1)
                        if bear["score"] < 5: bear = None
                
                signals = []
                # Rule: if both trigger, higher score wins. Tie = bearish (conservative)
                if bull and bear:
                    if bear["score"] >= bull["score"]:
                        bear["direction"] = "bearish"
                        bearish_results.append(bear)
                        signals.append(f"bear={bear['score']}(wins)")
                    else:
                        bull["direction"] = "bullish"
                        accum_results.append(bull)
                        signals.append(f"bull={bull['score']}(wins)")
                elif bull:
                    bull["direction"] = "bullish"
                    accum_results.append(bull)
                    signals.append(f"bull={bull['score']}")
                elif bear:
                    bear["direction"] = "bearish"
                    bearish_results.append(bear)
                    signals.append(f"bear={bear['score']}")
                if signals:
                    print(f"  {ticker}... {' '.join(signals)}")
            except Exception as e:
                pass
    
    scan_elapsed = time.time() - scan_start
    print(f"  Scan completed in {scan_elapsed:.1f}s ({len(accum_results)} bull, {len(bearish_results)} bear)")

    # Query yesterday's signals for transition + momentum labels
    print("  Checking yesterday's signals for transitions...")
    try:
        from datetime import date as date_cls
        yesterday = (tw - timedelta(days=1)).strftime("%Y-%m-%d")
        # Also check 2 days ago for weekends
        two_days_ago = (tw - timedelta(days=2)).strftime("%Y-%m-%d")
        three_days_ago = (tw - timedelta(days=3)).strftime("%Y-%m-%d")
        
        prev_req = urllib.request.Request(
            f"{SUPABASE_URL}/rest/v1/accumulation_signals?date=in.({yesterday},{two_days_ago},{three_days_ago})&select=symbol,date,score,direction&order=date.desc",
            headers={**SB_HEADERS, "Accept": "application/json", "Prefer": ""}
        )
        prev_signals = json.loads(urllib.request.urlopen(prev_req, timeout=10).read())
        
        # Build lookup: most recent signal per symbol
        prev_by_sym = {}
        for ps in prev_signals:
            sym = ps["symbol"]
            if sym not in prev_by_sym:  # first = most recent
                prev_by_sym[sym] = ps
        
        print(f"  Found {len(prev_by_sym)} previous signals")
        
        # Apply transition + momentum labels
        for s in accum_results + bearish_results:
            sym = s["symbol"]
            prev = prev_by_sym.get(sym)
            
            if prev:
                prev_dir = prev["direction"]
                curr_dir = s["direction"]
                prev_score = prev["score"]
                curr_score = s["score"]
                
                # Transition label
                if prev_dir == "bearish" and curr_dir == "bullish":
                    s["transition"] = "⚡ 空翻多"
                elif prev_dir == "bullish" and curr_dir == "bearish":
                    s["transition"] = "⚡ 多翻空"
                elif prev_dir == curr_dir:
                    s["transition"] = "持續" + ("看多" if curr_dir == "bullish" else "看空")
                else:
                    s["transition"] = ""
                
                # Momentum change
                score_diff = curr_score - prev_score
                if score_diff >= 2:
                    s["momentum_change"] = "🔺 動能轉強"
                elif score_diff >= 1:
                    s["momentum_change"] = "▲ 動能略升"
                elif score_diff <= -2:
                    s["momentum_change"] = "🔻 動能轉弱"
                elif score_diff <= -1:
                    s["momentum_change"] = "▼ 動能略降"
                else:
                    s["momentum_change"] = "➡️ 動能持平"
                
                s["prev_score"] = prev_score
            else:
                s["transition"] = "🆕 新訊號"
                s["momentum_change"] = ""
                s["prev_score"] = None
    except Exception as e:
        print(f"  Transition check failed: {e}")

    # Sort: phase desc (3>2>1), then score desc — matches website rendering
    accum_results.sort(key=lambda x: (x.get("phase", 1), x["score"]), reverse=True)
    bearish_results.sort(key=lambda x: (x.get("phase", 1), x["score"]), reverse=True)

    # ── 4b. Query Supabase for historical consecutive days ────────────────────
    print("\n📅 Querying Supabase for consecutive day streaks...")
    streak_map = {}
    try:
        today_date = tw.strftime("%Y-%m-%d")
        symbols_str = ",".join(f'"{s["symbol"]}"' for s in accum_results)
        # Get last 30 days of signals for these symbols
        req_sb = urllib.request.Request(
            f"{SUPABASE_URL}/rest/v1/accumulation_signals"
            f"?symbol=in.({','.join(s['symbol'] for s in accum_results)})"
            f"&date=gte.{(tw - timedelta(days=30)).strftime('%Y-%m-%d')}"
            f"&order=symbol.asc,date.desc"
            f"&select=symbol,date,score",
            headers={**SB_HEADERS, "Accept": "application/json"}
        )
        r_sb = urllib.request.urlopen(req_sb, timeout=10)
        hist = json.loads(r_sb.read())
        # Build streak per symbol: count consecutive days from today backwards
        by_sym = defaultdict(list)
        for row in hist:
            by_sym[row["symbol"]].append(row["date"])
        for sym, dates in by_sym.items():
            dates.sort(reverse=True)
            streak = 0
            # Check today or yesterday (market might be closed today)
            from datetime import date as date_cls
            check_date = date_cls.fromisoformat(today_date)
            for d in dates:
                d_obj = date_cls.fromisoformat(d)
                diff = (check_date - d_obj).days
                if diff <= streak + 1:  # allow 1-day gap for weekends
                    streak += 1
                    check_date = d_obj
                else:
                    break
            streak_map[sym] = streak
        print(f"  Got streaks for {len(streak_map)} symbols")
    except Exception as e:
        print(f"  Supabase streak query failed: {e}")

    # Apply streaks from DB (more accurate than single-day calculation)
    for s in accum_results:
        if s["symbol"] in streak_map:
            s["consec_days"] = streak_map[s["symbol"]]

    # Include market context in output
    if market_ctx:
        for s in accum_results + bearish_results:
            s["market_sentiment"] = market_sentiment
            s["cnn_fg"] = cnn_fg
            s["vix"] = vix_val
    
    all_signals = accum_results + bearish_results
    # Save all signals (both directions) to Supabase
    rows_all = []
    for s in all_signals:
        rows_all.append({
            "date": today_date,
            "symbol": s["symbol"],
            "direction": s.get("direction", "bullish"),
            "score": s["score"],
            "score_max": s.get("score_max", 10),
            "score_vol": s.get("score_vol", 0),
            "score_comp": s.get("score_comp", 0),
            "score_pos": s.get("score_pos", 0),
            "score_obv": s.get("score_obv", 0),
            "score_mom": s.get("score_mom", 0),
            "signal": s.get("signal", ""),
            "price": s.get("price"),
            "change_1d": s.get("change_1d"),
            "change_1m": s.get("change_1m"),
            "vol_ratio": s.get("vol_ratio"),
            "price_range_pct": s.get("price_range_pct"),
            "range_position_pct": s.get("range_position_pct"),
            "consec_days": s.get("consec_days", 0),
            "change_3m": s.get("change_3m", 0),
        })

    accum_data = {
        "generated_at": now_str,
        "stocks": accum_results,
        "bearish": bearish_results,
        "total_scanned": len(SCAN_TICKERS),
        "scan_list": list(SCAN_TICKERS),
    }

    # ── 4c. Save to Supabase ─────────────────────────────────────────────────
    print("\n💾 Saving to Supabase...")
    today_date = tw.strftime("%Y-%m-%d")
    rows = []
    for s in accum_results:
        rows.append({
            "date": today_date,
            "symbol": s["symbol"],
            "direction": s.get("direction", "bullish"),
            "score": s["score"],
            "score_max": s.get("score_max", 10),
            "score_vol": s.get("score_vol", 0),
            "score_comp": s.get("score_comp", 0),
            "score_pos": s.get("score_pos", 0),
            "score_obv": s.get("score_obv", 0),
            "score_mom": s.get("score_mom", 0),
            "signal": s.get("signal", ""),
            "price": s.get("price"),
            "change_1d": s.get("change_1d"),
            "change_1m": s.get("change_1m"),
            "vol_ratio": s.get("vol_ratio"),
            "price_range_pct": s.get("price_range_pct"),
            "range_position_pct": s.get("range_position_pct"),
            "consec_days": s.get("consec_days", 0),
            "change_3m": s.get("change_3m", 0),
        })
    try:
        req_ins = urllib.request.Request(
            f"{SUPABASE_URL}/rest/v1/accumulation_signals?on_conflict=date,symbol,direction",
            data=json.dumps(rows).encode(),
            headers=SB_HEADERS,
            method="POST"
        )
        urllib.request.urlopen(req_ins, timeout=15)
        print(f"  ✅ Saved {len(rows)} rows to Supabase for {today_date}")
    except Exception as e:
        print(f"  ❌ Supabase save failed: {e}")

    # ── 4d. Signal change detection (vs yesterday) ─────────────────────────
    signal_changes = {"lost": [], "new": [], "targets": []}
    try:
        import requests as req_lib
        sb_h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        # Get yesterday's bullish signals
        r_prev = req_lib.get(f"{SUPABASE_URL}/rest/v1/accumulation_signals",
            headers=sb_h,
            params={"select": "symbol,score,price,phase,consec_days",
                    "direction": "eq.bullish", "date": f"lt.{today_date}",
                    "order": "date.desc", "limit": 200}, timeout=10)
        prev_data = r_prev.json()
        # Get the most recent previous date
        if prev_data:
            prev_date = None
            # Query for distinct previous date
            r_dates = req_lib.get(f"{SUPABASE_URL}/rest/v1/accumulation_signals",
                headers=sb_h,
                params={"select": "date", "date": f"lt.{today_date}",
                        "order": "date.desc", "limit": 1}, timeout=10)
            prev_dates = r_dates.json()
            if prev_dates:
                prev_date = prev_dates[0]["date"]
                r_prev2 = req_lib.get(f"{SUPABASE_URL}/rest/v1/accumulation_signals",
                    headers=sb_h,
                    params={"select": "symbol,score,price,phase,consec_days",
                            "direction": "eq.bullish", "date": f"eq.{prev_date}",
                            "order": "score.desc", "limit": 200}, timeout=10)
                prev_bulls = {d["symbol"]: d for d in r_prev2.json()}
                today_bulls = {s["symbol"]: s for s in accum_results}
                
                # Lost signals (yesterday bullish, today not)
                for sym, prev in prev_bulls.items():
                    if sym not in today_bulls:
                        signal_changes["lost"].append({
                            "symbol": sym,
                            "prev_score": prev["score"],
                            "prev_price": prev["price"],
                            "consec_days": prev.get("consec_days", 0),
                        })
                
                # New signals (today bullish, yesterday not)
                for sym, curr in today_bulls.items():
                    if sym not in prev_bulls:
                        signal_changes["new"].append({
                            "symbol": sym,
                            "score": curr["score"],
                            "price": curr.get("price"),
                        })
                
                print(f"  📊 Signal changes: {len(signal_changes['lost'])} lost, {len(signal_changes['new'])} new")
        
        # Calculate +15% targets: find streak start from Supabase history
        for s in accum_results:
            if s.get("score", 0) >= 6 and s.get("price"):
                try:
                    # Get all bullish history for this symbol, ordered by date
                    r_hist = req_lib.get(f"{SUPABASE_URL}/rest/v1/accumulation_signals",
                        headers=sb_h,
                        params={"select": "date,price",
                                "symbol": f"eq.{s['symbol']}", "direction": "eq.bullish",
                                "order": "date.desc", "limit": 60}, timeout=10)
                    hist = r_hist.json()
                    if not hist or len(hist) < 2:
                        continue
                    
                    # Count consecutive days from today backwards
                    streak_dates = sorted([h["date"] for h in hist], reverse=True)
                    consec = 1
                    for i in range(1, len(streak_dates)):
                        d1 = datetime.strptime(streak_dates[i-1], "%Y-%m-%d")
                        d2 = datetime.strptime(streak_dates[i], "%Y-%m-%d")
                        gap = (d1 - d2).days
                        if gap <= 3:  # Allow weekend gaps
                            consec += 1
                        else:
                            break
                    
                    if consec < 3:
                        continue  # Too new, skip
                    
                    # Entry = earliest date in current streak
                    entry_idx = min(consec, len(hist)) - 1
                    entry_date = hist[entry_idx]["date"]
                    entry_price = hist[entry_idx]["price"]
                    
                    if entry_price and entry_price > 0:
                        target_15 = round(entry_price * 1.15, 2)
                        current = s["price"]
                        gain_pct = round((current / entry_price - 1) * 100, 1)
                        signal_changes["targets"].append({
                            "symbol": s["symbol"],
                            "entry_date": entry_date,
                            "entry_price": round(entry_price, 2),
                            "current_price": current,
                            "target_15": target_15,
                            "gain_pct": gain_pct,
                            "score": s["score"],
                            "consec_days": consec,
                            "hit_target": current >= target_15,
                        })
                except Exception:
                    pass
        
        signal_changes["targets"].sort(key=lambda x: x.get("gain_pct", 0), reverse=True)
        hit_count = sum(1 for t in signal_changes["targets"] if t["hit_target"])
        print(f"  🎯 Targets: {len(signal_changes['targets'])} tracked, {hit_count} hit +15%")
    except Exception as e:
        print(f"  ⚠️  Signal change detection failed: {e}")
        import traceback; traceback.print_exc()
    
    # Store in accum_data for email
    accum_data["signal_changes"] = signal_changes

    # ── 4e. Save JSON to GitHub ───────────────────────────────────────────────
    accum_json = json.dumps(accum_data, ensure_ascii=False, indent=2)
    sha = gh_put("data/accumulation.json", accum_json, f"Update accumulation.json {tw.strftime('%Y/%m/%d %H:%M')}")
    print(f"  ✅ data/accumulation.json → {sha} ({len(accum_results)} signals found)")

    # ── 5. Earnings calendar (weekly, via Nasdaq API) ────────────────────────
    # Run every Sunday or if market_events.json is older than 6 days
    should_update_earnings = (tw.weekday() == 6)  # Sunday
    if not should_update_earnings:
        # Check if file exists and is fresh
        _, existing = gh_get("data/market_events.json")
        if existing:
            try:
                ex = json.loads(existing)
                age_days = (tw - datetime.fromisoformat(ex.get("generated_at","2000-01-01T00:00:00+08:00").replace("Z",""))).days
                should_update_earnings = age_days >= 6
            except:
                should_update_earnings = True
        else:
            should_update_earnings = True

    if should_update_earnings:
        print("\n📅 Fetching earnings calendar (Nasdaq API)...")
        events = []
        nasdaq_headers = {
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.nasdaq.com/",
        }
        # Watched symbols for earnings tracking
        WATCHED_SYMBOLS = {
            "NVDA","AAPL","MSFT","GOOGL","META","AMZN","TSLA","AMD","AVGO","PLTR",
            "MU","INTC","QCOM","ARM","SMCI","NFLX","ORCL","ADBE","CRM","NOW",
            "CRWD","PANW","SNOW","DDOG","NET","ZS",
        }
        # Fetch next 45 days of earnings from Nasdaq
        from datetime import date as date_cls
        today_d = tw.date()
        fetched_dates = set()
        for delta in range(0, 46, 1):
            check_d = today_d + timedelta(days=delta)
            if check_d.weekday() >= 5:  # skip weekends
                continue
            date_str = check_d.strftime("%Y-%m-%d")
            if date_str in fetched_dates:
                continue
            fetched_dates.add(date_str)
            try:
                time.sleep(0.3)
                url = f"https://api.nasdaq.com/api/calendar/earnings?date={date_str}"
                req_nasdaq = urllib.request.Request(url, headers=nasdaq_headers)
                r_nasdaq = urllib.request.urlopen(req_nasdaq, timeout=10)
                rows = json.loads(r_nasdaq.read()).get("data", {}).get("rows", [])
                for row in rows:
                    sym = row.get("symbol", "")
                    if sym in WATCHED_SYMBOLS:
                        timing = row.get("time", "")
                        note_time = "盤後" if "after" in timing else "盤前" if "pre" in timing else ""
                        events.append({
                            "sym": sym,
                            "date": date_str,
                            "type": "earnings",
                            "note": f"{sym} Q財報 {note_time}".strip(),
                            "eps_forecast": row.get("epsForecast", ""),
                            "market_cap": row.get("marketCap", ""),
                        })
            except Exception as e:
                print(f"  Nasdaq {date_str}: {e}")

        # Add static market events (holidays, FOMC, options expiry)
        STATIC_EVENTS = [
            {"sym": "📌", "date": "2026-07-04", "type": "event", "note": "美國獨立紀念日（休市）"},
            {"sym": "📌", "date": "2026-07-31", "type": "event", "note": "FOMC 利率決策"},
            {"sym": "📌", "date": "2026-09-05", "type": "event", "note": "勞動節（休市）"},
            {"sym": "📌", "date": "2026-09-18", "type": "event", "note": "FOMC 利率決策"},
            {"sym": "📌", "date": "2026-09-19", "type": "event", "note": "四巫日（指數期貨/期權結算）"},
            {"sym": "📌", "date": "2026-11-26", "type": "event", "note": "感恩節（休市）"},
            {"sym": "📌", "date": "2026-12-19", "type": "event", "note": "四巫日（指數期貨/期權結算）"},
            {"sym": "📌", "date": "2026-12-25", "type": "event", "note": "聖誕節（休市）"},
        ]
        # Filter static events to upcoming 90 days
        for ev in STATIC_EVENTS:
            ev_date = date_cls.fromisoformat(ev["date"])
            diff = (ev_date - today_d).days
            if -7 <= diff <= 90:
                events.append(ev)

        events.sort(key=lambda x: x["date"])
        events_data = {
            "generated_at": now_str,
            "events": events,
            "earnings_count": sum(1 for e in events if e["type"] == "earnings"),
        }
        events_json = json.dumps(events_data, ensure_ascii=False, indent=2)
        sha = gh_put("data/market_events.json", events_json, f"Update market_events.json {tw.strftime('%Y/%m/%d %H:%M')}")
        print(f"  ✅ data/market_events.json → {sha} ({len(events)} events, {events_data['earnings_count']} earnings)")
    else:
        print("\n📅 Earnings calendar: skipping (updated recently)")

    # ── 6. News headlines (always runs, including weekends) ───────────────────
    print("\n📰 Fetching market news...")
    news_items = []
    try:
        news_url = "https://query1.finance.yahoo.com/v1/finance/search?q=stock+market&newsCount=15&quotesCount=0"
        r_news = urllib.request.urlopen(urllib.request.Request(news_url, headers=YF_HEADERS), timeout=10)
        raw_news = json.loads(r_news.read()).get("news", [])
        for n in raw_news:
            news_items.append({
                "title": n.get("title", ""),
                "url": n.get("link", ""),
                "publisher": n.get("publisher", ""),
                "published": n.get("providerPublishTime", 0),
            })
        print(f"  {len(news_items)} news items")
    except Exception as e:
        print(f"  News fetch failed: {e}")

    news_data = {"generated_at": now_str, "news": news_items}
    if news_items:
        news_json = json.dumps(news_data, ensure_ascii=False, indent=2)
        sha = gh_put("data/news.json", news_json, f"Update news.json {tw.strftime('%Y/%m/%d %H:%M')}")
        print(f"  ✅ data/news.json → {sha}")

    # ── 6b. Alpha framework scan ──────────────────────────────────────────
    print("\n🔬 Fetching alpha framework data (EPS + Options + Positioning)...")
    try:
        alpha_data = fetch_alpha_data(SCAN_TICKERS)
        
        # Rank by expected return
        ranked = sorted(alpha_data.values(), key=lambda x: x.get("expected_return", 0), reverse=True)
        
        # Classification summary
        from collections import Counter
        class_counts = Counter(d.get("classification", "?") for d in alpha_data.values())
        print(f"  分類: 加碼={class_counts.get('type4_accumulate',0)} 持有={class_counts.get('type3_hold',0)} "
              f"減碼={class_counts.get('type2_reduce',0)} 清倉={class_counts.get('type1_exit',0)}")
        top5 = ', '.join(d["symbol"] + "(" + format(d["expected_return"], "+.1f") + ")" for d in ranked[:5])
        print(f"  Top 5 Expected Return: {top5}")
        
        alpha_output = {
            "generated_at": now_str,
            "count": len(alpha_data),
            "classification_summary": dict(class_counts),
            "top_expected_return": [d for d in ranked[:20]],
            "bottom_expected_return": [d for d in ranked[-10:]],
            "stocks": {sym: data for sym, data in alpha_data.items()},
        }
        alpha_json = json.dumps(alpha_output, ensure_ascii=False, indent=2)
        sha = gh_put("data/alpha.json", alpha_json, f"Update alpha.json {tw.strftime('%Y/%m/%d %H:%M')}")
        print(f"  ✅ data/alpha.json → {sha}")
    except Exception as e:
        print(f"  ⚠️  Alpha scan failed: {e}")
        import traceback; traceback.print_exc()

    # ── Batch commit all queued files ──────────────────────────────────────
    print("\n📦 Pushing all data files in single commit...")
    result = gh_batch_commit(f"📊 Daily data update {tw.strftime('%Y/%m/%d %H:%M')}")
    if result:
        sha, count = result
        print(f"  ✅ Single commit: {sha} ({count} files)")

    # ── 7. Send daily email ─────────────────────────────────────────────────
    print("\n📧 Sending daily email...")
    try:
        send_daily_email(tw, accum_results, bearish_results, market_ctx,
                         news_items if 'news_items' in dir() else [],
                         movers_data if 'movers_data' in dir() else None,
                         macro_result if 'macro_result' in dir() else None,
                         alpha_data if 'alpha_data' in dir() else None,
                         signal_changes if 'signal_changes' in dir() else None)
    except Exception as e:
        print(f"  ❌ Email failed: {e}")

    print(f"\n✅ All data files updated — {tw.strftime('%Y/%m/%d %H:%M')} TW")
    return True

if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)
