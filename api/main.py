from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os, sys, json, time
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

app = FastAPI(title="AI Investment HQ API", version="3.2.4")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Rate Limiting ===
_rate_store: dict = defaultdict(list)
RATE_LIMIT = 50  # requests per hour per IP (normal users)

# === Admin / Whitelist (unlimited access) ===
# Add your own IP here for unlimited use
# Format: set of IPs or special token "ADMIN_TOKEN"
ADMIN_TOKEN = "stockiq-admin-2026"  # Pass as X-Admin-Token header for unlimited
LAUNCH_MODE = True  # During launch: all users get higher limits

# Launch mode: 200 requests/hour instead of 50
LAUNCH_RATE_LIMIT = 200

def check_rate_limit(ip: str, admin_token: str = "") -> tuple:
    # Admin token = unlimited
    if admin_token == ADMIN_TOKEN:
        return True, 9999, 0
    
    # Use higher limit during launch phase
    limit = LAUNCH_RATE_LIMIT if LAUNCH_MODE else RATE_LIMIT
    
    now = time.time()
    window_start = now - 3600
    _rate_store[ip] = [t for t in _rate_store[ip] if t > window_start]
    count = len(_rate_store[ip])
    if count >= limit:
        reset_in = int(_rate_store[ip][0] + 3600 - now)
        return False, 0, reset_in
    _rate_store[ip].append(now)
    return True, limit - count - 1, 0

# === Query Tracking (热门追踪) ===
_query_counter: dict = defaultdict(int)  # {ticker: count}
_query_history: list = []  # [{ticker, timestamp, persona}]

def track_query(ticker: str, persona: str):
    ticker = ticker.upper()
    _query_counter[ticker] += 1
    _query_history.append({
        "ticker": ticker,
        "persona": persona,
        "timestamp": datetime.now().isoformat(),
    })
    # Keep only last 1000 queries
    if len(_query_history) > 1000:
        _query_history.pop(0)



SUPABASE_URL = "https://kggwnlevbxghmqpieoet.supabase.co"
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImtnZ3dubGV2YnhnaG1xcGllb2V0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzg0NDE2MTgsImV4cCI6MjA5NDAxNzYxOH0.G-Z1R_OoyqT_3AGQThzPaOdh-qhrBe8cD1acz-nV_QY")
# Note: for production, set SUPABASE_SERVICE_KEY env var with the service_role key (not anon key)

FREE_DAILY_LIMIT = 3  # Unregistered users: 3/day via IP
REGISTERED_FREE_CREDITS = 3  # New users start with 3 credits

def verify_jwt_and_get_credits(jwt_token: str) -> tuple:
    """Verify Supabase JWT and return (user_id, credits_remaining)"""
    try:
        headers = {"Authorization": f"Bearer {jwt_token}", "apikey": SUPABASE_SERVICE_KEY}
        resp = requests.get(f"{SUPABASE_URL}/auth/v1/user", headers=headers, timeout=5)
        if resp.status_code != 200:
            return None, 0
        user_data = resp.json()
        user_id = user_data.get("id")
        if not user_id:
            return None, 0
        credit_resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/user_credits?user_id=eq.{user_id}&select=credits",
            headers={**headers, "Content-Type": "application/json"},
            timeout=5
        )
        if credit_resp.status_code == 200:
            data = credit_resp.json()
            credits = data[0]["credits"] if data else REGISTERED_FREE_CREDITS
        else:
            credits = REGISTERED_FREE_CREDITS
        return user_id, credits
    except Exception as e:
        print(f"JWT verify error: {e}")
        return None, 0

def deduct_credit(user_id: str, jwt_token: str) -> bool:
    """Deduct 1 credit from user."""
    try:
        headers = {"Authorization": f"Bearer {jwt_token}", "apikey": SUPABASE_SERVICE_KEY,
                   "Content-Type": "application/json"}
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/rpc/deduct_credit",
            json={"p_user_id": user_id},
            headers=headers,
            timeout=5
        )
        return resp.status_code in (200, 204)
    except Exception as e:
        print(f"Deduct credit error: {e}")
        return False


