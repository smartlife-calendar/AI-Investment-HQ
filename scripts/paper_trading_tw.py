#!/usr/bin/env python3
"""
StockIQ 台股模擬操作 v1
追蹤基於訊號系統的虛擬投資組合，所有交易可驗證。

驗證規則：
1. 進場價 = 訊號當日收盤價（Yahoo Finance 可查）
2. 出場價 = 出場日收盤價
3. 完整審計軌跡：每筆交易記錄完整市場數據
4. 台股交易時間：09:00-13:30 (UTC+8)

投資組合規則：
- 初始資金 NT$1,000,000
- 最多 10 檔持股
- 單檔最多 10% 資金
- 進場條件：score >= 7, 外資/投信連買 >= 2 日
- 停損：-8%
- 停利 T1：+15% 賣一半
- 停利 T2：+25% 追蹤停損 -15% from peak
- 冷卻期：5 個交易日

輸出：tw/data/paper_portfolio.json on gh-pages
"""
import os, json, base64, urllib.request, math, time
from datetime import datetime, timedelta, timezone

GH_TOKEN = os.environ.get("GH_TOKEN", "")
REPO = "smartlife-calendar/AI-Investment-HQ"
API = f"https://api.github.com/repos/{REPO}"
GH_H = {"Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github.v3+json"}
YF_H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
TW_TZ = timezone(timedelta(hours=8))

# ── Config ──
INITIAL_CAPITAL = 1_000_000  # NT$1,000,000
MAX_POSITIONS = 10
MAX_POSITION_PCT = 0.10
STOP_LOSS_PCT = -0.08
TAKE_PROFIT_T1 = 0.15  # +15% sell half
TAKE_PROFIT_T2 = 0.25  # +25% trailing stop
TRAILING_STOP_FROM_PEAK = 0.15
COOLDOWN_DAYS = 5
MIN_SCORE = 7
MIN_VOLUME = 500_000  # 最低成交量 50 萬股
MIN_INST_CONSEC = 2   # 外資或投信連續買超至少 2 日

# Weekday bias (台股: 週三最強 = 美股 Tue lag 1 day)
WEEKDAY_BIAS = {0: 1.00, 1: 1.10, 2: 1.15, 3: 0.90, 4: 0.85}  # Mon-Fri


def gh_get(path):
    """Read file from gh-pages branch."""
    try:
        url = f"{API}/contents/{path}?ref=gh-pages"
        req = urllib.request.Request(url, headers=GH_H)
        resp = urllib.request.urlopen(req, timeout=15)
        d = json.loads(resp.read())
        if d.get("content"):
            return json.loads(base64.b64decode(d["content"]).decode()), d["sha"]
        dl = d.get("download_url")
        if dl:
            req2 = urllib.request.Request(dl, headers=GH_H)
            return json.loads(urllib.request.urlopen(req2, timeout=15).read()), d["sha"]
    except:
        pass
    return None, None


def gh_put(path, data, msg):
    """Push file to gh-pages branch."""
    content_b64 = base64.b64encode(json.dumps(data, ensure_ascii=False, indent=2).encode()).decode()
    _, sha = gh_get(path)
    payload = {"message": msg, "content": content_b64, "branch": "gh-pages"}
    if sha:
        payload["sha"] = sha
    req = urllib.request.Request(
        f"{API}/contents/{path}", data=json.dumps(payload).encode(),
        headers={**GH_H, "Content-Type": "application/json"}, method="PUT"
    )
    r = json.loads(urllib.request.urlopen(req, timeout=30).read())
    return r.get("commit", {}).get("sha", "?")[:7]


