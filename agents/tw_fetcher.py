"""
tw_fetcher.py - Taiwan Stock Data Fetcher
Free sources only:
- Yahoo Finance Chart v8 (price, 52w high/low)
- TWSE open API (P/E, P/B, dividend yield, foreign investor flow)
- TWSE monthly revenue
- TWSE quarterly financials (via iFin XBRL)
"""
import requests
import json
import re
from datetime import datetime, timedelta


def get_tw_stock_id(ticker: str) -> str:
    """Extract Taiwan stock ID: '2330.TW' -> '2330'"""
    return ticker.upper().replace(".TW", "").replace(".TWO", "").strip()


def safe(v, d="N/A"):
    return str(v) if v is not None else d


def fetch_tw_price(ticker: str) -> dict:
    """Yahoo Finance Chart v8 - works for Taiwan stocks."""
    result = {}
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            params={"interval": "1d", "range": "1d"},
            timeout=10
        )
        if resp.status_code == 200:
            meta = resp.json().get("chart", {}).get("result", [{}])[0].get("meta", {})
            result["price_twd"] = meta.get("regularMarketPrice")
            result["high_52w_twd"] = meta.get("fiftyTwoWeekHigh")
            result["low_52w_twd"] = meta.get("fiftyTwoWeekLow")
            result["prev_close_twd"] = meta.get("chartPreviousClose")
            result["currency"] = "TWD"
            # Convert to USD
            if result.get("price_twd"):
                p = result["price_twd"]
                result["price_usd"] = round(p * 0.031, 2)
                if result.get("high_52w_twd"):
                    result["high_52w_usd"] = round(result["high_52w_twd"] * 0.031, 2)
                if result.get("low_52w_twd"):
                    result["low_52w_usd"] = round(result["low_52w_twd"] * 0.031, 2)
            print(f"TW price OK: NT${result['price_twd']}")
    except Exception as e:
        print(f"TW price failed: {e}")
    return result


def fetch_twse_valuation(stock_id: str) -> dict:
    """TWSE free API - P/E, P/B, dividend yield from daily report."""
    result = {}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        url = "https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?response=json&date=&selectType=ALL"
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            d = resp.json()
            for row in d.get("data", []):
                if row and str(row[0]).strip() == stock_id:
                    # Fields: 證券代號, 證券名稱, 收盤價, 殖利率, 股利年度, 本益比, 股價淨值比, 財報年/季
                    result["company_name_tw"] = str(row[1]).strip() if len(row) > 1 else ""
                    result["pe_ratio"] = str(row[5]).strip() if len(row) > 5 else "N/A"
                    result["pb_ratio"] = str(row[6]).strip() if len(row) > 6 else "N/A"
                    result["dividend_yield"] = str(row[3]).strip() + "%" if len(row) > 3 else "N/A"
                    result["financial_period"] = str(row[7]).strip() if len(row) > 7 else ""
                    print(f"TWSE valuation: {stock_id} PE={result['pe_ratio']} PB={result['pb_ratio']}")
                    break
    except Exception as e:
        print(f"TWSE valuation failed: {e}")
    return result


def fetch_twse_foreign_flow(stock_id: str) -> dict:
    """TWSE foreign investor (外資) buy/sell data."""
    result = {}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        url = "https://www.twse.com.tw/rwd/zh/fund/TWT38U?response=json&stockNo=" + stock_id
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            d = resp.json()
            data_rows = d.get("data", [])
            if data_rows:
                # Get last 3 days
                recent = data_rows[-3:]
                net_flows = []
                for row in recent:
                    if len(row) >= 6:
                        # Row: [類型, 買進, 賣出, 買賣超, ...]
                        try:
                            net = int(str(row[5]).replace(",", "").replace(" ", ""))
                            net_flows.append(net)
                        except Exception:
                            pass
                if net_flows:
                    total_net = sum(net_flows)
                    result["foreign_net_3d"] = f"{'+'if total_net>=0 else ''}{total_net:,} shares (3-day)"
                    result["foreign_sentiment"] = "買超 (Bullish)" if total_net > 0 else "賣超 (Bearish)"
                    print(f"Foreign flow: {result['foreign_sentiment']}")
    except Exception as e:
        print(f"Foreign flow failed: {e}")
    return result


def fetch_twse_revenue(stock_id: str) -> dict:
    """TWSE monthly revenue data."""
    result = {}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        now = datetime.now()
        year_tw = now.year - 1911
        month = now.month - 1 if now.month > 1 else 12
        year_rev = year_tw if now.month > 1 else year_tw - 1

        # Try MOPS revenue API
        url = f"https://mops.twse.com.tw/nas/t21/sii/t21sc03_{year_rev}_{month:02d}_0.html"
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            text = resp.text
            # Find stock row
            pattern = rf'>{stock_id}<.*?</tr>'
            match = re.search(pattern, text, re.DOTALL)
            if match:
                row_text = re.sub(r'<[^>]+>', ' ', match.group(0))
                numbers = re.findall(r'[\d,]+', row_text)
                # Numbers: [股號, 本月, 上月, 去年同月, 月增率, 年增率, ...]
                if len(numbers) >= 4:
                    this_month = int(numbers[1].replace(',', ''))
                    last_year_month = int(numbers[3].replace(',', ''))
                    yoy = round((this_month - last_year_month) / last_year_month * 100, 1) if last_year_month > 0 else 0
                    result["monthly_rev_twd_k"] = this_month  # thousands TWD
                    result["monthly_rev_usd"] = f"${this_month * 1000 * 0.031 / 1e9:.2f}B"
                    result["monthly_rev_yoy"] = f"{'+' if yoy >= 0 else ''}{yoy}% YoY"
                    result["revenue_period"] = f"{year_rev+1911}/{month:02d}"
                    print(f"Revenue: {result['monthly_rev_usd']} ({result['monthly_rev_yoy']})")
    except Exception as e:
        print(f"Revenue fetch failed: {e}")
    return result


