import requests
import json
import re
from datetime import datetime


# SEC CIK lookup for common tickers (auto-populated for tickers that don't appear in main JSON)
TICKER_CIK_OVERRIDE = {
    "SNDK": "0002023554",
    "MU": "0000723125",
    "NVDA": "0001045810",
    "AAPL": "0000320193",
    "AMD": "0000002488",
    "INTC": "0000050863",
    "QCOM": "0000804328",
    "AVGO": "0001730168",
    "TSM": "0001046179",   # TAIWAN SEMICONDUCTOR - IFRS+TWD
    "ANET": "0001313925",
    "TER": "0000097210",
    "RMBS": "0000917273",
    "VICR": "0000751629",
    "RDW": "0001819989",
    "ASML": "0000937556",
}

# Companies that file 20-F and use IFRS (not US-GAAP)
IFRS_COMPANIES = {"TSM", "ASML"}
# Approximate FX rates to USD
FX_TO_USD = {"TWD": 0.031, "EUR": 1.08, "GBP": 1.27}



def _safe(v, default="N/A"):
    """Safely convert value to string"""
    return str(v) if v is not None else default


def _fmt_num(v):
    """Format large numbers"""
    try:
        v = float(v)
        if abs(v) >= 1e12: return str(round(v/1e12, 2)) + "T"
        if abs(v) >= 1e9: return str(round(v/1e9, 2)) + "B"
        if abs(v) >= 1e6: return str(round(v/1e6, 1)) + "M"
        return str(round(v, 2))
    except Exception:
        return str(v)


def get_cik_for_ticker(ticker: str) -> str:
    """Get CIK from override table or SEC company_tickers.json"""
    ticker_upper = ticker.upper()
    if ticker_upper in TICKER_CIK_OVERRIDE:
        return TICKER_CIK_OVERRIDE[ticker_upper]
    
    try:
        req = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers={"User-Agent": "AI-Investment-HQ research@example.com"},
            timeout=10
        )
        if req.status_code == 200:
            for key, company in req.json().items():
                if company.get("ticker", "").upper() == ticker_upper:
                    return str(company["cik_str"]).zfill(10)
    except Exception as e:
        print("CIK lookup failed: " + str(e))
    return None


