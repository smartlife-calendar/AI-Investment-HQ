"""
Threads Auto-Poster - integrated into Railway API
Posts daily at 01:00 UTC (09:00 Taiwan) to both StockIQ and SmartLife
"""
import os
import time
import requests

THREADS_TOKEN = os.environ.get("THREADS_TOKEN", "THAHZCwqhe0ZAWtBYlkwTHJ6dEhYUXVLYWVWMjVybkFQRGhORl85S3FRaWd2UjgxWHBwY0tELVp4Yk5GaE84QllidjNOLUtTaF9HLTRPVG43VEhOSndYeVdYbmkzTFB2dUI4dHVSaDl1OFhqcHFqUGY3ZAlFESjZAteHVnUHhwNFM2SlVDcW1USl9FZAUhpSmFLaHMZD")
THREADS_USER_ID = "26779577381733831"

def get_prompt(is_stockiq: bool) -> str:
    if is_stockiq:
        return (
            "用繁體中文寫一則自然的 Threads 貼文，80-120字，推廣 StockIQ AI 股票分析工具。"
            "強調：省時間、AI分析、看懂市場趨勢、適合上班族投資人。"
            "結尾附上：stockiq.tw "
            "Hashtag 必須包含：#Stock #美股，再加一個相關的。"
            "只輸出貼文內容，不要加任何說明。"
        )
    else:
        return (
            "用繁體中文寫一則自然的 Threads 貼文，80-120字，推廣 SmartLife Calendar 智慧行事曆 App。"
            "強調：時間管理、生活規劃、不漏掉重要事項。口語輸入行程、AI生成旅遊計畫。"
            "iOS: https://apps.apple.com/tw/app/smartlife-calendar/id6762165674 "
            "Android: https://play.google.com/store/apps/details?id=app.smartlifecalendar "
            "Hashtag 必須包含：#App #好用工具，再加一個相關的。"
            "只輸出貼文內容，不要加任何說明。"
        )

def post_to_threads(text: str) -> dict:
    resp1 = requests.post(
        f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads",
        json={"media_type": "TEXT", "text": text, "access_token": THREADS_TOKEN},
        timeout=15
    )
    if resp1.status_code != 200:
        return {"success": False, "error": resp1.text}
    container_id = resp1.json().get("id")
    time.sleep(5)
    resp2 = requests.post(
        f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish",
        json={"creation_id": container_id, "access_token": THREADS_TOKEN},
        timeout=15
    )
    if resp2.status_code == 200:
        return {"success": True, "thread_id": resp2.json().get("id")}
    return {"success": False, "error": resp2.text}

def generate_and_post(anthropic_client) -> list:
    """Generate and post for both products. Returns list of result strings."""
    results = []
    for is_stockiq in [True, False]:
        try:
            prompt = get_prompt(is_stockiq)
            msg = anthropic_client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}]
            )
            text = msg.content[0].text.strip()
            if is_stockiq and "stockiq.tw" not in text:
                text += "\n\n🔍 https://stockiq.tw"
            result = post_to_threads(text)
            product = "StockIQ" if is_stockiq else "SmartLife"
            status = "✅" if result.get("success") else "❌"
            results.append(f"{product}: {status} {result.get('thread_id', result.get('error', ''))}")
            print(f"[Threads] {product}: {status}")
            time.sleep(10)
        except Exception as e:
            product = "StockIQ" if is_stockiq else "SmartLife"
            results.append(f"{product}: Error {e}")
            print(f"[Threads] {product} error: {e}")
    return results
