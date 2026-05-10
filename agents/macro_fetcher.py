"""
macro_fetcher.py - Macroeconomic & Sector/Sub-Sector Flow Data
Includes: macro indicators + broad sectors + sub-sectors (more granular)
Cache: results stored 15 min to reduce API calls
"""
import requests
import json
import os
import time
from datetime import datetime

# === CACHE ===
_cache = {}
_cache_ttl = 900  # 15 minutes

def _get_cached(key):
    if key in _cache:
        ts, val = _cache[key]
        if time.time() - ts < _cache_ttl:
            return val
    return None

def _set_cached(key, val):
    _cache[key] = (time.time(), val)

# === SECTORS ===
BROAD_SECTORS = [
    ("XLK", "科技 Tech"), ("XLF", "金融 Finance"), ("XLE", "能源 Energy"),
    ("XLV", "醫療 Health"), ("XLI", "工業 Industrial"), ("XLB", "原材料 Materials"),
    ("XLU", "公用事業 Utilities"), ("XLRE", "房地產 RE"), ("XLY", "非必需消費 Cyclical"),
    ("XLP", "必需消費 Staples"), ("XLC", "通訊 Comm"),
]

# Granular sub-sectors grouped by parent
SUB_SECTORS = {
    "科技": [
        ("SOXX", "半導體"), ("SMH", "半導體設備"), ("BOTZ", "機器人/AI"),
        ("AIQ", "AI廣泛"), ("WCLD", "雲端"), ("IGV", "軟體"),
    ],
    "國防/太空": [
        ("ITA", "國防"), ("UFO", "太空"),
    ],
    "醫療": [
        ("IBB", "生技"), ("XPH", "製藥"),
    ],
    "金融": [
        ("KBE", "銀行"), ("KRE", "區域銀行"),
    ],
    "能源": [
        ("ICLN", "清潔能源"), ("UNG", "天然氣"),
    ],
    "消費": [
        ("XRT", "零售"), ("ARKK", "創新成長"),
    ],
    "商品": [
        ("GLD", "黃金"), ("SLV", "白銀"), ("PDBC", "大宗商品"),
    ],
}

MACRO = [
    ("^TNX", "10年債殖利率"),
    ("DX-Y.NYB", "美元指數 DXY"),
    ("GC=F", "黃金 Gold"),
    ("CL=F", "原油WTI"),
    ("^VIX", "VIX 恐慌指數"),
    ("^GSPC", "S&P 500"),
    ("^IXIC", "NASDAQ"),
]

# Ticker → sector mapping for individual stock context
TICKER_SECTOR_MAP = {
    # Semiconductors
    "NVDA": "科技/半導體", "AMD": "科技/半導體", "INTC": "科技/半導體",
    "MU": "科技/半導體", "SNDK": "科技/半導體", "QCOM": "科技/半導體",
    "AVGO": "科技/半導體", "TSM": "科技/半導體", "AMAT": "科技/半導體",
    "LRCX": "科技/半導體設備", "KLAC": "科技/半導體設備", "ASML": "科技/半導體設備",
    "TER": "科技/半導體設備",
    # Software/Cloud
    "MSFT": "科技/軟體", "GOOGL": "科技/軟體", "META": "科技/軟體",
    "AAPL": "科技/軟體硬體", "CRM": "科技/軟體",
    # AI
    "ANET": "科技/AI基礎設施",
    "AAOI": "科技/半導體設備",  # Applied Optoelectronics - fiber optics for AI data centers
    "LITE": "科技/半導體",
    # Defense/Space
    "RDW": "國防/太空", "LMT": "國防/太空", "RTX": "國防/太空",
    # EV/Auto
    "TSLA": "消費/電動車",
    # Healthcare
    "NVTS": "科技/半導體",
    # Others
    "VST": "能源/電力", "USAR": "原材料/稀土",
}


def fetch_52w_perf(ticker: str) -> dict:
    """Fetch 52W performance with 15-min cache."""
    cache_key = f"52w_{ticker}"
    cached = _get_cached(cache_key)
    if cached:
        return cached
    
    try:
        resp = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
            headers={"User-Agent": "Mozilla/5.0"},
            params={"interval": "1wk", "range": "52wk"},
            timeout=8
        )
        if resp.status_code == 200:
            result = resp.json().get("chart",{}).get("result",[{}])[0]
            meta = result.get("meta",{})
            closes = [c for c in result.get("indicators",{}).get("quote",[{}])[0].get("close",[]) if c]
            if closes and len(closes) > 1:
                perf_52w = (closes[-1] - closes[0]) / closes[0] * 100
                weekly_raw = closes
                # Week-over-week changes (last 8 weeks)
                timestamps = result.get("timestamp",[])
                wow = []
                for i in range(max(1, len(closes)-8), len(closes)):
                    if i > 0 and closes[i-1]:
                        w = (closes[i]-closes[i-1])/closes[i-1]*100
                        dt = datetime.fromtimestamp(timestamps[i]).strftime("%m/%d") if i < len(timestamps) else ""
                        wow.append((dt, round(closes[i],2), round(w,1)))
                
                # Momentum: recent 4W vs prior 4W
                recent4 = closes[-5:-1] if len(closes) >= 5 else closes
                prior4 = closes[-9:-5] if len(closes) >= 9 else []
                momentum = "N/A"
                if recent4 and prior4 and prior4[0]:
                    rg = (recent4[-1]-recent4[0])/recent4[0]*100
                    pg = (prior4[-1]-prior4[0])/prior4[0]*100
                    if abs(rg) > abs(pg)*1.2: momentum = "📈 加速" if rg>0 else "📉 加速下跌"
                    elif abs(rg) < abs(pg)*0.8: momentum = "📉 趨緩" if rg>0 else "📈 跌勢趨緩"
                    else: momentum = "➡️ 穩定"
                
                data = {
                    "current": round(closes[-1],2),
                    "perf_52w": round(perf_52w,1),
                    "flow": "🟢流入" if perf_52w>10 else "🔴流出" if perf_52w<-10 else "⚪中性",
                    "momentum": momentum,
                    "wow": wow[-8:],
                }
                _set_cached(cache_key, data)
                return data
    except Exception:
        pass
    return {}