def fetch_sec_xbrl(cik: str, ticker: str = "") -> dict:
    """Fetch fundamental data from SEC XBRL - the most reliable free source"""
    facts = {}
    try:
        cik_padded = cik.lstrip("0").zfill(10)
        url = "https://data.sec.gov/api/xbrl/companyfacts/CIK" + cik_padded + ".json"
        req = requests.get(
            url,
            headers={"User-Agent": "AI-Investment-HQ research@example.com"},
            timeout=15
        )
        if req.status_code == 200:
            all_facts = req.json().get("facts", {})
            ticker_upper = (ticker or "").upper()
            if ticker_upper in IFRS_COMPANIES:
                ifrs_raw = all_facts.get("ifrs-full", {})
                # Map IFRS keys to US-GAAP equivalents
                raw = {}
                ifrs_map = {
                    "Revenues": "Revenue",
                    "RevenueFromContractWithCustomerExcludingAssessedTax": "Revenue",
                    "GrossProfit": "GrossProfit",
                    "NetIncomeLoss": "ProfitLoss",
                    "OperatingIncomeLoss": "ProfitFromOperations",
                    "Assets": "Assets",
                    "Liabilities": "Liabilities",
                    "CashAndCashEquivalentsAtCarryingValue": "CashAndCashEquivalents",
                    "LongTermDebt": "NoncurrentPortionOfLongtermBorrowings",
                    "StockholdersEquity": "Equity",
                    "NetCashProvidedByUsedInOperatingActivities": "CashFlowsFromUsedInOperatingActivities",
                    "PaymentsToAcquirePropertyPlantAndEquipment": "PurchaseOfPropertyPlantAndEquipment",
                    "ShareBasedCompensation": "ExpenseFromSharebasedPaymentTransactionsWithEmployees",
                    "GoodwillAndIntangibleAssetsNet": "Goodwill",
                    "InventoryNet": "Inventories",
                }
                for gaap_key, ifrs_key in ifrs_map.items():
                    if ifrs_key in ifrs_raw:
                        raw[gaap_key] = ifrs_raw[ifrs_key]
                # Set FX rate for conversion
                if ticker_upper == "TSM":
                    fx_rate = FX_TO_USD.get("TWD", 0.031)
                elif ticker_upper == "ASML":
                    fx_rate = FX_TO_USD.get("EUR", 1.08)
                else:
                    fx_rate = 1.0
                print("IFRS mode: " + ticker_upper + " fx=" + str(fx_rate))
            else:
                raw = all_facts.get("us-gaap", {})
                fx_rate = 1.0
            
            def get_latest(key, form_types=None):
                """Get latest value - prefer annual (10-K) for consistency in ratio calculations"""
                if form_types is None:
                    form_types = ["10-K", "10-Q"]
                data = raw.get(key, {}).get("units", {}).get("USD", [])
                
                # First try annual (10-K) - most consistent for ratios
                annual = [x for x in data if x.get("form") == "10-K" and x.get("end","") >= "2022-01-01"]
                if annual:
                    return sorted(annual, key=lambda x: x.get("end",""))[-1].get("val")
                
                # Fall back to quarterly single-period entries (frame=CYxxxxQx)
                quarterly = [x for x in data if x.get("form") == "10-Q" 
                             and x.get("frame","").startswith("CY20")
                             and "Q" in x.get("frame","")
                             and x.get("end","") >= "2022-01-01"]
                if quarterly:
                    return sorted(quarterly, key=lambda x: x.get("end",""))[-1].get("val")
                
                # Last resort: any 10-Q
                any_q = [x for x in data if x.get("form") in form_types and x.get("end","") >= "2022-01-01"]
                if any_q:
                    return sorted(any_q, key=lambda x: x.get("end",""))[-1].get("val")
                return None
            
            def get_latest_shares(key):
                data = raw.get(key, {}).get("units", {}).get("shares", [])
                filtered = [x for x in data if x.get("form") in ["10-K", "10-Q"]]
                if not filtered:
                    return None
                return sorted(filtered, key=lambda x: x.get("end", ""))[-1].get("val")
            
            # Revenue: try multiple XBRL keys (different companies use different standards)
            rev = (get_latest("Revenues") or
                   get_latest("RevenueFromContractWithCustomerExcludingAssessedTax") or
                   get_latest("RevenueFromContractWithCustomerIncludingAssessedTax") or
                   get_latest("SalesRevenueNet") or
                   get_latest("SalesRevenueGoodsNet"))
            gp = get_latest("GrossProfit")
            ni = get_latest("NetIncomeLoss")
            op = get_latest("OperatingIncomeLoss")
            assets = get_latest("Assets")
            liabilities = get_latest("Liabilities")
            cash = get_latest("CashAndCashEquivalentsAtCarryingValue")
            ltdebt = get_latest("LongTermDebt")
            equity = get_latest("StockholdersEquity")
            ocf = get_latest("NetCashProvidedByUsedInOperatingActivities")
            capex = get_latest("PaymentsToAcquirePropertyPlantAndEquipment")
            sbc = get_latest("ShareBasedCompensation")
            goodwill = get_latest("GoodwillAndIntangibleAssetsNet")
            inventory = get_latest("InventoryNet")
            shares = get_latest_shares("CommonStockSharesOutstanding")
            
            if capex and ocf:
                fcf = ocf - capex
            else:
                fcf = None
            
            # Apply FX conversion if needed (e.g. TSM reports in TWD)
            if fx_rate != 1.0:
                def _convert(v):
                    return int(v * fx_rate) if v is not None else None
                rev = _convert(rev); gp = _convert(gp); ni = _convert(ni)
                op = _convert(op); assets = _convert(assets)
                liabilities = _convert(liabilities); cash = _convert(cash)
                ltdebt = _convert(ltdebt); equity = _convert(equity)
                ocf = _convert(ocf); capex = _convert(capex)
                sbc = _convert(sbc); goodwill = _convert(goodwill)
                inventory = _convert(inventory); fcf = _convert(fcf)
            
            facts["revenue"] = _fmt_num(rev) if rev else None
            facts["gross_profit"] = _fmt_num(gp) if gp else None
            facts["net_income"] = _fmt_num(ni) if ni else None
            facts["operating_income"] = _fmt_num(op) if op else None
            facts["total_assets"] = _fmt_num(assets) if assets else None
            facts["total_liabilities"] = _fmt_num(liabilities) if liabilities else None
            facts["cash"] = _fmt_num(cash) if cash else None
            facts["long_term_debt"] = _fmt_num(ltdebt) if ltdebt else None
            facts["equity"] = _fmt_num(equity) if equity else None
            facts["operating_cashflow"] = _fmt_num(ocf) if ocf else None
            facts["capex"] = _fmt_num(capex) if capex else None
            facts["free_cashflow"] = _fmt_num(fcf) if fcf else None
            facts["sbc"] = _fmt_num(sbc) if sbc else None
            facts["goodwill_intangibles"] = _fmt_num(goodwill) if goodwill else None
            facts["inventory"] = _fmt_num(inventory) if inventory else None
            facts["shares_outstanding"] = _fmt_num(shares) if shares else None
            
            # Derived ratios
            if gp and rev and rev > 0:
                facts["gross_margin"] = str(round(gp/rev*100, 1)) + "%"
            if ni and rev and rev > 0:
                facts["net_margin"] = str(round(ni/rev*100, 1)) + "%"
            if goodwill and assets and assets > 0:
                facts["goodwill_ratio"] = str(round(goodwill/assets*100, 1)) + "%"
            if sbc and rev and rev > 0:
                facts["sbc_pct"] = str(round(sbc/rev*100, 1)) + "%"
            if cash and ltdebt:
                net_debt = ltdebt - cash
                facts["net_debt"] = _fmt_num(net_debt)
                facts["net_cash"] = "Net Cash" if net_debt < 0 else "Net Debt"
            
            print("SEC XBRL OK: " + str(len(facts)) + " metrics")
    except Exception as e:
        print("SEC XBRL failed: " + str(e))
    
    return facts


