#!/usr/bin/env python3
"""
collect_sector_flow.py — Sector fund-flow collector (US + TW)

Responsibilities:
  1. BACKFILL  — Download 52-week historical sector ETF data, compute
                 daily dollar-flow proxies, and store them.
  2. COLLECT   — Append today's sector flow snapshot to the history file.
  3. SUMMARISE — Generate acceleration alerts (momentum-of-flow).

Data model  (ASD-STE100 naming):
  sector_flow_history.json = {
      "updated_at": "...",
      "us": { "XLK": [ {"date":"2025-10-14","flow_m":123.4,"close":180.5,"vol":12345678}, ... ] },
      "tw": { "0052.TW": [ ... ] }
  }

Usage:
  python3 collect_sector_flow.py --backfill   # one-time: fill 52 weeks
  python3 collect_sector_flow.py --daily      # cron: append today + push
  python3 collect_sector_flow.py --summary    # print acceleration alerts
"""

import argparse, json, os, sys, math
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────
US_SECTOR_ETFS = {
    "XLK": "科技 Tech",
    "XLV": "醫療 Health",
    "XLE": "能源 Energy",
    "XLF": "金融 Financials",
    "XLY": "非必需消費 Discretionary",
    "XLP": "必需消費 Staples",
    "XLI": "工業 Industrials",
    "XLU": "公用 Utilities",
    "XLB": "原物料 Materials",
    "XLRE": "房地產 Real Estate",
    "XLC": "通訊 Comm Services",
}

TW_SECTOR_ETFS = {
    "0052.TW": "科技電子",
    "0055.TW": "金融",
    "0053.TW": "電子中型",
    "0056.TW": "高股息",
    "0050.TW": "台灣50",
    "00881.TW": "國泰半導體",
    "00891.TW": "中信ESG",
}

HISTORY_FILE = "data/sector_flow_history.json"
TW_TZ = timezone(timedelta(hours=8))

# ── Known stock splits ─────────────────────────────────────────────────
# Format: { "symbol": [{"date": "YYYY-MM-DD", "ratio": float}] }
# ratio = post-split price / pre-split price (e.g. 1:7 split → ratio ≈ 0.1429)
KNOWN_SPLITS = {
    "0052.TW": [{"date": "2025-11-17", "ratio": 1/7}],  # 1:7 split
}


def adjust_splits(rows, symbol):
    """Adjust historical prices for known stock splits."""
    splits = KNOWN_SPLITS.get(symbol, [])
    if not splits:
        return rows
    for split in splits:
        split_date = split["date"]
        ratio = split["ratio"]
        for r in rows:
            if r["date"] < split_date:
                if r.get("close") and r["close"] > 100:  # Only adjust if looks pre-split
                    r["close"] = safe_float(r["close"] * ratio)
                    if r.get("flow_m") is not None:
                        r["flow_m"] = safe_float(r["flow_m"] * ratio)
    return rows


# ── Helpers ────────────────────────────────────────────────────────────
def safe_float(v):
    """Return None if NaN/Inf, else float."""
    if v is None:
        return None
    f = float(v)
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, 2)


def compute_dollar_flow(hist_df):
    """
    Compute daily dollar-flow proxy from OHLCV DataFrame.

    Formula: flow_m = volume × (close − open) / 1e6
      Positive → net buying pressure (close > open)
      Negative → net selling pressure (close < open)

    Also compute: cumulative flow, 5-day and 20-day moving averages.
    """
    rows = []
    for i in range(len(hist_df)):
        row = hist_df.iloc[i]
        date_str = str(hist_df.index[i].date())
        close = float(row["Close"])
        open_ = float(row["Open"])
        volume = int(row["Volume"])

        # Dollar flow proxy (in millions)
        flow_m = safe_float(volume * (close - open_) / 1e6)

        rows.append({
            "date": date_str,
            "flow_m": flow_m,
            "close": safe_float(close),
            "vol": volume,
        })

    return rows


