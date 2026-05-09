import os
import json
import anthropic

def load_persona(persona_id: str) -> dict:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_dir, "..", "personas", "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        personas = json.load(f)["analysts"]
    return next((p for p in personas if p["id"] == persona_id), None)

def analyze_stock(ticker: str, financial_text: str, persona_id: str) -> str:
    persona = load_persona(persona_id)
    if not persona:
        return f"找不到分析框架: {persona_id}"
    
    framework_steps = "
".join(persona["analysis_framework"])
    metrics = ", ".join(persona["priority_metrics"])
    valuation_methods = ", ".join(persona.get("valuation_methods", []))
    
    system_prompt = f"""你是一位專業股票分析師，使用「{persona["name"]}」框架進行分析。

分析框架（依序執行）：
{framework_steps}

重點追蹤指標：
{metrics}

適用估值方法：
{valuation_methods}

要求：
- 嚴格按照上述框架逐步分析，每個步驟都要有具體數據支撐
- 直接給出分析結論，不需要角色扮演或特定語氣
- 每個關鍵判斷都要引用具體數字
- 最後給出明確的估值區間和投資判斷"""

    user_prompt = f"""請用「{persona["name"]}」框架，分析以下  的資料：

{financial_text}

請依照框架步驟逐一分析，最後輸出：
1. 各步驟核心發現（條列）
2. 主要風險因子（前三項）
3. 估值區間（悲觀 / 基準 / 樂觀）
4. 投資判斷：買進 / 觀望 / 迴避，並說明觸發條件"""

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2500,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}]
    )
    
    return message.content[0].text

def run_analysis(ticker: str, financial_text: str, personas: list = None) -> dict:
    if personas is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(base_dir, "..", "personas", "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        personas = [a["id"] for a in config["analysts"]]
    
    results = {}
    for persona_id in personas:
        print(f"執行分析框架: {persona_id}...")
        results[persona_id] = analyze_stock(ticker, financial_text, persona_id)
    
    return results

if __name__ == "__main__":
    sample = "請替換成財報內容"
    result = analyze_stock("SNDK", sample, "financial_structure")
    print(result)
