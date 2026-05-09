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
    _price_match = _re.search(r"Current[^\n]*?\$?([0-9,]+\.?[0-9]*)", str(financial_text or "")[:800])
    _price_note = ""
    if _price_match:
        _cp = _price_match.group(1).replace(",", "")
        try:
            _cp_float = float(_cp)
            if _cp_float > 0.5:  # sanity check - skip tiny values
                _price_note = (
                    "\n\n⚠️ 重要：當前市場股價為 $" + _cp +
                    "。目標價必須以此為基準，給出合理範圍（通常 ±70% 以內）。" +
                    "例如若股價 $293，悲觀 $200、基準 $320、樂觀 $400。" +
                    "請勿給出與市場價格相差 5 倍以上的目標價。"
                )
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

    bear = re.search(r"悲觀[^$\d]*\$?\s*([0-9]+\.?[0-9]*)", text)
    base = re.search(r"基準[^$\d]*\$?\s*([0-9]+\.?[0-9]*)", text)
    bull = re.search(r"樂觀[^$\d]*\$?\s*([0-9]+\.?[0-9]*)", text)

    if bear:
        result["bear_price"] = float(bear.group(1))
    if base:
        result["base_price"] = float(base.group(1))
    if bull:
        result["bull_price"] = float(bull.group(1))

    for r in ["強力買進", "買進", "觀望", "賣出", "強力迴避"]:
        if r in text:
            result["rating"] = r
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