# === Data Cache ===
# Cache: {ticker: {"data": {...}, "expires": timestamp, "version": str}}
_data_cache: dict = {}

# Cache TTL by data type
CACHE_TTL = {
    "price": 5 * 60,          # 5 min - stock prices change frequently
    "financials": 24 * 3600,   # 24 hours - financial statements update quarterly
    "analysis": 6 * 3600,      # 6 hours - full analysis (expensive to compute)
    "market_context": 15 * 60, # 15 min - VIX/sentiment changes
}

def get_cached(ticker: str, persona: str) -> Optional[dict]:
    key = f"{ticker}:{persona}"
    if key in _data_cache:
        entry = _data_cache[key]
        if time.time() < entry["expires"]:
            return entry["data"]
        else:
            del _data_cache[key]
    return None

def set_cache(ticker: str, persona: str, data: dict):
    key = f"{ticker}:{persona}"
    _data_cache[key] = {
        "data": data,
        "expires": time.time() + CACHE_TTL["analysis"],
        "cached_at": datetime.now().isoformat(),
    }


class AnalysisRequest(BaseModel):
    ticker: str
    persona_id: Optional[str] = "all"
    manual_text: Optional[str] = ""
    force_refresh: Optional[bool] = False  # bypass cache
    lang: Optional[str] = "zh"  # "zh" = Traditional Chinese, "en" = English


@app.get("/")
def root():
    return {"status": "ok", "version": "4.2.3", "model": "claude-haiku-4-5 (fast)"}


@app.get("/tw-test/{ticker}")
async def tw_test(ticker: str):
    """Direct test of tw_fetcher for Taiwan stocks."""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, os.path.join(base_dir, "..", "agents"))
        from tw_fetcher import fetch_tw_stock_data, build_tw_summary, fetch_tw_news, get_tw_stock_id
        data = fetch_tw_stock_data(ticker)
        return {
            "ticker": ticker,
            "raw_data": data,
            "revenue": data.get("revenue"),
            "gross_margin": data.get("gross_margin"),
            "net_income": data.get("net_income"),
            "eps": data.get("eps"),
            "pe_ratio": data.get("pe_ratio"),
            "pb_ratio": data.get("pb_ratio"),
            "company_name": data.get("company_name"),
            "keys": list(data.keys()),
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "trace": traceback.format_exc()[:1000]}


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "version": "4.2.3",
        "model": "claude-haiku-4-5 (fast)",
        "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "fmp_key_set": bool(os.environ.get("FMP_API_KEY")),
        "cache_entries": len(_data_cache),
        "total_queries": sum(_query_counter.values()),
    }


