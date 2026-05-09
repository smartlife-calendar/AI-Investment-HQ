"""
technical_fetcher.py - Technical Analysis Module
Calculates: RSI, Bollinger Bands, MACD, MA crossovers
Data source: Yahoo Finance Chart v8 (free, no key needed)
"""
import requests
import json
import math
from datetime import datetime


def fetch_price_history(ticker: str, period: str = "6mo") -> list:
    """Fetch daily price history from Yahoo Finance Chart v8."""
    try:
        resp = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
            headers={"User-Agent": "Mozilla/5.0"},
            params={"interval": "1d", "range": period},
            timeout=15
        )
        if resp.status_code == 200:
            data = resp.json().get("chart", {}).get("result", [{}])[0]
            timestamps = data.get("timestamp", [])
            closes = data.get("indicators", {}).get("quote", [{}])[0].get("close", [])
            highs = data.get("indicators", {}).get("quote", [{}])[0].get("high", [])
            lows = data.get("indicators", {}).get("quote", [{}])[0].get("low", [])
            volumes = data.get("indicators", {}).get("quote", [{}])[0].get("volume", [])

            prices = []
            for i in range(len(timestamps)):
                if i < len(closes) and closes[i] is not None:
                    prices.append({
                        "date": datetime.fromtimestamp(timestamps[i]).strftime("%Y-%m-%d"),
                        "close": closes[i],
                        "high": highs[i] if i < len(highs) and highs[i] else closes[i],
                        "low": lows[i] if i < len(lows) and lows[i] else closes[i],
                        "volume": volumes[i] if i < len(volumes) else 0,
                    })
            print(f"Price history: {len(prices)} days for {ticker}")
            return prices
    except Exception as e:
        print(f"Price history failed: {e}")
    return []


def calc_sma(prices: list, period: int) -> float:
    """Simple Moving Average."""
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period


def calc_ema(prices: list, period: int) -> list:
    """Exponential Moving Average - returns full series."""
    if len(prices) < period:
        return []
    k = 2 / (period + 1)
    emas = [sum(prices[:period]) / period]  # seed with SMA
    for p in prices[period:]:
        emas.append(p * k + emas[-1] * (1 - k))
    return emas