def fetch_stock_price(ticker: str) -> dict:
    """Fetch current price via Yahoo Finance Chart API v8 (most reliable free endpoint)"""
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/" + ticker
        params = {"interval": "1d", "range": "1d"}
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.yahoo.com/"}
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        if resp.status_code == 200:
            meta = resp.json().get("chart", {}).get("result", [{}])[0].get("meta", {})
            return {
                "current_price": meta.get("regularMarketPrice"),
                "52w_high": meta.get("fiftyTwoWeekHigh"),
                "52w_low": meta.get("fiftyTwoWeekLow"),
                "prev_close": meta.get("chartPreviousClose"),
            }
    except Exception as e:
        print("Price fetch failed: " + str(e))
    return {}


def fetch_company_name(ticker: str) -> str:
    """Get company name from SEC company_tickers.json"""
    try:
        req = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers={"User-Agent": "AI-Investment-HQ research@example.com"},
            timeout=10
        )
        if req.status_code == 200:
            for key, company in req.json().items():
                if company.get("ticker", "").upper() == ticker.upper():
                    return company.get("title", ticker)
    except Exception:
        pass
    return ticker


def fetch_news(ticker: str) -> list:
    """Fetch news from Yahoo Finance search"""
    news = []
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(
            "https://query1.finance.yahoo.com/v1/finance/search",
            headers=headers,
            params={"q": ticker, "newsCount": 8},
            timeout=8
        )
        if resp.status_code == 200:
            for item in resp.json().get("news", [])[:6]:
                news.append({
                    "title": item.get("title", ""),
                    "publisher": item.get("publisher", ""),
                    "published": datetime.fromtimestamp(
                        item.get("providerPublishTime", 0)
                    ).strftime("%Y-%m-%d") if item.get("providerPublishTime") else ""
                })
    except Exception as e:
        print("News failed: " + str(e))
    return news


