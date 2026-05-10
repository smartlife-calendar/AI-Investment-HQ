"""
macro_fetcher.py - Macroeconomic & Sector Flow Data
Free: Yahoo Finance Chart API v8 (52-week performance)
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
    ("^TNX", "10年債殖利率", "%"),
    ("^IRX", "3月債殖利率", "%"),
    ("DX-Y.NYB", "美元指數 DXY", ""),
    ("GC=F", "黃金 Gold", "$"),
    ("CL=F", "原油WTI", "$"),
    ("^VIX", "VIX 恐慌指數", ""),
    ("^GSPC", "S&P 500", ""),
    ("^IXIC", "NASDAQ", ""),
]


def fetch_52w_data(ticker: str) -> dict:
    """Fetch 52-week price data for a ticker."""
    try:
        resp = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
            headers={"User-Agent": "Mozilla/5.0"},
            params={"interval": "1wk", "range": "52wk"},
            timeout=8
        )
        if resp.status_code == 200:
            result = resp.json().get("chart", {}).get("result", [{}])[0]
            meta = result.get("meta", {})
            closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
            current = meta.get("regularMarketPrice")
            if closes and current:
                start = next((c for c in closes if c is not None), None)
                if start and start > 0:
                    perf = (current - start) / start * 100
                    return {"current": current, "perf_52w": round(perf, 1)}
    except Exception:
        pass
    return {}


def fetch_macro_overview() -> str:
    """Fetch complete macro + sector overview. Returns formatted markdown string."""
    lines = [f"## 🌍 總體經濟 & 板塊資金流動", f"*截至 {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC*", ""]
    
    # === MACRO INDICATORS ===
    lines.append("### 📊 宏觀指標（近52週）")
    lines.append("| 指標 | 當前 | 52週變化 | 解讀 |")
    lines.append("|---|---|---|---|")
    
    for ticker, name, prefix in MACRO:
        d = fetch_52w_data(ticker)
        if not d:
            lines.append(f"| {name} | N/A | N/A | — |")
            continue
        
        current = d.get("current", 0)
        perf = d.get("perf_52w", 0)
        direction = "📈" if perf > 0 else "📉"
        
        # Interpretation
        interp = ""
        if ticker == "^TNX":
            interp = "高利率壓估值" if current > 4.5 else "利率中性" if current > 3.5 else "低利率利成長"
            prefix = ""
            current_fmt = f"{current:.2f}%"
        elif ticker == "^IRX":
            current_fmt = f"{current:.2f}%"
            prefix = ""
            interp = "短端利率"
        elif ticker == "DX-Y.NYB":
            interp = "強美元" if current > 104 else "弱美元利新興" if current < 98 else "美元中性"
            current_fmt = f"{current:.2f}"
        elif ticker == "^VIX":
            interp = "極度恐慌" if current > 30 else "偏恐慌" if current > 20 else "市場平靜"
            current_fmt = f"{current:.1f}"
        else:
            current_fmt = f"{prefix}{current:,.0f}" if current > 100 else f"{prefix}{current:.2f}"
            interp = ""
        
        perf_str = f"{'+' if perf>=0 else ''}{perf:.1f}%"
        lines.append(f"| {name} | {current_fmt} | {direction} {perf_str} | {interp} |")
    
    lines.append("")
    
    # === SECTOR FLOW (52-week performance as proxy for capital flow) ===
    lines.append("### 🔄 板塊資金流動（近52週ETF表現）")
    
    sector_data = []
    for etf, name in SECTORS:
        d = fetch_52w_data(etf)
        if d:
            sector_data.append((name, etf, d.get("current"), d.get("perf_52w", 0)))
    
    # Sort by 52w performance (descending = capital flowing in)
    sector_data.sort(key=lambda x: x[3], reverse=True)
    
    lines.append("| 板塊 | ETF | 當前 | 52週 | 資金趨勢 |")
    lines.append("|---|---|---|---|---|")
    
    for name, etf, price, perf in sector_data:
        direction = "🟢 流入" if perf > 10 else "🔴 流出" if perf < -10 else "⚪ 中性"
        perf_str = f"{'+' if perf>=0 else ''}{perf:.1f}%"
        price_str = f"${price:.2f}" if price else "N/A"
        lines.append(f"| {name} | {etf} | {price_str} | {perf_str} | {direction} |")
    
    # Summary
    top3 = sector_data[:3]
    bot3 = sector_data[-3:]
    lines.append("")
    lines.append("**資金流入前3名：** " + " | ".join(f"{n}({p:+.1f}%)" for n,e,c,p in top3))
    lines.append("**資金流出前3名：** " + " | ".join(f"{n}({p:+.1f}%)" for n,e,c,p in bot3))
    
    return "\n".join(lines)


if __name__ == "__main__":
    print(fetch_macro_overview())
