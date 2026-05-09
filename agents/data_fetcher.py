"""
data_fetcher.py - Stock data fetcher
Sources: Yahoo Finance Chart API (price) + SEC XBRL (US fundamentals) + FMP (analyst estimates + Taiwan stocks)
All values go through safe() to prevent NoneType errors.
"""
import requests
import json
import os
import re
from datetime import datetime


# === CIK lookup table for US-listed stocks ===
TICKER_CIK = {
    "SNDK": "0002023554", "MU": "0000723125", "NVDA": "0001045810",
    "AAPL": "0000320193", "AMD": "0000002488", "INTC": "0000050863",
    "QCOM": "0000804328", "AVGO": "0001730168", "TSM": "0001046179",
    "ANET": "0001313925", "TER": "0000097210", "RMBS": "0000917273",
    "VICR": "0000751629", "RDW": "0001819989", "ASML": "0000937556",
    "LRCX": "0000707549", "KLAC": "0000319201", "AMAT": "0000796343",
    "LITE": "0001234006", "NVTS": "0001838672",
}

# IFRS companies (file 20-F instead of 10-K)
IFRS_TICKERS = {"TSM", "ASML"}

# FX rates (TWD/EUR/GBP → USD)
FX_USD = {"TWD": 0.031, "EUR": 1.08, "GBP": 1.27}


def safe(v, default="N/A"):
    """Always return a string, never None."""
    if v is None:
        return default
    return str(v)


def fmt_num(v):
    """Format number to readable string."""
    try:
        n = float(v)
        if abs(n) >= 1e12:
            return f"${n/1e12:.2f}T"
        if abs(n) >= 1e9:
            return f"${n/1e9:.2f}B"
        if abs(n) >= 1e6:
            return f"${n/1e6:.1f}M"
        return f"${n:.2f}"
    except Exception:
        return str(v)


