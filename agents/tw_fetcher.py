"""
tw_fetcher.py - Taiwan Stock Data Fetcher
Free sources:
- Yahoo Finance Chart v8 (price, 52w)
- TWSE API (P/E, P/B, dividend yield)
- FinMind (income statement, balance sheet, cash flow) - completely free
- FMP stable profile (market cap, beta)
"""
import requests
import json
import re
import os
from datetime import datetime


def get_tw_stock_id(ticker: str) -> str:
    return ticker.upper().replace(".TW", "").replace(".TWO", "").strip()


def s(v, d="N/A"):
    """Safe string conversion"""
    return str(v) if v is not None else d


def fmt_b(v, unit="NT$"):
    """Format billions TWD"""
    try:
        n = float(v)
        if abs(n) >= 1e12: return f"{unit}{n/1e12:.2f}兆"
        if abs(n) >= 1e9: return f"{unit}{n/1e9:.1f}B"
        if abs(n) >= 1e6: return f"{unit}{n/1e6:.0f}M"
        return f"{unit}{n:.2f}"
    except Exception:
        return str(v)


def fetch_tw_price(ticker: str) -> dict:
    result = {}
    try:
        resp = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
            headers={"User-Agent": "Mozilla/5.0"},
            params={"interval": "1d", "range": "1d"},
            timeout=10
        )
        if resp.status_code == 200:
            meta = resp.json().get("chart", {}).get("result", [{}])[0].get("meta", {})
            result["price"] = meta.get("regularMarketPrice")
            result["high_52w"] = meta.get("fiftyTwoWeekHigh")
            result["low_52w"] = meta.get("fiftyTwoWeekLow")
            result["currency"] = "TWD"
            print(f"Price: NT${result['price']}")
    except Exception as e:
        print(f"Price failed: {e}")
    return result


def fetch_twse_valuation(stock_id: str) -> dict:
    result = {}
    try:
        resp = requests.get(
            "https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?response=json&date=&selectType=ALL",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10
        )
        if resp.status_code == 200:
            for row in resp.json().get("data", []):
                if row and str(row[0]).strip() == stock_id:
                    result["company_name"] = str(row[1]).strip() if len(row) > 1 else ""
                    result["pe_ratio"] = str(row[5]).strip() if len(row) > 5 else "N/A"
                    result["pb_ratio"] = str(row[6]).strip() if len(row) > 6 else "N/A"
                    result["dividend_yield"] = str(row[3]).strip() + "%" if len(row) > 3 else "N/A"
                    result["financial_period"] = str(row[7]).strip() if len(row) > 7 else ""
                    print(f"TWSE: PE={result['pe_ratio']} PB={result['pb_ratio']}")
                    break
    except Exception as e:
        print(f"TWSE valuation failed: {e}")
    return result


