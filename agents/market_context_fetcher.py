import requests
from datetime import datetime


def fetch_market_context(lang="zh") -> str:
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
                sector_lines.append("  - " + str(name or "") + " (" + str(etf or "") + "): " + str(chg or "N/A"))
        except Exception:
            pass

    if sector_lines:
        context_lines.append("### 板塊 ETF 今日表現")
        context_lines.extend(sector_lines)
        context_lines.append("")

    

    # Fear & Greed Index (alternative.me - free, no key needed)
    try:
        fg_resp = requests.get(
            "https://api.alternative.me/fng/?limit=4",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=6
        )
        if fg_resp.status_code == 200:
            fg_data = fg_resp.json().get("data", [])
            if fg_data:
                current_fg = fg_data[0]
                score = current_fg.get("value", "N/A")
                rating = current_fg.get("value_classification", "N/A")
                # Emoji indicator
                if isinstance(score, str) and score.isdigit():
                    s = int(score)
                    emoji = "🔴" if s < 25 else "🟡" if s < 45 else "⚪" if s < 55 else "🟢" if s < 75 else "🟢🟢"
                else:
                    emoji = ""
                context_lines.append("### 貪婪/恐懼指數 (Fear & Greed)")
                context_lines.append(f"- 當前: {score}/100 - {rating} {emoji}")
                # Historical comparison
                if len(fg_data) >= 4:
                    week_ago = fg_data[min(3, len(fg_data)-1)]
                    context_lines.append(f"- 一週前: {week_ago.get('value', 'N/A')}/100 ({week_ago.get('value_classification', '')})")
                if isinstance(score, str) and score.isdigit():
                    s = int(score)
                    if s < 25:
                        context_lines.append("- 解讀: 極度恐懼 → 歷史上常為買入機會")
                    elif s < 45:
                        context_lines.append("- 解讀: 恐懼 → 市場謹慎，注意逢低機會")
                    elif s < 55:
                        context_lines.append("- 解讀: 中性 → 無明顯情緒偏向")
                    elif s < 75:
                        context_lines.append("- 解讀: 貪婪 → 市場樂觀，留意追高風險")
                    else:
                        context_lines.append("- 解讀: 極度貪婪 → 歷史上常為賣出訊號")
                context_lines.append("")
    except Exception as e:
        context_lines.append(f"### 貪婪/恐懼指數: 無法取得\n")

    # Trending tickers
    try:
        trend_resp = requests.get(
            "https://query1.finance.yahoo.com/v1/finance/trending/US",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=6
        )
        if trend_resp.status_code == 200:
            trending = trend_resp.json().get("finance", {}).get("result", [{}])[0].get("quotes", [])[:8]
            stock_trending = [q.get("symbol","") for q in trending if "BTC" not in q.get("symbol","") and "-" not in q.get("symbol","")]
            if stock_trending:
                context_lines.append("### 市場熱門股 (Yahoo Trending)")
                context_lines.append("- 今日熱門: " + ", ".join(stock_trending[:6]))
                context_lines.append("")
    except Exception as e:
        pass

    # === MARKET SENTIMENT SCORING ===
    # Compute an overall market sentiment score based on available indicators
    sentiment_score = 0  # -100 (extreme fear) to +100 (extreme greed)
    factors = []
    
    # Factor 1: Fear & Greed Index (most weight)
    try:
        fg_resp = requests.get("https://api.alternative.me/fng/?limit=1", headers=headers, timeout=5)
        if fg_resp.status_code == 200:
            fg_val = int(fg_resp.json().get("data",[{}])[0].get("value", 50))
            fg_contribution = (fg_val - 50) * 0.6  # -30 to +30
            sentiment_score += fg_contribution
            factors.append(f"F&G:{fg_val}")
    except Exception:
        pass
    
    # Factor 2: VIX (inverse - high VIX = fear = low sentiment)
    try:
        vix_resp = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX",
            headers=headers, params={"interval":"1d","range":"1d"}, timeout=5
        )
        if vix_resp.status_code == 200:
            vix = vix_resp.json().get("chart",{}).get("result",[{}])[0].get("meta",{}).get("regularMarketPrice",20)
            if vix < 15: vix_contribution = 20
            elif vix < 20: vix_contribution = 10
            elif vix < 25: vix_contribution = 0
            elif vix < 30: vix_contribution = -15
            else: vix_contribution = -30
            sentiment_score += vix_contribution
            factors.append(f"VIX:{round(vix,1)}")
    except Exception:
        pass
    
    # Factor 3: S&P 500 trend
    try:
        spx_resp = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC",
            headers=headers, params={"interval":"1d","range":"5d"}, timeout=5
        )
        if spx_resp.status_code == 200:
            meta = spx_resp.json().get("chart",{}).get("result",[{}])[0].get("meta",{})
            price = meta.get("regularMarketPrice",0)
            high52 = meta.get("fiftyTwoWeekHigh",price)
            if high52 > 0:
                from_high = (price - high52) / high52 * 100
                if from_high > -3: spx_contribution = 20
                elif from_high > -10: spx_contribution = 5
                elif from_high > -20: spx_contribution = -10
                else: spx_contribution = -20
                sentiment_score += spx_contribution
                factors.append(f"SPX:{round(from_high,1)}%fmHigh")
    except Exception:
        pass
    
    # Clamp to -100 to +100
    sentiment_score = max(-100, min(100, int(sentiment_score)))
    
    # Determine label
    if sentiment_score >= 50:
        sentiment_label = "🟢 極度樂觀 (Extreme Greed)"
        sentiment_action = "市場過熱，注意高估風險，考慮逢高減持"
    elif sentiment_score >= 20:
        sentiment_label = "🟢 樂觀 (Greed)"
        sentiment_action = "市場情緒偏多，追高需謹慎"
    elif sentiment_score >= -20:
        sentiment_label = "⚪ 中性 (Neutral)"
        sentiment_action = "市場情緒中性，依個股基本面決策"
    elif sentiment_score >= -50:
        sentiment_label = "🔴 悲觀 (Fear)"
        sentiment_action = "市場情緒偏空，但可能存在逢低機會"
    else:
        sentiment_label = "🔴 極度悲觀 (Extreme Fear)"
        sentiment_action = "市場恐慌，歷史上常為長期買入機會"
    
    context_lines.append("### 📊 市場情緒綜合評分")
    context_lines.append(f"- 情緒分數: **{sentiment_score}/100** → {sentiment_label}")
    context_lines.append(f"- 操作建議: {sentiment_action}")
    context_lines.append(f"- 計算因子: {' | '.join(factors) if factors else '數據不足'}")
    context_lines.append("")
    context_lines.append("### 市場情緒說明")
    context_lines.append("100=極度貪婪 | 0=中性 | -100=極度恐懼")
    context_lines.append("分析框架應結合此情緒分數調整進出場建議的積極程度")

    return "\n".join(str(x) for x in context_lines)


if __name__ == "__main__":
    print(fetch_market_context())
