#!/usr/bin/env python3
"""
StockIQ Health Monitor
Checks all data files and modules are up to date.
Run: python3 scripts/stockiq_health.py
Returns: 0 = healthy, 1 = issues found
"""
import urllib.request, json, sys, re
from datetime import datetime, timezone, timedelta

import os
GH_TOKEN = os.environ.get("GH_TOKEN", "")
REPO = "smartlife-calendar/AI-Investment-HQ"
RAILWAY_API = "https://ai-investment-hq-production.up.railway.app"
SITE = "https://stockiq.tw"

TW = timezone(timedelta(hours=8))

# ── Checks config ──────────────────────────────────────────────────────────────
# Each entry: (file, label, max_age_hours, check_nan, check_generated_at)
# max_age_hours: how stale is too stale (weekday context aware)
DATA_CHECKS = [
    # Core daily data (updated by update_data.py at ~00:30 UTC)
    ("data/macro.json",           "📊 Macro & Sectors",     4,  False, False),
    ("data/market_movers.json",   "📈 Market Movers",       4,  False, False),
    ("data/indices.json",         "🌐 Indices",             4,  False, False),
    ("data/accumulation.json",    "🔍 Accumulation Scan",   4,  True,  False),
    ("data/daily_flows.json",     "🌊 Sector Flows",        4,  False, False),
    ("data/market_context.json",  "🎯 Market Context",      4,  False, False),
    ("data/news.json",            "📰 News (basic)",        4,  False, True),
    ("data/market_events.json",   "📅 Earnings Calendar",   26, False, False),
    # Full pipeline (updated by Railway run_daily.sh ~01:00–02:00 UTC)
    ("data/news_intel.json",      "🌍 News Intel",          26, False, True),
    ("data/alpha.json",           "⚡ Alpha Signals",       26, True,  False),
    ("data/signals.json",         "📡 Signals",             26, True,  False),
    ("data/sector_flow_history.json","📜 Flow History",     26, False, False),
    ("data/paper_portfolio.json", "💼 Paper Portfolio",     26, False, False),
    ("data/watchlist.json",       "👁️  Watchlist",          26, False, False),
    # Weekly (Saturday)
    ("data/event_calendar.json",  "🗓️  Event Calendar",    200, False, True),
    ("data/weekly_report.json",   "📋 Weekly Report",      200, False, False),
    ("data/predictions.json",     "🔮 Predictions",        200, False, False),
]

# Briefing check — gh-pages daily/ folder
BRIEFING_CHECKS = [
    ("morning", "🌅 早報"),
    ("evening", "🌙 晚報"),
]

# ── Helpers ────────────────────────────────────────────────────────────────────
def gh_api(path):
    url = f"https://api.github.com/repos/{REPO}/{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {GH_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def gh_raw(path, branch="gh-pages"):
    url = f"https://raw.githubusercontent.com/{REPO}/{branch}/{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"token {GH_TOKEN}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()

def last_commit_age(path, branch="gh-pages"):
    """Returns (datetime, age_hours) of last commit to a path."""
    commits = gh_api(f"commits?path={path}&sha={branch}&per_page=1")
    if not commits:
        return None, None
    dt_str = commits[0]["commit"]["committer"]["date"]
    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    return dt, age_h

def is_trading_day():
    """Simple weekday check (Mon–Fri). Doesn't account for holidays."""
    return datetime.now(TW).weekday() < 5

def check_nan(content_bytes):
    """Returns count of bare NaN values in JSON content."""
    return len(re.findall(rb'\bNaN\b', content_bytes))

