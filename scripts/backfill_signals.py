#!/usr/bin/env python3
"""
StockIQ Accumulation Signal Backfill
Reconstructs historical signals for the past N days (default 180)
and stores them in Supabase accumulation_signals table.

Usage:
  python3 scripts/backfill_signals.py          # 180 days
  python3 scripts/backfill_signals.py --days 90
  python3 scripts/backfill_signals.py --dry-run  # preview without saving
"""
import urllib.request, json, time, sys, argparse
from datetime import datetime, timezone, timedelta, date as date_cls

SUPABASE_URL = "https://kggwnlevbxghmqpieoet.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
SB_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates,return=minimal",
}

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
YF_HEADERS = {"User-Agent": UA, "Accept": "*/*", "Referer": "https://finance.yahoo.com/"}

SCAN_TICKERS = [
    # S&P 500 Top 50 (by market cap)
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AVGO","JPM","LLY",
    "V","XOM","UNH","MA","JNJ","PG","HD","ABBV","WMT","BAC",
    "NFLX","CRM","CVX","ORCL","KO","PEP","ACN","MCD","COST","ADBE",
    "TMO","CSCO","ABT","LIN","NKE","DHR","AMGN","TXN","NEE","PM",
    "BMY","RTX","UNP","HON","COP","QCOM","INTU","MS","GS","PLTR",
    # Nasdaq 100 additions
    "AMD","LRCX","KLAC","MRVL","CDNS","SNPS","FTNT","PANW","CRWD","DDOG",
    "ZS","OKTA","NET","SNOW","MDB","MNST","PCAR","PAYX","FAST","ODFL",
    "CSGP","VRSK","IDXX","WDAY","PYPL","EBAY","TEAM","TTD","DOCU","ZM",
    "ABNB","DASH","RIVN","LCID","HOOD","MSTR","COIN","INTC","AMAT","MU",
    # Semis
    "ON","WOLF","SWKS","MCHP","STM","ASML","TER","ARM","SMCI","BTDR",
    # Space/Defense
    "RDW","RKLB","ASTS","SATL","LUNR","ACHR","JOBY","LMT","NOC","GD","BA",
    # Quantum
    "IONQ","RGTI","QUBT","QBTS","ARQQ",
    # Crypto/Web3
    "MARA","RIOT","CLSK","SQ","CIFR","BTBT","SOUN","BBAI",
    # Biotech
    "RXRX","HIMS","CRSP","BEAM","EDIT","PACB","MRNA","BNTX","NVAX","BFLY",
    # EV/Energy
    "NIO","FSLR","ENPH","PLUG","BLNK","CHPT","SEDG","CRNC",
    # Cybersecurity
    "S","TENB","QLYS","CYBR",
    # Social/SaaS
    "RBLX","LYFT","PINS","SNAP","U",
    # ETFs
    "SOXX","ARKK","WCLD","BOTZ","UFO","ICLN","XLK","XLF","XLE",
]


def fetch_1y_data(ticker):
    """Fetch 1 year of daily OHLCV data for a ticker."""
    for base in ["query1", "query2"]:
        try:
            url = f"https://{base}.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1y"
            r = urllib.request.urlopen(urllib.request.Request(url, headers=YF_HEADERS), timeout=12)
            result = json.loads(r.read()).get("chart", {}).get("result", [None])[0]
            if not result:
                continue
            timestamps = result.get("timestamp", [])
            quote = result.get("indicators", {}).get("quote", [{}])[0]
            closes = quote.get("close", [])
            volumes = quote.get("volume", [])
            opens = quote.get("open", [])
            # Build aligned list of (date, close, volume, open)
            rows = []
            for ts, c, v, o in zip(timestamps, closes, volumes, opens):
                if c and v:
                    d = datetime.fromtimestamp(ts, tz=timezone.utc).date()
                    rows.append((d, float(c), int(v), float(o) if o else float(c)))
            if rows:
                return rows
        except Exception as e:
            pass
        time.sleep(0.5)
    return []


