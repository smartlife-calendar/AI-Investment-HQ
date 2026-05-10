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
        # PARALLEL DATA FETCH: all sources simultaneously (~10s instead of 35s)
        import concurrent.futures as _cf
        print("[PARALLEL] Fetching all US stock data sources simultaneously...")
        
        def _fetch_main():
            try:
                return fetch_stock_data(ticker)
            except Exception as e:
                print("Main data failed:", e)
                return {"summary": "", "financials": {"company_name": ticker}}
        
        def _fetch_fmp():
            try:
                return fetch_fmp_financials(ticker) or ""
            except Exception as e:
                return ""
        
        def _fetch_technical():
            try:
                return analyze_technical(ticker) or ""
            except Exception as e:
                return ""
        
        def _fetch_news():
            try:
                nt = search_stock_news(ticker, ticker)
                sent = analyze_news_sentiment(nt, ticker)
                return (nt or "") + "\n" + (sent or "")
            except Exception as e:
                return ""
        
        def _fetch_market():
            try:
                from market_context_fetcher import fetch_market_context
                return fetch_market_context() or ""
            except Exception as e:
                return ""
        
        with _cf.ThreadPoolExecutor(max_workers=5) as ex:
            f_main = ex.submit(_fetch_main)
            f_fmp = ex.submit(_fetch_fmp)
            f_tech = ex.submit(_fetch_technical)
            f_news = ex.submit(_fetch_news)
            f_market = ex.submit(_fetch_market)
            
            stock_data = f_main.result(timeout=30)
            fmp_text = f_fmp.result(timeout=20)
            tech_summary = f_tech.result(timeout=20)
            news_combined = f_news.result(timeout=15)
            market_context = f_market.result(timeout=15)
        
        combined_data += str(stock_data.get("summary") or "") + "\n\n"
        company_name = stock_data["financials"].get("company_name") or ticker
        
        if fmp_text and len(fmp_text) > 100:
            combined_data += fmp_text + "\n\n"
        if tech_summary:
            combined_data += tech_summary + "\n\n"
        if news_combined:
            combined_data += news_combined + "\n\n"
        if market_context:
            combined_data += str(market_context) + "\n\n"
        print(f"[PARALLEL] Done: {ticker} company={company_name}")
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