def compute_acceleration(flow_series):
    """
    Detect acceleration/deceleration in fund flows.

    Compare recent 5-day avg flow vs prior 20-day avg flow.
    Returns dict with alerts.
    """
    if len(flow_series) < 25:
        return None

    recent = flow_series[-5:]
    prior = flow_series[-25:-5]

    recent_vals = [r["flow_m"] for r in recent if r["flow_m"] is not None]
    prior_vals = [r["flow_m"] for r in prior if r["flow_m"] is not None]

    if not recent_vals or not prior_vals:
        return None

    avg_recent = sum(recent_vals) / len(recent_vals)
    avg_prior = sum(prior_vals) / len(prior_vals)

    # Cumulative flow over last 5 and 20 days
    cum_5d = sum(recent_vals)
    cum_20d = sum(prior_vals) + cum_5d

    # Acceleration ratio
    if abs(avg_prior) < 0.01:
        accel_ratio = 0
    else:
        accel_ratio = avg_recent / avg_prior

    # Classify
    if avg_recent > 0 and accel_ratio > 2.0:
        status = "🚀 加速流入"
    elif avg_recent > 0 and accel_ratio > 1.3:
        status = "📈 持續流入"
    elif avg_recent > 0:
        status = "🟢 小幅流入"
    elif avg_recent < 0 and accel_ratio > 2.0:
        status = "🔻 加速流出"
    elif avg_recent < 0 and accel_ratio > 1.3:
        status = "📉 持續流出"
    elif avg_recent < 0:
        status = "🔴 小幅流出"
    else:
        status = "➖ 中性"

    return {
        "avg_5d_m": safe_float(avg_recent),
        "avg_20d_m": safe_float(avg_prior),
        "cum_5d_m": safe_float(cum_5d),
        "cum_20d_m": safe_float(cum_20d),
        "accel_ratio": safe_float(accel_ratio),
        "status": status,
    }


# ── Backfill ───────────────────────────────────────────────────────────
def backfill_history():
    """Download 52-week history for all sector ETFs and build history file."""
    import yfinance as yf

    end = datetime.now()
    start = end - timedelta(weeks=53)  # extra week for safety
    start_str = start.strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")

    result = {"updated_at": "", "us": {}, "tw": {}}

    # ── US sectors ──
    print("📊 Backfill US sector ETFs...")
    for etf, name in US_SECTOR_ETFS.items():
        try:
            hist = yf.Ticker(etf).history(start=start_str, end=end_str)
            rows = compute_dollar_flow(hist)
            result["us"][etf] = rows
            print(f"  ✅ {etf} ({name}): {len(rows)} days")
        except Exception as e:
            print(f"  ❌ {etf}: {e}")

    # ── TW sectors ──
    print("\n📊 Backfill TW sector ETFs...")
    for etf, name in TW_SECTOR_ETFS.items():
        try:
            hist = yf.Ticker(etf).history(start=start_str, end=end_str)
            rows = compute_dollar_flow(hist)
            rows = adjust_splits(rows, etf)
            result["tw"][etf] = rows
            print(f"  ✅ {etf} ({name}): {len(rows)} days")
        except Exception as e:
            print(f"  ❌ {etf}: {e}")

    now_tw = datetime.now(TW_TZ)
    result["updated_at"] = now_tw.strftime("%Y-%m-%dT%H:%M:%S+08:00")

    return result