def fetch_ohlcv(symbol, days=5):
    """Fetch OHLCV from Yahoo Finance for verification. TW stocks use .TW suffix."""
    yf_sym = symbol if symbol.endswith(".TW") or symbol.endswith(".TWO") else f"{symbol}.TW"
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_sym}?range={days}d&interval=1d"
        req = urllib.request.Request(url, headers=YF_H)
        r = json.loads(urllib.request.urlopen(req, timeout=10).read())
        result = r.get("chart", {}).get("result", [{}])[0]
        ts = result.get("timestamp", [])
        quotes = result.get("indicators", {}).get("quote", [{}])[0]
        
        if not ts:
            # Try .TWO for OTC stocks
            if not symbol.endswith(".TWO"):
                yf_sym2 = f"{symbol}.TWO"
                url2 = f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_sym2}?range={days}d&interval=1d"
                req2 = urllib.request.Request(url2, headers=YF_H)
                r2 = json.loads(urllib.request.urlopen(req2, timeout=10).read())
                result = r2.get("chart", {}).get("result", [{}])[0]
                ts = result.get("timestamp", [])
                quotes = result.get("indicators", {}).get("quote", [{}])[0]
        
        out = {}
        for i, t in enumerate(ts):
            dt = datetime.fromtimestamp(t, tz=TW_TZ)
            date_str = dt.strftime("%Y-%m-%d")
            o = quotes.get("open", [None])[i]
            h = quotes.get("high", [None])[i]
            l = quotes.get("low", [None])[i]
            c = quotes.get("close", [None])[i]
            v = quotes.get("volume", [None])[i]
            if c is not None:
                out[date_str] = {"open": round(o, 2), "high": round(h, 2), "low": round(l, 2), "close": round(c, 2), "volume": v}
        return out
    except Exception as e:
        print(f"  ⚠️ YF {yf_sym} error: {e}")
        return {}


def is_tw_market_open(dt):
    """Check if Taiwan market is open on this date (Mon-Fri, not holiday)."""
    if dt.weekday() >= 5:
        return False
    # Known TW market holidays 2026
    holidays = {
        "2026-01-01", "2026-01-26", "2026-01-27", "2026-01-28", "2026-01-29", "2026-01-30",
        "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20",
        "2026-04-03", "2026-04-06",
        "2026-05-01", "2026-05-25",
        "2026-06-19",
        "2026-09-27", "2026-09-28", "2026-09-29",
        "2026-10-09", "2026-10-10",
    }
    return dt.strftime("%Y-%m-%d") not in holidays


def get_latest_price(ohlcv_data):
    """Get the most recent closing price from OHLCV data."""
    if not ohlcv_data:
        return None, None
    latest_date = max(ohlcv_data.keys())
    return ohlcv_data[latest_date]["close"], latest_date