def fetch_finmind(stock_id: str) -> dict:
    """FinMind free API - complete financial statements for Taiwan stocks"""
    result = {}
    headers = {"User-Agent": "Mozilla/5.0"}
    base = "https://api.finmindtrade.com/api/v4/data"

    def get_dataset(dataset):
        try:
            resp = requests.get(
                base,
                params={"dataset": dataset, "data_id": stock_id, "start_date": "2024-01-01"},
                headers=headers,
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                if not data:
                    return {}
                by_date = {}
                for row in data:
                    dt = row.get("date", "")
                    tp = row.get("type", "")
                    val = row.get("value", 0)
                    if dt not in by_date:
                        by_date[dt] = {}
                    by_date[dt][tp] = val
                latest = sorted(by_date.keys())[-1]
                return {"date": latest, "data": by_date[latest]}
        except Exception as e:
            print(f"FinMind {dataset} failed: {e}")
        return {}

    # 1. Income Statement
    inc = get_dataset("TaiwanStockFinancialStatements")
    if inc:
        d = inc["data"]
        date = inc["date"]
        rev = d.get("Revenue")
        gp = d.get("GrossProfit")
        ni = d.get("IncomeAfterTaxes") or d.get("EquityAttributableToOwnersOfParent")
        op = d.get("OperatingIncome")
        eps = d.get("EPS")
        if rev:
            result["revenue"] = fmt_b(rev)
            if gp:
                result["gross_profit"] = fmt_b(gp)
                result["gross_margin"] = f"{gp/rev*100:.1f}%"
            if ni:
                result["net_income"] = fmt_b(ni)
                result["net_margin"] = f"{ni/rev*100:.1f}%"
            if op:
                result["operating_income"] = fmt_b(op)
                result["op_margin"] = f"{op/rev*100:.1f}%"
            result["fiscal_year"] = date[:7]
        if eps:
            result["eps"] = f"NT${eps:.2f}"
        print(f"FinMind income: rev={result.get('revenue')} GM={result.get('gross_margin')}")

    # 2. Balance Sheet
    bs = get_dataset("TaiwanStockBalanceSheet")
    if bs:
        d = bs["data"]
        cash = d.get("CashAndCashEquivalents")
        assets = d.get("TotalAssets")
        liab = d.get("TotalLiabilities")
        equity = d.get("TotalEquity")
        if cash: result["cash"] = fmt_b(cash)
        if assets: result["total_assets"] = fmt_b(assets)
        if liab: result["total_liabilities"] = fmt_b(liab)
        if equity: result["equity"] = fmt_b(equity)
        # Net debt
        debt_keys = ["NoncurrentLiabilities", "ShortTermBorrowings", "LongtermLiabilitiesCurrentPortion"]
        total_debt = sum(d.get(k, 0) or 0 for k in debt_keys)
        if total_debt and cash:
            nd = total_debt - cash
            result["net_debt"] = fmt_b(abs(nd))
            result["net_position"] = "淨現金" if nd < 0 else "淨負債"
        elif cash:
            result["net_position"] = "淨現金（無長期負債）"
        print(f"FinMind BS: cash={result.get('cash')} assets={result.get('total_assets')}")

    # 3. Cash Flow
    cf = get_dataset("TaiwanStockCashFlowsStatement")
    if cf:
        d = cf["data"]
        ocf = d.get("CashFlowsFromOperatingActivities") or d.get("NetCashInflowFromOperatingActivities")
        capex = d.get("PropertyAndPlantAndEquipment")  # negative = outflow
        if ocf:
            result["ocf"] = fmt_b(ocf)
            if capex:
                result["capex"] = fmt_b(abs(capex))
                fcf = ocf + capex  # capex is negative
                result["fcf"] = fmt_b(fcf)
        print(f"FinMind CF: OCF={result.get('ocf')} FCF={result.get('fcf')}")

    return result


def fetch_fmp_profile(ticker: str) -> dict:
    result = {}
    fmp_key = os.environ.get("FMP_API_KEY", "")
    if not fmp_key:
        return result
    try:
        resp = requests.get(
            "https://financialmodelingprep.com/stable/profile",
            params={"symbol": ticker, "apikey": fmp_key},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8
        )
        if resp.status_code == 200 and resp.text.strip():
            profiles = resp.json()
            if isinstance(profiles, list) and profiles:
                p = profiles[0]
                mc = p.get("marketCap", 0)
                if mc:
                    # Market cap from FMP for TW is in TWD
                    result["market_cap"] = fmt_b(mc)
                result["beta"] = str(round(p.get("beta", 0), 2)) if p.get("beta") else "N/A"
                result["volume"] = f"{p.get('volume', 0):,}"
                print(f"FMP: MC={result.get('market_cap')} Beta={result.get('beta')}")
    except Exception as e:
        print(f"FMP profile failed: {e}")
    return result


def fetch_tw_news(stock_id: str) -> list:
    news = []
    try:
        resp = requests.get(
            "https://query1.finance.yahoo.com/v1/finance/search",
            headers={"User-Agent": "Mozilla/5.0"},
            params={"q": stock_id, "newsCount": 6},
            timeout=8
        )
        if resp.status_code == 200:
            for item in resp.json().get("news", [])[:5]:
                ts = item.get("providerPublishTime", 0)
                date = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else ""
                news.append({
                    "title": str(item.get("title", "")),
                    "publisher": str(item.get("publisher", "")),
                    "date": date,
                })
    except Exception as e:
        print(f"News failed: {e}")
    return news


def fetch_tw_stock_data(ticker: str) -> dict:
    stock_id = get_tw_stock_id(ticker)
    print(f"Taiwan stock: {ticker} ({stock_id})")
    result = {"ticker": ticker, "stock_id": stock_id}

    price_data = fetch_tw_price(ticker)
    result.update(price_data)

    val_data = fetch_twse_valuation(stock_id)
    result.update(val_data)

    fin_data = fetch_finmind(stock_id)
    result.update(fin_data)

    fmp_data = fetch_fmp_profile(ticker)
    for k, v in fmp_data.items():
        if k not in result or result[k] in (None, "N/A"):
            result[k] = v

    return result


def build_tw_summary(ticker: str, data: dict, news: list = None) -> str:
    company = data.get("company_name") or ticker
    if news is None:
        news = []
    news_text = "\n".join(
        f"- [{n.get('date','')}] {n.get('title','')} ({n.get('publisher','')})"
        for n in news
    ) or "No recent news"

    price = data.get("price")
    high = data.get("high_52w")
    low = data.get("low_52w")

    lines = [
        f"## {company} ({ticker}) - 台灣上市股票",
        "",
        "### 股價（台幣）",
        f"- 現價: NT${s(price)}",
        f"- 52週高點: NT${s(high)}",
        f"- 52週低點: NT${s(low)}",
        f"- 市值: {s(data.get('market_cap'))}",
        f"- Beta: {s(data.get('beta'))}",
        "",
        "### 估值指標（TWSE）",
        f"- 本益比 P/E: {s(data.get('pe_ratio'))}x",
        f"- 股價淨值比 P/B: {s(data.get('pb_ratio'))}x",
        f"- 殖利率: {s(data.get('dividend_yield'))}",
        f"- EPS: {s(data.get('eps'))}",
        f"- 財報期間: {s(data.get('financial_period'))}",
        "",
        f"### 損益表（{s(data.get('fiscal_year', '年度'))}，台幣）",
        f"- 營收: {s(data.get('revenue'))}",
        f"- 毛利: {s(data.get('gross_profit'))} | 毛利率: {s(data.get('gross_margin'))}",
        f"- 營業利益: {s(data.get('operating_income'))} | 營益率: {s(data.get('op_margin'))}",
        f"- 淨利: {s(data.get('net_income'))} | 淨利率: {s(data.get('net_margin'))}",
        "",
        "### 現金流量（台幣）",
        f"- 營業現金流 OCF: {s(data.get('ocf'))}",
        f"- 資本支出 CapEx: {s(data.get('capex'))}",
        f"- 自由現金流 FCF: {s(data.get('fcf'))}",
        "",
        "### 資產負債表（台幣）",
        f"- 現金: {s(data.get('cash'))}",
        f"- 總資產: {s(data.get('total_assets'))}",
        f"- 股東權益: {s(data.get('equity'))}",
        f"- 淨位置: {s(data.get('net_debt'))} （{s(data.get('net_position'))}）",
        "",
        "### 最新新聞",
        news_text,
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "2330.TW"
    data = fetch_tw_stock_data(ticker)
    news = fetch_tw_news(get_tw_stock_id(ticker))
    print(build_tw_summary(ticker, data, news))
