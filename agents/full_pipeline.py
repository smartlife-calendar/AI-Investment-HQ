import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_fetcher import fetch_stock_data
from sec_fetcher import fetch_sec_filing
from news_fetcher import search_stock_news, analyze_news_sentiment
from analyst import run_analysis

def full_auto_pipeline(ticker: str, persona: str = "all", manual_text: str = "") -> dict:
    """
    全自動三合一管道
    A: Yahoo Finance 財務數據
    B: SEC EDGAR 財報文字  
    C: 多源新聞爬蟲
    全部整合後交給大師分析
    """
    ticker = ticker.upper().strip()
    print(f"
{'='*60}")
    print(f"🚀 啟動 AI 大師分析: ")
    print(f"{'='*60}
")
    
    combined_data = f"#  全方位數據報告
生成時間: {datetime.now().strftime('%Y-%m-%d %H:%M')}

"
    
    # === A: Yahoo Finance 財務數據 ===
    print("[A] 抓取 Yahoo Finance 財務數據...")
    try:
        stock_data = fetch_stock_data(ticker)
        combined_data += stock_data["summary"] + "

"
        company_name = stock_data["financials"].get("company_name", ticker)
    except Exception as e:
        print(f"⚠️ Yahoo Finance 失敗: {e}")
        company_name = ticker
        combined_data += f"## 財務數據
暫無 (抓取失敗)

"
    
    # === B: SEC 財報文字 ===
    print("
[B] 抓取 SEC EDGAR 財報...")
    try:
        sec_text = fetch_sec_filing(ticker, "10-Q")
        if sec_text and len(sec_text) > 200:
            # 只取前 6000 字避免 token 超限
            combined_data += "## SEC 財報摘要 (10-Q)
"
            combined_data += sec_text[:6000] + "...

"
        else:
            combined_data += "## SEC 財報
暫無最新 10-Q 資料

"
    except Exception as e:
        print(f"⚠️ SEC 抓取失敗: {e}")
        combined_data += "## SEC 財報
暫無 (抓取失敗)

"
    
    # === C: 新聞爬蟲 ===
    print("
[C] 抓取最新新聞...")
    try:
        news_text = search_stock_news(ticker, company_name)
        sentiment = analyze_news_sentiment(news_text, ticker)
        combined_data += news_text + "
"
        combined_data += sentiment + "

"
    except Exception as e:
        print(f"⚠️ 新聞抓取失敗: {e}")
        combined_data += "## 新聞
暫無 (抓取失敗)

"
    
    # === 如果有手動補充文字 ===
    if manual_text and len(manual_text) > 50:
        combined_data += "## 手動補充資料 (法說會/分析文章)
"
        combined_data += manual_text + "

"
    
    print(f"
✅ 數據整合完成，共 {len(combined_data)} 字")
    print(f"
{'='*60}")
    print("🧠 啟動大師分析引擎...")
    print(f"{'='*60}
")
    
    # === 決定 personas ===
    if persona == "all":
        personas = None
    else:
        personas = [p.strip() for p in persona.split(",")]
    
    # === 執行大師分析 ===
    results = run_analysis(ticker, combined_data, personas)
    
    # === 存報告 ===
    os.makedirs("reports", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    report = {
        "ticker": ticker,
        "company": company_name,
        "timestamp": timestamp,
        "raw_data_length": len(combined_data),
        "analyses": results
    }
    
    json_path = f"reports/{ticker}_{timestamp}.json"
    txt_path = f"reports/{ticker}_{timestamp}.txt"
    
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"#  ({company_name}) 大師解析報告
")
        f.write(f"生成時間: {timestamp}
")
        f.write("=" * 60 + "

")
        
        f.write("## 原始數據摘要
")
        f.write(combined_data[:3000] + "...

")
        f.write("=" * 60 + "

")
        
        for persona_id, analysis in results.items():
            f.write(f"## 【{persona_id}】大師解析

")
            f.write(analysis + "

")
            f.write("-" * 40 + "

")
    
    print(f"
✅ 完成！報告已存至:")
    print(f"   {txt_path}")
    
    # 印出結果
    print("
" + "=" * 60)
    for persona_id, analysis in results.items():
        print(f"
【{persona_id}】")
        print("-" * 40)
        print(analysis)
    
    return report

if __name__ == "__main__":
    ticker = os.environ.get("TICKER") or (sys.argv[1] if len(sys.argv) > 1 else "SNDK")
    persona = os.environ.get("PERSONA", "all")
    manual_text = os.environ.get("FINANCIAL_TEXT", "")
    
    full_auto_pipeline(ticker, persona, manual_text)