def compute_signal_for_window(data_slice, direction="bullish"):
    """v4: phases, sector resonance (without API call), distribution gate."""
    if len(data_slice) < 60:
        return None

    closes = [r[1] for r in data_slice]
    volumes = [r[2] for r in data_slice]
    opens = [r[3] for r in data_slice]
    n = len(closes)
    current = closes[-1]
    current_date = data_slice[-1][0]

    # ADV filter
    avg_dollar_vol = sum(v * c for v, c in zip(volumes[-20:], closes[-20:])) / 20
    if avg_dollar_vol < 5_000_000:
        return None

    # Volume ratio: 20d vs prior 40d
    vol_recent_20 = sum(volumes[-20:]) / 20
    vol_prior_40 = sum(volumes[-60:-20]) / 40 if n >= 60 else sum(volumes[:n-20]) / max(1, n-20)
    vol_ratio = vol_recent_20 / vol_prior_40 if vol_prior_40 > 0 else 1.0
    vol_score = 3 if vol_ratio > 1.8 else 2 if vol_ratio > 1.4 else 1 if vol_ratio > 1.1 else 0

    price_min = min(closes)
    price_max = max(closes)
    price_range_pct = (price_max - price_min) / price_min * 100 if price_min > 0 else 100
    range_pos = (current - price_min) / (price_max - price_min) * 100 if price_max > price_min else 50

    change_3m = (closes[-1] - closes[-65]) / closes[-65] * 100 if n >= 65 else 0
    change_1d = (closes[-1] - closes[-2]) / closes[-2] * 100 if n >= 2 else 0
    change_1m = (closes[-1] - closes[-22]) / closes[-22] * 100 if n >= 22 else 0
    change_2w = (closes[-1] - closes[-10]) / closes[-10] * 100 if n >= 10 else 0

    # OBV
    obv_series = [0]
    for i in range(1, n):
        delta = volumes[i] if closes[i] > closes[i-1] else -volumes[i] if closes[i] < closes[i-1] else 0
        obv_series.append(obv_series[-1] + delta)
    obv_20d = obv_series[-1] - obv_series[-20] if len(obv_series) >= 20 else 0
    price_20d = (closes[-1] - closes[-20]) / closes[-20] * 100 if n >= 20 else 0

    down_vol = sum(volumes[i] for i in range(n-10, n) if i > 0 and closes[i] < closes[i-1])
    up_vol = sum(volumes[i] for i in range(n-10, n) if i > 0 and closes[i] >= closes[i-1])
    dist_ratio = down_vol / up_vol if up_vol > 0 else 1.0

    # MAs
    def sma(data, p):
        return sum(data[-p:]) / p if len(data) >= p else None
    ma10, ma20, ma50 = sma(closes, 10), sma(closes, 20), sma(closes, 50)

    ma_conv = 0
    ma_cross_bear = 0
    if ma10 and ma20 and ma50:
        spread = (max(ma10, ma20, ma50) - min(ma10, ma20, ma50)) / current * 100
        ma_conv = 2 if spread < 2 else 1 if spread < 5 else 0
        if ma10 < ma20 < ma50: ma_cross_bear = 2
        elif ma10 < ma50: ma_cross_bear = 1

    # Volume profile
    mid_price = (price_min + price_max) / 2
    bot_vol = sum(v for c, v in zip(closes, volumes) if c < mid_price)
    top_vol = sum(v for c, v in zip(closes, volumes) if c >= mid_price)
    vp_bull = 1 if bot_vol > top_vol * 1.3 else 0
    vp_bear = 1 if top_vol > bot_vol * 1.3 else 0

    # ATR
    atr_bull = atr_bear = 0
    if n >= 15:
        trs = [max(max(closes[i], opens[i]) - min(closes[i], opens[i]),
                    abs(max(closes[i], opens[i]) - closes[i-1]),
                    abs(min(closes[i], opens[i]) - closes[i-1])) for i in range(n-14, n)]
        atr_pct = (sum(trs) / len(trs)) / current * 100
        if atr_pct < 1.5: atr_bull = 1
        if atr_pct > 3 and range_pos > 60: atr_bear = 1

    # RS proxy
    rs_bull = 2 if (change_1m > 2 and change_3m < 0) else 1 if (change_1m > 0 and change_3m < -5) else 0
    rs_bear = 1 if (change_1m < -5 and change_3m > 10) else 0

    if direction == "bullish":
        comp = 2 if price_range_pct < 20 else 1 if price_range_pct < 35 else 0 if price_range_pct < 60 else -1
        pos = 2 if range_pos < 40 else 1 if range_pos < 60 else 0
        trend = -2 if change_3m > 25 else -1 if change_3m > 15 else 1 if -25 <= change_3m <= -5 else 0
        obv = 2 if obv_20d > 0 and price_20d < 5 else 1 if obv_20d > 0 else 0
        mom = 1 if 0 < change_2w < 8 else 0
        raw = vol_score + comp + pos + trend + obv + mom + ma_conv + rs_bull + vp_bull + atr_bull
        score = max(0, min(10, round(raw * 10 / 17)))
        signal = "🔥 強吸籌" if score >= 7 else "📈 吸籌中"

        # Phase detection
        phase = 1
        phase_label = "Phase 1 觀察期"
        if vol_ratio > 1.2 and obv_20d > 0 and price_20d < 5:
            phase = 2; phase_label = "Phase 2 吸籌進行"
        if phase >= 2 and ma_conv >= 1 and change_2w > 0:
            phase = 3; phase_label = "Phase 3 準備突破"
        if current > (ma20 or 0) and vol_ratio > 1.4 and change_2w > 2:
            phase = 3; phase_label = "Phase 3 突破確認"

        consec = 0
        for i in range(n-1, max(n-15, 0), -1):
            if closes[i] >= opens[i] and volumes[i] > vol_recent_20 * 0.9: consec += 1
            else: break
        comp_score, pos_score, obv_score, mom_score = comp, pos, obv, mom

    else:  # bearish
        if not (obv_20d < 0 or dist_ratio > 1.2):
            return None
        pos = 2 if range_pos > 80 else 1 if range_pos > 65 else 0
        trend = 2 if change_3m > 40 else 1 if change_3m > 20 else 0 if change_3m > 5 else -1
        obv = 2 if obv_20d < 0 and price_20d > -3 else 1 if obv_20d < 0 else 0
        dist = 2 if dist_ratio > 1.5 else 1 if dist_ratio > 1.2 else 0
        raw = vol_score + pos + trend + obv + dist + ma_cross_bear + rs_bear + vp_bear + atr_bear
        score = max(0, min(10, round(raw * 10 / 15)))
        signal = "🔻 強出貨" if score >= 7 else "⚠️ 出貨中"
        phase = 0; phase_label = ""
        consec = 0
        comp_score, pos_score, obv_score, mom_score = 0, pos, obv, 0

    if score < 5:
        return None

    return {
        "date": current_date.isoformat(),
        "direction": direction,
        "score": score, "score_max": 10,
        "signal": signal,
        "price": round(current, 2),
        "change_1d": round(change_1d, 2),
        "change_1m": round(change_1m, 1),
        "change_3m": round(change_3m, 1),
        "vol_ratio": round(vol_ratio, 2),
        "price_range_pct": round(price_range_pct, 1),
        "range_position_pct": round(range_pos, 1),
        "consec_days": consec,
        "score_vol": vol_score, "score_comp": comp_score,
        "score_pos": pos_score, "score_obv": obv_score, "score_mom": mom_score,
        "phase": phase, "phase_label": phase_label,
    }


