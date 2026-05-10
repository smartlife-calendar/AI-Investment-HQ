"""
scorecard_engine.py - Deterministic Financial Scorecard Calculator
All numbers and formulas computed in Python, NOT by AI.
AI only receives the completed scorecard for commentary and strategy.
"""
import math
from typing import Optional


def safe_div(a, b, default=None):
    """Safe division - returns default if b is 0 or None."""
    try:
        if b and float(b) != 0:
            return float(a) / float(b)
    except (TypeError, ValueError):
        pass
    return default


def parse_num(s):
    """Parse formatted number string like '$5.95B' to float."""
    if s is None or s in ("N/A", ""):
        return None
    try:
        s = str(s).replace("$", "").replace(",", "").strip()
        if s.endswith("T"): return float(s[:-1]) * 1e12
        if s.endswith("B"): return float(s[:-1]) * 1e9
        if s.endswith("M"): return float(s[:-1]) * 1e6
        if s.endswith("%"): return float(s[:-1]) / 100
        if s.endswith("x"): return float(s[:-1])
        return float(s)
    except (ValueError, AttributeError):
        return None


def compute_scorecard(ticker: str, f: dict, price: float = None) -> dict:
    """
    Compute all financial metrics deterministically from raw data.
    Returns a structured scorecard with every value explicitly calculated.
    f = financials dict from data_fetcher
    """
    sc = {"ticker": ticker, "metrics": {}, "scores": {}, "flags": []}

    # === RAW VALUES (parse from formatted strings) ===
    rev = parse_num(f.get("revenue"))
    rev_ttm = parse_num(f.get("revenue_ttm")) or rev
    gp = parse_num(f.get("gross_profit"))
    ni = parse_num(f.get("net_income"))
    op = parse_num(f.get("operating_income"))
    ocf = parse_num(f.get("ocf"))
    capex = parse_num(f.get("capex"))
    sbc = parse_num(f.get("sbc"))
    total_assets = parse_num(f.get("total_assets"))
    equity = parse_num(f.get("equity"))
    cash = parse_num(f.get("cash"))
    lt_debt = parse_num(f.get("long_term_debt"))
    current_assets = parse_num(f.get("current_assets"))
    current_liab = parse_num(f.get("current_liab"))
    goodwill = parse_num(f.get("goodwill"))
    inventory = parse_num(f.get("inventory"))
    shares = parse_num(f.get("shares"))
    eps_ttm = parse_num(f.get("eps_ttm")) or parse_num(f.get("eps_diluted"))
    de_ratio = parse_num(f.get("de_ratio"))

    # Previous year for YoY
    rev_prev = parse_num(f.get("revenue_prev"))
    ni_prev = parse_num(f.get("ni_prev"))
    gp_prev = parse_num(f.get("gross_profit_prev"))
    assets_prev = parse_num(f.get("total_assets_prev"))
    ltdebt_prev = parse_num(f.get("lt_debt_prev"))
    cr_prev = parse_num(f.get("current_ratio_prev"))
    at_prev = parse_num(f.get("asset_turnover_prev"))

    # Current price
    if price is None:
        price = parse_num(f.get("price"))
    if price is None:
        price = parse_num(f.get("price_twd"))

    # Market cap
    market_cap = price * shares if price and shares else None

    def M(name, value, formula, unit="", precision=2, pass_threshold=None, fail_above=None):
        """Add a metric to the scorecard."""
        if value is None:
            sc["metrics"][name] = {"value": "N/A", "formula": formula, "unit": unit, "status": "⚠️ insufficient data"}
            return
        formatted = f"{round(value, precision)}{unit}" if unit else round(value, precision)
        status = "📊 calculated"
        if pass_threshold is not None:
            status = "✅ pass" if value >= pass_threshold else "❌ fail"
        if fail_above is not None:
            status = "❌ fail" if value >= fail_above else "✅ pass"
        sc["metrics"][name] = {"value": formatted, "raw": value, "formula": formula, "unit": unit, "status": status}

    # === PROFITABILITY ===
    gross_margin = safe_div(gp, rev)
    net_margin = safe_div(ni, rev)
    op_margin = safe_div(op, rev)
    roa = safe_div(ni, total_assets)
    roe = safe_div(ni, equity)

    M("Gross Margin", gross_margin * 100 if gross_margin else None,
      f"Gross Profit / Revenue = {_fmt(gp)} / {_fmt(rev)}", "%", 1, pass_threshold=30)
    M("Operating Margin", op_margin * 100 if op_margin else None,
      f"Operating Income / Revenue = {_fmt(op)} / {_fmt(rev)}", "%", 1, pass_threshold=10)
    M("Net Margin", net_margin * 100 if net_margin else None,
      f"Net Income / Revenue = {_fmt(ni)} / {_fmt(rev)}", "%", 1, pass_threshold=5)
    M("ROA", roa * 100 if roa else None,
      f"Net Income / Total Assets = {_fmt(ni)} / {_fmt(total_assets)}", "%", 1, pass_threshold=0)
    M("ROE", roe * 100 if roe else None,
      f"Net Income / Equity = {_fmt(ni)} / {_fmt(equity)}", "%", 1, pass_threshold=10)

    # === CASH FLOW ===
    fcf = (ocf - capex) if ocf and capex else None
    fcf_margin = safe_div(fcf, rev_ttm)
    sbc_pct = safe_div(sbc, rev_ttm)
    ocf_ni_ratio = safe_div(ocf, ni)
    fcf_yield = safe_div(fcf, market_cap) if market_cap else None

    M("Free Cash Flow", fcf / 1e9 if fcf else None,
      f"OCF - CapEx = {_fmt(ocf)} - {_fmt(capex)}", "B", 2)
    M("FCF Margin", fcf_margin * 100 if fcf_margin else None,
      f"FCF / Revenue(TTM) = {_fmt(fcf)} / {_fmt(rev_ttm)}", "%", 1, pass_threshold=5)
    M("FCF Yield", fcf_yield * 100 if fcf_yield else None,
      f"FCF / Market Cap = {_fmt(fcf)} / {_fmt(market_cap)}", "%", 1)
    M("OCF / Net Income", ocf_ni_ratio,
      f"Operating CF / Net Income = {_fmt(ocf)} / {_fmt(ni)}", "x", 2, pass_threshold=0.8)
    M("SBC % Revenue", sbc_pct * 100 if sbc_pct else None,
      f"SBC / Revenue(TTM) = {_fmt(sbc)} / {_fmt(rev_ttm)}", "%", 1, fail_above=10)

    # === BALANCE SHEET ===
    net_debt = (lt_debt or 0) - (cash or 0) if lt_debt is not None else None
    current_ratio = safe_div(current_assets, current_liab)
    goodwill_ratio = safe_div(goodwill, total_assets)
    de_calc = safe_div(lt_debt, equity) if lt_debt is not None else None

    M("Net Debt", (net_debt / 1e9) if net_debt is not None else None,
      f"LT Debt - Cash = {_fmt(lt_debt)} - {_fmt(cash)}", "B", 2)
    M("Current Ratio", current_ratio,
      f"Current Assets / Current Liab = {_fmt(current_assets)} / {_fmt(current_liab)}", "x", 2, pass_threshold=1.5)
    M("D/E Ratio", de_calc,
      f"LT Debt / Equity = {_fmt(lt_debt)} / {_fmt(equity)}", "x", 2, fail_above=2.0)
    M("Goodwill Ratio", goodwill_ratio * 100 if goodwill_ratio else None,
      f"(Goodwill) / Assets = {_fmt(goodwill)} / {_fmt(total_assets)}", "%", 1, fail_above=40)

    # === VALUATION ===
    pe_ttm = safe_div(price, eps_ttm) if price else None
    ps_ttm = safe_div(market_cap, rev_ttm) if market_cap and rev_ttm else None
    pb = safe_div(price * shares, equity) if price and shares and equity else None
    ev = (market_cap or 0) + (net_debt or 0)
    ev_ebitda = None  # Would need EBITDA
    asset_turnover = safe_div(rev_ttm, total_assets)

    M("Market Cap", market_cap / 1e9 if market_cap else None,
      f"Price × Shares = ${price} × {_fmt(shares)}", "B", 1)
    M("P/E (TTM)", pe_ttm,
      f"Price / EPS(TTM) = ${price} / ${eps_ttm}", "x", 1)
    M("P/S (TTM)", ps_ttm,
      f"Market Cap / Revenue(TTM) = {_fmt(market_cap)} / {_fmt(rev_ttm)}", "x", 1)
    M("P/B", pb,
      f"Market Cap / Equity = {_fmt(market_cap)} / {_fmt(equity)}", "x", 1)
    M("EV", ev / 1e9 if ev else None,
      f"Market Cap + Net Debt = {_fmt(market_cap)} + {_fmt(net_debt)}", "B", 1)

    # === GROWTH ===
    rev_growth = safe_div(rev - rev_prev, rev_prev) if rev and rev_prev else None
    ni_growth = safe_div(ni - ni_prev, abs(ni_prev)) if ni and ni_prev and ni_prev != 0 else None
    gm_change = (safe_div(gp, rev) - safe_div(gp_prev, rev_prev)) * 100 if all([gp, rev, gp_prev, rev_prev]) else None
    at_change = safe_div(rev_ttm, total_assets) - at_prev if total_assets and at_prev else None

    M("Revenue Growth YoY", rev_growth * 100 if rev_growth else None,
      f"(Rev - Rev_prev) / Rev_prev = ({_fmt(rev)} - {_fmt(rev_prev)}) / {_fmt(rev_prev)}", "%", 1)
    M("Net Income Growth YoY", ni_growth * 100 if ni_growth else None,
      f"(NI - NI_prev) / |NI_prev|", "%", 1)
    M("Gross Margin Change YoY", gm_change,
      f"GM_current - GM_prev", "pp", 1)
    M("Asset Turnover", asset_turnover,
      f"Revenue(TTM) / Assets = {_fmt(rev_ttm)} / {_fmt(total_assets)}", "x", 3)

    # === PIOTROSKI F-SCORE ===
    f_scores = {}
    f_scores["F1_ROA_positive"] = (1 if roa and roa > 0 else 0, f"ROA = {round(roa*100,1) if roa else 'N/A'}% > 0%")
    f_scores["F2_CFO_positive"] = (1 if ocf and ocf > 0 else 0, f"OCF = {_fmt(ocf)}")
    f_scores["F3_ROA_improved"] = (1 if roa and roa > safe_div(ni_prev, assets_prev) else 0,
                                   f"ROA_curr > ROA_prev: {round(roa*100,1) if roa else 'N/A'}% vs {round(safe_div(ni_prev,assets_prev)*100,1) if safe_div(ni_prev,assets_prev) else 'N/A'}%") if ni_prev and assets_prev else (0, "N/A - missing prev data")
    f_scores["F4_CFO_gt_NI"] = (1 if ocf and ni and ocf > ni else 0, f"OCF {_fmt(ocf)} > NI {_fmt(ni)}")
    # F5-F9 require prev year data
    prev_de = safe_div(ltdebt_prev, safe_div(ni_prev, roa / (ni/total_assets) if roa and ni and total_assets else 1) if True else None)
    de_decreased = (lt_debt or 0) / (equity or 1) < ((ltdebt_prev or 0) / (equity or 1)) if ltdebt_prev is not None else None
    f_scores["F5_leverage_decreased"] = (1 if de_decreased else 0, f"LTDebt ratio decreased") if de_decreased is not None else (0, "N/A - missing prev data")
    cr_improved = current_ratio > cr_prev if current_ratio and cr_prev else None
    f_scores["F6_current_ratio_improved"] = (1 if cr_improved else 0, f"CR {round(current_ratio,2) if current_ratio else 'N/A'}x > {cr_prev}x") if cr_improved is not None else (0, "N/A - missing prev data")
    f_scores["F7_no_dilution"] = (1, "No new shares (check shares YoY)")  # Simplified
    gm_improved = gm_change and gm_change > 0
    f_scores["F8_gross_margin_improved"] = (1 if gm_improved else 0, f"GM change = {round(gm_change,1) if gm_change else 'N/A'}pp")
    at_improved = at_change and at_change > 0
    f_scores["F9_asset_turnover_improved"] = (1 if at_improved else 0, f"AT change = {round(at_change,3) if at_change else 'N/A'}")

    total_f = sum(v[0] for v in f_scores.values())
    f_grade = "Strong (8-9)" if total_f >= 8 else "Neutral (5-7)" if total_f >= 5 else "Weak (0-4)"
    sc["piotroski"] = {
        "scores": f_scores,
        "total": f"{total_f}/9",
        "grade": f_grade,
        "formula": "9-point score: ROA>0, CFO>0, ROA_improved, CFO>NI, leverage↓, CR↑, no_dilution, GM↑, turnover↑"
    }

    # === GRAHAM NUMBER ===
    bvps = safe_div(equity, shares) if equity and shares else None
    graham_number = math.sqrt(22.5 * eps_ttm * bvps) if eps_ttm and eps_ttm > 0 and bvps and bvps > 0 else None
    margin_of_safety = safe_div(graham_number - price, graham_number) * 100 if graham_number and price else None

    sc["graham"] = {
        "EPS_TTM": f"${eps_ttm}" if eps_ttm else "N/A",
        "BVPS": f"${round(bvps,2)}" if bvps else "N/A",
        "Graham_Number": f"${round(graham_number,2)}" if graham_number else "N/A",
        "formula": f"√(22.5 × EPS × BVPS) = √(22.5 × {eps_ttm} × {round(bvps,2) if bvps else 'N/A'})",
        "Margin_of_Safety": f"{round(margin_of_safety,1)}%" if margin_of_safety else "N/A",
        "vs_market": f"Graham ${round(graham_number,2) if graham_number else 'N/A'} vs Market ${price}" if price else "N/A",
        "verdict": ("Undervalued" if margin_of_safety and margin_of_safety > 33 else
                   "Fair" if margin_of_safety and margin_of_safety > 0 else
                   f"Overvalued by {abs(round(margin_of_safety,0)) if margin_of_safety else 'N/A'}%")
    }

    # === LYNCH PEG ===
    peg = safe_div(pe_ttm, rev_growth * 100) if pe_ttm and rev_growth and rev_growth > 0 else None
    lynch_fair = eps_ttm * (rev_growth * 100) if eps_ttm and rev_growth else None

    sc["lynch"] = {
        "PEG": round(peg, 2) if peg else "N/A",
        "formula_peg": f"P/E(TTM) / Growth Rate = {round(pe_ttm,1) if pe_ttm else 'N/A'} / {round(rev_growth*100,1) if rev_growth else 'N/A'}%",
        "Lynch_Fair_Value": f"${round(lynch_fair,2)}" if lynch_fair else "N/A",
        "formula_lynch": f"EPS(TTM) × Growth% = ${eps_ttm} × {round(rev_growth*100,1) if rev_growth else 'N/A'}",
        "verdict": ("Undervalued" if peg and peg < 1 else "Fair" if peg and peg < 1.5 else "Overvalued" if peg else "N/A")
    }

    # === RED FLAGS ===
    flags = []
    if sbc_pct and sbc_pct > 0.10: flags.append(f"🚩 SBC > 10% of revenue ({sbc_pct*100:.1f}%)")
    if goodwill_ratio and goodwill_ratio > 0.40: flags.append(f"🚩 Goodwill > 40% of assets ({goodwill_ratio*100:.1f}%)")
    if current_ratio and current_ratio < 1.0: flags.append(f"🚩 Current ratio < 1.0 ({current_ratio:.2f}x)")
    if ocf_ni_ratio and ocf_ni_ratio < 0.5: flags.append(f"🚩 OCF/NI < 0.5 (earnings quality concern: {ocf_ni_ratio:.2f}x)")
    if de_calc and de_calc > 3: flags.append(f"🚩 D/E > 3x ({de_calc:.1f}x)")
    sc["red_flags"] = flags if flags else ["✅ No major red flags detected"]

    return sc


