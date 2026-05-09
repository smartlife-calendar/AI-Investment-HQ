import requests
import re
from datetime import datetime, timedelta

def search_stock_news(ticker: str, company_name: str = "") -> str:
    """
    用多個來源抓取股票新聞
    全免費，不需要 API Key
    """
    all_news = []
    
    # 來源 1: Yahoo Finance RSS
    try:
        rss_url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(rss_url, headers=headers, timeout=10)
        
        if resp.status_code == 200:
            items = re.findall(r"<item>(.*?)</item>", resp.text, re.DOTALL)
            for item in items[:8]:
                title = re.search(r"<title><![CDATA[(.*?)]]></title>", item)
                pubdate = re.search(r"<pubDate>(.*?)</pubDate>", item)
                desc = re.search(r"<description><![CDATA[(.*?)]]></description>", item)
                
                if title:
                    all_news.append({
                        "source": "Yahoo Finance",
                        "title": title.group(1).strip(),
                        "date": pubdate.group(1).strip() if pubdate else "",
                        "desc": re.sub(r"<[^>]+>", "", desc.group(1)).strip()[:200] if desc else ""
                    })
            print(f"✅ Yahoo RSS: {len(items[:8])} 則新聞")
    except Exception as e:
        print(f"⚠️ Yahoo RSS 失敗: {e}")
    
    # 來源 2: Seeking Alpha RSS（免費）
    try:
        sa_url = f"https://seekingalpha.com/api/sa/combined/{ticker}.xml"
        resp = requests.get(sa_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        
        if resp.status_code == 200:
            items = re.findall(r"<item>(.*?)</item>", resp.text, re.DOTALL)
            for item in items[:5]:
                title = re.search(r"<title>(.*?)</title>", item)
                pubdate = re.search(r"<pubDate>(.*?)</pubDate>", item)
                
                if title:
                    all_news.append({
                        "source": "Seeking Alpha",
                        "title": re.sub(r"<[^>]+>", "", title.group(1)).strip(),
                        "date": pubdate.group(1).strip() if pubdate else "",
                        "desc": ""
                    })
            print(f"✅ Seeking Alpha: {len(items[:5])} 則")
    except Exception as e:
        print(f"⚠️ Seeking Alpha 失敗: {e}")
    
    # 來源 3: MarketWatch RSS
    try:
        mw_url = f"https://feeds.marketwatch.com/marketwatch/bulletins/"
        resp = requests.get(mw_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        
        if resp.status_code == 200:
            items = re.findall(r"<item>(.*?)</item>", resp.text, re.DOTALL)
            ticker_upper = ticker.upper()
            count = 0
            for item in items[:30]:
                title_match = re.search(r"<title>(.*?)</title>", item)
                desc_match = re.search(r"<description>(.*?)</description>", item)
                pubdate_match = re.search(r"<pubDate>(.*?)</pubDate>", item)
                
                if title_match:
                    title_text = re.sub(r"<[^>]+>", "", title_match.group(1)).strip()
                    desc_text = re.sub(r"<[^>]+>", "", desc_match.group(1)).strip() if desc_match else ""
                    
                    # 過濾相關新聞
                    if ticker_upper in title_text.upper() or (company_name and company_name[:6].upper() in title_text.upper()):
                        all_news.append({
                            "source": "MarketWatch",
                            "title": title_text,
                            "date": pubdate_match.group(1).strip() if pubdate_match else "",
                            "desc": desc_text[:200]
                        })
                        count += 1
                        if count >= 5:
                            break
            if count:
                print(f"✅ MarketWatch: {count} 則")
    except Exception as e:
        print(f"⚠️ MarketWatch 失敗: {e}")
    
    # 整理輸出
    if not all_news:
        return f"暫無 {ticker} 相關新聞"
    
    output = f"##  最新市場新聞

"
    for i, news in enumerate(all_news[:15], 1):
        output += f"{i}. [{news['source']}] {news['title']}"
        if news["date"]:
            output += f" ({news['date'][:16]})".replace("  ", " ")
        output += "
"
        if news["desc"]:
            output += f"   摘要: {news['desc']}
"
        output += "
"
    
    return output

def analyze_news_sentiment(news_text: str, ticker: str) -> str:
    """快速情緒判斷（不用 LLM，純關鍵字）"""
    positive_words = ["beat", "surge", "growth", "record", "upgrade", "buy", "bullish", "strong", "exceed"]
    negative_words = ["miss", "decline", "loss", "downgrade", "sell", "bearish", "weak", "cut", "lawsuit", "investigation"]
    
    text_lower = news_text.lower()
    pos_count = sum(1 for w in positive_words if w in text_lower)
    neg_count = sum(1 for w in negative_words if w in text_lower)
    
    if pos_count > neg_count + 2:
        sentiment = "偏多 📈"
    elif neg_count > pos_count + 2:
        sentiment = "偏空 📉"
    else:
        sentiment = "中性 ➡️"
    
    return f"新聞情緒初步判斷: {sentiment} (正面訊號: {pos_count} | 負面訊號: {neg_count})"

if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "SNDK"
    result = search_stock_news(ticker)
    print(result)
    print(analyze_news_sentiment(result, ticker))
