import requests
import os
from datetime import datetime


FMP_BASE = "https://financialmodelingprep.com/api/v3"


def get_fmp_key() -> str:
    return os.environ.get("FMP_API_KEY", "demo")


def fetch_fmp_financials(ticker: str) -> str:
    """
    Fetch detailed financials from Financial Modeling Prep API.
    Free tier (demo key): limited to demo tickers.
    Set FMP_API_KEY env var for full access (free: 250 req/day).
    """
    key = get_fmp_key()
    headers = {"User-Agent": "AI-Investment-HQ"}
    output_lines = ["## " + ticker + " Detailed Financials (FMP)\n"]

    # 1. Income Statement (last 4 quarters)
    try:
        url = FMP_BASE + "/income-statement/" + ticker + "?period=quarter&limit=4&apikey=" + key
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data and isinstance(data, list):
                output_lines.append("### Income Statement (Last 4 Quarters)")
                output_lines.append("| Quarter | Revenue | Gross Profit | Net Income | EPS | Gross Margin |")
                output_lines.append("|---|---|---|---|---|---|")
                for q in data[:4]:
                    rev = q.get("revenue", 0)
                    gp = q.get("grossProfit", 0)
                    ni = q.get("netIncome", 0)
                    eps = q.get("eps", 0)
                    gm = round(gp / rev * 100, 1) if rev else 0
                    date = q.get("date", "")[:7]
                    output_lines.append(
                        "| " + date + " | $" + fmt_num(rev) +
                        " | $" + fmt_num(gp) +
                        " | $" + fmt_num(ni) +
                        " | $" + str(round(eps, 2)) +
                        " | " + str(gm) + "% |"
                    )
                output_lines.append("")
                print("FMP Income Statement: OK")
    except Exception as e:
        print("FMP Income Statement failed: " + str(e))

    # 2. Cash Flow Statement
    try:
        url = FMP_BASE + "/cash-flow-statement/" + ticker + "?period=quarter&limit=4&apikey=" + key
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data and isinstance(data, list):
                output_lines.append("### Cash Flow (Last 4 Quarters)")
                output_lines.append("| Quarter | Operating CF | CapEx | FCF | SBC |")
                output_lines.append("|---|---|---|---|---|")
                for q in data[:4]:
                    op_cf = q.get("operatingCashFlow", 0)
                    capex = q.get("capitalExpenditure", 0)
                    fcf = op_cf + capex  # capex is negative in FMP
                    sbc = q.get("stockBasedCompensation", 0)
                    date = q.get("date", "")[:7]
                    output_lines.append(
                        "| " + date +
                        " | $" + fmt_num(op_cf) +
                        " | $" + fmt_num(capex) +
                        " | $" + fmt_num(fcf) +
                        " | $" + fmt_num(sbc) + " |"
                    )
                output_lines.append("")
                print("FMP Cash Flow: OK")
    except Exception as e:
        print("FMP Cash Flow failed: " + str(e))

    # 3. Balance Sheet
    try:
        url = FMP_BASE + "/balance-sheet-statement/" + ticker + "?period=quarter&limit=2&apikey=" + key
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data and isinstance(data, list) and len(data) > 0:
                q = data[0]
                output_lines.append("### Balance Sheet (Latest Quarter: " + q.get("date", "")[:7] + ")")
                cash = q.get("cashAndCashEquivalents", 0)
                total_assets = q.get("totalAssets", 0)
                goodwill = q.get("goodwill", 0)
                intangibles = q.get("intangibleAssets", 0)
                total_debt = q.get("totalDebt", 0)
                equity = q.get("totalStockholdersEquity", 0)
                shares = q.get("commonStock", 0)
                goodwill_ratio = round((goodwill + intangibles) / total_assets * 100, 1) if total_assets else 0
                net_debt = total_debt - cash
                de_ratio = round(total_debt / equity, 2) if equity else "N/A"

                output_lines.append("- Cash: $" + fmt_num(cash))
                output_lines.append("- Total Debt: $" + fmt_num(total_debt))
                output_lines.append("- Net Debt: $" + fmt_num(net_debt))
                output_lines.append("- Total Assets: $" + fmt_num(total_assets))
                output_lines.append("- Goodwill + Intangibles: $" + fmt_num(goodwill + intangibles) +
                                    " (" + str(goodwill_ratio) + "% of assets)")
                output_lines.append("- Shareholders Equity: $" + fmt_num(equity))
                output_lines.append("- D/E Ratio: " + str(de_ratio))
                output_lines.append("")
                print("FMP Balance Sheet: OK")
    except Exception as e:
        print("FMP Balance Sheet failed: " + str(e))

    # 4. Key Metrics
    try:
        url = FMP_BASE + "/key-metrics/" + ticker + "?period=quarter&limit=4&apikey=" + key
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data and isinstance(data, list) and len(data) > 0:
                q = data[0]
                output_lines.append("### Key Metrics (Latest)")
                output_lines.append("- Book Value Per Share: $" + str(round(q.get("bookValuePerShare", 0), 2)))
                output_lines.append("- FCF Per Share: $" + str(round(q.get("freeCashFlowPerShare", 0), 2)))
                output_lines.append("- Revenue Per Share: $" + str(round(q.get("revenuePerShare", 0), 2)))
                output_lines.append("- EV/EBITDA: " + str(round(q.get("evToEbitda", 0), 2)))
                output_lines.append("- EV/Sales: " + str(round(q.get("evToSales", 0), 2)))
                output_lines.append("- P/FCF: " + str(round(q.get("priceToFreeCashFlowsRatio", 0), 2)))
                output_lines.append("- ROE: " + str(round(q.get("roe", 0) * 100, 1)) + "%")
                output_lines.append("- ROA: " + str(round(q.get("roa", 0) * 100, 1)) + "%")
                output_lines.append("- Current Ratio: " + str(round(q.get("currentRatio", 0), 2)))
                output_lines.append("- Debt/Equity: " + str(round(q.get("debtToEquity", 0), 2)))
                output_lines.append("")
                print("FMP Key Metrics: OK")
    except Exception as e:
        print("FMP Key Metrics failed: " + str(e))

    # 5. Analyst Estimates
    try:
        url = FMP_BASE + "/analyst-estimates/" + ticker + "?period=annual&limit=2&apikey=" + key
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data and isinstance(data, list):
                output_lines.append("### Analyst Estimates")
                for est in data[:2]:
                    year = est.get("date", "")[:4]
                    rev_avg = est.get("estimatedRevenueAvg", 0)
                    eps_avg = est.get("estimatedEpsAvg", 0)
                    output_lines.append(
                        "- " + year + ": Revenue est. $" + fmt_num(rev_avg) +
                        " | EPS est. $" + str(round(eps_avg, 2))
                    )
                output_lines.append("")
                print("FMP Analyst Estimates: OK")
    except Exception as e:
        print("FMP Analyst Estimates failed: " + str(e))

    result = "\n".join(output_lines)

    if len(result) < 200:
        return ""  # FMP returned no useful data (demo key limitation)

    return result


def fmt_num(n) -> str:
    """Format large numbers to readable form"""
    try:
        n = float(n)
        if abs(n) >= 1e9:
            return str(round(n / 1e9, 2)) + "B"
        elif abs(n) >= 1e6:
            return str(round(n / 1e6, 1)) + "M"
        else:
            return str(round(n, 0))
    except Exception:
        return str(n)


if __name__ == "__main__":
    import sys
    t = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    result = fetch_fmp_financials(t)
    print(result if result else "No FMP data available (check API key)")
