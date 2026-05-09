import os
import json
import re
import concurrent.futures
import anthropic


def load_persona(persona_id: str) -> dict:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_dir, "..", "personas", "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        personas = json.load(f)["analysts"]
    return next((p for p in personas if p["id"] == persona_id), None)


def build_prompt(persona: dict, ticker: str, financial_text: str, market_context: str = "") -> tuple:
    calculation_specs = {
        "financial_structure": [
            "FCF = Operating Cash Flow - CapEx (show numbers)",
            "SBC% = Stock-Based Compensation / Revenue",
            "Goodwill Ratio = (Goodwill + Intangibles) / Total Assets",
            "Net Debt = Total Debt - Cash",
            "EV/FCF = (Market Cap + Net Debt) / FCF",
        ],
        "supply_chain_structure": [
            "In-house Supply Rate = Self-made / Total components needed",
            "CapEx Intensity = CapEx / Revenue",
            "Customer Concentration = Top 3 customers %",
            "GAAP vs Non-GAAP Gross Margin gap",
        ],
        "benjamin_graham": [
            "NCAV = Current Assets - Total Liabilities",
            "Graham Number = sqrt(22.5 x EPS x BVPS)",
            "Margin of Safety = (Graham Number - Price) / Graham Number x 100%",
            "Current Ratio must be > 2.0",
            "P/E x P/B must be < 22.5",
        ],
        "peter_lynch": [
            "PEG = P/E / Earnings Growth Rate (< 1.0 is undervalued)",
            "Lynch Fair Value = EPS x Earnings Growth Rate",
            "D/E Ratio = Total Debt / Equity (< 0.8 preferred)",
            "Inventory Growth vs Revenue Growth (inventory should not outpace revenue)",
        ],
        "cathie_wood": [
            "Revenue CAGR (3-year compound annual growth)",
            "R&D / Revenue ratio",
            "Gross Margin expansion trend (QoQ)",
            "5-year target price = current revenue x projected P/S at maturity",
            "Potential return multiple = 5yr target / current price",
        ],
        "piotroski_fscore": [
            "F1: ROA > 0 (+1)", "F2: CFO > 0 (+1)", "F3: ROA improved YoY (+1)",
            "F4: CFO > Net Income (+1)", "F5: Debt ratio decreased (+1)",
            "F6: Current ratio improved (+1)", "F7: No new shares issued (+1)",
            "F8: Gross margin improved (+1)", "F9: Asset turnover improved (+1)",
            "Total F-Score: 8-9=Strong, 5-7=Neutral, 0-4=Weak",
        ],
        "technical_analysis": [
            "RSI(14): >70超買 / <30超賣 / 40-60中性",
            "布林通道%B: >0.8超買上軌 / <0.2超賣下軌",
            "MACD: 黃金交叉(買) / 死亡交叉(賣) / 柱狀圖方向",
            "均線: MA20/MA50/MA200位置 + 黃金/死亡排列",
            "成交量: 量比>1.3放大 / <0.7萎縮 + 與價格背離判斷",
        ],
        "uncle_stock_notes": [
            "Double Beat check: Did EPS AND Revenue both beat consensus?",
            "OCF / Net Income conversion ratio (> 80% = high quality earnings)",
            "Book-to-Bill Ratio (> 1.5 = strong, > 2.0 = sold out)",
            "SBC% = SBC / Revenue (> 5% = red flag)",
            "Goodwill + Intangibles / Total Assets (> 50% = red flag)",
            "YoY share count change (> 15% = red flag)",
            "Forward P/S vs industry peers",
            "3-scenario DCF: Bear/Base/Bull with probability weights",
        ],
    }

    formulas = "\n".join(calculation_specs.get(persona["id"], []))
    framework = "\n".join(persona.get("analysis_framework", []))
    market_section = ""
    if market_context:
        market_section = "\n\nCurrent Market Context (use this in timing assessment):\n" + str(market_context or "")

    system_prompt = (
        "You are a professional stock analyst using the " + persona["name"] + " framework.\n\n"
        "Framework steps:\n" + str(framework or "") + "\n\n"
        "Required calculations (show work):\n" + str(formulas or "") + "\n\n"
        "Rules:\n"
        "- Show actual numbers in every calculation\n"
        "- Mark each metric: pass / fail / insufficient data\n"
        "- Give specific price targets in USD\n"
        "- Write in Traditional Chinese (zh-TW)\n"
        "- Be concise: max 600 words total"
    )

    # Extract current price to anchor target prices
    import re as _re
    _price_note = ""
    # Try to find market price from data (look for "Current: $XXX" pattern)
    _price_matches = _re.findall(r"Current[^\n]*?\$([0-9,]+\.?[0-9]*)", str(financial_text or "")[:1500])
    for _cp_raw in _price_matches:
        try:
            _cp = _cp_raw.replace(",", "")
            _cp_float = float(_cp)
            # Must be a reasonable stock price (> $1 and < $100,000)
            if 1.0 < _cp_float < 100000:
                _price_note = (
                    "\n\n⚠️ 當前市場股價為 $" + _cp + "。"
                    "所有目標價（悲觀/基準/樂觀）必須以當前股價為基準。"
                    "合理的目標價區間通常在當前價格的 50%-200% 之間。"
                    "例如當前 $" + _cp + "，悲觀 $" + str(round(_cp_float * 0.7, 0)) + 
                    "，基準 $" + str(round(_cp_float * 1.1, 0)) + 
                    "，樂觀 $" + str(round(_cp_float * 1.4, 0)) + "（僅為範例，請基於分析給出合理數字）。"
                    "禁止給出與市場價格相差10倍以上的目標價。"
                )
                break
        except Exception:
            pass

    user_prompt = (
        "Analyze $" + str(ticker or "") + " using " + str(persona["name"] or "") + ".\n\n"
        "Data:\n" + str(financial_text or "")[:4000] + str(market_section or "") + str(_price_note) + "\n\n"
        "Output format (required):\n"
        "**核心計算**\n[calculations with numbers]\n\n"
        "**指標評分**\n[pass/fail table]\n\n"
        "**主要風險**\n[top 3 risks]\n\n"
        "**估值結論**\n"
        "- 悲觀目標價: $___\n"
        "- 基準目標價: $___\n"
        "- 樂觀目標價: $___\n"
        "- 評級: [強力買進/買進/觀望/賣出/強力迴避]\n"
        "- 觸發條件: [what changes the rating]"
    )

    return system_prompt, user_prompt


