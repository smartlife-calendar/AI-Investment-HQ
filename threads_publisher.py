import os
import requests
import google.generativeai as genai
from datetime import datetime

# 取得環境變數
THREADS_USER_ID = os.getenv("THREADS_USER_ID")
THREADS_ACCESS_TOKEN = os.getenv("THREADS_ACCESS_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

def generate_threads_content():
    """使用 AI 生成 Threads 推廣文案"""
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-pro')
    
    prompt = """
    你現在是一位獨立開發者 (Indie Hacker)，正在 Threads 上分享你的產品。
    請幫我寫一篇短小精悍、帶有幽默感或實用價值的 Threads 貼文。
    
    今天的目標是推廣以下兩個產品的其中一個，或將兩者結合推廣：
    1. SmartLife Calendar (讓日程管理更聰明): https://apps.apple.com/tw/app/smartlife-calendar/id6762165674
    2. StockIQ (AI 多模型股市分析): https://stockiq.tw/
    
    要求：
    - 字數在 150 字以內，符合 Threads 的快節奏閱讀。
    - 語氣輕鬆自然，像是在跟朋友分享開發心得或投資觀察，絕對不要像機器人發的生硬廣告。
    - 適當加上 1-2 個 Emoji 和相關 hashtag (如 #IndieDev #StockIQ #生產力 #台股 #美股)。
    - 確保附上網址連結。
    """
    response = model.generate_content(prompt)
    return response.text.strip()

def post_to_threads(text_content):
    """透過 Threads Graph API 發布貼文"""
    if not THREADS_USER_ID or not THREADS_ACCESS_TOKEN:
        print("❌ 錯誤：找不到 Threads API 憑證 (THREADS_USER_ID 或 THREADS_ACCESS_TOKEN)")
        print("請確保你已設定環境變數。")
        return False

    print("======================================")
    print(f"準備發布的內容：\n{text_content}\n")
    print("======================================")

    # Step 1: 建立媒體容器 (Container)
    # 這是 Threads API 的機制，發文前要先建一個裝載內容的容器
    url_create = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads"
    payload_create = {
        "media_type": "TEXT",
        "text": text_content,
        "access_token": THREADS_ACCESS_TOKEN
    }
    
    print("➡️ 正在建立 Threads 容器...")
    res_create = requests.post(url_create, data=payload_create)
    if res_create.status_code != 200:
        print(f"❌ 建立容器失敗: {res_create.json()}")
        return False
        
    creation_id = res_create.json().get("id")
    print(f"✅ 容器建立成功，ID: {creation_id}")

    # Step 2: 發布容器 (Publish)
    url_publish = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish"
    payload_publish = {
        "creation_id": creation_id,
        "access_token": THREADS_ACCESS_TOKEN
    }
    
    print("➡️ 正在發布貼文...")
    res_publish = requests.post(url_publish, data=payload_publish)
    if res_publish.status_code != 200:
        print(f"❌ 發布失敗: {res_publish.json()}")
        return False
        
    post_id = res_publish.json().get("id")
    print(f"🎉 發布成功！Threads 貼文 ID: {post_id}")
    return True

if __name__ == "__main__":
    print(f"[{datetime.now()}] 啟動 Threads 自動發文機器人...")
    try:
        if not GEMINI_API_KEY:
            print("❌ 錯誤：找不到 GEMINI_API_KEY，無法生成文案。")
        else:
            content = generate_threads_content()
            post_to_threads(content)
    except Exception as e:
        print(f"❌ 執行過程中發生錯誤: {e}")