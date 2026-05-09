import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_fetcher import fetch_stock_data
from sec_fetcher import fetch_sec_filing
from news_fetcher import search_stock_news, analyze_news_sentiment
from fmp_fetcher import fetch_fmp_financials
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

    # B: FMP Detailed Financials (FCF, SBC, Balance Sheet)
    print("[B] Financial Modeling Prep...")
    try:
        fmp_text = fetch_fmp_financials(ticker)
        if fmp_text and len(fmp_text) > 100:
            combined_data += fmp_text + "\n\n"
            print("FMP data added: " + str(len(fmp_text)) + " chars")
        else:
            print("FMP: no data (demo key limitation or ticker not found)")
            combined_data += "## FMP Financials\nNot available for this ticker with current API key\n\n"
    except Exception as e:
        print("FMP failed: " + str(e))
        combined_data += "## FMP Financials\nUnavailable\n\n"

    # C: SEC Filing
    print("[C] SEC EDGAR...")
    try:
        sec_text = fetch_sec_filing(ticker, "10-Q")
        if sec_text and len(sec_text) > 200:
            combined_data += "## SEC 10-Q Filing\n" + sec_text[:6000] + "...\n\n"
        else:
            combined_data += "## SEC Filing\nNo recent 10-Q found\n\n"
    except Exception as e:
        print("SEC failed: " + str(e))
        combined_data += "## SEC Filing\nUnavailable\n\n"

    # D: News
    print("[D] News...")
    try:
        news_text = search_stock_news(ticker, company_name)
        sentiment = analyze_news_sentiment(news_text, ticker)
        combined_data += news_text + "\n" + sentiment + "\n\n"
    except Exception as e:
        print("News failed: " + str(e))
        combined_data += "## News\nUnavailable\n\n"

    # Manual supplement
    if manual_text and len(manual_text) > 50:
        combined_data += "## Manual Supplement (Earnings Call / Analysis)\n" + manual_text + "\n\n"

    print("Data ready: " + str(len(combined_data)) + " chars")
    print("Running analysis...")

    if persona == "all":
        personas = None
    else:
        personas = [p.strip() for p in persona.split(",")]

    results = run_analysis(ticker, combined_data, personas)
    comparison_table = generate_comparison_table(ticker, results)

    os.makedirs("reports", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    report = {
        "ticker": ticker,
        "company": company_name,
        "timestamp": timestamp,
        "raw_data_length": len(combined_data),
        "comparison_table": comparison_table,
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
    txt_path = "reports/" + ticker + "_" + timestamp + ".txt"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("# " + ticker + " (" + company_name + ") Analysis Report\n")
        f.write("Generated: " + timestamp + "\n")
        f.write("=" * 60 + "\n\n")
        f.write(comparison_table + "\n")
        f.write("=" * 60 + "\n\n")
        for persona_id, result in results.items():
            name = result.get("persona_name", persona_id) if isinstance(result, dict) else persona_id
            analysis = result.get("full_analysis", result) if isinstance(result, dict) else result
            f.write("## " + name + "\n\n")
            f.write(str(analysis) + "\n\n")
            f.write("-" * 40 + "\n\n")

    print("Reports saved: " + txt_path)
    print("\n" + comparison_table)

    return report


if __name__ == "__main__":
    ticker = os.environ.get("TICKER") or (sys.argv[1] if len(sys.argv) > 1 else "SNDK")
    persona = os.environ.get("PERSONA", "all")
    manual_text = os.environ.get("FINANCIAL_TEXT", "")
    full_auto_pipeline(ticker, persona, manual_text)
