import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_fetcher import fetch_stock_data
from sec_fetcher import fetch_sec_filing
from news_fetcher import search_stock_news, analyze_news_sentiment
from fmp_fetcher import fetch_fmp_financials
from market_context_fetcher import fetch_market_context
from analyst import run_analysis, generate_comparison_table


def full_auto_pipeline(ticker: str, persona: str = "all", manual_text: str = "") -> dict:
    ticker = ticker.upper().strip()
    print("Starting analysis for " + ticker)

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    combined_data = "# " + ticker + " Full Data Report\nGenerated: " + ts + "\n\n"
    company_name = ticker

    # A: Yahoo Finance
    print("[A] Yahoo Finance...")
    try:
        stock_data = fetch_stock_data(ticker)
        combined_data += stock_data["summary"] + "\n\n"
        company_name = stock_data["financials"].get("company_name") or ticker
    except Exception as e:
        print("Yahoo Finance failed: " + str(e))
        combined_data += "## Financial Data\nUnavailable\n\n"

    # B: FMP Detailed Financials
    print("[B] FMP Financials...")
    try:
        fmp_text = fetch_fmp_financials(ticker)
        if fmp_text and len(fmp_text) > 100:
            combined_data += fmp_text + "\n\n"
        else:
            combined_data += "## FMP: No detailed data available\n\n"
    except Exception as e:
        print("FMP failed: " + str(e))

    # C: SEC Filing
    print("[C] SEC EDGAR...")
    try:
        sec_text = fetch_sec_filing(ticker, "10-Q")
        if sec_text and len(sec_text) > 200:
            combined_data += "## SEC 10-Q\n" + sec_text[:5000] + "\n\n"
        else:
            combined_data += "## SEC Filing: Not found\n\n"
    except Exception as e:
        print("SEC failed: " + str(e))

    # D: News
    print("[D] News...")
    try:
        news_text = search_stock_news(ticker, company_name)
        sentiment = analyze_news_sentiment(news_text, ticker)
        combined_data += news_text + "\n" + sentiment + "\n\n"
    except Exception as e:
        print("News failed: " + str(e))

    # E: Market Context (NEW)
    print("[E] Market Context...")
    market_context = ""
    try:
        market_context = fetch_market_context()
        combined_data += market_context + "\n\n"
        print("Market context: " + str(len(market_context)) + " chars")
    except Exception as e:
        print("Market context failed: " + str(e))

    # Manual supplement
    if manual_text and len(manual_text) > 50:
        combined_data += "## Manual Supplement\n" + manual_text + "\n\n"

    print("Total data: " + str(len(combined_data)) + " chars")
    print("Running parallel analysis...")

    if persona == "all":
        personas = None
    else:
        personas = [p.strip() for p in persona.split(",")]

    # Parallel execution
    results = run_analysis(ticker, combined_data, personas, market_context)
    comparison_table = generate_comparison_table(ticker, results)

    os.makedirs("reports", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    report = {
        "ticker": ticker,
        "company": company_name,
        "timestamp": timestamp,
        "raw_data_length": len(combined_data),
        "comparison_table": comparison_table,
        "market_context": market_context,
        "analyses": {
            k: v.get("full_analysis", v) if isinstance(v, dict) else v
            for k, v in results.items()
        },
        "structured_results": {
            k: {kk: vv for kk, vv in v.items() if kk != "full_analysis"}
            for k, v in results.items()
            if isinstance(v, dict)
        }
    }

    json_path = "reports/" + ticker + "_" + timestamp + ".json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("Done: " + json_path)
    return report


if __name__ == "__main__":
    ticker = os.environ.get("TICKER") or (sys.argv[1] if len(sys.argv) > 1 else "SNDK")
    persona = os.environ.get("PERSONA", "all")
    manual_text = os.environ.get("FINANCIAL_TEXT", "")
    full_auto_pipeline(ticker, persona, manual_text)
