import os
import json
import re
import concurrent.futures
import anthropic


from scorecard_engine import compute_scorecard, format_scorecard_text


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

    # Compute deterministic scorecard from financial_text (already fetched, no re-fetch)
    # Note: scorecard uses the financial data passed in, not fetch_stock_data again
    try:
        # Extract price from financial_text
        _price_for_sc = None
        _price_match_sc = re.search(r"Current[^\n]{0,30}\$([0-9,]+\.?[0-9]*)", str(financial_text or "")[:800])
        if _price_match_sc:
            try: _price_for_sc = float(_price_match_sc.group(1).replace(",",""))
            except: pass
        # Build minimal financials dict from financial_text for scorecard
        _f_sc = {}
        for _k, _pattern in [
            ("gross_margin", r"Gross Margin[：: ]*([0-9.]+)%"),
            ("net_margin", r"Net Margin[：: ]*([0-9.]+)%"),
            ("revenue", r"Revenue[：: ]*\$([0-9.]+[BMK]?)"),
        ]:
            _m = re.search(_pattern, str(financial_text or "")[:3000])
            if _m: _f_sc[_k] = _m.group(1)
        if _price_for_sc: _f_sc["price"] = _price_for_sc
        _sc = compute_scorecard(str(ticker or ""), _f_sc, price=_price_for_sc)
        _scorecard_text = format_scorecard_text(_sc, str(ticker or ""), price=_price_for_sc)
    except Exception as _e:
        _scorecard_text = ""
        print(f"Scorecard engine error (non-blocking): {_e}")

    user_prompt = (
        "Analyze $" + str(ticker or "") + " using the " + str(persona.get("name","") or "") + " framework.\n\n"
        "=== PYTHON-CALCULATED SCORECARD (use these exact numbers - do not recalculate) ===\n" 
        + str(_scorecard_text) + "\n\n"
        "=== ADDITIONAL DATA ===\n" + str(financial_text or "")[:3000] + str(market_section or "") + str(_price_note) + "\n\n"
        "=== REQUIRED OUTPUT (Traditional Chinese, ALL sections mandatory) ===\n\n"
        "**分析框架：" + str(persona.get("name","") or "") + "**\n\n"
        "**一、核心計算**\n"
        "（逐一列出所有公式，顯示計算過程和具體數字）\n\n"
        "**二、指標評分**\n"
        "| 指標 | 數值 | 標準 | 評分 |\n|---|---|---|---|\n"
        "（每個指標填入具體數值，✅通過 / ❌未通過 / ⚠️數據不足）\n\n"
        "**三、市場情緒評估**\n"
        "（根據VIX/利率/板塊ETF數據，說明當前市場情緒對本股的影響）\n\n"
        "**四、主要風險**\n"
        "（列出前3項風險，每項附具體數字佐證）\n\n"
        "**五、估值結論**\n"
        "- 悲觀目標價: $___\n"
        "- 基準目標價: $___\n"
        "- 樂觀目標價: $___\n"
        "- **評級: [強力買進/買進/觀望/賣出/強力迴避]**\n"
        "- 升級觸發: ___\n"
        "- 降級觸發: ___"
    )
    return system_prompt, user_prompt



# === Tiered Model Selection ===
MODEL_TIERS = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-4-5",
    "opus": "claude-opus-4-5",
}
# Opus for complex qualitative reasoning - only when data quality is LOW (<40%)
# High data quality stocks can use Sonnet which is 3x faster
OPUS_FRAMEWORKS = set()  # Disabled - use data_quality check instead for Opus
# Haiku for structured scoring (fast, deterministic)
HAIKU_FRAMEWORKS = {"piotroski_fscore", "technical_analysis"}