def calc_rsi(closes: list, period: int = 14) -> float:
    """Relative Strength Index."""
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [max(d, 0) for d in deltas[-period:]]
    losses = [abs(min(d, 0)) for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def calc_bollinger(closes: list, period: int = 20, std_mult: float = 2.0) -> dict:
    """Bollinger Bands."""
    if len(closes) < period:
        return {}
    window = closes[-period:]
    mid = sum(window) / period
    variance = sum((x - mid) ** 2 for x in window) / period
    std = math.sqrt(variance)
    upper = round(mid + std_mult * std, 2)
    lower = round(mid - std_mult * std, 2)
    mid = round(mid, 2)
    current = closes[-1]
    # %B indicator: position within bands (0=lower, 1=upper, 0.5=middle)
    pct_b = round((current - lower) / (upper - lower), 2) if (upper - lower) > 0 else 0.5
    bandwidth = round((upper - lower) / mid * 100, 1) if mid > 0 else 0
    return {
        "upper": upper,
        "middle": mid,
        "lower": lower,
        "pct_b": pct_b,
        "bandwidth_pct": bandwidth,
        "position": "超買區域" if pct_b > 0.8 else "超賣區域" if pct_b < 0.2 else "中性區間",
    }


def calc_macd(closes: list, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """MACD (Moving Average Convergence/Divergence)."""
    if len(closes) < slow + signal:
        return {}
    ema_fast = calc_ema(closes, fast)
    ema_slow = calc_ema(closes, slow)
    # Align series lengths
    min_len = min(len(ema_fast), len(ema_slow))
    macd_line = [ema_fast[-(min_len - i)] - ema_slow[-(min_len - i)] for i in range(min_len)]
    if len(macd_line) < signal:
        return {}
    signal_line = calc_ema(macd_line, signal)
    if not signal_line:
        return {}
    macd_val = round(macd_line[-1], 4)
    signal_val = round(signal_line[-1], 4)
    histogram = round(macd_val - signal_val, 4)
    # Trend: positive histogram = bullish momentum
    trend = "多頭動能" if histogram > 0 else "空頭動能"
    # Crossover detection
    if len(macd_line) >= 2 and len(signal_line) >= 2:
        prev_hist = macd_line[-2] - signal_line[-2]
        if prev_hist < 0 and histogram > 0:
            trend = "🟢 黃金交叉（買入訊號）"
        elif prev_hist > 0 and histogram < 0:
            trend = "🔴 死亡交叉（賣出訊號）"
    return {
        "macd": macd_val,
        "signal": signal_val,
        "histogram": histogram,
        "trend": trend,
    }


def calc_moving_averages(closes: list) -> dict:
    """MA20, MA50, MA200 with crossover signals."""
    result = {}
    current = closes[-1] if closes else 0
    for period in [20, 50, 200]:
        sma = calc_sma(closes, period)
        if sma:
            result[f"ma{period}"] = round(sma, 2)
            result[f"above_ma{period}"] = current > sma

    # Golden/Death cross: MA50 vs MA200
    if "ma50" in result and "ma200" in result:
        if result["above_ma50"] and result["ma50"] > result["ma200"]:
            result["ma_signal"] = "🟢 黃金排列（多頭）"
        elif not result["above_ma50"] and result["ma50"] < result["ma200"]:
            result["ma_signal"] = "🔴 空頭排列（空頭）"
        else:
            result["ma_signal"] = "中性整理"

    return result


def calc_volume_analysis(prices: list) -> dict:
    """Volume trend analysis."""
    if len(prices) < 20:
        return {}
    volumes = [p["volume"] for p in prices if p.get("volume")]
    if not volumes:
        return {}
    recent_vol = sum(volumes[-5:]) / 5  # 5-day avg
    avg_vol = sum(volumes[-20:]) / 20   # 20-day avg
    vol_ratio = round(recent_vol / avg_vol, 2) if avg_vol > 0 else 1.0
    signal = "成交量放大（動能增強）" if vol_ratio > 1.3 else \
             "成交量萎縮（動能減弱）" if vol_ratio < 0.7 else "成交量正常"
    return {
        "avg_volume_20d": int(avg_vol),
        "recent_volume_5d": int(recent_vol),
        "volume_ratio": vol_ratio,
        "volume_signal": signal,
    }


def analyze_technical(ticker: str) -> str:
    """
    Full technical analysis for a stock.
    Returns formatted summary string.
    """
    prices = fetch_price_history(ticker, "1y")  # 1 year of data
    if not prices:
        return f"## {ticker} 技術分析\n無法取得價格歷史數據\n"

    closes = [p["close"] for p in prices]
    current = closes[-1]
    prev = closes[-2] if len(closes) > 1 else current
    change_pct = round((current - prev) / prev * 100, 2) if prev > 0 else 0

    rsi = calc_rsi(closes)
    bb = calc_bollinger(closes)
    macd = calc_macd(closes)
    mas = calc_moving_averages(closes)
    vol = calc_volume_analysis(prices)

    # RSI interpretation
    if rsi is None:
        rsi_signal = "N/A"
    elif rsi > 70:
        rsi_signal = f"超買 ({rsi}) ⚠️"
    elif rsi < 30:
        rsi_signal = f"超賣 ({rsi}) 💡"
    else:
        rsi_signal = f"中性 ({rsi})"

    # Overall technical signal
    signals = []
    if rsi and rsi < 35:
        signals.append("RSI超賣")
    if rsi and rsi > 70:
        signals.append("RSI超買")
    if bb.get("pct_b", 0.5) < 0.15:
        signals.append("布林下軌")
    if bb.get("pct_b", 0.5) > 0.85:
        signals.append("布林上軌")
    if "黃金交叉" in macd.get("trend", ""):
        signals.append("MACD黃金交叉")
    if "死亡交叉" in macd.get("trend", ""):
        signals.append("MACD死亡交叉")
    if mas.get("above_ma200") is False and mas.get("above_ma50") is False:
        signals.append("跌破均線")

    if signals:
        overall = "📊 關鍵訊號: " + " | ".join(signals)
    else:
        overall = "📊 無明顯技術訊號，趨勢中性"

    lines = [
        f"## {ticker} 技術分析",
        f"分析日期: {prices[-1]['date']} | 日期區間: {len(prices)} 交易日",
        "",
        "### 即時狀態",
        f"- 當前價格: ${current} ({'+' if change_pct >= 0 else ''}{change_pct}%)",
        f"- 整體訊號: {overall}",
        "",
        "### RSI 相對強弱",
        f"- RSI(14): {rsi_signal}",
        f"- 解讀: {'建議等待，動能過熱' if rsi and rsi > 70 else '可能存在逢低機會' if rsi and rsi < 30 else '動能正常，無超買超賣'}",
        "",
        "### 布林通道 (20日)",
        f"- 上軌: ${bb.get('upper', 'N/A')}",
        f"- 中軌: ${bb.get('middle', 'N/A')}",
        f"- 下軌: ${bb.get('lower', 'N/A')}",
        f"- 位置 %B: {bb.get('pct_b', 'N/A')} → {bb.get('position', 'N/A')}",
        f"- 帶寬: {bb.get('bandwidth_pct', 'N/A')}%（{'波動收斂' if bb.get('bandwidth_pct', 10) < 5 else '波動正常' if bb.get('bandwidth_pct', 10) < 15 else '波動擴大'}）",
        "",
        "### MACD (12/26/9)",
        f"- MACD線: {macd.get('macd', 'N/A')}",
        f"- 訊號線: {macd.get('signal', 'N/A')}",
        f"- 柱狀圖: {macd.get('histogram', 'N/A')}",
        f"- 趨勢: {macd.get('trend', 'N/A')}",
        "",
        "### 均線系統",
        f"- MA20: ${mas.get('ma20', 'N/A')} ({'上方✅' if mas.get('above_ma20') else '下方❌'})",
        f"- MA50: ${mas.get('ma50', 'N/A')} ({'上方✅' if mas.get('above_ma50') else '下方❌'})",
        f"- MA200: ${mas.get('ma200', 'N/A')} ({'上方✅' if mas.get('above_ma200') else '下方❌'})",
        f"- 均線訊號: {mas.get('ma_signal', 'N/A')}",
        "",
        "### 成交量",
        f"- 5日均量: {vol.get('recent_volume_5d', 'N/A'):,}",
        f"- 20日均量: {vol.get('avg_volume_20d', 'N/A'):,}",
        f"- 量比: {vol.get('volume_ratio', 'N/A')}x → {vol.get('volume_signal', 'N/A')}",
    ]

    return "\n".join(str(l) for l in lines)


if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(analyze_technical(ticker))
