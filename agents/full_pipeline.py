import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_fetcher import fetch_stock_data
from sec_fetcher import fetch_sec_filing
from news_fetcher import search_stock_news, analyze_news_sentiment
from analyst import run_analysis, generate_comparison_table

def full_auto_pipeline(ticker: str, persona: str = "all", manual_text: str = "") -> dict:
    ticker = ticker.upper().strip()
    print(f"Starting analysis for {ticker}")
    
    combined_data = f"# {ticker} Full Data Report
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}

"
    company_name = ticker
    
    # A: Yahoo Finance
    print("[A] Yahoo Finance...")
    try:
        stock_data = fetch_stock_data(ticker)
        combined_data += stock_data["summary"] + "

"
        company_name = stock_data["financials"].get("company_name", ticker)
    except Exception as e:
        print(f"Yahoo Finance failed: {e}")
        combined_data += "## Financial Data
Unavailable

"
    
    # B: SEC Filing
    print("[B] SEC EDGAR...")
    try:
        sec_text = fetch_sec_filing(ticker, "10-Q")
        if sec_text and len(sec_text) > 200:
            combined_data += "## SEC 10-Q Filing
" + sec_text[:6000] + "...

"
        else:
            combined_data += "## SEC Filing
No recent 10-Q found

"
    except Exception as e:
        print(f"SEC failed: {e}")
        combined_data += "## SEC Filing
Unavailable

"
    
    # C: News
    print("[C] News...")
    try:
        news_text = search_stock_news(ticker, company_name)
        sentiment = analyze_news_sentiment(news_text, ticker)
        combined_data += news_text + "
" + sentiment + "

"
    except Exception as e:
        print(f"News failed: {e}")
        combined_data += "## News
Unavailable

"
    
    # Manual supplement
    if manual_text and len(manual_text) > 50:
        combined_data += "## Manual Supplement
" + manual_text + "

"
    
    print(f"Data ready: {len(combined_data)} chars")
    print("Running analysis...")
    
    # Personas
    if persona == "all":
        personas = None
    else:
        personas = [p.strip() for p in persona.split(",")]
    
    results = run_analysis(ticker, combined_data, personas)
    
    # Comparison table
    comparison_table = generate_comparison_table(ticker, results)
    
    # Save reports
    os.makedirs("reports", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    report = {
        "ticker": ticker,
        "company": company_name,
        "timestamp": timestamp,
        "raw_data_length": len(combined_data),
        "comparison_table": comparison_table,
        "analyses": {k: v.get("full_analysis", v) if isinstance(v, dict) else v 
                      for k, v in results.items()},
        "structured_results": {k: {kk: vv for kk, vv in v.items() if kk != "full_analysis"}
                                 for k, v in results.items() if isinstance(v, dict)}
    }
    
    json_path = f"reports/{ticker}_{timestamp}.json"
    txt_path = f"reports/{ticker}_{timestamp}.txt"
    
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"# {ticker} ({company_name}) Analysis Report
")
        f.write(f"Generated: {timestamp}
")
        f.write("=" * 60 + "

")
        f.write(comparison_table + "
")
        f.write("=" * 60 + "

")
        for persona_id, result in results.items():
            name = result.get("persona_name", persona_id) if isinstance(result, dict) else persona_id
            analysis = result.get("full_analysis", result) if isinstance(result, dict) else result
            f.write(f"## {name}

")
            f.write(str(analysis) + "

")
            f.write("-" * 40 + "

")
    
    print(f"Reports saved: {txt_path}")
    print("
" + comparison_table)
    
    return report

if __name__ == "__main__":
    ticker = os.environ.get("TICKER") or (sys.argv[1] if len(sys.argv) > 1 else "SNDK")
    persona = os.environ.get("PERSONA", "all")
    manual_text = os.environ.get("FINANCIAL_TEXT", "")
    full_auto_pipeline(ticker, persona, manual_text)