def assess_data_quality(text: str) -> int:
    """Score 0-100: how much real financial data is available."""
    import re
    score = 0
    if re.search(r"Revenue:.*\$[0-9]", text): score += 20
    if re.search(r"Net Income:.*\$[0-9]", text): score += 20
    if re.search(r"Gross Margin:.*[0-9]+%", text): score += 15
    if re.search(r"(FCF|Free Cash Flow):.*\$[0-9]", text): score += 15
    if re.search(r"P/E.*[0-9]+", text): score += 10
    if re.search(r"EPS.*[0-9]+", text): score += 10
    if "VIX" in text: score += 5
    if re.search(r"Market Cap.*\$[0-9]", text): score += 5
    return min(score, 100)

def select_model(persona_id: str, data_quality: int) -> str:
    """Choose model: Haiku/Sonnet/Opus based on task complexity and data availability."""
    # SPEED PROTECTION: Never use Opus from env override (too slow: 50s+)
    # Set ANALYSIS_MODEL=claude-sonnet-4-5 in Railway to use Sonnet everywhere
    # Or leave empty to use tiered selection (recommended)
    env_override = os.environ.get("ANALYSIS_MODEL", "")
    if env_override and env_override == MODEL_TIERS["haiku"]:
        return MODEL_TIERS["haiku"]
    if env_override and env_override == MODEL_TIERS["sonnet"]:
        return MODEL_TIERS["sonnet"]
    # Ignore opus env override - use tiered selection instead
    if persona_id in HAIKU_FRAMEWORKS and data_quality >= 70:
        return MODEL_TIERS["haiku"]   # Fast + cheap for structured scoring
    else:
        return MODEL_TIERS["sonnet"]  # Default: use Sonnet for speed (~10-15s vs Opus 50s+)


