import os
import json
import anthropic

def load_persona(persona_id: str) -> dict:
    """載入指定分析師人格設定"""
    with open("./personas/config.json", "r", encoding="utf-8") as f:
        personas = json.load(f)["analysts"]
    return next((p for p in personas if p["id"] == persona_id), None)

def analyze_stock(ticker: str, financial_text: str, persona_id: str) -> str:
    """
    用指定大師人格分析股票財報
    
    Args:
        ticker: 股票代號，例如 "RDW"
        financial_text: 財報內容或新聞文字
        persona_id: 使用的分析師 ID（dashu_veteran / bian_supplychain）
    
    Returns:
        大師風格的分析報告文字
    """
    persona = load_persona(persona_id)
    if not persona:
        return f"找不到 persona: {persona_id}"
    
    framework_text = "
".join([f"{i+1}. {step}" for i, step in enumerate(persona["analysis_framework"])])
    metrics_text = ", ".join(persona["priority_metrics"])
    
    system_prompt = f"""你是一位名為「{persona["name"]}」的投資分析師。
    
你的風格：{persona["tone"]}

你的分析框架（按順序執行）：
{framework_text}

你最重視的指標：{metrics_text}

你的慣用語：{" | ".join(persona.get("signature_phrases", []))}

請完全用這個角色的語氣和邏輯進行分析，不要打破角色。"""

    user_prompt = f"""請針對以下  的財報/報告內容，以你的分析框架給出完整解析：

{financial_text}

最後請給出：
1. 核心觀點（2-3 句）
2. 最大風險警示
3. 你的個人結論（買/觀望/避開，並說明理由）"""

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}]
    )
    
    return message.content[0].text

def run_analysis(ticker: str, financial_text: str, personas: list = None) -> dict:
    """
    對一支股票執行一個或多個大師分析
    
    Args:
        ticker: 股票代號
        financial_text: 財報內容
        personas: 要執行的 persona ID 列表，預設全部執行
    """
    if personas is None:
        with open("./personas/config.json", "r", encoding="utf-8") as f:
            config = json.load(f)
        personas = [a["id"] for a in config["analysts"]]
    
    results = {}
    for persona_id in personas:
        print(f"正在用 {persona_id} 分析 ...")
        results[persona_id] = analyze_stock(ticker, financial_text, persona_id)
    
    return results

# 範例用法
if __name__ == "__main__":
    # 測試用財報文字（替換成真實財報內容）
    sample_text = "請貼上財報內容"
    
    # 只跑大叔分析
    result = analyze_stock("RDW", sample_text, "dashu_veteran")
    print(result)