def fetch_twse_financials_xbrl(stock_id: str) -> dict:
    """
    Try to get financial statements from Taiwan XBRL (iXBRL) database.
    This is TWSE's structured financial data for listed companies.
    """
    result = {}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        # Taiwan Stock Exchange XBRL viewer
        # Format: year (ROC) + Q (1-4)
        now = datetime.now()
        year_tw = now.year - 1911 - 1  # Last complete year
        quarter = 4  # Q4 = annual

        url = f"https://apiV2.finmindtrade.com/api/v4/data?dataset=TaiwanStockFinancialStatements&data_id={stock_id}&start_date={now.year-2}-01-01&token="
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code == 200:
            d = resp.json()
            data = d.get("data", [])
            if data:
                # Get latest annual data
                annual = [x for x in data if x.get("type") == "EPS"]
                if annual:
                    latest = sorted(annual, key=lambda x: x.get("date", ""))[-1]
                    result["eps_twd"] = str(latest.get("value", "N/A"))
                    print(f"FinMind EPS: {result['eps_twd']}")

    except Exception as e:
        print(f"XBRL failed: {e}")
    return result


def fetch_tw_stock_data(ticker: str) -> dict:
    """Main function: fetch all Taiwan stock data."""
    stock_id = get_tw_stock_id(ticker)
    print(f"Fetching Taiwan stock: {ticker} (ID: {stock_id})")

    result = {"ticker": ticker, "stock_id": stock_id}

    # 1. Price
    price_data = fetch_tw_price(ticker)
    result.update(price_data)

    # 2. TWSE valuation metrics (P/E, P/B)
    val_data = fetch_twse_valuation(stock_id)
    result.update(val_data)

    # 3. Monthly revenue
    rev_data = fetch_twse_revenue(stock_id)
    result.update(rev_data)

    # 4. Foreign investor flow
    flow_data = fetch_twse_foreign_flow(stock_id)
    result.update(flow_data)

    # 5. FMP stable profile (market cap, beta, volume)
    import os
    fmp_key = os.environ.get("FMP_API_KEY", "")
    if fmp_key:
        try:
            prof_resp = __import__("requests").get(
                "https://financialmodelingprep.com/stable/profile",
                params={"symbol": ticker, "apikey": fmp_key},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=8
            )
            if prof_resp.status_code == 200 and prof_resp.text.strip():
                profiles = prof_resp.json()
                if isinstance(profiles, list) and profiles:
                    p = profiles[0]
                    result["company_name"] = result.get("company_name") or p.get("companyName", "")
                    mc = p.get("marketCap", 0)
                    if mc:
                        result["market_cap_usd"] = f"${mc * 0.031 / 1e9:.1f}B"
                        result["market_cap_twd"] = f"NT${mc/1e9:.0f}B"
                    result["beta"] = str(round(p.get("beta", 0), 2)) if p.get("beta") else "N/A"
                    print(f"FMP: {result.get('company_name')} MC={result.get('market_cap_usd')}")
        except Exception as e:
            print(f"FMP profile failed: {e}")

    return result


def build_tw_summary(ticker: str, data: dict, news: list = None) -> str:
    """Build analysis-ready summary string for Taiwan stocks."""
    company = data.get("company_name_tw") or ticker
    stock_id = data.get("stock_id", ticker)

    if news is None:
        news = []
    news_text = "\n".join(
        f"- [{n.get('date','')}] {n.get('title','')} ({n.get('publisher','')})"
        for n in news
    ) or "No recent news"

    price_twd = safe(data.get("price_twd"))
    price_usd = safe(data.get("price_usd"))

    lines = [
        f"## {company} ({ticker}) - Taiwan Listed Stock",
        "",
        "### Price (TWD)",
        f"- Current: NT${price_twd} (≈ US${price_usd})",
        f"- 52W High: NT${safe(data.get('high_52w_twd'))} (US${safe(data.get('high_52w_usd'))})",
        f"- 52W Low: NT${safe(data.get('low_52w_twd'))} (US${safe(data.get('low_52w_usd'))})",
        "",
        "### Valuation (from TWSE)",
        f"- P/E Ratio: {safe(data.get('pe_ratio'))}x",
        f"- P/B Ratio: {safe(data.get('pb_ratio'))}x",
        f"- Dividend Yield: {safe(data.get('dividend_yield'))}",
        f"- Financial Period: {safe(data.get('financial_period'))}",
        "",
        "### Monthly Revenue",
        f"- Latest Month ({safe(data.get('revenue_period'))}): {safe(data.get('monthly_rev_usd'))}",
        f"- YoY Change: {safe(data.get('monthly_rev_yoy'))}",
        "",
        "### Institutional Flow",
        f"- Foreign Investor Net (3-day): {safe(data.get('foreign_net_3d'))}",
        f"- Sentiment: {safe(data.get('foreign_sentiment'))}",
        "",
        "### Recent News",
        news_text,
    ]

    return "\n".join(lines)


def fetch_tw_news(stock_id: str) -> list:
    """Yahoo Finance news for Taiwan stock."""
    news = []
    try:
        resp = requests.get(
            "https://query1.finance.yahoo.com/v1/finance/search",
            headers={"User-Agent": "Mozilla/5.0"},
            params={"q": stock_id, "newsCount": 6},
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
        print(f"News failed: {e}")
    return news


if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "2330.TW"
    data = fetch_tw_stock_data(ticker)
    news = fetch_tw_news(get_tw_stock_id(ticker))
    print(build_tw_summary(ticker, data, news))
