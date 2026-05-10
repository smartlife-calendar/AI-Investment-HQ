import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_fetcher import fetch_stock_data
from tw_fetcher import fetch_tw_stock_data, fetch_tw_news, build_tw_summary, get_tw_stock_id
from technical_fetcher import analyze_technical
from sec_fetcher import fetch_sec_filing
from news_fetcher import search_stock_news, analyze_news_sentiment
from fmp_fetcher import fetch_fmp_financials
from market_context_fetcher import fetch_market_context
from analyst import run_analysis, generate_comparison_table


def full_auto_pipeline(ticker: str, persona: str = "all", manual_text: str = "") -> dict:
    ticker = ticker.upper().strip()
    print("Starting analysis for " + ticker)

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    combined_data = "# " + str(ticker) + " Full Data Report\nGenerated: " + str(ts) + "\n\n"
    company_name = ticker

    # A: Data fetching - Taiwan stocks use tw_fetcher, US stocks use data_fetcher
    is_taiwan = ticker.endswith(".TW") or ticker.endswith(".TWO")
    
    if is_taiwan:
        print("[A] Taiwan stock fetcher...")
        try:
            tw_data = fetch_tw_stock_data(ticker)
            tw_news = fetch_tw_news(get_tw_stock_id(ticker))
            tw_summary = build_tw_summary(ticker, tw_data, tw_news)
            combined_data += tw_summary + "\n\n"
            company_name = tw_data.get("company_name") or ticker
            print("TW data OK: " + str(company_name))
        except Exception as e:
            print("TW fetcher failed: " + str(e))
            combined_data += "## Taiwan Stock Data\nUnavailable: " + str(e) + "\n\n"
    else:
        print("[A] Yahoo Finance / SEC XBRL...")
        try:
            stock_data = fetch_stock_data(ticker)
            combined_data += str(stock_data.get("summary") or "") + "\n\n"
            company_name = stock_data["financials"].get("company_name") or ticker
        except Exception as e:
            print("Data fetch failed: " + str(e))
            combined_data += "## Financial Data\nUnavailable\n\n"

    # B: FMP Detailed Financials
    print("[B] FMP Financials...")
    try:
        fmp_text = fetch_fmp_financials(ticker)
        if fmp_text and len(fmp_text) > 100:
            combined_data += (fmp_text or "") + "\n\n"
        else:
            combined_data += "## FMP: No detailed data available\n\n"
    except Exception as e:
        print("FMP failed: " + str(e))

    # C: Technical Analysis (RSI, Bollinger, MACD, MA, Volume)
    print("[C] Technical Analysis...")
    try:
        tech_summary = analyze_technical(ticker)
        combined_data += tech_summary + "\n\n"
    except Exception as e:
        print("Technical analysis failed: " + str(e))
        combined_data += "## Technical Analysis\nUnavailable\n\n"

    # D: SEC Filing
    print("[D] SEC EDGAR...")
    try:
        sec_text = fetch_sec_filing(ticker, "10-Q")
        if sec_text and len(sec_text) > 200:
            combined_data += "## SEC 10-Q\n" + (sec_text or "")[:5000] + "\n\n"
        else:
            combined_data += "## SEC Filing: Not found\n\n"
    except Exception as e:
        print("SEC failed: " + str(e))

    # D: News
    print("[D] News...")
    try:
        news_text = search_stock_news(ticker, company_name)
        sentiment = analyze_news_sentiment(news_text, ticker)
        combined_data += (news_text or "") + "\n" + (sentiment or "") + "\n\n"
    except Exception as e:
        print("News failed: " + str(e))

    # E: Market Context (NEW)
    print("[E] Market Context...")
    market_context = ""
    try:
        market_context = fetch_market_context()
        combined_data += (market_context or "") + "\n\n"
        print("Market context: " + str(len(market_context)) + " chars")
    except Exception as e:
        print("Market context failed: " + str(e))

    # Manual supplement
    if manual_text and len(manual_text) > 50:
        combined_data += "## Manual Supplement\n" + str(manual_text or "") + "\n\n"

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

    # Format market context summary for display
    market_summary = ""
    if market_context:
        lines = [l for l in market_context.split("\n") if l.strip() and not l.startswith("##")]
        market_summary = "\n".join(lines[:15])  # First 15 meaningful lines

    report = {
        "ticker": ticker,
        "company": company_name,
        "timestamp": timestamp,
        "raw_data_length": len(combined_data),
        "comparison_table": comparison_table,
        "market_context": market_context,
        "market_summary": market_summary,
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