@app.get("/personas")
def list_personas():
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(base_dir, "..", "personas", "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        return {
            "personas": [
                {"id": a["id"], "name": a["name"], "description": a.get("description", "")}
                for a in config["analysts"]
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/trending")
def trending():
    """Top queried tickers - potential smart money flow indicator"""
    sorted_tickers = sorted(_query_counter.items(), key=lambda x: x[1], reverse=True)
    recent_hour = [q["ticker"] for q in _query_history[-100:]
                   if time.time() - time.mktime(
                       datetime.fromisoformat(q["timestamp"]).timetuple()) < 3600]
    from collections import Counter
    recent_counts = Counter(recent_hour)
    
    return {
        "all_time": [{"ticker": t, "queries": c} for t, c in sorted_tickers[:10]],
        "last_hour": [{"ticker": t, "queries": c} for t, c in recent_counts.most_common(10)],
        "note": "High query frequency may indicate institutional interest or news catalysts",
    }


@app.get("/data-test/{ticker}")
async def data_test(ticker: str):
    """Diagnostic: see what data we fetch for a ticker"""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, os.path.join(base_dir, "..", "agents"))
        from data_fetcher import fetch_stock_data, get_cik, get_sec_xbrl, TICKER_CIK
        
        ticker_up = ticker.upper()
        
        # Test SEC connectivity directly
        import requests as req_lib
        sec_test = {"status": "untested", "cik": None, "xbrl_keys": 0}
        try:
            cik = TICKER_CIK.get(ticker_up) or get_cik(ticker_up)
            sec_test["cik"] = cik
            if cik:
                cik_pad = cik.lstrip("0").zfill(10)
                sec_resp = req_lib.get(
                    f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_pad}.json",
                    headers={"User-Agent": "AI-Investment-HQ research@example.com"},
                    timeout=15
                )
                sec_test["http_status"] = sec_resp.status_code
                if sec_resp.status_code == 200:
                    raw_gaap = sec_resp.json().get("facts", {}).get("us-gaap", {})
                    sec_test["xbrl_keys"] = len(raw_gaap)
                    sec_test["sample_keys"] = list(raw_gaap.keys())[:5]
                    rev_data = raw_gaap.get("RevenueFromContractWithCustomerExcludingAssessedTax",{}).get("units",{}).get("USD",[])
                    k10s = [x for x in rev_data if x.get("form")=="10-K" and x.get("end","")>="2024-01-01"]
                    sec_test["revenue_10k_count"] = len(k10s)
                    sec_test["status"] = "ok"
                    if k10s:
                        latest = sorted(k10s, key=lambda x: x.get("end",""))[-1]
                        sec_test["revenue_latest"] = f"${latest.get('val',0)/1e9:.2f}B ({latest.get('end')})"
        except Exception as e:
            sec_test["error"] = str(e)[:100]
        
        # Full data fetch
        data = fetch_stock_data(ticker_up)
        f = data.get("financials", {})
        return {
            "ticker": ticker_up,
            "sec_test": sec_test,
            "company": f.get("company_name"),
            "price": f.get("price"),
            "revenue": f.get("revenue"),
            "revenue_ttm": f.get("revenue_ttm"),
            "net_income": f.get("net_income"),
            "gross_margin": f.get("gross_margin"),
            "ocf": f.get("ocf"),
            "capex": f.get("capex"),
            "fcf": f.get("fcf"),
            "eps_ttm": f.get("eps_ttm"),
            "eps_diluted": f.get("eps_diluted"),
            "eps_ttm": f.get("eps_ttm"),
            "eps_latest_q": f.get("eps_latest_q"),
            "eps_latest_q_period": f.get("eps_latest_q_period"),
            "eps_ttm_components": f.get("eps_ttm_components"),
            "gross_margin": f.get("gross_margin"),
            "gross_margin_latest_q": f.get("gross_margin_latest_q"),
            "gross_margin_annual": f.get("gross_margin_annual"),
            "qoq_data": f.get("qoq_data"),
            "de_ratio": f.get("de_ratio"),
            "revenue_growth_yoy": f.get("revenue_growth_yoy"),
            "current_ratio": f.get("current_ratio"),
            "goodwill_ratio": f.get("goodwill_ratio"),
            "sbc_pct": f.get("sbc_pct"),
            "financials_keys": list(f.keys()),
            "summary_length": len(data.get("summary", "")),
            "summary_preview": data.get("summary", "")[:600],
        }
    except Exception as e:
        import traceback
        raise HTTPException(status_code=500, detail=f"Data test failed: {str(e)}\n{traceback.format_exc()[:500]}")


@app.get("/cache")
def cache_status():
    """Show cache contents and hit rates"""
    now = time.time()
    active = {k: {"expires_in": int(v["expires"] - now), "cached_at": v["cached_at"]}
              for k, v in _data_cache.items() if v["expires"] > now}
    return {"active_entries": len(active), "entries": active}


