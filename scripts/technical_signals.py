#!/usr/bin/env python3
"""
三條件技術面選股模組 (MACD + Bollinger + MA20)
可用於美股和台股的 paper trading 系統。

三個條件同時成立 = 技術面強勢信號：
1. MACD 柱狀體由負轉正（動能確認）
2. 布林通道開口放大（波動放大 + 方向確認）
3. 收盤站上向上的 20 日均線（趨勢確認）

來源：社群策略（15萬→500萬實證），改寫為 Python 版本。
"""

import math


def compute_ema(data, period):
    """Exponential Moving Average."""
    if len(data) < period:
        return [None] * len(data)
    result = [None] * (period - 1)
    # SMA for first value
    sma = sum(data[:period]) / period
    result.append(sma)
    multiplier = 2.0 / (period + 1)
    for i in range(period, len(data)):
        val = (data[i] - result[-1]) * multiplier + result[-1]
        result.append(val)
    return result


def compute_sma(data, period):
    """Simple Moving Average."""
    result = [None] * (period - 1)
    for i in range(period - 1, len(data)):
        result.append(sum(data[i - period + 1:i + 1]) / period)
    return result


def compute_std(data, period):
    """Standard Deviation over rolling window."""
    result = [None] * (period - 1)
    for i in range(period - 1, len(data)):
        window = data[i - period + 1:i + 1]
        mean = sum(window) / period
        variance = sum((x - mean) ** 2 for x in window) / period
        result.append(math.sqrt(variance))
    return result


def compute_macd(closes, fast=12, slow=26, signal=9):
    """
    MACD using weighted close: (H+L+2*C)/4
    Returns: (dif_line, signal_line, histogram)
    """
    ema_fast = compute_ema(closes, fast)
    ema_slow = compute_ema(closes, slow)

    dif = []
    for f, s in zip(ema_fast, ema_slow):
        if f is not None and s is not None:
            dif.append(f - s)
        else:
            dif.append(None)

    # Signal line = EMA of DIF
    dif_values = [d for d in dif if d is not None]
    if len(dif_values) < signal:
        return dif, [None] * len(dif), [None] * len(dif)

    signal_line_raw = compute_ema(dif_values, signal)
    # Pad to match original length
    pad = len(dif) - len(dif_values)
    signal_line = [None] * pad + signal_line_raw

    histogram = []
    for d, s in zip(dif, signal_line):
        if d is not None and s is not None:
            histogram.append(d - s)
        else:
            histogram.append(None)

    return dif, signal_line, histogram


def compute_bollinger(closes, period=20, k=2.0):
    """
    Bollinger Bands.
    Returns: (upper, middle, lower, bandwidth_pct)
    """
    mid = compute_sma(closes, period)
    std = compute_std(closes, period)

    upper = []
    lower = []
    bw = []
    for m, s in zip(mid, std):
        if m is not None and s is not None:
            u = m + k * s
            l = m - k * s
            upper.append(u)
            lower.append(l)
            bw.append((u - l) / m * 100 if m > 0 else 0)
        else:
            upper.append(None)
            lower.append(None)
            bw.append(None)

    return upper, mid, lower, bw


