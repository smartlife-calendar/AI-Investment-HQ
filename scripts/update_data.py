#!/usr/bin/env python3
"""
StockIQ Data Preloader v1.1
Fetches: sector/macro data + market movers + accumulation scan + earnings calendar
Saves to data/ directory on GitHub → frontend loads instantly without waiting for Railway API

Run: python3 scripts/update_data.py
"""
import urllib.request, json, base64, time, sys, os
from datetime import datetime, timezone, timedelta

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
    sha, _ = gh_get(path, branch)
    payload = {"message": msg, "content": base64.b64encode(content_str.encode()).decode(), "branch": branch}
    if sha:
        payload["sha"] = sha
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/contents/{path}",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github.v3+json", "Content-Type": "application/json"},
        method="PUT"
    )
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=15).read())
        return r.get("commit", {}).get("sha", "")[:12]
    except Exception as e:
        print(f"  gh_put {path} failed: {e}")
        return None

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
    return {
        "current": round(closes[-1], 2),
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
    # Semis
    "ON","WOLF","SWKS","MCHP","STM","ASML","TER","ARM","SMCI","BTDR",
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

        # ── BULLISH v5: Momentum + Breakout ──────────────────────────────
        if direction == "bullish":
            # 1. Momentum confirmed (0-3): in upper range + above MA20
            mom_score = 0
            if range_pos > 60: mom_score += 2
            elif range_pos > 40: mom_score += 1
            if current > (ma20 or current * 0.99): mom_score += 1

            # 2. Volume expansion (0-2)
            vol_score = 2 if vol_ratio > 1.4 else 1 if vol_ratio > 1.1 else 0

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
            t2 = round(price_max * 1.01, 2)
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

    for ticker, name in MACRO_TICKERS:
        print(f"  {ticker}...", end=" ", flush=True)
        data = compute_52w(ticker)
        if data:
            macro_result["macro"].append({"name": name, "ticker": ticker, **data})
            print(f"{data['current']} ({data['perf_52w']:+.1f}%)")
        else:
            print("failed")

    for etf, name in BROAD_SECTORS:
        print(f"  {etf}...", end=" ", flush=True)
        data = compute_52w(etf)
        if data:
            macro_result["broad_sectors"].append({"name": name, "etf": etf, **data})
            print(f"{data['perf_52w']:+.1f}%")
        else:
            print("failed")

    macro_result["broad_sectors"].sort(key=lambda x: x["perf_52w"], reverse=True)

    for group, etfs in SUB_SECTORS.items():
        group_data = []
        for etf, name in etfs:
            print(f"  {etf}...", end=" ", flush=True)
            data = compute_52w(etf)
            if data:
                group_data.append({"name": name, "etf": etf, **data, "wow": data.get("wow", [])[-4:]})
                print(f"{data['perf_52w']:+.1f}%")
            else:
                print("failed")
        group_data.sort(key=lambda x: x["perf_52w"], reverse=True)
        macro_result["sub_sectors"][group] = group_data

    top3 = macro_result["broad_sectors"][:3]
    bot3 = macro_result["broad_sectors"][-3:]
    macro_result["summary"] = {
        "top_inflow": [(s["name"], s["perf_52w"]) for s in top3],
        "top_outflow": [(s["name"], s["perf_52w"]) for s in bot3],
    }

    macro_json = json.dumps(macro_result, ensure_ascii=False, indent=2)
    sha = gh_put("data/macro.json", macro_json, f"Update macro.json {tw.strftime('%Y/%m/%d %H:%M')}")
    print(f"  ✅ data/macro.json → {sha}")

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
                if bull:
                    bull["direction"] = "bullish"
                    accum_results.append(bull)
                    signals.append(f"bull={bull['score']}")
                if bear:
                    bear["direction"] = "bearish"
                    bearish_results.append(bear)
                    signals.append(f"bear={bear['score']}")
                if signals:
                    print(f"  {ticker}... {' '.join(signals)}")
            except Exception as e:
                pass
    
    scan_elapsed = time.time() - scan_start
    print(f"  Scan completed in {scan_elapsed:.1f}s ({len(accum_results)} bull, {len(bearish_results)} bear)")

    accum_results.sort(key=lambda x: x["score"], reverse=True)
    bearish_results.sort(key=lambda x: x["score"], reverse=True)

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
        from collections import defaultdict
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

    # ── 4d. Save JSON to GitHub ───────────────────────────────────────────────
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

    print(f"\n✅ All data files updated — {tw.strftime('%Y/%m/%d %H:%M')} TW")
    return True

if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)
