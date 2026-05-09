from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os, sys, json, time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

app = FastAPI(title="AI Investment HQ API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Rate Limiting ===
# In-memory store: {ip: [timestamp, ...]}
_rate_store: dict = defaultdict(list)
RATE_LIMIT_FREE = 50     # requests per hour per IP (raise for development)
RATE_LIMIT_WINDOW = 3600  # 1 hour in seconds

def check_rate_limit(ip: str, limit: int = RATE_LIMIT_FREE) -> tuple:
    """Returns (allowed: bool, remaining: int, reset_in: int)"""
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW
    # Clean old entries
    _rate_store[ip] = [t for t in _rate_store[ip] if t > window_start]
    count = len(_rate_store[ip])
    if count >= limit:
        oldest = _rate_store[ip][0]
        reset_in = int(oldest + RATE_LIMIT_WINDOW - now)
        return False, 0, reset_in
    _rate_store[ip].append(now)
    return True, limit - count - 1, 0


class AnalysisRequest(BaseModel):
    ticker: str
    persona_id: Optional[str] = "all"
    manual_text: Optional[str] = ""


@app.get("/")
def root():
    return {"status": "ok", "message": "AI Investment HQ API v2.0"}


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "fmp_key_set": bool(os.environ.get("FMP_API_KEY")),
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


@app.post("/analyze")
async def analyze(req: AnalysisRequest, request: Request):
    # Rate limiting
    client_ip = request.client.host if request.client else "unknown"
    allowed, remaining, reset_in = check_rate_limit(client_ip)

    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. {RATE_LIMIT_FREE} requests/hour. Try again in {reset_in}s."
        )

    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, os.path.join(base_dir, "..", "agents"))

        from full_pipeline import full_auto_pipeline
        result = full_auto_pipeline(
            ticker=req.ticker.upper().strip(),
            persona=req.persona_id or "all",
            manual_text=req.manual_text or ""
        )

        return {
            "ticker": result.get("ticker", req.ticker),
            "company": result.get("company", req.ticker),
            "timestamp": result.get("timestamp", ""),
            "comparison_table": result.get("comparison_table", ""),
            "analyses": result.get("analyses", {}),
            "structured_results": result.get("structured_results", {}),
            "raw_data_preview": "",
            "rate_limit_remaining": remaining,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析失敗: {str(e)}")