def get_trading_days(start_date, end_date):
    """Return list of weekday dates in range (Mon-Fri)."""
    days = []
    d = start_date
    while d <= end_date:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def supabase_upsert(rows):
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/accumulation_signals?on_conflict=date,symbol,direction",
        data=json.dumps(rows).encode(),
        headers=SB_HEADERS,
        method="POST"
    )
    try:
        urllib.request.urlopen(req, timeout=20)
        return True
    except urllib.error.HTTPError as e:
        print(f"    Supabase error: {e.code} {e.read().decode()[:200]}")
        return False


def run(backfill_days=180, dry_run=False):
    today = datetime.now(timezone.utc).date()
    end_date = today - timedelta(days=1)  # yesterday (today's signal is being collected)
    start_date = today - timedelta(days=backfill_days)

    trading_days = get_trading_days(start_date, end_date)
    print(f"📅 Backfill range: {start_date} → {end_date}")
    print(f"   Trading days: {len(trading_days)}")
    print(f"   Tickers: {len(SCAN_TICKERS)}")
    print(f"   Estimated signals to store: up to {len(trading_days) * len(SCAN_TICKERS):,}")
    print(f"   Dry run: {dry_run}\n")

    total_signals = 0
    total_rows_stored = 0

    for ticker_idx, ticker in enumerate(SCAN_TICKERS):
        print(f"[{ticker_idx+1:3}/{len(SCAN_TICKERS)}] {ticker}...", end=" ", flush=True)
        time.sleep(0.4)  # rate limiting

        # Fetch full 1-year history once
        data = fetch_1y_data(ticker)
        if len(data) < 80:
            print(f"insufficient data ({len(data)} days)")
            continue

        # Sort by date ascending
        data.sort(key=lambda r: r[0])

        # Build date → index map for fast lookup
        date_to_idx = {r[0]: i for i, r in enumerate(data)}

        # For each trading day in backfill range, compute signal
        ticker_signals = []
        for target_date in trading_days:
            # Find data up to this date (simulate "as of target_date")
            if target_date not in date_to_idx:
                # Try nearest previous trading day
                for offset in range(1, 5):
                    alt = target_date - timedelta(days=offset)
                    if alt in date_to_idx:
                        target_date_idx = date_to_idx[alt]
                        break
                else:
                    continue
            else:
                target_date_idx = date_to_idx[target_date]

            # Use 126 trading days (~6 months) of data ending at target_date
            window_start = max(0, target_date_idx - 125)
            window = data[window_start:target_date_idx + 1]

            if len(window) < 60:
                continue

            # Check both bullish and bearish signals
            for direction in ["bullish", "bearish"]:
                sig = compute_signal_for_window(window, direction=direction)
                if sig:
                    sig["symbol"] = ticker
                    sig["date"] = target_date.isoformat()
                    sig["direction"] = direction
                    ticker_signals.append(sig)

        if ticker_signals:
            print(f"{len(ticker_signals)} signals", end="")
            total_signals += len(ticker_signals)

            if not dry_run:
                # Batch upsert in groups of 100
                for i in range(0, len(ticker_signals), 100):
                    batch = ticker_signals[i:i+100]
                    if supabase_upsert(batch):
                        total_rows_stored += len(batch)
            print(" ✅" if not dry_run else " (dry)")
        else:
            print("no signals")

    print(f"\n{'='*50}")
    print(f"✅ Backfill complete!")
    print(f"   Total signals found: {total_signals:,}")
    if not dry_run:
        print(f"   Rows stored in Supabase: {total_rows_stored:,}")
    print(f"   Date range: {start_date} → {end_date}")
    print(f"   Tickers processed: {len(SCAN_TICKERS)}")

    # Quick stats from Supabase
    if not dry_run:
        try:
            req = urllib.request.Request(
                f"{SUPABASE_URL}/rest/v1/accumulation_signals?select=count",
                headers={**SB_HEADERS, "Prefer": "count=exact", "Accept": "application/json"}
            )
            r = urllib.request.urlopen(req, timeout=10)
            count_range = r.headers.get("content-range", "")
            print(f"\n📊 Supabase total rows: {count_range}")
        except:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill accumulation signals into Supabase")
    parser.add_argument("--days", type=int, default=180, help="Days to backfill (default: 180)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without saving to Supabase")
    args = parser.parse_args()

    run(backfill_days=args.days, dry_run=args.dry_run)
