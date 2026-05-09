import requests
import json
import time
from datetime import datetime

def get_cik_from_ticker(ticker: str) -> str:
    """把股票代號轉換成 SEC 的 CIK 編號"""
    url = "https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&dateRange=custom&startdt=2020-01-01&forms=10-K"
    
    # 用 SEC 的公司搜尋 API
    search_url = f"https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&forms=10-Q"
    
    # 直接用 company tickers JSON（官方提供，免費）
    tickers_url = "https://www.sec.gov/files/company_tickers.json"
    headers = {"User-Agent": "AI-Investment-HQ research@example.com"}
    
    try:
        resp = requests.get(tickers_url, headers=headers, timeout=15)
        if resp.status_code == 200:
            tickers_data = resp.json()
            ticker_upper = ticker.upper()
            for key, company in tickers_data.items():
                if company.get("ticker", "").upper() == ticker_upper:
                    cik = str(company["cik_str"]).zfill(10)
                    print(f"✅ 找到 CIK: {cik} ({company['title']})")
                    return cik
    except Exception as e:
        print(f"⚠️ CIK 查詢失敗: {e}")
    
    return None

def get_latest_filing_text(cik: str, form_type: str = "10-Q") -> str:
    """抓取最新財報的文字內容"""
    headers = {"User-Agent": "AI-Investment-HQ research@example.com"}
    
    # 取得最新財報清單
    submissions_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    
    try:
        resp = requests.get(submissions_url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return ""
        
        data = resp.json()
        company_name = data.get("name", "Unknown")
        filings = data.get("filings", {}).get("recent", {})
        
        forms = filings.get("form", [])
        accession_numbers = filings.get("accessionNumber", [])
        filing_dates = filings.get("filingDate", [])
        primary_docs = filings.get("primaryDocument", [])
        
        # 找最新的目標報告
        for i, form in enumerate(forms):
            if form == form_type:
                acc_num = accession_numbers[i].replace("-", "")
                filing_date = filing_dates[i]
                primary_doc = primary_docs[i]
                
                print(f"✅ 找到最新 {form_type}: {filing_date}")
                
                # 抓取財報索引頁
                index_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_num}/{accession_numbers[i]}-index.htm"
                
                # 直接抓主要文件
                doc_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_num}/{primary_doc}"
                
                time.sleep(0.5)  # SEC 要求不要爬太快
                doc_resp = requests.get(doc_url, headers=headers, timeout=30)
                
                if doc_resp.status_code == 200:
                    # 提取純文字（去掉 HTML 標籤）
                    text = doc_resp.text
                    
                    # 簡單清理 HTML
                    import re
                    text = re.sub(r"<[^>]+>", " ", text)
                    text = re.sub(r"&nbsp;", " ", text)
                    text = re.sub(r"&amp;", "&", text)
                    text = re.sub(r"&lt;", "<", text)
                    text = re.sub(r"&gt;", ">", text)
                    text = re.sub(r"\s+", " ", text)
                    
                    # 只取關鍵段落（避免太長）
                    # 找 Risk Factors, MD&A, Financial Results 等關鍵區塊
                    key_sections = []
                    
                    # 截取重要段落（前 8000 字 + 後 4000 字）
                    if len(text) > 15000:
                        # 找 Management Discussion 部分
                        mda_start = text.lower().find("management's discussion")
                        if mda_start == -1:
                            mda_start = text.lower().find("results of operations")
                        
                        if mda_start > 0:
                            extract = text[mda_start:mda_start+8000]
                        else:
                            extract = text[:8000]
                        
                        risk_start = text.lower().find("risk factor")
                        if risk_start > 0:
                            extract += "

[風險因素摘要]
" + text[risk_start:risk_start+3000]
                    else:
                        extract = text
                    
                    return f"## {company_name} - {form_type} ({filing_date})

{extract}"
                
                break
    
    except Exception as e:
        print(f"⚠️ SEC 財報抓取失敗: {e}")
    
    return ""

def fetch_sec_filing(ticker: str, form_type: str = "10-Q") -> str:
    """主入口：輸入股票代號，回傳最新財報關鍵文字"""
    print(f"📋 正在抓取  的 SEC {form_type}...")
    
    cik = get_cik_from_ticker(ticker)
    if not cik:
        return f"找不到 {ticker} 的 SEC 資料"
    
    text = get_latest_filing_text(cik, form_type)
    if not text:
        # 嘗試 10-K
        if form_type == "10-Q":
            print("10-Q 未找到，嘗試 10-K...")
            text = get_latest_filing_text(cik, "10-K")
    
    return text if text else f"無法取得 {ticker} 的 {form_type} 內容"

if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "SNDK"
    result = fetch_sec_filing(ticker)
    print(result[:2000])
