import os
import json
import re
import anthropic


def load_persona(persona_id: str) -> dict:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_dir, "..", "personas", "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        personas = json.load(f)["analysts"]
    return next((p for p in personas if p["id"] == persona_id), None)


def build_calculation_prompt(persona: dict, ticker: str, financial_text: str) -> tuple:
    calculation_specs = {
        "financial_structure": {
            "formulas": [
                "FCF = Operating Cash Flow - CapEx",
                "SBC% = Stock-Based Compensation / Total Revenue",
                "Goodwill Ratio = Goodwill / Total Assets",
                "Net Debt = Total Debt - Cash",
                "EV/FCF = (Market Cap + Net Debt) / FCF",
            ],
        },
        "supply_chain_structure": {
            "formulas": [
                "In-house Supply Rate = Self-made components / Total component needs",
                "CapEx Intensity = CapEx / Revenue",
                "Customer Concentration = Top 3 customers revenue %",
                "Margin Gap = Non-GAAP Gross Margin - GAAP Gross Margin",
            ],
        },
        "benjamin_graham": {
            "formulas": [
                "NCAV = Current Assets - Total Liabilities",
                "Graham Number = sqrt(22.5 x EPS x Book Value Per Share)",
                "Margin of Safety = (Graham Number - Current Price) / Graham Number",
                "Current Ratio = Current Assets / Current Liabilities (needs > 2.0)",
                "P/E < 15 AND P/B < 1.5 (or P/E x P/B < 22.5)",
            ],
        },
        "peter_lynch": {
            "formulas": [
                "PEG = P/E / Earnings Growth Rate (PEG < 1.0 = undervalued)",
                "Adjusted PEG = P/E / (Earnings Growth Rate + Dividend Yield)",
                "Inventory Growth Rate vs Revenue Growth Rate",
                "D/E = Total Debt / Shareholders Equity (< 0.8 preferred)",
                "Lynch Fair Value = EPS x Fair P/E (Fair P/E = Earnings Growth Rate)",
            ],
        },
        "cathie_wood": {
            "formulas": [
                "Revenue CAGR (3-year compound annual growth rate)",
                "R&D / Revenue ratio (higher = more innovation investment)",
                "Gross Margin trend (expanding quarter over quarter?)",
                "TAM penetration: 5-year revenue projection under adoption scenario",
                "5-year target market cap / current market cap = potential return multiple",
            ],
        },
        "piotroski_fscore": {
            "formulas": [
                "F1: ROA > 0 (1 point)",
                "F2: Operating Cash Flow CFO > 0 (1 point)",
                "F3: ROA improved vs prior year (1 point)",
                "F4: CFO > ROA - cash quality (1 point)",
                "F5: Long-term debt ratio decreased (1 point)",
                "F6: Current ratio improved (1 point)",
                "F7: No share dilution issued (1 point)",
                "F8: Gross margin improved (1 point)",
                "F9: Asset turnover improved (1 point)",
                "Total 0-9: 8-9 Strong, 5-7 Neutral, 0-4 Weak",
            ],
        },
    }

    spec = calculation_specs.get(persona["id"], {})
    formulas = "\n".join(spec.get("formulas", []))
    framework_steps = "\n".join(persona.get("analysis_framework", []))

    system_prompt = (
        "You are a professional stock analyst using the " + persona["name"] + " framework.\n\n"
        "Analysis framework steps:\n" + framework_steps + "\n\n"
        "Core calculation formulas for this framework:\n" + formulas + "\n\n"
        "Rules:\n"
        "- All indicators must show actual numerical values, not just descriptions like 'high' or 'good'\n"
        "- If a value cannot be found in the data, mark as 'Data insufficient'\n"
        "- Show calculation process (e.g.: FCF = $384M - $125M = $259M)\n"
        "- Valuation conclusion must include specific price range in USD\n"
        "- Write in Traditional Chinese (zh-TW)"
    )

    user_prompt = (
        "Please analyze $" + ticker + " using the " + persona["name"] + " framework.\n\n"
        "Market data:\n" + financial_text + "\n\n"
        "Execute in order:\n"
        "1. Calculate all core formulas (show calculation process)\n"
        "2. Mark each indicator pass/fail (pass / fail / insufficient data)\n"
        "3. Red flag review (list any triggered)\n"
        "4. Valuation conclusion:\n"
        "   - Bear target price: $___\n"
        "   - Base target price: $___\n"
        "   - Bull target price: $___\n"
        "5. Investment rating: [Strong Buy / Buy / Hold / Sell / Strong Sell]\n"
        "6. Trigger conditions: what would change the rating"
    )

    return system_prompt, user_prompt