def get_ticker_sector_context(ticker: str) -> dict:
    """Get sector context for a specific stock ticker."""
    ticker = ticker.upper().split(".")[0]
    sector = TICKER_SECTOR_MAP.get(ticker, None)
    
    if not sector:
        return {"sector": "未知", "sector_perf": None, "sub_sector": None, "sub_perf": None}
    
    parts = sector.split("/")
    broad = parts[0]
    sub = parts[1] if len(parts) > 1 else None
    
    # Find ETF for broad sector
    broad_etf_map = {
        "科技": "XLK", "金融": "XLF", "能源": "XLE", "醫療": "XLV",
        "工業": "XLI", "原材料": "XLB", "消費": "XLY", "國防": "ITA",
    }
    
    # Find ETF for sub-sector
    sub_etf_map = {
        "半導體": "SOXX", "半導體設備": "SMH", "AI基礎設施": "BOTZ",
        "軟體": "IGV", "雲端": "WCLD", "電動車": "TSLA",
        "太空": "UFO", "稀土": "USAR", "電力": "XLU",
        "軟體硬體": "XLK",
    }
    
    broad_etf = broad_etf_map.get(broad)
    sub_etf = sub_etf_map.get(sub) if sub else None
    
    broad_data = fetch_52w_perf(broad_etf) if broad_etf else {}
    sub_data = fetch_52w_perf(sub_etf) if sub_etf else {}
    
    return {
        "ticker": ticker,
        "sector": sector,
        "broad_sector": broad,
        "sub_sector": sub,
        "broad_etf": broad_etf,
        "sub_etf": sub_etf,
        "broad_perf_52w": broad_data.get("perf_52w"),
        "broad_flow": broad_data.get("flow"),
        "sub_perf_52w": sub_data.get("perf_52w"),
        "sub_flow": sub_data.get("flow"),
        "sub_momentum": sub_data.get("momentum"),
        "sub_wow": sub_data.get("wow", []),
    }


def fetch_macro_overview() -> dict:
    """Fetch complete macro + sector + sub-sector data. Results are cached."""
    cache_key = "full_macro"
    cached = _get_cached(cache_key)
    if cached:
        cached["from_cache"] = True
        return cached
    
    result = {
        "generated_at": datetime.now().isoformat(),
        "from_cache": False,
        "macro": [],
        "broad_sectors": [],
        "sub_sectors": {},
        "summary": {},
    }
    
    # Macro
    for ticker, name in MACRO:
        data = fetch_52w_perf(ticker)
        if data:
            result["macro"].append({
                "name": name, "ticker": ticker,
                "current": data["current"],
                "perf_52w": data["perf_52w"],
                "momentum": data.get("momentum","N/A"),
                "wow": data.get("wow",[]),
            })
    
    # Broad sectors
    for etf, name in BROAD_SECTORS:
        data = fetch_52w_perf(etf)
        if data:
            result["broad_sectors"].append({
                "name": name, "etf": etf,
                "current": data["current"],
                "perf_52w": data["perf_52w"],
                "flow": data["flow"],
                "momentum": data.get("momentum","N/A"),
                "wow": data.get("wow",[]),
            })
    result["broad_sectors"].sort(key=lambda x: x["perf_52w"], reverse=True)
    
    # Sub-sectors
    for group, etfs in SUB_SECTORS.items():
        group_data = []
        for etf, name in etfs:
            data = fetch_52w_perf(etf)
            if data:
                group_data.append({
                    "name": name, "etf": etf,
                    "current": data["current"],
                    "perf_52w": data["perf_52w"],
                    "flow": data["flow"],
                    "momentum": data.get("momentum","N/A"),
                    "wow": data.get("wow",[])[-4:],
                })
        group_data.sort(key=lambda x: x["perf_52w"], reverse=True)
        result["sub_sectors"][group] = group_data
    
    # Summary
    top3 = result["broad_sectors"][:3]
    bot3 = result["broad_sectors"][-3:]
    result["summary"] = {
        "top_inflow": [(s["name"], s["perf_52w"]) for s in top3],
        "top_outflow": [(s["name"], s["perf_52w"]) for s in bot3],
    }
    
    _set_cached(cache_key, result)
    return result
