import requests
from datetime import datetime


def fetch_market_context() -> str:
    """
    Fetch real-time market context factors for timing assessment.
    All free, no API key required.
    """
    context_lines = ["## Market Context (Real-Time)\n"]
    headers = {"User-Agent": "Mozilla/5.0"}

    # 1. VIX (Fear Index)
    try:
        url = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/%5EVIX"
        params = {"modules": "price"}
        resp = requests.get(url, headers=headers, params=params, timeout=8)
        if resp.status_code == 200:
            price = resp.json()["quoteSummary"]["result"][0]["price"]
            vix = price.get("regularMarketPrice", {}).get("raw") or "N/A"
            vix_change = price.get("regularMarketChangePercent", {}).get("fmt", "N/A")
            level = "極度恐慌 (買入機會)" if isinstance(vix, (int, float)) and vix > 30 else \
                    "恐慌" if isinstance(vix, (int, float)) and vix > 20 else "低恐慌 (謹慎)"
            context_lines.append("### VIX 恐慌指數")
            context_lines.append("- 當前值: " + str(vix) + " (" + str(vix_change) + ")")
            context_lines.append("- 解讀: " + level)
            context_lines.append("")
    except Exception as e:
        context_lines.append("### VIX: 無法取得 (" + str(e) + ")\n")

    # 2. 10-Year Treasury Yield
    try:
        url = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/%5ETNX"
        params = {"modules": "price"}
        resp = requests.get(url, headers=headers, params=params, timeout=8)
        if resp.status_code == 200:
            price = resp.json()["quoteSummary"]["result"][0]["price"]
            tnx = price.get("regularMarketPrice", {}).get("raw", "N/A")
            tnx_change = price.get("regularMarketChange", {}).get("fmt", "N/A")
            level = "高利率環境 (壓制成長股估值)" if isinstance(tnx, (int, float)) and tnx > 4.5 else \
                    "中性" if isinstance(tnx, (int, float)) and tnx > 3.5 else "低利率 (利好成長股)"
            context_lines.append("### 10年期美債殖利率")
            context_lines.append("- 當前: " + str(tnx) + "% (日變動 " + str(tnx_change) + ")")
            context_lines.append("- 解讀: " + level)
            context_lines.append("")
    except Exception as e:
        context_lines.append("### 10Y Treasury: 無法取得\n")

    # 3. DXY (US Dollar Index)
    try:
        url = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/DX-Y.NYB"
        params = {"modules": "price"}
        resp = requests.get(url, headers=headers, params=params, timeout=8)
        if resp.status_code == 200:
            price = resp.json()["quoteSummary"]["result"][0]["price"]
            dxy = price.get("regularMarketPrice", {}).get("raw", "N/A")
            dxy_change = price.get("regularMarketChangePercent", {}).get("fmt", "N/A")
            level = "強美元 (壓制海外營收/原物料)" if isinstance(dxy, (int, float)) and dxy > 103 else \
                    "弱美元 (利好新興市場/原物料)"
            context_lines.append("### 美元指數 DXY")
            context_lines.append("- 當前: " + str(dxy) + " (" + str(dxy_change) + ")")
            context_lines.append("- 解讀: " + level)
            context_lines.append("")
    except Exception as e:
        context_lines.append("### DXY: 無法取得\n")

    # 4. S&P 500 trend
    try:
        url = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/%5EGSPC"
        params = {"modules": "price,summaryDetail"}
        resp = requests.get(url, headers=headers, params=params, timeout=8)
        if resp.status_code == 200:
            result = resp.json()["quoteSummary"]["result"][0]
            price = result["price"]
            detail = result.get("summaryDetail", {})
            spx = price.get("regularMarketPrice", {}).get("raw", "N/A")
            spx_chg = price.get("regularMarketChangePercent", {}).get("fmt", "N/A")
            w52h = detail.get("fiftyTwoWeekHigh", {}).get("raw", 0)
            if isinstance(spx, (int, float)) and isinstance(w52h, (int, float)) and w52h > 0:
                pct_from_high = round((spx - w52h) / w52h * 100, 1)
                trend = "接近歷史高點 (市場樂觀)" if pct_from_high > -5 else \
                        "回檔中 " + str(pct_from_high) + "% (觀察支撐)" if pct_from_high > -15 else \
                        "修正/熊市 " + str(pct_from_high) + "% (謹慎)"
            else:
                trend = "N/A"
            context_lines.append("### S&P 500")
            context_lines.append("- 當前: " + str(spx) + " (" + str(spx_chg) + ")")
            context_lines.append("- 距52週高點: " + trend)
            context_lines.append("")
    except Exception as e:
        context_lines.append("### S&P 500: 無法取得\n")

    # 5. Sector ETF flows (check tech XLK vs defensive XLU relative performance)
    sectors = [
        ("XLK", "科技"),
        ("XLF", "金融"),
        ("XLE", "能源"),
        ("XLV", "醫療"),
        ("XLU", "公用事業(防禦)"),
        ("ARKK", "創新/高成長"),
    ]
    sector_lines = []
    for etf, name in sectors:
        try:
            url = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/" + etf
            params = {"modules": "price"}
            resp = requests.get(url, headers=headers, params=params, timeout=5)
            if resp.status_code == 200:
                price = resp.json()["quoteSummary"]["result"][0]["price"]
                chg = price.get("regularMarketChangePercent", {}).get("fmt", "N/A")
                sector_lines.append("  - " + name + " (" + etf + "): " + str(chg))
        except Exception:
            pass

    if sector_lines:
        context_lines.append("### 板塊 ETF 今日表現")
        context_lines.extend(sector_lines)
        context_lines.append("")

    # 6. Put/Call Ratio (CBOE - scrape headline)
    try:
        resp = requests.get(
            "https://query1.finance.yahoo.com/v10/finance/quoteSummary/%5EPCALL",
            headers=headers, params={"modules": "price"}, timeout=5
        )
        # Fallback: note it's not easily available free
        context_lines.append("### Put/Call Ratio")
        context_lines.append("- 需要 CBOE 付費數據 (可用 VIX 作為替代指標)")
        context_lines.append("")
    except Exception:
        pass

    # Summary scoring
    context_lines.append("### 市場情緒綜合判斷")
    context_lines.append("（由分析框架根據以上數據自動判斷進出場時機）")

    return "\n".join(str(x) for x in context_lines)


if __name__ == "__main__":
    print(fetch_market_context())
