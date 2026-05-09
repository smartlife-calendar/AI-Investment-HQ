"""
tw_fetcher.py - Taiwan Stock Data Fetcher
Sources: Yahoo Finance (price) + TWSE open API (financials)
Works for: 2330.TW (TSMC), 2317.TW (Foxconn), etc.
"""
import requests
import json
import re
from datetime import datetime


def get_tw_stock_id(ticker: str) -> str:
    """Extract Taiwan stock ID from ticker like '2330.TW' -> '2330'"""
    return ticker.upper().replace(".TW", "").replace(".TWO", "").strip()


def fetch_tw_financials(ticker: str) -> dict:
    """
    Fetch Taiwan stock financials from TWSE open data API.
    Free, no key required.
    """
    stock_id = get_tw_stock_id(ticker)
    result = {}
    headers = {"User-Agent": "Mozilla/5.0"}

    # 1. TWSE Company Profile
    try:
        url = f"https://www.twse.com.tw/exchangeReport/BWIBBU_d?response=json&selectType=ALL"
        # Use the company info API
        info_url = f"https://mops.twse.com.tw/mops/web/ajax_t05st10?firstin=1&off=1&step=1&co_id={stock_id}"
        resp = requests.post(info_url, headers=headers, timeout=8)
        if resp.status_code == 200 and len(resp.text) > 100:
            text = resp.text
            # Extract company name from HTML
            name_match = re.search(r'公司名稱[^<]*</[^>]+>\s*<[^>]+>([^<]+)', text)
            if name_match:
                result["company_name"] = name_match.group(1).strip()
    except Exception as e:
        print(f"TWSE profile failed: {e}")

    # 2. Monthly Revenue (月營收) - most reliable free data
    try:
        # Get current year/month
        now = datetime.now()
        year_tw = now.year - 1911  # ROC year
        month = now.month - 1 if now.month > 1 else 12
        if month == 12:
            year_tw -= 1

        rev_url = f"https://mops.twse.com.tw/nas/t21/sii/t21sc03_{year_tw}_{month:02d}_0.html"
        resp = requests.get(rev_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            text = resp.text
            # Find the row for our stock
            pattern = rf'{stock_id}.*?</tr>'
            match = re.search(pattern, text, re.DOTALL)
            if match:
                row = match.group(0)
                numbers = re.findall(r'[\d,]+', row)
                if len(numbers) >= 3:
                    monthly_rev = int(numbers[2].replace(',', ''))  # thousands TWD
                    result["monthly_revenue_twd"] = monthly_rev * 1000
                    result["monthly_revenue_usd"] = f"${monthly_rev * 1000 * 0.031 / 1e9:.2f}B"
                    result["revenue_period"] = f"{year_tw+1911}/{month:02d}"
    except Exception as e:
        print(f"Monthly revenue failed: {e}")

    # 3. Use Yahoo Finance financial data for Taiwan stocks
    try:
        yf_url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        resp = requests.get(
            yf_url,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.yahoo.com/"},
            params={"interval": "1d", "range": "1d"},
            timeout=10
        )
        if resp.status_code == 200:
            meta = resp.json().get("chart", {}).get("result", [{}])[0].get("meta", {})
            result["price_twd"] = meta.get("regularMarketPrice")
            result["high_52w_twd"] = meta.get("fiftyTwoWeekHigh")
            result["low_52w_twd"] = meta.get("fiftyTwoWeekLow")
            result["currency"] = meta.get("currency", "TWD")

            # Convert to USD
            if result.get("price_twd"):
                p = result["price_twd"]
                result["price_usd"] = round(p * 0.031, 2)
                if result.get("high_52w_twd"):
                    result["high_52w_usd"] = round(result["high_52w_twd"] * 0.031, 2)
                if result.get("low_52w_twd"):
                    result["low_52w_usd"] = round(result["low_52w_twd"] * 0.031, 2)
    except Exception as e:
        print(f"Yahoo TW price failed: {e}")

    # 4. FMP for Taiwan fundamentals if available
    fmp_key = __import__("os").environ.get("FMP_API_KEY", "")
    if fmp_key:
        try:
            base = "https://financialmodelingprep.com/api/v3"

            # Profile
            prof = requests.get(f"{base}/profile/{ticker}", params={"apikey": fmp_key}, headers=headers, timeout=8)
            if prof.status_code == 200:
                profiles = prof.json()
                if isinstance(profiles, list) and profiles:
                    p = profiles[0]
                    result["company_name"] = result.get("company_name") or p.get("companyName", "")
                    result["market_cap_usd"] = f"${p.get('mktCap', 0)/1e9:.1f}B" if p.get("mktCap") else "N/A"
                    result["pe_ratio"] = str(round(p.get("pe", 0), 1)) if p.get("pe") else "N/A"
                    result["eps"] = str(p.get("eps", "N/A"))
                    result["sector"] = p.get("sector", "")
                    result["industry"] = p.get("industry", "")
                    print(f"FMP profile: {result.get('company_name')} MC={result.get('market_cap_usd')}")

            # Income statement
            inc = requests.get(
                f"{base}/income-statement/{ticker}",
                params={"period": "annual", "limit": 2, "apikey": fmp_key},
                headers=headers,
                timeout=8
            )
            if inc.status_code == 200:
                incs = inc.json()
                if isinstance(incs, list) and incs:
                    i0 = incs[0]
                    rev = i0.get("revenue", 0)
                    gp = i0.get("grossProfit", 0)
                    ni = i0.get("netIncome", 0)
                    op = i0.get("operatingIncome", 0)
                    if rev:
                        result["revenue"] = f"${rev/1e9:.2f}B"
                        if gp:
                            result["gross_profit"] = f"${gp/1e9:.2f}B"
                            result["gross_margin"] = f"{gp/rev*100:.1f}%"
                        if ni:
                            result["net_income"] = f"${ni/1e9:.2f}B"
                            result["net_margin"] = f"{ni/rev*100:.1f}%"
                        if op:
                            result["operating_income"] = f"${op/1e9:.2f}B"
                            result["op_margin"] = f"{op/rev*100:.1f}%"
                        result["fiscal_year"] = i0.get("date", "")[:7]
                        print(f"FMP income: rev={result.get('revenue')} GM={result.get('gross_margin')}")

            # Cash flow
            cf = requests.get(
                f"{base}/cash-flow-statement/{ticker}",
                params={"period": "annual", "limit": 2, "apikey": fmp_key},
                headers=headers,
                timeout=8
            )
            if cf.status_code == 200:
                cfs = cf.json()
                if isinstance(cfs, list) and cfs:
                    c0 = cfs[0]
                    ocf = c0.get("operatingCashFlow", 0)
                    capex = c0.get("capitalExpenditure", 0)  # negative in FMP
                    sbc = c0.get("stockBasedCompensation", 0)
                    if ocf:
                        result["ocf"] = f"${ocf/1e9:.2f}B"
                        fcf = ocf + capex  # capex is negative
                        result["fcf"] = f"${fcf/1e9:.2f}B"
                    if capex:
                        result["capex"] = f"${abs(capex)/1e9:.2f}B"
                    if sbc:
                        result["sbc"] = f"${sbc/1e6:.0f}M"

            # Balance sheet
            bs = requests.get(
                f"{base}/balance-sheet-statement/{ticker}",
                params={"period": "annual", "limit": 1, "apikey": fmp_key},
                headers=headers,
                timeout=8
            )
            if bs.status_code == 200:
                bss = bs.json()
                if isinstance(bss, list) and bss:
                    b0 = bss[0]
                    result["cash"] = f"${b0.get('cashAndCashEquivalents', 0)/1e9:.2f}B"
                    result["total_assets"] = f"${b0.get('totalAssets', 0)/1e9:.2f}B"
                    result["total_debt"] = f"${b0.get('totalDebt', 0)/1e9:.2f}B"
                    result["equity"] = f"${b0.get('totalStockholdersEquity', 0)/1e9:.2f}B"
                    result["shares"] = f"{b0.get('commonStock', 0)/1e9:.2f}B"

        except Exception as e:
            print(f"FMP TW failed: {e}")

    return result


def fetch_tw_news(stock_id: str) -> list:
    """Fetch Taiwan stock news from Yahoo Finance."""
    news = []
    try:
        resp = requests.get(
            "https://query1.finance.yahoo.com/v1/finance/search",
            headers={"User-Agent": "Mozilla/5.0"},
            params={"q": stock_id + " Taiwan", "newsCount": 6},
            timeout=8
        )
        if resp.status_code == 200:
            for item in resp.json().get("news", [])[:5]:
                ts = item.get("providerPublishTime", 0)
                date = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else ""
                news.append({
                    "title": str(item.get("title", "")),
                    "publisher": str(item.get("publisher", "")),
                    "date": date,
                })
    except Exception as e:
        print(f"TW news failed: {e}")
    return news


def build_tw_summary(ticker: str, data: dict, news: list) -> str:
    """Build analysis-ready text for Taiwan stock."""
    stock_id = get_tw_stock_id(ticker)
    company = data.get("company_name") or ticker

    def s(v, d="N/A"):
        return str(v) if v is not None else d

    price_twd = s(data.get("price_twd"))
    price_usd = s(data.get("price_usd"))
    high_twd = s(data.get("high_52w_twd"))
    low_twd = s(data.get("low_52w_twd"))

    news_text = "\n".join(f"- [{n['date']}] {n['title']} ({n['publisher']})" for n in news) or "No recent news"

    lines = [
        f"## {company} ({ticker}) - Taiwan Stock",
        "",
        "### Price",
        f"- Current: NT${price_twd} (≈ US${price_usd})",
        f"- 52W High/Low: NT${high_twd} / NT${low_twd}",
        f"- Market Cap: {s(data.get('market_cap_usd'))}",
        f"- P/E: {s(data.get('pe_ratio'))} | EPS: NT${s(data.get('eps'))}",
        f"- Sector: {s(data.get('sector'))} | Industry: {s(data.get('industry'))}",
        "",
        f"### Income Statement ({s(data.get('fiscal_year', 'Annual'))})",
        f"- Revenue: {s(data.get('revenue'))}",
        f"- Gross Profit: {s(data.get('gross_profit'))} | Gross Margin: {s(data.get('gross_margin'))}",
        f"- Operating Income: {s(data.get('operating_income'))} | Op Margin: {s(data.get('op_margin'))}",
        f"- Net Income: {s(data.get('net_income'))} | Net Margin: {s(data.get('net_margin'))}",
    ]

    if data.get("monthly_revenue_usd"):
        lines += [
            "",
            f"### Monthly Revenue ({s(data.get('revenue_period'))})",
            f"- Monthly Rev: {s(data.get('monthly_revenue_usd'))} (from TWSE)",
        ]

    lines += [
        "",
        "### Cash Flow",
        f"- Operating CF: {s(data.get('ocf'))}",
        f"- CapEx: {s(data.get('capex'))}",
        f"- Free Cash Flow: {s(data.get('fcf'))}",
        f"- SBC: {s(data.get('sbc'))}",
        "",
        "### Balance Sheet",
        f"- Cash: {s(data.get('cash'))}",
        f"- Total Debt: {s(data.get('total_debt'))}",
        f"- Total Assets: {s(data.get('total_assets'))}",
        f"- Equity: {s(data.get('equity'))}",
        f"- Shares: {s(data.get('shares'))}",
        "",
        "### Recent News",
        news_text,
    ]

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "2330.TW"
    data = fetch_tw_financials(ticker)
    news = fetch_tw_news(get_tw_stock_id(ticker))
    print(build_tw_summary(ticker, data, news))