def run():
    now = datetime.now(TW_TZ)
    today_str = now.strftime("%Y-%m-%d")
    print(f"📈 台股模擬操作 — {today_str} ({now.strftime('%A')})")

    # Check if market is open today
    if not is_tw_market_open(now):
        print("  ⏸️ 今日休市，跳過")
        return

    # Load existing portfolio
    portfolio, _ = gh_get("tw/data/paper_portfolio.json")
    if not portfolio:
        portfolio = {
            "initial_capital": INITIAL_CAPITAL,
            "cash": INITIAL_CAPITAL,
            "positions": [],
            "closed_trades": [],
            "pending_orders": [],
            "audit_log": [],
            "created_at": now.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        }
        print("  🆕 初始化台股投資組合: NT$1,000,000")

    cash = portfolio.get("cash", INITIAL_CAPITAL)
    positions = portfolio.get("positions", [])
    closed = portfolio.get("closed_trades", [])
    pending = portfolio.get("pending_orders", [])
    audit = portfolio.get("audit_log", [])

    # Load TW signals
    signals_data, _ = gh_get("tw/data/tw_signals.json")
    if not signals_data:
        print("  ❌ 無法讀取 tw_signals.json")
        return

    signals = signals_data.get("signals", [])
    buys = [s for s in signals if s.get("action") == "BUY" and s.get("score", 0) >= MIN_SCORE]
    print(f"  📊 訊號: {len(signals)} 總共, {len(buys)} BUY (score≥{MIN_SCORE})")

    # ── Step 1: Check existing positions ──
    print(f"\n  💼 持倉: {len(positions)} 檔, 現金: NT${cash:,.0f}")
    positions_to_close = []
    positions_updated = []

    for pos in positions:
        code = pos["code"]
        ohlcv = fetch_ohlcv(code)
        time.sleep(0.3)  # Rate limit

        if not ohlcv:
            positions_updated.append(pos)
            continue

        current_price, price_date = get_latest_price(ohlcv)
        if not current_price:
            positions_updated.append(pos)
            continue

        entry_price = pos["entry_price"]
        shares = pos["shares"]
        pnl_pct = (current_price - entry_price) / entry_price
        pos["current_price"] = current_price
        pos["pnl_pct"] = round(pnl_pct * 100, 2)
        pos["market_value"] = round(current_price * shares, 0)

        # Track peak for trailing stop
        if current_price > pos.get("peak_price", entry_price):
            pos["peak_price"] = current_price

        peak = pos.get("peak_price", entry_price)
        drawdown_from_peak = (current_price - peak) / peak if peak > 0 else 0

        # Verification data
        latest_date = max(ohlcv.keys())
        verify = ohlcv.get(latest_date, {})
        verify_str = f"YF {code} {latest_date}: O={verify.get('open')} H={verify.get('high')} L={verify.get('low')} C={verify.get('close')}"

        sell_reason = None

        # Stop loss check
        if pnl_pct <= STOP_LOSS_PCT:
            sell_reason = f"停損 ({pnl_pct*100:+.1f}%)"

        # T1: Take profit at +15% — sell half
        elif pnl_pct >= TAKE_PROFIT_T1 and not pos.get("t1_sold"):
            half = shares // 2
            if half > 0:
                sell_shares = half
                proceeds = round(sell_shares * current_price)
                cash += proceeds
                pos["shares"] -= sell_shares
                pos["t1_sold"] = True
                pos["t1_date"] = today_str
                audit.append({
                    "date": today_str, "action": "T1_SELL", "code": code, "name": pos.get("name", ""),
                    "shares": sell_shares, "price": current_price, "proceeds": proceeds,
                    "pnl_pct": round(pnl_pct * 100, 1), "cash_after": cash,
                    "verify": verify_str, "reason": f"T1 停利 ({pnl_pct*100:+.1f}%)"
                })
                print(f"    T1 SELL {code} {pos.get('name','')} {sell_shares}股 @{current_price} | +{pnl_pct*100:.1f}%")
                print(f"      驗證: {verify_str}")
                positions_updated.append(pos)
                continue

        # T2: Trailing stop after +25%
        elif pnl_pct >= TAKE_PROFIT_T2 and drawdown_from_peak <= -TRAILING_STOP_FROM_PEAK:
            sell_reason = f"T2 追蹤停損 (peak={peak:.1f}, drawdown={drawdown_from_peak*100:.1f}%)"

        if sell_reason:
            proceeds = round(shares * current_price)
            cash += proceeds
            pnl_amount = round(proceeds - shares * entry_price)
            closed.append({
                "code": code, "name": pos.get("name", ""),
                "entry_date": pos["entry_date"], "entry_price": entry_price,
                "exit_date": today_str, "exit_price": current_price,
                "shares": shares, "pnl_pct": round(pnl_pct * 100, 2),
                "pnl_amount": pnl_amount, "reason": sell_reason,
                "hold_days": (now - datetime.strptime(pos["entry_date"], "%Y-%m-%d").replace(tzinfo=TW_TZ)).days,
            })
            audit.append({
                "date": today_str, "action": "SELL", "code": code, "name": pos.get("name", ""),
                "shares": shares, "price": current_price, "proceeds": proceeds,
                "pnl_pct": round(pnl_pct * 100, 1), "cash_after": cash,
                "verify": verify_str, "reason": sell_reason
            })
            print(f"    SELL {code} {pos.get('name','')} {shares}股 @{current_price} | {sell_reason}")
            print(f"      驗證: {verify_str}")
        else:
            positions_updated.append(pos)

    positions = positions_updated

    # ── Step 2: Process pending orders ──
    new_pending = []
    for order in pending:
        code = order["code"]
        limit_price = order["limit_price"]
        ohlcv = fetch_ohlcv(code, days=3)
        time.sleep(0.3)

        if not ohlcv:
            if (now - datetime.strptime(order["order_date"], "%Y-%m-%d").replace(tzinfo=TW_TZ)).days < 3:
                new_pending.append(order)
            continue

        # Check if today's low <= limit price (fill condition)
        filled = False
        for date_str, bar in sorted(ohlcv.items()):
            if date_str <= order["order_date"]:
                continue
            if bar["low"] <= limit_price:
                # Filled!
                shares = order["shares"]
                cost = round(shares * limit_price)
                if cost > cash:
                    shares = int(cash // limit_price)
                    cost = round(shares * limit_price)
                if shares <= 0:
                    break

                cash -= cost
                pos_entry = {
                    "code": code, "name": order.get("name", ""),
                    "entry_date": date_str, "entry_price": limit_price,
                    "shares": shares, "current_price": bar["close"],
                    "peak_price": bar["high"],
                    "pnl_pct": round((bar["close"] - limit_price) / limit_price * 100, 2),
                    "market_value": round(bar["close"] * shares),
                    "t1_sold": False,
                }
                positions.append(pos_entry)
                verify_str = f"YF {code} {date_str}: O={bar['open']} H={bar['high']} L={bar['low']} C={bar['close']}"
                audit.append({
                    "date": date_str, "action": "BUY", "code": code, "name": order.get("name", ""),
                    "shares": shares, "price": limit_price, "cost": cost,
                    "cash_after": cash, "verify": verify_str,
                    "weekday": datetime.strptime(date_str, "%Y-%m-%d").weekday(),
                    "weekday_mult": WEEKDAY_BIAS.get(datetime.strptime(date_str, "%Y-%m-%d").weekday(), 1.0),
                    "reason": f"限價單成交 (low={bar['low']} ≤ limit={limit_price})"
                })
                print(f"    BUY {code} {order.get('name','')} {shares}股 @{limit_price} (限價單成交)")
                print(f"      驗證: {verify_str}")
                filled = True
                break

        if not filled:
            # Keep pending if within 3 days
            order_age = (now - datetime.strptime(order["order_date"], "%Y-%m-%d").replace(tzinfo=TW_TZ)).days
            if order_age < 3:
                new_pending.append(order)
            else:
                print(f"    ❌ 掛單過期: {code} {order.get('name','')} @{limit_price}")

    pending = new_pending

    # ── Step 3: New buy signals ──
    # Recently closed codes (cooldown)
    cooldown_codes = set()
    for t in closed:
        exit_dt = datetime.strptime(t["exit_date"], "%Y-%m-%d").replace(tzinfo=TW_TZ)
        if (now - exit_dt).days < COOLDOWN_DAYS:
            cooldown_codes.add(t["code"])

    held_codes = {p["code"] for p in positions}
    pending_codes = {o["code"] for o in pending}

    weekday = now.weekday()
    weekday_mult = WEEKDAY_BIAS.get(weekday, 1.0)

    # Filter and rank buy candidates
    candidates = []
    for s in buys:
        code = s["code"]
        if code in held_codes or code in pending_codes or code in cooldown_codes:
            continue
        
        price = s.get("price")
        volume = s.get("volume", 0)
        if not price or price <= 0:
            continue
        if volume < MIN_VOLUME:
            continue

        # Institutional flow check
        inst = s.get("institutional", {})
        trend = s.get("inst_trend", {})
        consec_buy = trend.get("cb", 0) if trend else 0
        trust_consec_buy = trend.get("tcb", 0) if trend else 0
        
        if consec_buy < MIN_INST_CONSEC and trust_consec_buy < MIN_INST_CONSEC:
            continue

        candidates.append(s)

    # Sort by score descending, then by volume
    candidates.sort(key=lambda x: (-x.get("score", 0), -x.get("volume", 0)))

    # How many slots available?
    slots = MAX_POSITIONS - len(positions) - len(pending)
    if slots <= 0:
        print(f"  📋 持倉已滿 ({len(positions)}/{MAX_POSITIONS})")
    else:
        nav = cash + sum(p.get("market_value", p["entry_price"] * p["shares"]) for p in positions)
        for s in candidates[:slots]:
            code = s["code"]
            price = s["price"]
            
            # Position sizing with weekday bias
            base_size = nav * MAX_POSITION_PCT * weekday_mult
            shares = int(base_size // price)
            
            # TW stocks trade in lots of 1000 for regular market, but can do odd lots
            # Round to nearest 100 for cleaner sizing
            shares = (shares // 100) * 100
            if shares < 100:
                shares = 100
            
            cost = round(shares * price)
            if cost > cash:
                shares = (int(cash // price) // 100) * 100
                cost = round(shares * price)
            if shares < 100 or cost > cash:
                continue

            # Create pending limit order at signal price
            order = {
                "code": code, "name": s.get("name", ""),
                "limit_price": price,
                "shares": shares,
                "score": s.get("score", 0),
                "order_date": today_str,
                "sector": s.get("sector", ""),
                "reasons": s.get("reasons", [])[:3],
                "institutional": s.get("institutional", {}),
                "weekday": weekday,
                "weekday_mult": weekday_mult,
            }
            pending.append(order)
            print(f"    📝 掛單: {code} {s.get('name','')} {shares}股 @{price} (score={s['score']}, {s.get('sector','')})")

    # ── Step 4: Calculate NAV ──
    total_position_value = sum(p.get("market_value", p["entry_price"] * p["shares"]) for p in positions)
    nav = cash + total_position_value
    pnl_pct = (nav - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    # Win/loss stats
    wins = [t for t in closed if t.get("pnl_pct", 0) > 0]
    losses = [t for t in closed if t.get("pnl_pct", 0) <= 0]
    win_rate = len(wins) / len(closed) * 100 if closed else 0

    print(f"\n  💰 NAV: NT${nav:,.0f} ({pnl_pct:+.2f}%)")
    print(f"  💵 Cash: NT${cash:,.0f}")
    print(f"  📊 Positions: {len(positions)} (NT${total_position_value:,.0f})")
    print(f"  📈 Trades: {len(closed)} (Win: {win_rate:.0f}%)")

    # ── Step 5: Build output ──
    portfolio = {
        "initial_capital": INITIAL_CAPITAL,
        "currency": "TWD",
        "cash": round(cash),
        "nav": round(nav),
        "pnl_pct": round(pnl_pct, 2),
        "positions": positions,
        "closed_trades": closed,
        "pending_orders": pending,
        "total_trades": len(closed),
        "win_rate": round(win_rate, 1),
        "wins": len(wins),
        "losses": len(losses),
        "best_trade": max([t.get("pnl_pct", 0) for t in closed], default=0),
        "worst_trade": min([t.get("pnl_pct", 0) for t in closed], default=0),
        "updated_at": now.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "audit_log": audit[-100:],  # Keep last 100 entries
        "methodology": {
            "initial_capital": "NT$1,000,000",
            "max_positions": MAX_POSITIONS,
            "position_size": f"{MAX_POSITION_PCT*100:.0f}%",
            "entry_criteria": f"score≥{MIN_SCORE}, 法人連買≥{MIN_INST_CONSEC}日, 成交量≥{MIN_VOLUME/10000:.0f}萬股",
            "exit_rules": f"停損 {STOP_LOSS_PCT*100:.0f}%, T1 +{TAKE_PROFIT_T1*100:.0f}% 賣半, T2 追蹤停損",
            "cooldown": f"{COOLDOWN_DAYS} 交易日",
            "weekday_bias": "週三 ×1.15, 週二 ×1.10, 週一 ×1.00, 週四 ×0.90, 週五 ×0.85",
            "data_source": "Yahoo Finance (可驗證)",
            "verification": "所有交易價格可至 Yahoo Finance 查證 OHLCV",
        },
    }

    sha = gh_put("tw/data/paper_portfolio.json", portfolio, f"📈 台股模擬操作 {today_str}")
    print(f"  ✅ → {sha}")

    # Print audit trail
    today_audit = [a for a in audit if a.get("date") == today_str]
    if today_audit:
        print(f"\n  📋 Today's audit trail:")
        for a in today_audit:
            action = a["action"]
            code = a["code"]
            name = a.get("name", "")
            shares = a.get("shares", 0)
            price = a.get("price", 0)
            if action == "BUY":
                print(f"    BUY {code} {name} {shares}股 @{price} | cash=NT${a.get('cash_after', 0):,.0f}")
            elif action in ("SELL", "T1_SELL"):
                print(f"    {action} {code} {name} {shares}股 @{price} | {a.get('pnl_pct', 0):+.1f}% | cash=NT${a.get('cash_after', 0):,.0f}")
            print(f"      驗證: {a.get('verify', '')}")


if __name__ == "__main__":
    run()
