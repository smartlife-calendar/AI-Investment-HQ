#!/bin/bash
# StockIQ Taiwan daily pipeline
# Runs at UTC 07:00 (Taiwan 15:00) — after Taiwan market closes
cd /data/workspace
. ./.env
export GH_TOKEN

ERRORS=""

echo "=== 🇹🇼 Step 1: Taiwan Stock Update ==="
if ! python3 scripts/update_tw_data.py 2>&1; then
    ERRORS="${ERRORS}❌ update_tw_data.py 失敗\n"
fi

echo "=== 🇹🇼 Step 2: Backtest ==="
if ! python3 scripts/backtest_tw.py 2>&1; then
    ERRORS="${ERRORS}⚠️ backtest_tw.py 失敗（不影響主數據）\n"
fi

echo "=== 🇹🇼 Step 3: Fundamentals ==="
python3 scripts/fetch_tw_fundamentals.py || echo "⚠️ fetch_tw_fundamentals.py failed (non-critical)"

echo "=== 🇹🇼 Step 4: Paper Trading ==="
python3 scripts/paper_trading_tw.py || ERRORS="${ERRORS}⚠️ paper_trading_tw.py 失敗\n"

echo "=== 🇹🇼 Step 5: Social Post ==="
python3 scripts/generate_social_post.py || echo "⚠️ generate_social_post.py failed (non-critical)"

# Saturday-only: TW deep stock reports
DOW=$(date -u +%u)  # 1-7 (Monday-Sunday)
if [ "$DOW" = "6" ]; then
    echo "=== 🇹🇼 Step 5: TW Deep Stock Reports (Saturday) ==="
    python3 scripts/generate_tw_stock_report.py || ERRORS="${ERRORS}⚠️ generate_tw_stock_report.py 失敗\n"
fi

# Validate the live JSON after push
echo "=== 🇹🇼 Step 3: Validate live JSON ==="
LIVE_JSON=$(curl -sf "https://stockiq.tw/tw/data/tw_signals.json?t=$(date +%s)" 2>/dev/null)
if [ -z "$LIVE_JSON" ]; then
    ERRORS="${ERRORS}❌ tw_signals.json 無法存取\n"
elif echo "$LIVE_JSON" | grep -q "NaN"; then
    ERRORS="${ERRORS}❌ tw_signals.json 包含 NaN — 瀏覽器會壞\n"
elif ! echo "$LIVE_JSON" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
    ERRORS="${ERRORS}❌ tw_signals.json 不是合法 JSON\n"
else
    echo "✅ Live JSON validated"
fi

# Report errors via Discord DM
if [ -n "$ERRORS" ]; then
    echo "=== ⚠️ Errors detected, notifying ==="
    echo -e "$ERRORS"
    # Write to a file that HEARTBEAT.md can check
    echo -e "$(date -u '+%Y-%m-%d %H:%M UTC')\n${ERRORS}" > /data/workspace/scripts/.tw_cron_errors
else
    echo "=== ✅ All steps completed successfully ==="
    rm -f /data/workspace/scripts/.tw_cron_errors
fi