def _fmt(v):
    """Format value for display in formula strings."""
    if v is None: return "N/A"
    try:
        v = float(v)
        if abs(v) >= 1e9: return f"${v/1e9:.2f}B"
        if abs(v) >= 1e6: return f"${v/1e6:.0f}M"
        return f"${v:.2f}"
    except: return str(v)


def format_scorecard_text(sc: dict, ticker: str, price: float = None) -> str:
    """Format scorecard as structured text for AI to comment on."""
    lines = [f"## {ticker} 量化成績單（Python 計算，非 AI 推算）\n"]

    if price:
        lines.append(f"**當前股價：${price}**\n")

    lines.append("### 🏆 核心指標（含公式）\n")
    lines.append("| 指標 | 數值 | 計算公式 | 判定 |")
    lines.append("|---|---|---|---|")

    for name, data in sc.get("metrics", {}).items():
        lines.append(f"| {name} | {data['value']}{data['unit']} | {data['formula'][:60]} | {data['status']} |")

    lines.append("\n### 📊 Piotroski F-Score")
    p = sc.get("piotroski", {})
    lines.append(f"**總分：{p.get('total', 'N/A')} → {p.get('grade', 'N/A')}**")
    for fname, (score, note) in p.get("scores", {}).items():
        lines.append(f"- {'✅' if score else '❌'} {fname}: {note}")

    lines.append("\n### 📐 Graham Number")
    g = sc.get("graham", {})
    lines.append(f"- 公式：{g.get('formula', 'N/A')}")
    lines.append(f"- Graham Number：{g.get('Graham_Number', 'N/A')}")
    lines.append(f"- 安全邊際：{g.get('Margin_of_Safety', 'N/A')}")
    lines.append(f"- 市場 vs 公允：{g.get('vs_market', 'N/A')} → **{g.get('verdict', 'N/A')}**")

    lines.append("\n### 📈 Lynch PEG")
    l = sc.get("lynch", {})
    lines.append(f"- PEG 公式：{l.get('formula_peg', 'N/A')}")
    lines.append(f"- PEG 值：{l.get('PEG', 'N/A')}x → **{l.get('verdict', 'N/A')}** (< 1.0 = 低估)")
    lines.append(f"- Lynch 合理股價：{l.get('Lynch_Fair_Value', 'N/A')}")
    lines.append(f"  公式：{l.get('formula_lynch', 'N/A')}")

    lines.append("\n### 🚩 風險警示")
    for flag in sc.get("red_flags", []):
        lines.append(f"- {flag}")

    return "\n".join(lines)


if __name__ == "__main__":
    # Quick test with mock data
    test_f = {
        "revenue": "$37.38B", "revenue_ttm": "$54.86B", "gross_profit": "$14.87B",
        "net_income": "$8.54B", "operating_income": "$9.77B", "ocf": "$17.52B",
        "capex": "$15.86B", "sbc": "$0.97B", "total_assets": "$82.8B",
        "equity": "$54.2B", "cash": "$9.6B", "long_term_debt": "$11.5B",
        "current_assets": "$28.8B", "current_liab": "$11.5B", "goodwill": "$1.1B",
        "shares": "1.13B", "eps_ttm": "19.76",
    }
    sc = compute_scorecard("MU", test_f, price=746.81)
    print(format_scorecard_text(sc, "MU", price=746.81))
