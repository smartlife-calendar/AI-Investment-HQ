import os
import json
from datetime import datetime
from agents.analyst import run_analysis, analyze_stock

def main():
    ticker = os.environ.get("TICKER", "UNKNOWN")
    persona = os.environ.get("PERSONA", "all")
    financial_text = os.environ.get("FINANCIAL_TEXT", "")
    
    if not financial_text:
        print("ERROR: 沒有提供財報文字")
        return
    
    print(f"開始分析 ${ticker}...")
    
    # 決定跑哪些 persona
    if persona == "all":
        personas = None  # run_analysis 會自動跑全部
    else:
        personas = [persona]
    
    results = run_analysis(ticker, financial_text, personas)
    
    # 存到 reports 資料夾
    os.makedirs("reports", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = f"reports/{ticker}_{timestamp}.json"
    
    report = {
        "ticker": ticker,
        "timestamp": timestamp,
        "analyses": results
    }
    
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    # 也輸出純文字版
    txt_path = f"reports/{ticker}_{timestamp}.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"# {ticker} 大師解析報告
")
        f.write(f"時間: {timestamp}

")
        for persona_id, analysis in results.items():
            f.write(f"---
")
            f.write(f"## {persona_id}

")
            f.write(analysis)
            f.write("

")
    
    print(f"報告已儲存: {txt_path}")
    print("
" + "="*60)
    for persona_id, analysis in results.items():
        print(f"
【{persona_id}】
")
        print(analysis)
        print()

if __name__ == "__main__":
    main()