def analyze_one(ticker: str, financial_text: str, persona_id: str, market_context: str = "") -> dict:
    persona = load_persona(persona_id)
    if not persona:
        return {"error": "Persona not found: " + persona_id, "persona_id": persona_id}

    system_prompt, user_prompt = build_prompt(persona, ticker, financial_text, market_context)
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1500,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}]
    )

    raw_text = message.content[0].text
    structured = extract_prices(raw_text, persona_id)
    structured["full_analysis"] = raw_text
    structured["persona_name"] = persona["name"]
    return structured


def analyze_stock(ticker: str, financial_text: str, persona_id: str, market_context: str = "") -> dict:
    return analyze_one(ticker, financial_text, persona_id, market_context)


def run_analysis(ticker: str, financial_text: str, personas: list = None, market_context: str = "") -> dict:
    if personas is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(base_dir, "..", "personas", "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        personas = [a["id"] for a in config["analysts"]]

    results = {}

    # Run all personas in PARALLEL (major speedup: 6x sequential -> ~1x parallel)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(personas)) as executor:
        future_to_persona = {
            executor.submit(analyze_one, ticker, financial_text, pid, market_context): pid
            for pid in personas
        }
        for future in concurrent.futures.as_completed(future_to_persona):
            pid = future_to_persona[future]
            try:
                results[pid] = future.result(timeout=90)
                print("Done: " + pid)
            except Exception as e:
                results[pid] = {"error": str(e), "persona_id": pid, "persona_name": pid}
                print("Failed: " + pid + " - " + str(e))

    return results


def extract_prices(text: str, persona_id: str) -> dict:
    result = {"bear_price": None, "base_price": None, "bull_price": None, "rating": None, "persona_id": persona_id}

    # Extract prices with multiple pattern attempts
    def find_price(patterns):
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                try:
                    v = float(m.group(1))
                    if v > 0:
                        return v
                except Exception:
                    pass
        return None

    bear = find_price([
        r"悲觀[目標價：: ]*\$?\s*([0-9]+\.?[0-9]*)",
        r"Bear[^$\d]*\$\s*([0-9]+\.?[0-9]*)",
    ])
    base = find_price([
        r"基準[目標價：: ]*\$?\s*([0-9]+\.?[0-9]*)",
        r"Base[^$\d]*\$\s*([0-9]+\.?[0-9]*)",
    ])
    bull = find_price([
        r"樂觀[目標價：: ]*\$?\s*([0-9]+\.?[0-9]*)",
        r"Bull[^$\d]*\$\s*([0-9]+\.?[0-9]*)",
    ])

    # Extract current market price for plausibility check
    current_price = None
    for cp_pat in [r"當前市場股價為 \$([0-9,]+\.?[0-9]*)", r"Current[^\n]{0,30}?\$([0-9]+\.?[0-9]*)"]:
        cp_m = re.search(cp_pat, text[:2000])
        if cp_m:
            try:
                current_price = float(cp_m.group(1).replace(",", ""))
                if current_price > 0.5:
                    break
            except Exception:
                pass

    # === VALIDATION & AUTO-FIX ===
    # Value frameworks (Graham, Piotroski) intentionally show prices below market
    # Only apply plausibility filter for growth/momentum frameworks
    VALUE_FRAMEWORKS = {"benjamin_graham", "piotroski_fscore", "technical_analysis"}
    skip_plausibility = persona_id in VALUE_FRAMEWORKS

    valid_prices = []
    for v in [bear, base, bull]:
        if v is None:
            valid_prices.append(None)
        elif skip_plausibility:
            # For value frameworks: accept any positive price (even if below market)
            valid_prices.append(v)
        elif current_price and current_price > 1:
            # Price must be within 10x of current price (for growth/momentum frameworks)
            if 0.1 < v / current_price < 10:
                valid_prices.append(v)
            else:
                valid_prices.append(None)
        else:
            valid_prices.append(v)

    bear, base, bull = valid_prices

    # Ensure bear <= base <= bull order
    non_null = sorted([p for p in [bear, base, bull] if p is not None])
    if len(non_null) == 3 and not (non_null[0] <= non_null[1] <= non_null[2]):
        # Values exist but in wrong order - re-sort
        bear, base, bull = non_null[0], non_null[1], non_null[2]
    elif len(non_null) == 2:
        # Missing one - estimate it
        if bear is None and base is not None and bull is not None:
            bear = round(base * 0.8, 1)
        elif bull is None and bear is not None and base is not None:
            bull = round(base * 1.2, 1)
        elif base is None and bear is not None and bull is not None:
            base = round((bear + bull) / 2, 1)
    elif len(non_null) == 1:
        # Only one price - estimate range
        ref = non_null[0]
        if base is None: base = ref
        if bear is None: bear = round(ref * 0.8, 1)
        if bull is None: bull = round(ref * 1.2, 1)

    result["bear_price"] = bear
    result["base_price"] = base
    result["bull_price"] = bull

    # Rating
    rating_map = {
        "Strong Buy": "強力買進", "強力買進": "強力買進",
        "Buy": "買進", "買進": "買進",
        "Hold": "觀望", "觀望": "觀望",
        "Sell": "賣出", "賣出": "賣出",
        "Strong Sell": "強力迴避", "強力迴避": "強力迴避",
    }
    for eng, chi in rating_map.items():
        if eng in text:
            result["rating"] = chi
            break

    return result

def generate_comparison_table(ticker: str, results: dict) -> str:
    table = "## $" + str(ticker or "") + " 多框架估值對比表\n\n"
    table += "| 分析框架 | 悲觀 | 基準 | 樂觀 | 評級 |\n"
    table += "|---|---|---|---|---|\n"

    base_prices = []
    for pid, r in results.items():
        if not isinstance(r, dict) or "full_analysis" not in r:
            continue
        bear = "$" + str(r["bear_price"]) if r.get("bear_price") else "—"
        base = "$" + str(r["base_price"]) if r.get("base_price") else "—"
        bull = "$" + str(r["bull_price"]) if r.get("bull_price") else "—"
        rating = r.get("rating", "—")
        name = r.get("persona_name", pid)
        table += "| " + str(name or "N/A") + " | " + str(bear or "—") + " | " + str(base or "—") + " | " + str(bull or "—") + " | " + str(rating or "—") + " |\n"
        if r.get("base_price"):
            base_prices.append(r["base_price"])

    if base_prices:
        consensus = round(sum(base_prices) / len(base_prices), 2)
        table += "\n**共識目標價（基準均值）: $" + str(consensus) + "**\n"

    return table
