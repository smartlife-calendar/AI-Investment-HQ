import requests
import re
from datetime import datetime


def search_stock_news(ticker: str, company_name: str = "") -> str:
    """Multi-source stock news scraper - no API key required"""
    all_news = []

    headers = {"User-Agent": "Mozilla/5.0"}

    # Source 1: Yahoo Finance RSS
    try:
        rss_url = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=" + ticker + "&region=US&lang=en-US"
        resp = requests.get(rss_url, headers=headers, timeout=10)

        if resp.status_code == 200:
            items = re.findall(r"<item>(.*?)</item>", resp.text, re.DOTALL)
            for item in items[:8]:
                title = re.search(r"<title><!\[CDATA\[(.*?)\]\]></title>", item)
                pubdate = re.search(r"<pubDate>(.*?)</pubDate>", item)
                if title:
                    all_news.append({
                        "source": "Yahoo Finance",
                        "title": title.group(1).strip(),
                        "date": pubdate.group(1).strip()[:16] if pubdate else "",
                    })
            print("Yahoo RSS: " + str(len(all_news)) + " items")
    except Exception as e:
        print("Yahoo RSS failed: " + str(e))

    # Source 2: Seeking Alpha RSS
    try:
        sa_url = "https://seekingalpha.com/api/sa/combined/" + ticker + ".xml"
        resp = requests.get(sa_url, headers=headers, timeout=10)

        if resp.status_code == 200:
            items = re.findall(r"<item>(.*?)</item>", resp.text, re.DOTALL)
            count = 0
            for item in items[:5]:
                title = re.search(r"<title>(.*?)</title>", item)
                pubdate = re.search(r"<pubDate>(.*?)</pubDate>", item)
                if title:
                    all_news.append({
                        "source": "Seeking Alpha",
                        "title": re.sub(r"<[^>]+>", "", title.group(1)).strip(),
                        "date": pubdate.group(1).strip()[:16] if pubdate else "",
                    })
                    count += 1
            print("Seeking Alpha: " + str(count) + " items")
    except Exception as e:
        print("Seeking Alpha failed: " + str(e))

    # Build output
    if not all_news:
        return "## $" + str(ticker or "") + " News\nNo recent news available\n"

    lines = ["## $" + str(ticker or "") + " Latest News\n"]
    for i, news in enumerate(all_news[:15], 1):
        line = str(i) + ". [" + news["source"] + "] " + news["title"]
        if news["date"]:
            line += " (" + news["date"] + ")"
        lines.append(line)

    return "\n".join(lines) + "\n"


def analyze_news_sentiment(news_text: str, ticker: str) -> str:
    """Basic keyword sentiment analysis"""
    positive_words = ["beat", "surge", "growth", "record", "upgrade", "buy", "bullish", "strong", "exceed"]
    negative_words = ["miss", "decline", "loss", "downgrade", "sell", "bearish", "weak", "cut", "lawsuit"]

    text_lower = news_text.lower()
    pos_count = sum(1 for w in positive_words if w in text_lower)
    neg_count = sum(1 for w in negative_words if w in text_lower)

    if pos_count > neg_count + 2:
        sentiment = "Bullish"
    elif neg_count > pos_count + 2:
        sentiment = "Bearish"
    else:
        sentiment = "Neutral"

    return "News Sentiment: " + sentiment + " (positive signals: " + str(pos_count) + " | negative signals: " + str(neg_count) + ")"


if __name__ == "__main__":
    import sys
    t = sys.argv[1] if len(sys.argv) > 1 else "SNDK"
    result = search_stock_news(t)
    print(result)
    print(analyze_news_sentiment(result, t))