def get_price(ticker: str) -> dict:
    """Yahoo Finance Chart API v8 - works for US + Taiwan stocks."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, params={"interval": "1d", "range": "1d"}, timeout=10)
        if resp.status_code == 200:
            meta = resp.json().get("chart", {}).get("result", [{}])[0].get("meta", {})
            return {
                "price": meta.get("regularMarketPrice"),
                "high_52w": meta.get("fiftyTwoWeekHigh"),
                "low_52w": meta.get("fiftyTwoWeekLow"),
                "prev_close": meta.get("chartPreviousClose"),
                "currency": meta.get("currency", "USD"),
            }
    except Exception as e:
        print(f"Price fetch failed for {ticker}: {e}")
    return {}


def get_cik(ticker: str) -> str:
    """Get SEC CIK - from override table or SEC company_tickers.json."""
    t = ticker.upper().split(".")[0]  # handle 2330.TW → 2330
    if t in TICKER_CIK:
        return TICKER_CIK[t]
    try:
        resp = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers={"User-Agent": "AI-Investment-HQ research@example.com"},
            timeout=10
        )
        if resp.status_code == 200:
            for _, co in resp.json().items():
                if co.get("ticker", "").upper() == t:
                    return str(co["cik_str"]).zfill(10)
    except Exception:
        pass
    return None


def get_sec_xbrl(cik: str, ticker: str) -> dict:
    """Fetch financials from SEC XBRL (US-GAAP or IFRS)."""
    result = {}
    try:
        cik_pad = cik.lstrip("0").zfill(10)
        resp = requests.get(
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_pad}.json",
            headers={"User-Agent": "AI-Investment-HQ research@example.com"},
            timeout=15
        )
        if resp.status_code != 200:
            return result

        all_facts = resp.json().get("facts", {})
        t = ticker.upper().split(".")[0]
        is_ifrs = t in IFRS_TICKERS

        if is_ifrs:
            raw = all_facts.get("ifrs-full", {})
            key_map = {
                "Revenues": "Revenue",
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
                "CommonStockSharesOutstanding": "IssuedCapital",
            }
            remapped = {}
            for gaap, ifrs in key_map.items():
                if ifrs in raw:
                    remapped[gaap] = raw[ifrs]
            raw_gaap = remapped
            # FX rate
            if t == "TSM":
                fx = FX_USD.get("TWD", 0.031)
            elif t == "ASML":
                fx = FX_USD.get("EUR", 1.08)
            else:
                fx = 1.0
        else:
            raw_gaap = all_facts.get("us-gaap", {})
            fx = 1.0

        def latest(key, fallbacks=None):
            """Get latest annual value from XBRL."""
            keys_to_try = [key] + (fallbacks or [])
            for k in keys_to_try:
                data = raw_gaap.get(k, {}).get("units", {}).get("USD", [])
                if not data:
                    # Try TWD for IFRS
                    data = raw_gaap.get(k, {}).get("units", {}).get("TWD", [])
                if not data:
                    data = raw_gaap.get(k, {}).get("units", {})
                    if data:
                        # Get first available currency
                        first_currency = list(data.values())[0] if data else []
                        data = first_currency
                    else:
                        data = []

                # Prefer 10-K annual
                annual = [x for x in data if x.get("form") == "10-K" and x.get("end", "") >= "2022-01-01"]
                if annual:
                    v = sorted(annual, key=lambda x: x.get("end", ""))[-1].get("val")
                    return v * fx if v and fx != 1.0 else v

                # Fall back to 10-Q single quarter
                quarterly = [x for x in data if x.get("form") == "10-Q"
                             and x.get("frame", "").startswith("CY20")
                             and "Q" in x.get("frame", "")
                             and x.get("end", "") >= "2022-01-01"]
                if quarterly:
                    v = sorted(quarterly, key=lambda x: x.get("end", ""))[-1].get("val")
                    return v * fx if v and fx != 1.0 else v
            return None

        def latest_shares():
            for k in ["CommonStockSharesOutstanding", "CommonStockSharesIssued"]:
                data = raw_gaap.get(k, {}).get("units", {}).get("shares", [])
                recent = [x for x in data if x.get("end", "") >= "2022-01-01"]
                if recent:
                    return sorted(recent, key=lambda x: x.get("end", ""))[-1].get("val")
            return None

        rev = latest("Revenues", ["RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"])
        gp = latest("GrossProfit")
        ni = latest("NetIncomeLoss")
        op = latest("OperatingIncomeLoss")
        assets = latest("Assets")
        liab = latest("Liabilities")
        cash = latest("CashAndCashEquivalentsAtCarryingValue")
        ltdebt = latest("LongTermDebt")
        equity = latest("StockholdersEquity")
        ocf = latest("NetCashProvidedByUsedInOperatingActivities")
        capex = latest("PaymentsToAcquirePropertyPlantAndEquipment")
        sbc = latest("ShareBasedCompensation")
        goodwill = latest("GoodwillAndIntangibleAssetsNet")
        inventory = latest("InventoryNet")
        shares = latest_shares()
        fcf = (ocf - capex) if ocf and capex else None

        if rev:
            result["revenue"] = fmt_num(rev)
            if gp:
                result["gross_profit"] = fmt_num(gp)
                result["gross_margin"] = f"{gp/rev*100:.1f}%"
            if ni:
                result["net_income"] = fmt_num(ni)
                result["net_margin"] = f"{ni/rev*100:.1f}%"
            if op:
                result["operating_income"] = fmt_num(op)
                result["op_margin"] = f"{op/rev*100:.1f}%"
            if sbc:
                result["sbc"] = fmt_num(sbc)
                result["sbc_pct"] = f"{sbc/rev*100:.1f}%"

        if assets:
            result["total_assets"] = fmt_num(assets)
            if goodwill:
                result["goodwill"] = fmt_num(goodwill)
                result["goodwill_ratio"] = f"{goodwill/assets*100:.1f}%"
        if cash:
            result["cash"] = fmt_num(cash)
        if ltdebt:
            result["long_term_debt"] = fmt_num(ltdebt)
            if cash:
                nd = ltdebt - cash
                result["net_debt"] = fmt_num(abs(nd))
                result["net_position"] = "Net Cash" if nd < 0 else "Net Debt"
        elif cash:
            result["net_debt"] = fmt_num(cash)
            result["net_position"] = "Net Cash (no LT debt)"
        if equity:
            result["equity"] = fmt_num(equity)
        if ocf:
            result["ocf"] = fmt_num(ocf)
        if capex:
            result["capex"] = fmt_num(capex)
        if fcf:
            result["fcf"] = fmt_num(fcf)
        if inventory:
            result["inventory"] = fmt_num(inventory)
        if shares:
            if shares >= 1e9:
                result["shares"] = f"{shares/1e9:.2f}B"
            else:
                result["shares"] = f"{shares/1e6:.0f}M"

        print(f"SEC XBRL OK: {len(result)} metrics (IFRS={is_ifrs})")

    except Exception as e:
        print(f"SEC XBRL failed: {e}")
    return result


def get_fmp_data(ticker: str) -> dict:
    """FMP API - analyst estimates + company profile (needs FMP_API_KEY)."""
    result = {}
    fmp_key = os.environ.get("FMP_API_KEY")
    if not fmp_key:
        return result
    try:
        base = "https://financialmodelingprep.com/api/v3"
        h = {"User-Agent": "Mozilla/5.0"}

        # Analyst estimates (forward EPS guidance)
        est_resp = requests.get(
            f"{base}/analyst-estimates/{ticker}",
            headers=h,
            params={"period": "quarter", "limit": 4, "apikey": fmp_key},
            timeout=8
        )
        if est_resp.status_code == 200:
            estimates = est_resp.json()
            if isinstance(estimates, list) and estimates:
                next_q = estimates[0]
                result["next_q_eps_est"] = safe(next_q.get("estimatedEpsAvg"))
                result["next_q_rev_est"] = fmt_num(next_q.get("estimatedRevenueAvg")) if next_q.get("estimatedRevenueAvg") else "N/A"
                result["next_q_date"] = safe(next_q.get("date", ""))[:7]
                print(f"FMP analyst estimates: next Q {result['next_q_date']} EPS={result['next_q_eps_est']}")

        # For Taiwan stocks - get financials via FMP
        if "." in ticker and ticker.upper().endswith(".TW"):
            # FMP uses different format for Taiwan stocks
            tw_ticker = ticker.replace(".TW", "")
            profile_resp = requests.get(
                f"{base}/profile/{ticker}",
                headers=h,
                params={"apikey": fmp_key},
                timeout=8
            )
            if profile_resp.status_code == 200:
                profiles = profile_resp.json()
                if isinstance(profiles, list) and profiles:
                    p = profiles[0]
                    result["company_name"] = safe(p.get("companyName"))
                    result["market_cap"] = fmt_num(p.get("mktCap")) if p.get("mktCap") else "N/A"
                    result["pe_ratio"] = safe(p.get("pe"))
                    result["eps"] = safe(p.get("eps"))
                    result["sector"] = safe(p.get("sector"))
                    print(f"FMP Taiwan profile: {result.get('company_name')}")

            # Taiwan stock financials
            inc_resp = requests.get(
                f"{base}/income-statement/{ticker}",
                headers=h,
                params={"period": "annual", "limit": 2, "apikey": fmp_key},
                timeout=8
            )
            if inc_resp.status_code == 200:
                incs = inc_resp.json()
                if isinstance(incs, list) and incs:
                    inc = incs[0]
                    result["revenue"] = fmt_num(inc.get("revenue"))
                    result["gross_profit"] = fmt_num(inc.get("grossProfit"))
                    if inc.get("revenue") and inc.get("grossProfit") and inc["revenue"] > 0:
                        result["gross_margin"] = f"{inc['grossProfit']/inc['revenue']*100:.1f}%"
                    result["net_income"] = fmt_num(inc.get("netIncome"))
                    result["operating_income"] = fmt_num(inc.get("operatingIncome"))
                    result["sbc"] = fmt_num(inc.get("stockBasedCompensation"))
                    result["fiscal_year"] = safe(inc.get("date", ""))[:7]
                    print(f"FMP Taiwan income: rev={result.get('revenue')}")

    except Exception as e:
        print(f"FMP failed: {e}")
    return result


def get_news(ticker: str, company: str = "") -> list:
    """Yahoo Finance news search."""
    news = []
    try:
        resp = requests.get(
            "https://query1.finance.yahoo.com/v1/finance/search",
            headers={"User-Agent": "Mozilla/5.0"},
            params={"q": ticker, "newsCount": 8},
            timeout=8
        )
        if resp.status_code == 200:
            for item in resp.json().get("news", [])[:6]:
                ts = item.get("providerPublishTime", 0)
                date = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else ""
                news.append({
                    "title": safe(item.get("title")),
                    "publisher": safe(item.get("publisher")),
                    "date": date,
                })
    except Exception as e:
        print(f"News fetch failed: {e}")
    return news


def fetch_stock_data(ticker: str) -> dict:
    """Main entry point - fetch all available data for a stock ticker."""
    ticker = ticker.upper().strip()
    data = {
        "ticker": ticker,
        "fetched_at": datetime.now().isoformat(),
        "financials": {"company_name": ticker},
        "news": [],
        "summary": "",
    }
    f = data["financials"]

    # 1. Price (works for all markets including .TW)
    print(f"[1] Price for {ticker}...")
    price_data = get_price(ticker)
    f.update({k: v for k, v in price_data.items() if v is not None})

    # 2. SEC XBRL (US stocks only)
    is_taiwan = ticker.endswith(".TW") or ticker.endswith(".TWO")
    cik = None if is_taiwan else get_cik(ticker)

    if cik:
        print(f"[2] SEC XBRL CIK={cik}...")
        xbrl = get_sec_xbrl(cik, ticker)
        f.update(xbrl)
    else:
        print(f"[2] No CIK (non-US or not found)")

    # 3. FMP (analyst estimates + Taiwan stock fundamentals)
    print(f"[3] FMP...")
    fmp = get_fmp_data(ticker)
    # FMP data fills in gaps, but don't overwrite SEC data
    for k, v in fmp.items():
        if k not in f or f[k] in (None, "N/A", ticker):
            f[k] = v

    # 4. News
    print(f"[4] News...")
    data["news"] = get_news(ticker, f.get("company_name", ticker))

    # 5. Build summary
    company = safe(f.get("company_name"), ticker)
    price = safe(f.get("price"), "N/A")
    currency = f.get("currency", "USD")
    curr_sym = "NT$" if currency == "TWD" else "$"

    # Market cap estimate
    mc_str = safe(f.get("market_cap"), "N/A")
    if mc_str == "N/A" and f.get("price") and f.get("shares"):
        try:
            p = float(f["price"])
            sh_str = f["shares"].replace("M", "e6").replace("B", "e9").replace("T", "e12").replace("$","")
            sh = float(sh_str)
            mc_str = fmt_num(p * sh)
        except Exception:
            pass

    news_text = "\n".join(f"- [{n['date']}] {n['title']} ({n['publisher']})" for n in data["news"]) or "No recent news"

    # Analyst estimates section
    est_section = ""
    if f.get("next_q_eps_est") and f["next_q_eps_est"] != "N/A":
        est_section = (
            f"\n### Analyst Estimates (Next Quarter: {safe(f.get('next_q_date'))})\n"
            f"- Consensus EPS Est: ${safe(f.get('next_q_eps_est'))}\n"
            f"- Consensus Revenue Est: {safe(f.get('next_q_rev_est'))}\n"
        )

    lines = [
        f"## {company} (${ticker}) - Market Data",
        "",
        f"### Price ({currency})",
        f"- Current: {curr_sym}{price}",
        f"- 52W High/Low: {curr_sym}{safe(f.get('high_52w'))} / {curr_sym}{safe(f.get('low_52w'))}",
        f"- Market Cap: {mc_str}",
        f"- P/E Ratio: {safe(f.get('pe_ratio'))} | EPS: {safe(f.get('eps'))}",
        "",
        "### Income Statement (Annual)",
        f"- Revenue: {safe(f.get('revenue'))}",
        f"- Gross Profit: {safe(f.get('gross_profit'))} | Gross Margin: {safe(f.get('gross_margin'))}",
        f"- Operating Income: {safe(f.get('operating_income'))} | Op Margin: {safe(f.get('op_margin'))}",
        f"- Net Income: {safe(f.get('net_income'))} | Net Margin: {safe(f.get('net_margin'))}",
        "",
        "### Cash Flow",
        f"- Operating CF: {safe(f.get('ocf'))}",
        f"- CapEx: {safe(f.get('capex'))}",
        f"- Free Cash Flow: {safe(f.get('fcf'))}",
        f"- SBC: {safe(f.get('sbc'))} ({safe(f.get('sbc_pct'))} of revenue)",
        "",
        "### Balance Sheet",
        f"- Cash: {safe(f.get('cash'))}",
        f"- Long-term Debt: {safe(f.get('long_term_debt'))}",
        f"- Net Position: {safe(f.get('net_debt'))} ({safe(f.get('net_position'))})",
        f"- Total Assets: {safe(f.get('total_assets'))}",
        f"- Equity: {safe(f.get('equity'))}",
        f"- Goodwill+Intangibles: {safe(f.get('goodwill'))} ({safe(f.get('goodwill_ratio'))} of assets)",
        f"- Inventory: {safe(f.get('inventory'))}",
        f"- Shares: {safe(f.get('shares'))}",
    ]

    if est_section:
        lines.append(est_section)

    lines += ["", "### Recent News", news_text]

    data["summary"] = "\n".join(lines)
    return data


def fetch_and_prepare(ticker: str) -> str:
    return fetch_stock_data(ticker)["summary"]


if __name__ == "__main__":
    import sys
    t = sys.argv[1] if len(sys.argv) > 1 else "MU"
    print(fetch_and_prepare(t))