def fetch_stock_data(ticker: str) -> dict:
    """
    Main function: fetch comprehensive stock data.
    Uses SEC XBRL for fundamentals (most reliable), Yahoo Chart for price.
    """
    ticker = ticker.upper().strip()
    data = {
        "ticker": ticker,
        "fetched_at": datetime.now().isoformat(),
        "financials": {},
        "news": [],
        "summary": ""
    }
    
    # 1. Get company name
    company_name = fetch_company_name(ticker)
    data["financials"]["company_name"] = company_name
    print("Company: " + company_name)
    
    # 2. Get current price
    price_data = fetch_stock_price(ticker)
    data["financials"].update(price_data)
    
    # 3. Get fundamentals from SEC XBRL
    cik = get_cik_for_ticker(ticker)
    xbrl_data = {}
    if cik:
        xbrl_data = fetch_sec_xbrl(cik, ticker)
        data["financials"].update(xbrl_data)
    else:
        print("No CIK found for " + ticker)
    
    # 4. News
    data["news"] = fetch_news(ticker)
    
    # 5. Build summary
    f = data["financials"]
    price = f.get("current_price")
    
    # Calculate market cap if we have price + shares
    market_cap_str = "N/A"
    if price and xbrl_data.get("shares_outstanding"):
        try:
            shares_num = float(xbrl_data["shares_outstanding"].replace("M","e6").replace("B","e9").replace("T","e12"))
            mc = price * shares_num
            market_cap_str = _fmt_num(mc)
        except Exception:
            pass
    
    # Calculate forward P/E if we have price + EPS proxy
    pe_str = "N/A"
    if price and xbrl_data.get("net_income") and xbrl_data.get("shares_outstanding"):
        try:
            ni_num = float(xbrl_data["net_income"].replace("B","e9").replace("M","e6").replace("T","e12"))
            shares_num = float(xbrl_data["shares_outstanding"].replace("M","e6").replace("B","e9"))
            eps = ni_num / shares_num
            if eps > 0:
                pe = price / eps
                pe_str = str(round(pe, 1)) + "x"
        except Exception:
            pass
    
    news_lines = ["- [" + n.get("published","") + "] " + n.get("title","") for n in data["news"]]
    news_text = "\n".join(news_lines) if news_lines else "No recent news"
    
    data["summary"] = (
        "## " + company_name + " ($" + ticker + ") - Comprehensive Data\n\n"
        "### Price\n"
        "- Current: $" + _safe(price) + "\n"
        "- 52W High/Low: $" + _safe(f.get("52w_high")) + " / $" + _safe(f.get("52w_low")) + "\n"
        "- Market Cap (est.): " + market_cap_str + "\n"
        "- P/E (est.): " + pe_str + "\n\n"
        "### Income Statement (SEC XBRL - Latest)\n"
        "- Revenue: " + _safe(f.get("revenue")) + "\n"
        "- Gross Profit: " + _safe(f.get("gross_profit")) + " | Gross Margin: " + _safe(f.get("gross_margin")) + "\n"
        "- Operating Income: " + _safe(f.get("operating_income")) + "\n"
        "- Net Income: " + _safe(f.get("net_income")) + " | Net Margin: " + _safe(f.get("net_margin")) + "\n\n"
        "### Cash Flow\n"
        "- Operating CF: " + _safe(f.get("operating_cashflow")) + "\n"
        "- CapEx: " + _safe(f.get("capex")) + "\n"
        "- Free Cash Flow: " + _safe(f.get("free_cashflow")) + "\n"
        "- SBC: " + _safe(f.get("sbc")) + " (" + _safe(f.get("sbc_pct")) + " of revenue)\n\n"
        "### Balance Sheet\n"
        "- Cash: " + _safe(f.get("cash")) + "\n"
        "- Long-term Debt: " + _safe(f.get("long_term_debt")) + "\n"
        "- Net Position: " + _safe(f.get("net_debt")) + " (" + _safe(f.get("net_cash")) + ")\n"
        "- Total Assets: " + _safe(f.get("total_assets")) + "\n"
        "- Equity: " + _safe(f.get("equity")) + "\n"
        "- Goodwill+Intangibles: " + _safe(f.get("goodwill_intangibles")) + " (" + _safe(f.get("goodwill_ratio")) + " of assets)\n"
        "- Inventory: " + _safe(f.get("inventory")) + "\n"
        "- Shares Outstanding: " + _safe(f.get("shares_outstanding")) + "\n\n"
        "### Recent News\n"
        + news_text
    )
    
    return data


def fetch_and_prepare(ticker: str) -> str:
    data = fetch_stock_data(ticker)
    return data["summary"]


if __name__ == "__main__":
    import sys
    t = sys.argv[1] if len(sys.argv) > 1 else "MU"
    print(fetch_and_prepare(t))
