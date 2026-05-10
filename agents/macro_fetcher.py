"""
macro_fetcher.py - Macroeconomic & Sector Flow Data
Includes: 52W performance + weekly momentum (week-over-week flow analysis)
"""
import requests
from datetime import datetime


SECTORS = [
    ("XLK", "科技 Tech"), ("XLF", "金融 Finance"), ("XLE", "能源 Energy"),
    ("XLV", "醫療 Health"), ("XLI", "工業 Industrial"), ("XLB", "原材料 Materials"),
    ("XLU", "公用事業 Utilities"), ("XLRE", "房地產 RE"), ("XLY", "非必需消費 Cyclical"),
    ("XLP", "必需消費 Staples"), ("XLC", "通訊 Comm"), ("ARKK", "創新成長 Innovation"),
]

MACRO = [
    ("^TNX", "10年債殖利率"),
    ("DX-Y.NYB", "美元指數 DXY"),
    ("GC=F", "黃金 Gold"),
    ("CL=F", "原油WTI"),
    ("^VIX", "VIX 恐慌指數"),
    ("^GSPC", "S&P 500"),
    ("^IXIC", "NASDAQ"),
]


def fetch_weekly_data(ticker: str, weeks: int = 12) -> list:
    """Fetch weekly close prices. Returns list of (date_str, price) tuples."""
    try:
        resp = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
            headers={"User-Agent": "Mozilla/5.0"},
            params={"interval": "1wk", "range": f"{weeks}wk"},
            timeout=8
        )
        if resp.status_code == 200:
            result = resp.json().get("chart", {}).get("result", [{}])[0]
            timestamps = result.get("timestamp", [])
            closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
            pairs = [(t, c) for t, c in zip(timestamps, closes) if c is not None]
            return [(datetime.fromtimestamp(t).strftime("%m/%d"), c) for t, c in pairs]
    except Exception:
        pass
    return []


def compute_momentum(weekly_data: list) -> dict:
    """Compute WoW changes and momentum trend."""
    if len(weekly_data) < 3:
        return {}
    
    # Week-over-week changes
    wow_changes = []
    for i in range(1, len(weekly_data)):
        date, curr = weekly_data[i]
        _, prev = weekly_data[i-1]
        wow = (curr - prev) / prev * 100 if prev != 0 else 0
        wow_changes.append((date, curr, round(wow, 1)))
    
    # Recent 4W vs Prior 4W momentum comparison
    recent4 = [c for _, c, _ in wow_changes[-4:]] if len(wow_changes) >= 4 else []
    prior4 = [c for _, c, _ in wow_changes[-8:-4]] if len(wow_changes) >= 8 else []
    
    momentum_signal = "N/A"
    if recent4 and prior4 and len(weekly_data) >= 2:
        r_start = weekly_data[-5][1] if len(weekly_data) >= 5 else weekly_data[0][1]
        r_end = weekly_data[-1][1]
        p_start = weekly_data[-9][1] if len(weekly_data) >= 9 else weekly_data[0][1]
        p_end = weekly_data[-5][1] if len(weekly_data) >= 5 else weekly_data[-1][1]
        
        recent_gain = (r_end - r_start) / r_start * 100 if r_start else 0
        prior_gain = (p_end - p_start) / p_start * 100 if p_start else 0
        
        # Determine trend direction (same sign = both up or both down)
        if abs(recent_gain) > abs(prior_gain) * 1.2:
            momentum_signal = "📈 加速" if recent_gain > 0 else "📉 加速下跌"
        elif abs(recent_gain) < abs(prior_gain) * 0.8:
            momentum_signal = "📉 趨緩" if recent_gain > 0 else "📈 跌勢趨緩"
        else:
            momentum_signal = "➡️ 穩定"
        
        return {
            "wow_changes": wow_changes[-8:],  # Last 8 weeks
            "recent_4w_gain": round(recent_gain, 1),
            "prior_4w_gain": round(prior_gain, 1),
            "momentum": momentum_signal,
        }
    
    return {"wow_changes": wow_changes[-8:]}


def fetch_macro_overview() -> dict:
    """Fetch complete macro + sector data with weekly momentum."""
    result = {
        "generated_at": datetime.now().isoformat(),
        "macro": [],
        "sectors": [],
        "summary": {},
    }
    
    # === MACRO INDICATORS ===
    for ticker, name in MACRO:
        weekly = fetch_weekly_data(ticker, 52)
        if not weekly:
            continue
        start_price = weekly[0][1]
        end_price = weekly[-1][1]
        perf_52w = (end_price - start_price) / start_price * 100 if start_price else 0
        mom = compute_momentum(weekly)
        
        # Interpretation
        interp = ""
        if ticker == "^TNX":
            interp = "高利率壓估值" if end_price > 4.5 else "利率中性" if end_price > 3.5 else "低利率利成長"
        elif ticker == "DX-Y.NYB":
            interp = "強美元" if end_price > 104 else "弱美元利新興" if end_price < 98 else "美元中性"
        elif ticker == "^VIX":
            interp = "極度恐慌" if end_price > 30 else "偏恐慌" if end_price > 20 else "市場平靜"
        
        result["macro"].append({
            "name": name, "ticker": ticker,
            "current": round(end_price, 2),
            "perf_52w": round(perf_52w, 1),
            "momentum": mom.get("momentum", "N/A"),
            "interpretation": interp,
            "weekly_detail": mom.get("wow_changes", []),
        })
    
    # === SECTOR DATA ===
    for etf, name in SECTORS:
        weekly = fetch_weekly_data(etf, 52)
        if not weekly:
            continue
        start_price = weekly[0][1]
        end_price = weekly[-1][1]
        perf_52w = (end_price - start_price) / start_price * 100 if start_price else 0
        mom = compute_momentum(weekly)
        
        flow = "🟢 流入" if perf_52w > 10 else "🔴 流出" if perf_52w < -10 else "⚪ 中性"
        
        result["sectors"].append({
            "name": name, "etf": etf,
            "current": round(end_price, 2),
            "perf_52w": round(perf_52w, 1),
            "flow": flow,
            "momentum": mom.get("momentum", "N/A"),
            "recent_4w": mom.get("recent_4w_gain"),
            "prior_4w": mom.get("prior_4w_gain"),
            "weekly_detail": mom.get("wow_changes", []),  # [(date, price, wow_pct), ...]
        })
    
    # Sort sectors by 52W performance
    result["sectors"].sort(key=lambda x: x["perf_52w"], reverse=True)
    
    # Summary
    top3 = result["sectors"][:3]
    bot3 = result["sectors"][-3:]
    result["summary"] = {
        "top_inflow": [(s["name"], s["perf_52w"]) for s in top3],
        "top_outflow": [(s["name"], s["perf_52w"]) for s in bot3],
    }
    
    return result


if __name__ == "__main__":
    data = fetch_macro_overview()
    print("Macro indicators:", len(data["macro"]))
    print("Sectors:", len(data["sectors"]))
    for s in data["sectors"][:3]:
        print(f"  {s['name']}: {s['perf_52w']:+.1f}% | momentum={s['momentum']}")
        for date, price, wow in (s["weekly_detail"] or [])[-4:]:
            print(f"    {date}: ${price:.2f} WoW={wow:+.1f}%")