# ── Daily collect ──────────────────────────────────────────────────────
def collect_today(history):
    """Fetch today's data and append to existing history."""
    import yfinance as yf

    today_str = datetime.now().strftime("%Y-%m-%d")
    added = 0

    for market, etfs in [("us", US_SECTOR_ETFS), ("tw", TW_SECTOR_ETFS)]:
        for etf in etfs:
            try:
                hist = yf.Ticker(etf).history(period="5d")
                if hist.empty:
                    continue

                rows = compute_dollar_flow(hist)
                existing_dates = {r["date"] for r in history.get(market, {}).get(etf, [])}

                for row in rows:
                    if row["date"] not in existing_dates:
                        if etf not in history.setdefault(market, {}):
                            history[market][etf] = []
                        history[market][etf].append(row)
                        added += 1

                # Keep only last 260 trading days (~52 weeks)
                if etf in history.get(market, {}):
                    history[market][etf] = sorted(
                        history[market][etf], key=lambda r: r["date"]
                    )[-260:]

            except Exception as e:
                print(f"  ⚠️ {etf}: {e}")

    history["updated_at"] = datetime.now(TW_TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    print(f"  📥 Added {added} new data points")
    return history


# ── Summary / alerts ───────────────────────────────────────────────────
def generate_summary(history):
    """Generate acceleration alerts for all sectors."""
    alerts = {"us": {}, "tw": {}, "generated_at": ""}

    for market, etf_names in [("us", US_SECTOR_ETFS), ("tw", TW_SECTOR_ETFS)]:
        for etf, name in etf_names.items():
            series = history.get(market, {}).get(etf, [])
            accel = compute_acceleration(series)
            if accel:
                accel["name"] = name
                alerts[market][etf] = accel

    # ── Sort by acceleration magnitude ──
    def sort_key(item):
        a = item[1]
        return abs(a.get("avg_5d_m", 0) or 0)

    # ── Build text summary ──
    lines = []

    # US highlights
    us_sorted = sorted(alerts["us"].items(), key=sort_key, reverse=True)
    us_accel_in = [(k, v) for k, v in us_sorted if "加速流入" in v["status"]]
    us_accel_out = [(k, v) for k, v in us_sorted if "加速流出" in v["status"]]

    if us_accel_in:
        lines.append("🇺🇸 **美股加速流入板塊:**")
        for etf, a in us_accel_in:
            lines.append(f"  {a['status']} {a['name']} — 5日均 ${a['avg_5d_m']}M vs 20日均 ${a['avg_20d_m']}M")

    if us_accel_out:
        lines.append("🇺🇸 **美股加速流出板塊:**")
        for etf, a in us_accel_out:
            lines.append(f"  {a['status']} {a['name']} — 5日均 ${a['avg_5d_m']}M vs 20日均 ${a['avg_20d_m']}M")

    # TW highlights
    tw_sorted = sorted(alerts["tw"].items(), key=sort_key, reverse=True)
    tw_accel_in = [(k, v) for k, v in tw_sorted if "加速流入" in v["status"]]
    tw_accel_out = [(k, v) for k, v in tw_sorted if "加速流出" in v["status"]]

    if tw_accel_in:
        lines.append("🇹🇼 **台股加速流入板塊:**")
        for etf, a in tw_accel_in:
            lines.append(f"  {a['status']} {a['name']} — 5日均 ${a['avg_5d_m']}M vs 20日均 ${a['avg_20d_m']}M")

    if tw_accel_out:
        lines.append("🇹🇼 **台股加速流出板塊:**")
        for etf, a in tw_accel_out:
            lines.append(f"  {a['status']} {a['name']} — 5日均 ${a['avg_5d_m']}M vs 20日均 ${a['avg_20d_m']}M")

    if not lines:
        lines.append("📊 目前無顯著板塊資金加速變動")

    alerts["generated_at"] = datetime.now(TW_TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    alerts["summary_text"] = "\n".join(lines)

    return alerts


# ── GitHub push ────────────────────────────────────────────────────────
def push_to_github(data, path, message):
    """Push JSON data to gh-pages branch."""
    import urllib.request, base64

    GH_TOKEN = os.environ.get("GH_TOKEN", "")
    if not GH_TOKEN:
        print("⚠️ No GH_TOKEN, saving locally only")
        return False

    REPO = "smartlife-calendar/AI-Investment-HQ"
    API = f"https://api.github.com/repos/{REPO}"
    H = {
        "Authorization": f"token {GH_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }

    payload = json.dumps(data, ensure_ascii=False, default=lambda x: None)
    content_b64 = base64.b64encode(payload.encode()).decode()

    # Get current SHA (if file exists)
    sha = None
    try:
        url = f"{API}/contents/{path}?ref=gh-pages"
        with urllib.request.urlopen(
            urllib.request.Request(url, headers=H), timeout=10
        ) as r:
            sha = json.loads(r.read())["sha"]
    except Exception:
        pass

    put = {"message": message, "content": content_b64, "branch": "gh-pages"}
    if sha:
        put["sha"] = sha

    req = urllib.request.Request(
        f"{API}/contents/{path}",
        data=json.dumps(put).encode(),
        headers=H,
        method="PUT",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        result = json.loads(r.read())

    print(f"  ✅ Pushed {path} ({len(payload):,} bytes)")
    return True


# ── Update normalized chart data ───────────────────────────────────────
def update_normalized_chart(history):
    """Update the normalized % series in sector_correlation.json for the chart."""
    import urllib.request as ur
    import base64

    GH_TOKEN = os.environ.get("GH_TOKEN", "")
    if not GH_TOKEN:
        return

    REPO = "smartlife-calendar/AI-Investment-HQ"
    API = f"https://api.github.com/repos/{REPO}"
    H = {
        "Authorization": f"token {GH_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }

    # Load existing sector_correlation.json
    try:
        url = f"{API}/contents/data/sector_correlation.json?ref=gh-pages"
        with ur.urlopen(ur.Request(url, headers=H), timeout=15) as r:
            d = json.loads(r.read())
        corr_data = json.loads(base64.b64decode(d["content"]).decode())
        corr_sha = d["sha"]
    except Exception as e:
        print(f"  ⚠️ Cannot load sector_correlation.json: {e}")
        return

    # Rebuild normalized data from history (with split adjustments applied)
    normalized = {"us": {}, "tw": {}}
    for market in ["us", "tw"]:
        for etf, rows in history.get(market, {}).items():
            if not rows:
                continue
            # Apply split adjustments
            adjusted = adjust_splits(list(rows), etf)
            baseline = adjusted[0]["close"]
            if not baseline or baseline <= 0:
                continue
            norm_rows = []
            for r in adjusted:
                close = r.get("close")
                if close is not None and close > 0:
                    val = round((close - baseline) / baseline * 100, 2)
                else:
                    val = None
                norm_rows.append({"date": r["date"], "val": val})
            normalized[market][etf] = norm_rows

    corr_data["normalized"] = normalized

    # Push
    payload = json.dumps(corr_data, ensure_ascii=False, separators=(",", ":"))
    content_b64 = base64.b64encode(payload.encode()).decode()
    put = {
        "message": f"Update normalized chart data {datetime.now(TW_TZ).strftime('%Y/%m/%d')}",
        "content": content_b64,
        "sha": corr_sha,
        "branch": "gh-pages",
    }
    try:
        req = ur.Request(f"{API}/contents/data/sector_correlation.json",
                         data=json.dumps(put).encode(), headers=H, method="PUT")
        ur.urlopen(req, timeout=30)
        print("  ✅ Updated sector_correlation.json normalized data")
    except Exception as e:
        print(f"  ⚠️ Failed to update sector_correlation.json: {e}")


# ── Main ───────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Sector fund-flow collector")
    parser.add_argument("--backfill", action="store_true", help="Backfill 52-week history")
    parser.add_argument("--daily", action="store_true", help="Append today's data")
    parser.add_argument("--summary", action="store_true", help="Print acceleration alerts")
    parser.add_argument("--push", action="store_true", help="Push to GitHub")
    args = parser.parse_args()

    if not any([args.backfill, args.daily, args.summary]):
        parser.print_help()
        return

    # Load existing history
    history = {}
    local_path = os.path.join(os.path.dirname(__file__), "..", HISTORY_FILE)
    if os.path.exists(local_path):
        with open(local_path) as f:
            history = json.load(f)

    if args.backfill:
        print("🔄 Starting 52-week backfill...")
        history = backfill_history()
        # Save locally
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "w") as f:
            json.dump(history, f, ensure_ascii=False)
        print(f"\n💾 Saved to {local_path}")

        if args.push:
            push_to_github(history, HISTORY_FILE, "Backfill 52-week sector flow history")

    if args.daily:
        print("📥 Collecting today's sector flows...")
        # Try loading from GitHub if no local file
        if not history.get("us"):
            try:
                import urllib.request as ur
                url = f"https://stockiq.tw/{HISTORY_FILE}"
                with ur.urlopen(url, timeout=15) as r:
                    history = json.loads(r.read())
                print(f"  📡 Loaded history from stockiq.tw ({len(history.get('us', {}))} US sectors)")
            except Exception:
                print("  ⚠️ No existing history found — run --backfill first")
                return

        history = collect_today(history)

        # Save locally
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "w") as f:
            json.dump(history, f, ensure_ascii=False)

        if args.push:
            push_to_github(history, HISTORY_FILE, f"Daily sector flow update {datetime.now(TW_TZ).strftime('%Y/%m/%d')}")
            # Also update normalized data in sector_correlation.json
            update_normalized_chart(history)

    if args.summary:
        if not history.get("us"):
            try:
                import urllib.request as ur
                url = f"https://stockiq.tw/{HISTORY_FILE}"
                with ur.urlopen(url, timeout=15) as r:
                    history = json.loads(r.read())
            except Exception:
                print("❌ No history data available")
                return

        alerts = generate_summary(history)
        print("\n" + alerts["summary_text"])

        if args.push:
            push_to_github(alerts, "data/sector_flow_alerts.json",
                         f"Sector flow alerts {datetime.now(TW_TZ).strftime('%Y/%m/%d')}")


if __name__ == "__main__":
    main()
