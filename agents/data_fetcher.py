import os
import json
import requests
from datetime import datetime, timedelta

def fetch_stock_data(ticker: str) -> dict:
    """
    自動抓取股票基本數據與新聞
    使用免費 API，不需要額外 Key
    """
    data = {
        "ticker": ticker,
        "fetched_at": datetime.now().isoformat(),
        "financials": {},
        "news": [],
        "summary": ""
    }
    
    # 1. Yahoo Finance 非官方 API（免費）
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        
        # 基本報價與財務摘要
        url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
        params = {
            "modules": "price,summaryDetail,financialData,defaultKeyStatistics,incomeStatementHistory,cashflowStatementHistory"
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
                "shares_change_pct": key_stats.get("sharesPercentSharesOut", {}).get("fmt", "N/A"),
            }
            print(f"✅ 財務數據抓取成功: {data['financials']['company_name']}")
        else:
            print(f"⚠️ Yahoo Finance 回應異常: {resp.status_code}")
            
    except Exception as e:
        print(f"⚠️ 財務數據抓取失敗: {e}")
    
    # 2. 抓最新新聞（Yahoo Finance 新聞）
    try:
        news_url = f"https://query1.finance.yahoo.com/v1/finance/search"
        news_params = {"q": ticker, "newsCount": 10, "enableFuzzyQuery": False}
        news_resp = requests.get(news_url, headers=headers, params=news_params, timeout=10)
        
        if news_resp.status_code == 200:
            news_items = news_resp.json().get("news", [])
            for item in news_items[:8]:
                data["news"].append({
                    "title": item.get("title", ""),
                    "publisher": item.get("publisher", ""),
                    "published": datetime.fromtimestamp(item.get("providerPublishTime", 0)).strftime("%Y-%m-%d")
                })
            print(f"✅ 新聞抓取成功: {len(data['news'])} 則")
    except Exception as e:
        print(f"⚠️ 新聞抓取失敗: {e}")
    
    # 3. 整合成大師可讀的文字摘要
    f = data["financials"]
    news_text = "
".join([f"- [{n['published']}] {n['title']} ({n['publisher']})") for n in data["news"]])
    
    data["summary"] = f"""
## {f.get('company_name', ticker)} () 數據摘要

### 估值指標
- 當前股價: {f.get('current_price')}
- 市值: {f.get('market_cap')}
- 52週高/低: {f.get('52w_high')} / {f.get('52w_low')}
- 本益比 (P/E): {f.get('pe_ratio')} | 前瞻 P/E: {f.get('forward_pe')}
- P/S 比: {f.get('ps_ratio')} | P/B 比: {f.get('pb_ratio')}
- EV/EBITDA: {f.get('ev_ebitda')}

### 獲利能力
- 毛利率: {f.get('gross_margin')}
- 營業利潤率: {f.get('operating_margin')}
- 淨利率: {f.get('profit_margin')}
- ROE: {f.get('roe')} | ROA: {f.get('roa')}

### 成長與現金流
- 營收成長率 (YoY): {f.get('revenue_growth')}
- 自由現金流: {f.get('free_cashflow')}

### 資產負債
- 現金: {f.get('cash')} | 總負債: {f.get('total_debt')}
- 流通股數: {f.get('shares_outstanding')}
- 放空比率: {f.get('short_ratio')}

### 最新新聞 (近期)
{news_text if news_text else "暫無新聞資料"}
"""
    
    return data


def fetch_and_prepare(ticker: str) -> str:
    """抓數據並回傳給分析師用的文字"""
    print(f"🔍 正在抓取  數據...")
    data = fetch_stock_data(ticker)
    return data["summary"]


if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "SNDK"
    summary = fetch_and_prepare(ticker)
    print(summary)
