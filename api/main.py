from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

app = FastAPI(
    title="AI Investment HQ API",
    description="多人格 AI 股市分析引擎",
    version="1.0.0"
)

# CORS - 允許前端呼叫
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class AnalysisRequest(BaseModel):
    ticker: str
    persona_id: Optional[str] = "all"
    manual_text: Optional[str] = ""

class AnalysisResponse(BaseModel):
    ticker: str
    company: str
    timestamp: str
    analyses: dict
    raw_data_preview: str

@app.get("/")
def root():
    return {"status": "ok", "message": "AI Investment HQ API"}

@app.get("/personas")
def list_personas():
    """列出所有可用的分析師人格"""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(base_dir, "..", "personas", "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        return {
            "personas": [
                {
                    "id": a["id"],
                    "name": a["name"],
                    "description": a["description"]
                }
                for a in config["analysts"]
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze", response_model=AnalysisResponse)
async def analyze(req: AnalysisRequest):
    """
    主分析端點
    輸入股票代號，自動抓資料並執行大師分析
    """
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, os.path.join(base_dir, "..", "agents"))
        
        from full_pipeline import full_auto_pipeline
        
        result = full_auto_pipeline(
            ticker=req.ticker.upper(),
            persona=req.persona_id,
            manual_text=req.manual_text or ""
        )
        
        return AnalysisResponse(
            ticker=result["ticker"],
            company=result.get("company", req.ticker),
            timestamp=result["timestamp"],
            analyses=result["analyses"],
            raw_data_preview=result.get("raw_data", "")[:500] + "..."
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析失敗: {str(e)}")

@app.get("/health")
def health():
    return {"status": "healthy", "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY"))}