def analyze_stock(ticker: str, financial_text: str, persona_id: str) -> dict:
    persona = load_persona(persona_id)
    if not persona:
        return {"error": "Persona not found: " + persona_id}

    system_prompt, user_prompt = build_calculation_prompt(persona, ticker, financial_text)

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=3000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}]
    )

    raw_text = message.content[0].text
    structured = extract_structured_output(raw_text, persona_id)
    structured["full_analysis"] = raw_text
    structured["persona_name"] = persona["name"]

    return structured


def extract_structured_output(text: str, persona_id: str) -> dict:
    result = {
        "bear_price": None,
        "base_price": None,
        "bull_price": None,
        "rating": None,
        "persona_id": persona_id
    }

    bear_match = re.search(r"(?:Bear|悲觀)[^$\d]*\$?\s*([0-9]+\.?[0-9]*)", text, re.IGNORECASE)
    base_match = re.search(r"(?:Base|基準)[^$\d]*\$?\s*([0-9]+\.?[0-9]*)", text, re.IGNORECASE)
    bull_match = re.search(r"(?:Bull|樂觀)[^$\d]*\$?\s*([0-9]+\.?[0-9]*)", text, re.IGNORECASE)

    if bear_match:
        result["bear_price"] = float(bear_match.group(1))
    if base_match:
        result["base_price"] = float(base_match.group(1))
    if bull_match:
        result["bull_price"] = float(bull_match.group(1))

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


def run_analysis(ticker: str, financial_text: str, personas: list = None) -> dict:
    if personas is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(base_dir, "..", "personas", "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        personas = [a["id"] for a in config["analysts"]]

    results = {}
    for persona_id in personas:
        print("Running framework: " + persona_id)
        results[persona_id] = analyze_stock(ticker, financial_text, persona_id)

    return results


def generate_comparison_table(ticker: str, results: dict) -> str:
    table = "## $" + ticker + " Multi-Framework Valuation Comparison\n\n"
    table += "| 分析框架 | 悲觀目標價 | 基準目標價 | 樂觀目標價 | 投資評級 |\n"
    table += "|---|---|---|---|---|\n"

    base_prices = []
    for persona_id, result in results.items():
        if isinstance(result, dict) and "full_analysis" in result:
            bear = "$" + str(result["bear_price"]) if result.get("bear_price") else "N/A"
            base = "$" + str(result["base_price"]) if result.get("base_price") else "N/A"
            bull = "$" + str(result["bull_price"]) if result.get("bull_price") else "N/A"
            rating = result.get("rating", "N/A")
            name = result.get("persona_name", persona_id)
            table += "| " + name + " | " + bear + " | " + base + " | " + bull + " | " + rating + " |\n"
            if result.get("base_price"):
                base_prices.append(result["base_price"])

    if base_prices:
        consensus = sum(base_prices) / len(base_prices)
        table += "\n**共識目標價（基準平均）: $" + str(round(consensus, 2)) + "**\n"

    return table


if __name__ == "__main__":
    sample = "Test financial data"
    result = analyze_stock("SNDK", sample, "piotroski_fscore")
    print(result.get("full_analysis", ""))