def analyze_one(ticker: str, financial_text: str, persona_id: str, market_context: str = "") -> dict:
    persona = load_persona(persona_id)
    if not persona:
        return {"error": "Persona not found: " + persona_id, "persona_id": persona_id}

    system_prompt, user_prompt = build_prompt(persona, ticker, financial_text, market_context)
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    # Use tiered model selection: Haiku(tech/piotroski), Sonnet(default), never Opus
    _dq = assess_data_quality(str(financial_text or ""))
    _selected = select_model(persona_id, _dq)
    print(f"  [{persona_id}] model={_selected.split('-')[-2]} dq={_dq}")
    
    message = client.messages.create(
        model=_selected,
        max_tokens=2500,  # Increased: 5-section format needs ~2000 tokens
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
    if not text:
        return result

    # === PRICE EXTRACTION ===
    # Match patterns like: 悲觀目標價: $250 or 悲觀目標價：$250 or 悲觀: $250 or Bear: $250
    # Chinese colon ：and English colon : both handled, dollar sign optional
    # Patterns: require 目標價 to avoid matching table rows or other uses of 悲觀/基準/樂觀
    # "悲觀目標價: $235" / "悲觀目標價：**$235**" / "Bear: $235"
    price_patterns = {
        "bear": [
            r"悲觀目標價[：:\s\*]*\$?([0-9,]+\.?[0-9]*)",
            r"悲觀[^\n]*?\*\*\$([0-9,]+\.?[0-9]*)\*\*",
            r"Bear[^$\n]{0,20}\$([0-9,]+\.?[0-9]*)",
        ],
        "base": [
            r"基準目標價[：:\s\*]*\$?([0-9,]+\.?[0-9]*)",
            r"Base[^$\n]{0,20}\$([0-9,]+\.?[0-9]*)",
        ],
        "bull": [
            r"樂觀目標價[：:\s\*]*\$?([0-9,]+\.?[0-9]*)",
            r"Bull[^$\n]{0,20}\$([0-9,]+\.?[0-9]*)",
        ],
    }

    def find_price(patterns):
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                try:
                    v = float(m.group(1).replace(",", ""))
                    if v > 0:
                        return v
                except Exception:
                    pass
        return None

    bear = find_price(price_patterns["bear"])
    base = find_price(price_patterns["base"])
    bull = find_price(price_patterns["bull"])

    # === CURRENT PRICE EXTRACTION ===
    current_price = None
    for cp_pat in [
        r"當前市場股價為 \$([0-9,]+\.?[0-9]*)",
        r"Current[^\n]{0,40}\$([0-9]+\.?[0-9]*)",
        r"現價[：: ]*NT?\$?([0-9,]+\.?[0-9]*)",
    ]:
        cp_m = re.search(cp_pat, text[:2000])
        if cp_m:
            try:
                cp = float(cp_m.group(1).replace(",", ""))
                if cp > 0.5:
                    current_price = cp
                    break
            except Exception:
                pass

    # === VALUE_FRAMEWORKS bypass plausibility check ===
    VALUE_FRAMEWORKS = {"benjamin_graham", "piotroski_fscore", "technical_analysis"}
    skip_plausibility = persona_id in VALUE_FRAMEWORKS

    def is_plausible(v):
        if v is None or v <= 0:
            return False
        if skip_plausibility:
            return True
        if current_price and current_price > 1:
            return 0.1 < v / current_price < 10
        return True

    bear = bear if is_plausible(bear) else None
    base = base if is_plausible(base) else None
    bull = bull if is_plausible(bull) else None

    # Auto-sort: ensure bear <= base <= bull
    non_null = sorted([p for p in [bear, base, bull] if p is not None])
    if len(non_null) == 3 and not (non_null[0] <= non_null[1] <= non_null[2]):
        bear, base, bull = non_null[0], non_null[1], non_null[2]
    elif len(non_null) == 2:
        if base is None:
            base = round((non_null[0] + non_null[1]) / 2, 1)
        elif bear is None:
            bear = round(base * 0.8, 1)
        elif bull is None:
            bull = round(base * 1.2, 1)
    elif len(non_null) == 1:
        ref = non_null[0]
        bear = bear or round(ref * 0.8, 1)
        base = base or ref
        bull = bull or round(ref * 1.2, 1)

    result["bear_price"] = bear
    result["base_price"] = base
    result["bull_price"] = bull

    # === RATING EXTRACTION ===
    # Find the ACTUAL rating line (after 評級: or Rating:), not mentions in trigger conditions
    rating = None
    # Look for rating in the 估值結論 section specifically
    valuation_section = ""
    val_idx = text.find("估值結論")
    if val_idx >= 0:
        valuation_section = text[val_idx:val_idx + 1000]
    else:
        valuation_section = text[-1200:]  # Use last part if no section found

    # Priority: find "評級: X" pattern (explicit rating declaration)
    explicit_patterns = [
        r"評級[：: ]*([強力買進觀望賣出迴避]+)",
        r"\*\*評級[：: ]*([^*\n]+)\*\*",
        r"Rating[：: ]*(Strong Buy|Buy|Hold|Sell|Strong Sell)",
    ]
    rating_map = {
        "強力買進": "強力買進", "Strong Buy": "強力買進",
        "買進": "買進", "Buy": "買進",
        "觀望": "觀望", "Hold": "觀望",
        "賣出": "賣出", "Sell": "賣出",
        "強力迴避": "強力迴避", "Strong Sell": "強力迴避",
        "迴避": "強力迴避",
    }

    for pat in explicit_patterns:
        m = re.search(pat, valuation_section)
        if m:
            raw = m.group(1).strip()
            for key, val in rating_map.items():
                if key in raw:
                    rating = val
                    break
            if rating:
                break

    # Fallback: search whole text but avoid trigger condition sections
    if not rating:
        # Remove trigger condition sections to avoid false matches
        clean_text = re.sub(r"觸發條件.*", "", valuation_section, flags=re.DOTALL)
        for key in ["強力買進", "買進", "觀望", "賣出", "強力迴避"]:
            if key in clean_text:
                rating = key
                break

    result["rating"] = rating
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
