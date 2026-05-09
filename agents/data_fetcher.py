import requests
import json
from datetime import datetime


def fetch_stock_data(ticker: str) -> dict:
    """Auto-fetch stock financial data from Yahoo Finance"""
    data = {
        "ticker": ticker,
        "fetched_at": datetime.now().isoformat(),
        "financials": {},
        "news": [],
        "summary": ""
    }

    headers = {"User-Agent": "Mozilla/5.0"}

    # Basic quote and financial summary
    try:
        url = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/" + ticker
        params = {
            "modules": "price,summaryDetail,financialData,defaultKeyStatistics,incomeStatementHistory"
        }
        resp = requests.get(url, headers=headers, params=params, timeout=10)

        if resp.status_code == 200:
            result = resp.json().get("quoteSummary", {}).get("result", [{}])[0]

            price_data = result.get("price", {})
            financial_data = result.get("financialData", {})
            key_stats = result.get("defaultKeyStatistics", {})
            summary_detail = result.get("summaryDetail", {})

            data["financials"] = {
                "company_name": price_data.get("longName", ticker),
                "current_price": price_data.get("regularMarketPrice", {}).get("raw", "N/A"),
                "market_cap": price_data.get("marketCap", {}).get("fmt", "N/A"),
                "52w_high": summary_detail.get("fiftyTwoWeekHigh", {}).get("raw", "N/A"),
                "52w_low": summary_detail.get("fiftyTwoWeekLow", {}).get("raw", "N/A"),
                "pe_ratio": summary_detail.get("trailingPE", {}).get("fmt", "N/A"),
                "forward_pe": summary_detail.get("forwardPE", {}).get("fmt", "N/A"),
                "ps_ratio": key_stats.get("priceToSalesTrailing12Months", {}).get("fmt", "N/A"),
                "pb_ratio": key_stats.get("priceToBook", {}).get("fmt", "N/A"),
                "ev_ebitda": key_stats.get("enterpriseToEbitda", {}).get("fmt", "N/A"),
                "revenue_growth": financial_data.get("revenueGrowth", {}).get("fmt", "N/A"),
                "gross_margin": financial_data.get("grossMargins", {}).get("fmt", "N/A"),
                "operating_margin": financial_data.get("operatingMargins", {}).get("fmt", "N/A"),
                "profit_margin": financial_data.get("profitMargins", {}).get("fmt", "N/A"),
                "free_cashflow": financial_data.get("freeCashflow", {}).get("fmt", "N/A"),
                "total_debt": financial_data.get("totalDebt", {}).get("fmt", "N/A"),
                "cash": financial_data.get("totalCash", {}).get("fmt", "N/A"),
                "roe": financial_data.get("returnOnEquity", {}).get("fmt", "N/A"),
                "roa": financial_data.get("returnOnAssets", {}).get("fmt", "N/A"),
                "short_ratio": key_stats.get("shortRatio", {}).get("fmt", "N/A"),
                "shares_outstanding": key_stats.get("sharesOutstanding", {}).get("fmt", "N/A"),
            }
            print("Yahoo Finance OK: " + data["financials"]["company_name"])
        else:
            print("Yahoo Finance status: " + str(resp.status_code))

    except Exception as e:
        print("Yahoo Finance failed: " + str(e))

    # News
    try:
        news_url = "https://query1.finance.yahoo.com/v1/finance/search"
        news_params = {"q": ticker, "newsCount": 10, "enableFuzzyQuery": False}
        news_resp = requests.get(news_url, headers=headers, params=news_params, timeout=10)

        if news_resp.status_code == 200:
            news_items = news_resp.json().get("news", [])
            for item in news_items[:8]:
                data["news"].append({
                    "title": item.get("title", ""),
                    "publisher": item.get("publisher", ""),
                    "published": datetime.fromtimestamp(
                        item.get("providerPublishTime", 0)
                    ).strftime("%Y-%m-%d")
                })
            print("News OK: " + str(len(data["news"])) + " items")
    except Exception as e:
        print("News failed: " + str(e))

    # Build summary text
    f = data["financials"]
    news_lines = []
    for n in data["news"]:
        news_lines.append("- [" + n["published"] + "] " + n["title"] + " (" + n["publisher"] + ")")
    news_text = "\n".join(news_lines) if news_lines else "No news available"

    data["summary"] = (
        "## " + f.get("company_name", ticker) + " ($" + ticker + ") Data Summary\n\n"
        "### Valuation\n"
        "- Price: " + str(f.get("current_price")) + "\n"
        "- Market Cap: " + str(f.get("market_cap")) + "\n"
        "- 52W High/Low: " + str(f.get("52w_high")) + " / " + str(f.get("52w_low")) + "\n"
        "- P/E: " + str(f.get("pe_ratio")) + " | Fwd P/E: " + str(f.get("forward_pe")) + "\n"
        "- P/S: " + str(f.get("ps_ratio")) + " | P/B: " + str(f.get("pb_ratio")) + "\n"
        "- EV/EBITDA: " + str(f.get("ev_ebitda")) + "\n\n"
        "### Profitability\n"
        "- Gross Margin: " + str(f.get("gross_margin")) + "\n"
        "- Operating Margin: " + str(f.get("operating_margin")) + "\n"
        "- Net Margin: " + str(f.get("profit_margin")) + "\n"
        "- ROE: " + str(f.get("roe")) + " | ROA: " + str(f.get("roa")) + "\n\n"
        "### Growth & Cash Flow\n"
        "- Revenue Growth YoY: " + str(f.get("revenue_growth")) + "\n"
        "- Free Cash Flow: " + str(f.get("free_cashflow")) + "\n\n"
        "### Balance Sheet\n"
        "- Cash: " + str(f.get("cash")) + " | Total Debt: " + str(f.get("total_debt")) + "\n"
        "- Shares Outstanding: " + str(f.get("shares_outstanding")) + "\n"
        "- Short Ratio: " + str(f.get("short_ratio")) + "\n\n"
        "### Recent News\n"
        + news_text
    )

    return data


def fetch_and_prepare(ticker: str) -> str:
    """Fetch data and return analysis-ready text"""
    print("Fetching $" + ticker + " data...")
    data = fetch_stock_data(ticker)
    return data["summary"]


if __name__ == "__main__":
    import sys
    t = sys.argv[1] if len(sys.argv) > 1 else "SNDK"
    print(fetch_and_prepare(t))
