#!/bin/bash
# StockIQ US daily pipeline: data → briefing → smartdata → signal map → signals → weekly (Sat)
# Each step runs independently; failures don't block subsequent steps
cd /data/workspace
. ./.env
export GH_TOKEN SUPABASE_SERVICE_KEY RESEND_API_KEY CLAUDE_API_KEY

ERRORS=""

echo "=== Step 1/5: update_data.py ==="
python3 scripts/update_data.py || ERRORS="${ERRORS}❌ update_data.py 失敗\n"

echo "=== Step 2/5: update_briefing.py ==="
python3 scripts/update_briefing.py || ERRORS="${ERRORS}⚠️ update_briefing.py 失敗\n"

echo "=== Step 3/5: update_smartdata.py ==="
python3 scripts/update_smartdata.py || ERRORS="${ERRORS}⚠️ update_smartdata.py 失敗\n"

echo "=== Step 4/6: signal_map.py ==="
python3 scripts/generate_signal_map.py || ERRORS="${ERRORS}⚠️ generate_signal_map.py 失敗\n"

echo "=== Step 5/7: generate_signals.py ==="
python3 scripts/generate_signals.py || ERRORS="${ERRORS}❌ generate_signals.py 失敗\n"

echo "=== Step 5b: collect_stock_news.py ==="
python3 scripts/collect_stock_news.py || ERRORS="${ERRORS}⚠️ collect_stock_news.py 失敗\n"

echo "=== Step 5c: update_backtest.py ==="
python3 scripts/update_backtest.py || echo "update_backtest.py failed (non-critical)"

echo "=== Step 5c2: collect_sector_flow.py ==="
python3 scripts/collect_sector_flow.py --daily --summary --push || echo "collect_sector_flow.py failed (non-critical)"

echo "=== Step 5d: record_signals.py ==="
python3 scripts/record_signals.py || echo "record_signals.py failed (non-critical)"

echo "=== Step 5e: breakout_watchlist.py ==="
python3 scripts/breakout_watchlist.py || echo "breakout_watchlist.py failed (non-critical)"

echo "=== Step 5f: paper_trading.py ==="
python3 scripts/paper_trading.py || echo "paper_trading.py failed (non-critical)"

echo "=== Step 5g: market_monitor.py ==="
python3 scripts/market_monitor.py || echo "market_monitor.py failed (non-critical)"

echo "=== Step 6/7: generate_social_post.py ==="
python3 scripts/generate_social_post.py || ERRORS="${ERRORS}⚠️ generate_social_post.py 失敗\n"

# Step 7: Weekly tasks on Saturdays
DAY_OF_WEEK=$(date -u +%u)
if [ "$DAY_OF_WEEK" = "6" ]; then
    echo "=== Step 7a: weekly_report.py (Saturday) ==="
    python3 scripts/weekly_report.py || ERRORS="${ERRORS}⚠️ weekly_report.py 失敗\n"

    echo "=== Step 7b: earnings reports (Saturday) ==="
    python3 scripts/update_earnings.py || ERRORS="${ERRORS}⚠️ update_earnings.py 失敗\n"

    echo "=== Step 7c: investment research loop (Saturday) ==="
    python3 scripts/investment_loop.py || ERRORS="${ERRORS}⚠️ investment_loop.py 失敗\n"

    echo "=== Step 7d: AI stock analyst (Saturday) ==="
    python3 scripts/ai_stock_analyst.py || ERRORS="${ERRORS}⚠️ ai_stock_analyst.py 失敗\n"

    echo "=== Step 7e: Event calendar (Saturday) ==="
    python3 scripts/event_calendar.py || ERRORS="${ERRORS}⚠️ event_calendar.py 失敗\n"

    echo "=== Step 7f: Deep stock reports (Saturday) ==="
    python3 scripts/generate_stock_report.py || ERRORS="${ERRORS}⚠️ generate_stock_report.py 失敗\n"

    echo "=== Step 7g: TW deep stock reports (Saturday) ==="
    python3 scripts/generate_tw_stock_report.py || ERRORS="${ERRORS}⚠️ generate_tw_stock_report.py 失敗\n"

    # Seasonality + ATR: recalculate quarterly (Jan/Apr/Jul/Oct first Saturday)
    MONTH=$(date -u +%-m)
    if [ "$MONTH" = "1" ] || [ "$MONTH" = "4" ] || [ "$MONTH" = "7" ] || [ "$MONTH" = "10" ]; then
        DAY=$(date -u +%-d)
        if [ "$DAY" -le 7 ]; then
            echo "=== Step 7c: seasonality recalculation (quarterly) ==="
            python3 scripts/recalc_seasonality.py || ERRORS="${ERRORS}⚠️ recalc_seasonality.py 失敗\n"
        fi
    fi
else
    echo "=== Step 7a: Ticker Discovery ==="
    python3 scripts/discover_tickers.py || echo "discover_tickers.py failed (non-critical)"

    echo "=== Step 7: Skipped (weekly tasks only on Saturday) ==="
fi

# Sync main branch ← gh-pages (prevent Sync script rollback)
echo "=== Sync main←gh-pages (防呆) ==="
python3 -c "
import json, base64, urllib.request, os
GH_TOKEN = os.environ.get('GH_TOKEN', '')
REPO = 'smartlife-calendar/AI-Investment-HQ'
H = {'Authorization': f'token {GH_TOKEN}', 'Accept': 'application/vnd.github.v3+json', 'Content-Type': 'application/json'}
# Read gh-pages index.html
with urllib.request.urlopen(urllib.request.Request(f'https://api.github.com/repos/{REPO}/contents/index.html?ref=gh-pages', headers=H)) as r:
    d = json.loads(r.read()); ghp_sha = d['sha']; content = d['content']
# Update main/index.html and main/frontend/index.html
for path in ['index.html', 'frontend/index.html']:
    try:
        with urllib.request.urlopen(urllib.request.Request(f'https://api.github.com/repos/{REPO}/contents/{path}?ref=main', headers=H)) as r:
            sha = json.loads(r.read())['sha']
    except: sha = None
    payload = {'message': 'Sync main←gh-pages (auto)', 'content': content, 'branch': 'main'}
    if sha: payload['sha'] = sha
    urllib.request.urlopen(urllib.request.Request(f'https://api.github.com/repos/{REPO}/contents/{path}', data=json.dumps(payload).encode(), headers=H, method='PUT'), timeout=30)
print('✅ main synced from gh-pages')
" 2>&1 || echo "⚠️ main sync failed (non-critical)"

# Validate live JSON + auto-fix NaN
echo "=== Validate live data ==="
for f in signals.json alpha.json accumulation.json; do
    LIVE=$(curl -sf "https://stockiq.tw/data/${f}?t=$(date +%s)" 2>/dev/null)
    if [ -n "$LIVE" ] && echo "$LIVE" | grep -q "NaN"; then
        echo "⚠️ ${f} has NaN — auto-fixing..."
        python3 scripts/fix_nan.py "data/${f}" 2>&1 || ERRORS="${ERRORS}❌ data/${f} NaN fix failed\n"
    fi
done

if [ -n "$ERRORS" ]; then
    echo "=== ⚠️ Errors detected ==="
    echo -e "$ERRORS"
    echo -e "$(date -u '+%Y-%m-%d %H:%M UTC')\n${ERRORS}" > /data/workspace/scripts/.us_cron_errors
else
    echo "=== ✅ All steps completed successfully ==="
    rm -f /data/workspace/scripts/.us_cron_errors
fi