def check_triple_signal(closes, highs=None, lows=None,
                        macd_fast=12, macd_slow=26, macd_signal=9,
                        bb_period=20, bb_k=2.0,
                        ma_period=20, ma_up_bars=1):
    """
    三條件技術面檢查。

    Args:
        closes: list of closing prices (oldest first)
        highs: list of high prices (optional, for weighted close)
        lows: list of low prices (optional, for weighted close)
        macd_fast/slow/signal: MACD parameters
        bb_period/bb_k: Bollinger Band parameters
        ma_period: Moving average period
        ma_up_bars: Number of bars to check MA is rising

    Returns:
        dict with:
            - "triple_signal": bool (all 3 conditions met)
            - "macd_cross": bool (histogram crossed from - to +)
            - "bb_expanding": bool (bandwidth expanding + bands diverging)
            - "above_rising_ma": bool (price above rising MA)
            - "macd_hist": float (current histogram value)
            - "bb_width": float (current bandwidth %)
            - "ma_distance_pct": float (% distance from MA)
            - "score_boost": int (0-3, number of conditions met)
    """
    if len(closes) < max(macd_slow + macd_signal, bb_period, ma_period + ma_up_bars) + 5:
        return {
            "triple_signal": False, "macd_cross": False,
            "bb_expanding": False, "above_rising_ma": False,
            "macd_hist": 0, "bb_width": 0, "ma_distance_pct": 0,
            "score_boost": 0
        }

    # Use weighted close if H/L available: (H+L+2*C)/4
    if highs and lows and len(highs) == len(closes):
        wc = [(h + l + 2 * c) / 4 for h, l, c in zip(highs, lows, closes)]
    else:
        wc = closes

    # 1. MACD
    _, _, hist = compute_macd(wc, macd_fast, macd_slow, macd_signal)
    macd_cross = False
    macd_hist_val = 0
    if len(hist) >= 2 and hist[-1] is not None and hist[-2] is not None:
        macd_hist_val = hist[-1]
        macd_cross = hist[-1] > 0 and hist[-2] <= 0

    # 2. Bollinger Bands
    upper, mid, lower, bw = compute_bollinger(closes, bb_period, bb_k)
    bb_expanding = False
    bb_width_val = 0
    if (len(bw) >= 2 and bw[-1] is not None and bw[-2] is not None
            and upper[-1] is not None and upper[-2] is not None
            and lower[-1] is not None and lower[-2] is not None):
        bb_width_val = bw[-1]
        bb_expanding = (bw[-1] > bw[-2]
                        and upper[-1] > upper[-2]
                        and lower[-1] < lower[-2])

    # 3. Price above rising MA
    ma = compute_sma(closes, ma_period)
    above_rising_ma = False
    ma_dist_pct = 0
    if (len(ma) > ma_up_bars and ma[-1] is not None
            and ma[-1 - ma_up_bars] is not None):
        above_rising_ma = (closes[-1] > ma[-1]
                           and ma[-1] > ma[-1 - ma_up_bars])
        if ma[-1] > 0:
            ma_dist_pct = (closes[-1] / ma[-1] - 1) * 100

    # Combined
    score_boost = sum([macd_cross, bb_expanding, above_rising_ma])
    triple = macd_cross and bb_expanding and above_rising_ma

    return {
        "triple_signal": triple,
        "macd_cross": macd_cross,
        "bb_expanding": bb_expanding,
        "above_rising_ma": above_rising_ma,
        "macd_hist": round(macd_hist_val, 4),
        "bb_width": round(bb_width_val, 2),
        "ma_distance_pct": round(ma_dist_pct, 2),
        "score_boost": score_boost,
    }


def fetch_ohlcv_yahoo(symbol, days=60):
    """
    Fetch OHLCV from Yahoo Finance.
    Returns: (closes, highs, lows, volumes) lists, oldest first.
    """
    import urllib.request
    import json
    from datetime import datetime, timedelta

    end = int(datetime.now().timestamp())
    start = int((datetime.now() - timedelta(days=days)).timestamp())

    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?period1={start}&period2={end}&interval=1d")
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        result = data["chart"]["result"][0]
        quotes = result["indicators"]["quote"][0]

        closes = quotes.get("close", [])
        highs = quotes.get("high", [])
        lows = quotes.get("low", [])
        volumes = quotes.get("volume", [])

        # Filter out None values (keep indices aligned)
        clean_c, clean_h, clean_l, clean_v = [], [], [], []
        for c, h, l, v in zip(closes, highs, lows, volumes):
            if c is not None and h is not None and l is not None:
                clean_c.append(c)
                clean_h.append(h)
                clean_l.append(l)
                clean_v.append(v or 0)

        return clean_c, clean_h, clean_l, clean_v
    except Exception as e:
        return [], [], [], []


def scan_symbols(symbols, min_volume=0):
    """
    Scan a list of symbols for triple signal.
    Returns list of dicts with signal info.
    """
    import time
    results = []
    for sym in symbols:
        closes, highs, lows, volumes = fetch_ohlcv_yahoo(sym, days=60)
        if len(closes) < 35:
            continue

        sig = check_triple_signal(closes, highs, lows)

        # Volume filter
        if min_volume > 0 and volumes and volumes[-1] < min_volume:
            continue

        if sig["score_boost"] > 0:
            results.append({
                "symbol": sym,
                **sig,
                "volume": volumes[-1] if volumes else 0,
                "price": closes[-1] if closes else 0,
            })
        time.sleep(0.3)

    # Sort: triple signals first, then by score_boost
    results.sort(key=lambda x: (x["triple_signal"], x["score_boost"]), reverse=True)
    return results


if __name__ == "__main__":
    # Quick test
    import sys
    symbols = sys.argv[1:] if len(sys.argv) > 1 else ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN"]
    print(f"Scanning {len(symbols)} symbols...")
    results = scan_symbols(symbols)
    for r in results:
        flag = "🔥" if r["triple_signal"] else f"({r['score_boost']}/3)"
        print(f"  {flag} {r['symbol']}: MACD={r['macd_cross']} BB={r['bb_expanding']} MA={r['above_rising_ma']} | hist={r['macd_hist']} bw={r['bb_width']}% dist={r['ma_distance_pct']}%")
