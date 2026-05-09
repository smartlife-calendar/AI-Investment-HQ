import os
import json
from datetime import datetime
import sys

# 加入 agents 路徑
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_fetcher import fetch_and_prepare
from analyst import run_analysis

def main():
    # 從環境變數或命令列讀取參數
    ticker = os.environ.get("TICKER") or (sys.argv[1] if len(sys.argv) > 1 else None)
    persona = os.environ.get("PERSONA", "all")
    financial_text_override = os.environ.get("FINANCIAL_TEXT", "")
    
    if not ticker:
        print("ERROR: 請提供股票代號")
        print("用法: python agents/full_pipeline.py SNDK [dashu_veteran]")
        return
    
    ticker = ticker.upper().strip()
    
    # 決定財報來源
    if financial_text_override and len(financial_text_override) > 50:
        # 用戶手動提供財報文字（更詳細）
        print(f"📄 使用手動提供的財報文字")
        analysis_text = financial_text_override
        source = "manual"
    else:
        # 自動抓取
        print(f"🌐 自動抓取  市場數據...")
        analysis_text = fetch_and_prepare(ticker)
        source = "auto"
    
    if not analysis_text:
        print("ERROR: 無法取得分析資料")
        return
    
    # 決定跑哪些 persona
    if persona == "all":
        personas = None
    else:
        personas = [persona]
    
    print(f"
🧠 啟動大師分析引擎...")
    results = run_analysis(ticker, analysis_text, personas)
    
    # 存報告
    os.makedirs("reports", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    report = {
        "ticker": ticker,
        "timestamp": timestamp,
        "source": source,
        "raw_data": analysis_text,
        "analyses": results
    }
    
    json_path = f"reports/{ticker}_{timestamp}.json"
    txt_path = f"reports/{ticker}_{timestamp}.txt"
    
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"#  大師解析報告
")
        f.write(f"生成時間: {timestamp} | 資料來源: {source}
")
        f.write("=" * 60 + "

")
        
        f.write("## 原始數據摘要
")
        f.write(analysis_text + "

")
        f.write("=" * 60 + "

")
        
        for persona_id, analysis in results.items():
            f.write(f"## {persona_id} 解析

")
            f.write(analysis + "

")
            f.write("-" * 40 + "

")
    
    print(f"
✅ 報告完成")
    print(f"   JSON: {json_path}")
    print(f"   TXT:  {txt_path}")
    print("
" + "=" * 60)
    
    for persona_id, analysis in results.items():
        print(f"
【{persona_id} 說】")
        print("-" * 40)
        print(analysis)
        print()

if __name__ == "__main__":
    main()