@app.get("/macro")
async def macro_overview():
    """Total economy + broad sector + sub-sector 52W capital flow. Cached 15 min."""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, os.path.join(base_dir, "..", "agents"))
        from macro_fetcher import fetch_macro_overview
        return fetch_macro_overview()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Macro data failed: {str(e)}")


@app.get("/macro/ticker/{ticker}")
async def ticker_sector_context(ticker: str):
    """Get sector context for a specific ticker - which sector it belongs to and that sector's flow."""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, os.path.join(base_dir, "..", "agents"))
        from macro_fetcher import get_ticker_sector_context
        return get_ticker_sector_context(ticker.upper())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sector context failed: {str(e)}")


@app.post("/analyze")
async def analyze(req: AnalysisRequest, request: Request, x_admin_token: str = Header(default=''), authorization: str = Header(default='')):
    client_ip = request.client.host if request.client else "unknown"
    allowed, remaining, reset_in = check_rate_limit(client_ip, admin_token=x_admin_token)
    
    # JWT auth check (skip for admin token)
    user_id = None
    if x_admin_token != ADMIN_TOKEN:
        jwt_token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else ""
        if jwt_token:
            user_id, user_credits = verify_jwt_and_get_credits(jwt_token)
            if user_id is None:
                raise HTTPException(status_code=401, detail="無效的登入憑證，請重新登入")
            if user_credits <= 0:
                raise HTTPException(status_code=403, detail="分析次數不足，請購買次數包")
        else:
            # No token: check IP-based daily limit (3/day)
            ip_day_key = client_ip + "_" + str(int(time.time() // 86400))
            ip_daily = _rate_store.get(ip_day_key, [])
            ip_daily = [t for t in ip_daily if time.time() - t < 86400]
            if len(ip_daily) >= FREE_DAILY_LIMIT:
                raise HTTPException(status_code=401, detail="免費次數已用完，請登入以繼續使用")
            ip_daily.append(time.time())
            _rate_store[ip_day_key] = ip_daily
    if not allowed:
        raise HTTPException(status_code=429, detail=f"Rate limit exceeded. Try again in {reset_in}s.")

    ticker_clean = req.ticker.upper().strip()
    persona = req.persona_id or "all"
    
    # Track this query
    track_query(ticker_clean, persona)
    
    # Check cache (unless force_refresh)
    if not req.force_refresh:
        cached = get_cached(ticker_clean, persona)
        if cached:
            cached["from_cache"] = True
            cached["rate_limit_remaining"] = remaining
            return cached

    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, os.path.join(base_dir, "..", "agents"))

        from data_fetcher import validate_ticker
        valid, err_msg = validate_ticker(ticker_clean)
        if not valid:
            raise HTTPException(status_code=404, detail=err_msg or f"查無此代碼：{ticker_clean}")

        from full_pipeline import full_auto_pipeline
        result = full_auto_pipeline(
            ticker=ticker_clean,
            persona=persona,
            manual_text=req.manual_text or ""
        , lang=req.lang)

        response = {
            "ticker": result.get("ticker", ticker_clean),
            "company": result.get("company", ticker_clean),
            "timestamp": result.get("timestamp", ""),
            "comparison_table": result.get("comparison_table", ""),
            "market_context": result.get("market_context", ""),
            "market_summary": result.get("market_summary", ""),
            "analyses": result.get("analyses", {}),
            "structured_results": result.get("structured_results", {}),
            "current_price": result.get("current_price"),
            "raw_data_preview": "",
            "rate_limit_remaining": remaining,
            "from_cache": False,
        }
        
        # Cache the result
        set_cache(ticker_clean, persona, response)
        
        # Deduct credit for authenticated users (only if not from cache)
        if user_id and not response.get("from_cache"):
            deduct_credit(user_id, jwt_token)
        return response

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析失敗: {str(e)}")
