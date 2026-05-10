"""
data_validator.py - Data Quality Gate
Validates data completeness and correctness before analysis.
Called by full_pipeline.py to ensure stable, correct inputs.
"""
import re


def validate_financial_data(ticker: str, data: dict) -> dict:
    """
    Validate financial data quality.
    Returns: {
        "valid": bool,
        "warnings": list of str,
        "errors": list of str,
        "score": int (0-100, data quality score)
    }
    """
    warnings = []
    errors = []
    f = data.get("financials", {})
    
    # === Price Check ===
    price = f.get("price") or f.get("price_twd")
    if not price or price <= 0:
        errors.append("PRICE: Current price unavailable")
    
    # === Core Financial Metrics ===
    required_metrics = ["revenue", "net_income", "total_assets"]
    optional_metrics = ["gross_profit", "ocf", "fcf", "cash", "equity", "shares"]
    
    missing_required = [m for m in required_metrics if not f.get(m)]
    missing_optional = [m for m in optional_metrics if not f.get(m)]
    
    if missing_required:
        errors.append(f"CRITICAL MISSING: {', '.join(missing_required)}")
    if missing_optional:
        warnings.append(f"MISSING (non-critical): {', '.join(missing_optional)}")
    
    # === Data Freshness Check ===
    # Look for fiscal year in summary text
    summary = data.get("summary", "")
    current_year = 2026
    years_found = [int(y) for y in re.findall(r"20(2[3-9]|3[0-9])", summary)]
    if years_found:
        latest_data_year = max(years_found)
        if latest_data_year < current_year - 1:
            warnings.append(f"STALE DATA: Most recent data from {latest_data_year} (expected {current_year-1} or {current_year})")
    
    # === Sanity Checks ===
    # Revenue should be positive
    rev_str = str(f.get("revenue", ""))
    if rev_str and rev_str.startswith("$-"):
        errors.append("REVENUE NEGATIVE: Revenue cannot be negative")
    
    # Gross margin sanity
    gm_str = str(f.get("gross_margin", ""))
    if gm_str and "%" in gm_str:
        try:
            gm = float(gm_str.replace("%",""))
            if gm < -50 or gm > 100:
                errors.append(f"GROSS MARGIN INVALID: {gm}% (outside -50% to 100% range)")
            elif gm > 90:
                warnings.append(f"GROSS MARGIN SUSPICIOUS: {gm}% (very high, verify data period alignment)")
        except Exception:
            pass
    
    # Net margin sanity for non-startup companies
    nm_str = str(f.get("net_margin", ""))
    if nm_str and "%" in nm_str:
        try:
            nm = float(nm_str.replace("%",""))
            if nm > 80:
                warnings.append(f"NET MARGIN SUSPICIOUS: {nm}% (very high)")
        except Exception:
            pass
    
    # Calculate quality score
    total_checks = len(required_metrics) + len(optional_metrics) + 2  # +2 for price and freshness
    passed_checks = (len(required_metrics) - len(missing_required)) + (len(optional_metrics) - len(missing_optional))
    if price: passed_checks += 1
    if not warnings: passed_checks += 1
    
    score = int(passed_checks / total_checks * 100)
    
    return {
        "valid": len(errors) == 0,
        "warnings": warnings,
        "errors": errors,
        "score": score,
        "summary": f"Data Quality: {score}/100" + (f" | Errors: {len(errors)}" if errors else "") + (f" | Warnings: {len(warnings)}" if warnings else "")
    }


def validate_analysis_output(persona_id: str, analysis_text: str, current_price: float = None) -> dict:
    """
    Validate analysis output quality.
    Checks: required sections present, prices reasonable, rating valid.
    """
    issues = []
    
    # Check required sections
    required_sections = ["核心計算", "指標評分", "估值結論"]
    for section in required_sections:
        if section not in analysis_text:
            issues.append(f"MISSING SECTION: {section}")
    
    # Check target prices extractable
    import re
    bear = re.search(r"悲觀[目標價:：\s]*\$?([0-9,]+\.?[0-9]*)", analysis_text)
    base = re.search(r"基準[目標價:：\s]*\$?([0-9,]+\.?[0-9]*)", analysis_text)
    bull = re.search(r"樂觀[目標價:：\s]*\$?([0-9,]+\.?[0-9]*)", analysis_text)
    
    if not any([bear, base, bull]):
        issues.append("NO TARGET PRICES: Analysis missing price targets")
    elif current_price and current_price > 1:
        # Value frameworks can show lower-than-market prices
        value_frameworks = {"benjamin_graham", "piotroski_fscore"}
        if persona_id not in value_frameworks:
            for label, match in [("Bear", bear), ("Base", base), ("Bull", bull)]:
                if match:
                    try:
                        v = float(match.group(1))
                        ratio = v / current_price
                        if ratio < 0.1 or ratio > 10:
                            issues.append(f"{label} PRICE IMPLAUSIBLE: ${v} vs current ${current_price}")
                    except Exception:
                        pass
    
    # Check rating present
    ratings = ["強力買進", "買進", "觀望", "賣出", "強力迴避"]
    rating_found = any(r in analysis_text for r in ratings)
    if not rating_found:
        issues.append("NO RATING: Analysis missing investment rating")
    
    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "quality": "GOOD" if not issues else ("WARN" if len(issues) <= 2 else "POOR")
    }