def check_generated_at(content_bytes, max_age_hours):
    """Returns age in hours of the generated_at field, or None."""
    try:
        d = json.loads(content_bytes)
        ga = d.get("generated_at", "")
        if not ga:
            return None
        dt = datetime.fromisoformat(ga.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except Exception:
        return None

def check_railway():
    """Ping Railway API."""
    try:
        req = urllib.request.Request(f"{RAILWAY_API}/health")
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            d = json.loads(raw)
            version = d.get("version", "?")
            # Accept any 2xx response as up
            return True, version
    except Exception as e:
        return False, str(e)

def check_site():
    """Ping the live site."""
    try:
        req = urllib.request.Request(f"{SITE}/data/indices.json",
                                     headers={"User-Agent": "StockIQ-HealthCheck/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception:
        return False

def get_today_briefing():
    """Check if today's briefing page was committed today via gh-pages commits."""
    tw_today = datetime.now(TW).strftime("%Y-%m-%d")
    path = f"daily/{tw_today}.html"
    try:
        # Check last commit on this file
        dt, age_h = last_commit_age(path)
        if dt is None:
            return tw_today, False, False, 0
        # If committed within last 24h, briefing ran
        has_morning = age_h is not None and age_h < 24
        # Evening runs at ~13:00 UTC → check if commit happened after 13:00 UTC today
        now_utc = datetime.now(timezone.utc)
        evening_cutoff = now_utc.replace(hour=13, minute=0, second=0, microsecond=0)
        has_evening = dt > evening_cutoff if dt else False
        # Also get file size
        try:
            raw = gh_raw(path)
            size = len(raw)
        except Exception:
            size = 0
        return tw_today, has_morning, has_evening, size
    except Exception:
        return tw_today, False, False, 0

# ── Main check ─────────────────────────────────────────────────────────────────
def run():
    now_tw = datetime.now(TW)
    now_utc = datetime.now(timezone.utc)
    hour_utc = now_utc.hour
    trading = is_trading_day()

    issues = []
    warnings = []
    ok_list = []

    print(f"\n{'='*60}")
    print(f"  StockIQ Health Check — {now_tw.strftime('%Y-%m-%d %H:%M')} TW")
    print(f"  Trading day: {'✅ Yes' if trading else '⛔ No (weekend)'}")
    print(f"{'='*60}\n")

    # ── 1. Data files ──
    print("📁 Data Files:")
    for (path, label, max_age_h, do_nan, do_gen_at) in DATA_CHECKS:
        # Relax age check on weekends for daily files (<26h threshold = daily)
        effective_max = max_age_h
        if not trading and max_age_h <= 26:
            effective_max = 72  # weekend: allow up to 3 days old

        try:
            dt, age_h = last_commit_age(path)
            if age_h is None:
                issues.append(f"{label}: no commits found")
                print(f"  ❌ {label}: no commits found")
                continue

            # Age check
            if age_h > effective_max:
                issues.append(f"{label}: stale ({age_h:.1f}h > {effective_max}h)")
                print(f"  ❌ {label}: STALE ({age_h:.1f}h old, max {effective_max}h)")
            else:
                status = "✅"
                age_str = f"{age_h:.1f}h ago"

                # NaN check
                if do_nan:
                    try:
                        raw = gh_raw(path)
                        nan_count = check_nan(raw)
                        if nan_count > 0:
                            issues.append(f"{label}: {nan_count} NaN value(s) in JSON")
                            print(f"  ⚠️  {label}: {nan_count} NaN(s) found! ({age_str})")
                            continue
                    except Exception as e:
                        warnings.append(f"{label}: couldn't fetch for NaN check ({e})")

                # generated_at freshness
                if do_gen_at:
                    try:
                        raw = gh_raw(path) if not do_nan else raw
                        gen_age = check_generated_at(raw, effective_max)
                        if gen_age is not None and gen_age > effective_max:
                            issues.append(f"{label}: generated_at stale ({gen_age:.1f}h)")
                            print(f"  ⚠️  {label}: generated_at old ({gen_age:.1f}h), commit {age_str}")
                            continue
                    except Exception:
                        pass

                print(f"  {status} {label}: {age_str}")
                ok_list.append(label)

        except Exception as e:
            warnings.append(f"{label}: check failed ({e})")
            print(f"  ⚠️  {label}: check failed ({e})")

    # ── 2. Briefing ──
    print("\n📄 Daily Briefing:")
    date_str, has_morning, has_evening, size = get_today_briefing()

    if not has_morning and not has_evening:
        issues.append(f"Briefing {date_str}: page missing entirely")
        print(f"  ❌ {date_str}: page not found")
    else:
        m_icon = "✅" if has_morning else "❌"
        e_icon = "✅" if has_evening else ("⏳" if hour_utc < 13 else "❌")
        print(f"  {m_icon} 早報 (morning)  {e_icon} 晚報 (evening)  [{size//1024}KB]")
        if not has_morning:
            issues.append(f"Briefing {date_str}: 早報 missing")
        if not has_evening and hour_utc >= 14:
            issues.append(f"Briefing {date_str}: 晚報 missing (already past 13:00 UTC)")

    # ── 3. Railway API ──
    print("\n🚂 Railway API:")
    ok, version = check_railway()
    if ok:
        print(f"  ✅ Up — v{version}")
        ok_list.append("Railway API")
    else:
        issues.append(f"Railway API: down or unreachable ({version})")
        print(f"  ❌ Railway API: {version}")

    # ── 4. Live site ──
    print("\n🌐 Live Site (stockiq.tw):")
    site_ok = check_site()
    if site_ok:
        print("  ✅ Reachable")
        ok_list.append("Live site")
    else:
        issues.append("Live site: unreachable or data CDN failing")
        print("  ❌ Unreachable")

    # ── Summary ──
    print(f"\n{'='*60}")
    print(f"  ✅ OK: {len(ok_list)}  ❌ Issues: {len(issues)}  ⚠️  Warnings: {len(warnings)}")
    print(f"{'='*60}")

    if issues:
        print("\n🚨 Issues:")
        for i in issues:
            print(f"   • {i}")
    if warnings:
        print("\n⚠️  Warnings:")
        for w in warnings:
            print(f"   • {w}")

    # Return structured result for heartbeat processing
    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "ok_count": len(ok_list),
        "checked_at": now_tw.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
    }


if __name__ == "__main__":
    result = run()
    sys.exit(0 if result["ok"] else 1)
