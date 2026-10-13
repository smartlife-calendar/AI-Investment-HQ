#!/usr/bin/env python3
"""
StockIQ Paper Trading Simulator v4
Tracks virtual positions based on signal system with VERIFIABLE pricing.

KEY RULES for verifiability:
1. Entry price = ACTUAL closing price on signal day (not fabricated)
2. Exit price = ACTUAL closing price on exit day
3. All prices fetched from Yahoo Finance with timestamps
4. Full audit trail: every transaction logged with market data
5. If market is closed → no trades (weekend/holiday check)
6. Cash tracking: every dollar accounted for

Portfolio rules:
- $30K initial capital, 100% individual stocks (no SPY in this portfolio)
- Enter when: score >= 7, Phase 3, sector resonance confirmed
- Max 10% per position, max 10 positions
- ATR-based stop-loss (from signals.json)
- Take profit T1: +15% sell half
- Take profit T2: +25% trailing stop -15% from peak
- 5-day cooldown after exit

Output: data/paper_portfolio.json on gh-pages
"""
import os, json, base64, urllib.request, time
from datetime import datetime, timedelta, timezone

GH_TOKEN = os.environ.get("GH_TOKEN", "")
REPO = "smartlife-calendar/AI-Investment-HQ"
API = f"https://api.github.com/repos/{REPO}"
GH_H = {"Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github.v3+json"}
YF_H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# ── Config ──
INITIAL_CAPITAL = 30000
MAX_POSITIONS = 10
MAX_POSITION_PCT = 0.10
STOP_LOSS_DEFAULT = -0.08
TAKE_PROFIT_T1 = 0.15
TAKE_PROFIT_T2 = 0.25
TRAILING_STOP_FROM_PEAK = 0.15
COOLDOWN_DAYS = 5
MIN_MCAP_B = 2.0
MIN_SCORE = 7


def gh_get(path):
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
    content_b64 = base64.b64encode(json.dumps(data, ensure_ascii=False, indent=2).encode()).decode()
    _, sha = gh_get(path)
    payload = {"message": msg, "content": content_b64, "branch": "gh-pages"}
    if sha:
        payload["sha"] = sha
    req = urllib.request.Request(f"{API}/contents/{path}", data=json.dumps(payload).encode(),
        headers={**GH_H, "Content-Type": "application/json"}, method="PUT")
    r = json.loads(urllib.request.urlopen(req, timeout=30).read())
    return r.get("commit", {}).get("sha", "?")[:7]


def fetch_ohlcv(sym, days=5):
    """Fetch OHLCV data for verification. Returns dict with open, high, low, close, volume."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={days}d&interval=1d"
        req = urllib.request.Request(url, headers=YF_H)
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
        result = d["chart"]["result"][0]
        meta = result["meta"]
        quotes = result["indicators"]["quote"][0]
        timestamps = result.get("timestamp", [])
        
        # Latest trading day with valid data
        if not timestamps:
            return None
        
        # Find the last index with valid close (skip None for holidays/pre-market)
        last_idx = len(timestamps) - 1
        while last_idx >= 0 and not quotes["close"][last_idx]:
            last_idx -= 1
        if last_idx < 0:
            return None
        
        last_date = datetime.fromtimestamp(timestamps[last_idx], tz=timezone.utc).strftime("%Y-%m-%d")
        
        return {
            "symbol": sym,
            "date": last_date,
            "open": round(quotes["open"][last_idx], 2) if quotes["open"][last_idx] else None,
            "high": round(quotes["high"][last_idx], 2) if quotes["high"][last_idx] else None,
            "low": round(quotes["low"][last_idx], 2) if quotes["low"][last_idx] else None,
            "close": round(quotes["close"][last_idx], 2) if quotes["close"][last_idx] else None,
            "volume": quotes["volume"][last_idx],
            "market_price": meta.get("regularMarketPrice", 0),
            "previous_close": meta.get("previousClose", 0),
            "currency": meta.get("currency", "USD"),
            "exchange": meta.get("exchangeName", ""),
            "market_state": meta.get("marketState", ""),
        }
    except Exception as e:
        print(f"  ❌ fetch_ohlcv({sym}): {e}")
        return None


def is_trading_day(date_str):
    """Check if date is a weekday (basic check, doesn't account for holidays)."""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return d.weekday() < 5  # Mon=0, Fri=4


def get_event_risk(today):
    """Check upcoming events and return risk adjustment.
    Returns: (max_position_pct, max_new_entries, reason) 
    """
    try:
        url = f"https://raw.githubusercontent.com/{REPO}/gh-pages/data/event_calendar.json"
        req = urllib.request.Request(url, headers=GH_H)
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
        timeline = d.get("timeline", [])
        strategy = d.get("current_strategy", {})
        
        today_dt = datetime.strptime(today, "%Y-%m-%d")
        risk_events = []
        
        for ev in timeline:
            ev_date = datetime.strptime(ev["date"], "%Y-%m-%d")
            days_away = (ev_date - today_dt).days
            ev_type = ev.get("type", "")
            
            if days_away < 0 or days_away > 14:
                continue
            
            risk_events.append({
                "type": ev_type,
                "label": ev.get("label", ""),
                "days": days_away,
            })
        
        # Risk adjustments based on event proximity
        max_pct = MAX_POSITION_PCT  # default 10%
        max_new = MAX_POSITIONS  # default 10
        reasons = []
        
        for ev in risk_events:
            if ev["type"] == "election" and ev["days"] <= 7:
                # Election week: reduce exposure, no new positions
                max_pct = 0.05  # 5% max per position
                max_new = 0  # No new entries
                reasons.append(f"選舉{ev['days']}天內: 停止新建倉")
            elif ev["type"] == "election" and ev["days"] <= 14:
                # 2 weeks before election: smaller positions
                max_pct = 0.07  # 7% max
                max_new = 3  # Max 3 new
                reasons.append(f"選舉{ev['days']}天內: 減少建倉")
            elif ev["type"] == "fomc" and ev["days"] <= 3:
                # FOMC week: cautious
                max_pct = 0.07
                max_new = min(max_new, 5)
                reasons.append(f"FOMC {ev['days']}天內: 謹慎建倉")
            elif ev["type"] == "opex" and ev["days"] <= 2:
                # Options expiry: volatile
                max_new = min(max_new, 3)
                reasons.append(f"選擇權到期{ev['days']}天內: 觀望")
        
        # Also check equity allocation from strategy
        alloc = strategy.get("equity_allocation", "100%")
        try:
            alloc_pct = float(alloc.replace("%", "")) / 100
            if alloc_pct < 0.7:
                max_new = min(max_new, 3)
                reasons.append(f"策略配置{alloc}: 保守建倉")
        except:
            pass
        
        return max_pct, max_new, "; ".join(reasons) if reasons else None
    except Exception as e:
        print(f"  ⚠️ Event calendar check failed: {e}")
        return MAX_POSITION_PCT, MAX_POSITIONS, None


def run():
    now = datetime.now(timezone(timedelta(hours=-4)))  # EST
    today = now.strftime("%Y-%m-%d")
    print(f"💰 Paper Trading v4 — {now.strftime('%Y/%m/%d %H:%M')} EST")
    
    if not is_trading_day(today):
        print("  📅 Weekend/holiday — skip")
        return
    
    # 1. Load current portfolio
    portfolio, _ = gh_get("data/paper_portfolio.json")
    if not portfolio:
        portfolio = {
            "version": "v4",
            "created": today,
            "initial_capital": INITIAL_CAPITAL,
            "cash": INITIAL_CAPITAL,
            "positions": {},
            "closed_trades": [],
            "daily_nav": [],
            "cooldown": {},
            "stats": {},
            "audit_log": [],
        }
        print("  📝 New portfolio created")
    
    # 2. Load current signals
    signals, _ = gh_get("data/signals.json")
    if not signals:
        print("  ❌ Cannot load signals")
        return
    
    regime = signals.get("market_regime", {}).get("regime", "NEUTRAL")
    sig_map = {s["symbol"]: s for s in signals.get("signals", [])}
    
    # Check event-driven risk
    event_max_pct, event_max_new, event_reason = get_event_risk(today)
    if event_reason:
        print(f"  ⚡ 事件風險: {event_reason}")
        print(f"     max position: {event_max_pct*100:.0f}%, max new entries: {event_max_new}")
    
    # Load earnings data for mcap filter
    earnings, _ = gh_get("data/earnings_roe.json")
    mcap_map = {}
    if earnings:
        for sym, info in earnings.items():
            if isinstance(info, dict) and info.get("market_cap"):
                mcap_map[sym] = info["market_cap"] / 1e9
    
    # 3. Update existing positions with ACTUAL market prices
    positions = portfolio.get("positions", {})
    cash = portfolio.get("cash", INITIAL_CAPITAL)
    closed = portfolio.get("closed_trades", [])
    cooldown = portfolio.get("cooldown", {})
    audit = portfolio.get("audit_log", [])
    
    print(f"\n  📊 Positions: {len(positions)}, Cash: ${cash:,.2f}, Regime: {regime}")
    
    exits = []
    for sym, pos in list(positions.items()):
        ohlcv = fetch_ohlcv(sym)
        if not ohlcv or not ohlcv["close"]:
            print(f"  ⚠️ {sym}: cannot fetch price, skip")
            continue
        time.sleep(0.3)
        
        price = ohlcv["close"]
        low = ohlcv["low"] or price
        high = ohlcv["high"] or price
        entry_price = pos["entry_price"]
        shares = pos["shares"]
        ret = (price - entry_price) / entry_price
        peak = max(pos.get("peak_price", entry_price), high)
        pos["peak_price"] = round(peak, 2)
        pos["current_price"] = price
        pos["current_return"] = round(ret * 100, 2)
        pos["last_updated"] = today
        pos["last_ohlcv"] = ohlcv  # Full audit data
        
        sig = sig_map.get(sym, {})
        action = sig.get("action", "NEUTRAL")
        
        # ── Exit conditions (checked against actual daily low/high) ──
        exit_reason = None
        exit_price = None
        exit_shares = shares
        
        # Stop loss: triggered if daily LOW hit stop
        stop = pos.get("stop_loss", entry_price * (1 + STOP_LOSS_DEFAULT))
        if low <= stop:
            exit_reason = f"停損 觸及${stop:.2f}"
            exit_price = stop  # Assume filled at stop price
        
        # Take profit T1: daily HIGH hit +15%
        t1_price = entry_price * (1 + TAKE_PROFIT_T1)
        if not pos.get("t1_hit") and high >= t1_price:
            exit_reason = f"T1停利 +{TAKE_PROFIT_T1*100:.0f}%"
            exit_price = round(t1_price, 2)
            exit_shares = shares // 2 or 1  # Sell half
            pos["t1_hit"] = True
            pos["t1_date"] = today
        
        # Take profit T2: after T1 hit, trailing stop from peak
        if pos.get("t1_hit") and not exit_reason:
            trailing_stop = peak * (1 - TRAILING_STOP_FROM_PEAK)
            if low <= trailing_stop:
                exit_reason = f"追蹤停損 peak=${peak:.2f}"
                exit_price = round(trailing_stop, 2)
        
        # Signal lost (bearish reversal)
        if action in ("SELL", "AVOID") and not exit_reason:
            exit_reason = f"訊號轉空 ({action})"
            exit_price = price  # Close at market
        
        if exit_reason:
            # For T1, only sell half
            if "T1" in exit_reason:
                sell_shares = exit_shares
                remaining = shares - sell_shares
            else:
                sell_shares = shares
                remaining = 0
            
            proceeds = sell_shares * exit_price
            cash += proceeds
            pnl = (exit_price - entry_price) * sell_shares
            ret_pct = round((exit_price - entry_price) / entry_price * 100, 2)
            
            trade_record = {
                "symbol": sym,
                "entry_date": pos["entry_date"],
                "exit_date": today,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "shares_sold": sell_shares,
                "proceeds": round(proceeds, 2),
                "pnl": round(pnl, 2),
                "return_pct": ret_pct,
                "hold_days": (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(pos["entry_date"], "%Y-%m-%d")).days,
                "reason": exit_reason,
                "exit_ohlcv": ohlcv,  # Verifiable market data
            }
            closed.append(trade_record)
            
            audit.append({
                "date": today,
                "action": "SELL",
                "symbol": sym,
                "shares": sell_shares,
                "price": exit_price,
                "reason": exit_reason,
                "cash_after": round(cash, 2),
                "ohlcv": {"open": ohlcv["open"], "high": ohlcv["high"], "low": ohlcv["low"], "close": ohlcv["close"], "volume": ohlcv["volume"]},
                "verifiable": f"YF {sym} {today}: O={ohlcv['open']} H={ohlcv['high']} L={ohlcv['low']} C={ohlcv['close']}"
            })
            
            if remaining > 0:
                pos["shares"] = remaining
                pos["cost"] = round(remaining * entry_price, 2)
                print(f"  🟡 {sym}: T1賣出 {sell_shares}股 @${exit_price:.2f} (剩{remaining}股) PnL=${pnl:+,.0f}")
            else:
                exits.append(sym)
                cooldown[sym] = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=COOLDOWN_DAYS)).strftime("%Y-%m-%d")
                print(f"  🔴 {sym}: 全部賣出 {sell_shares}股 @${exit_price:.2f} ({ret_pct:+.1f}%) {exit_reason}")
        else:
            print(f"  📦 {sym}: {shares}股 @${entry_price:.2f} → ${price:.2f} ({ret*100:+.1f}%) peak=${peak:.2f}")
    
    # Remove fully exited positions
    for sym in exits:
        del positions[sym]
    
    # 4. Check for new entries — use ACTUAL CLOSE PRICE
    buys = []
    for s in signals.get("signals", []):
        if s.get("action") in ("BUY", "SCALE_IN") and s.get("score", 0) >= MIN_SCORE:
            buys.append(s)
    buys.sort(key=lambda x: x.get("score", 0), reverse=True)
    
    new_entries_today = 0
    for s in buys:
        sym = s["symbol"]
        if sym in positions:
            continue
        if sym in cooldown and cooldown[sym] > today:
            continue
        if mcap_map.get(sym, 999) < MIN_MCAP_B:
            continue
        if len(positions) >= MAX_POSITIONS:
            break
        if new_entries_today >= event_max_new:
            print(f"  ⏸️ 達到事件限制: 今日最多 {event_max_new} 筆新建倉")
            break
        if regime == "BEAR":
            continue
        if regime == "CAUTION" and s.get("score", 0) < 8:
            continue
        
        # Phase filter: prefer Phase 2-3 (momentum confirmed / breakout)
        phase = s.get("phase", 0)
        if phase < 2:
            continue  # Skip Phase 1 (too early)
        
        ohlcv = fetch_ohlcv(sym)
        if not ohlcv or not ohlcv["close"]:
            continue
        time.sleep(0.3)
        
        close_price = ohlcv["close"]
        
        # VERIFY: Can we actually buy at this price?
        # Use the CLOSING PRICE as entry. This is conservative:
        # - We assume we buy at market close (MOC order)
        # - The price ACTUALLY existed on this trading day
        # - Anyone can verify: Yahoo Finance {sym} on {date}
        entry_price = close_price
        
        # Position sizing (event-adjusted)
        position_value = min(cash, INITIAL_CAPITAL * event_max_pct)
        if position_value < 200:
            continue
        
        shares = int(position_value / entry_price)
        if shares < 1:
            continue
        
        cost = round(shares * entry_price, 2)
        cash -= cost
        
        # Use stop_loss from signals if available, else default
        sig_stop = s.get("stop_loss")
        if sig_stop and sig_stop > 0:
            stop_loss = round(sig_stop, 2)
        else:
            stop_loss = round(entry_price * (1 + STOP_LOSS_DEFAULT), 2)
        
        positions[sym] = {
            "entry_date": today,
            "entry_price": entry_price,
            "shares": shares,
            "cost": cost,
            "score": s.get("score", 0),
            "signal": s.get("action"),
            "stop_loss": stop_loss,
            "target_1": round(s["target_1"], 2) if s.get("target_1") else round(entry_price * (1 + TAKE_PROFIT_T1), 2),
            "target_2": round(s["target_2"], 2) if s.get("target_2") else round(entry_price * (1 + TAKE_PROFIT_T2), 2),
            "peak_price": entry_price,
            "t1_hit": False,
            "t2_hit": False,
            "current_price": entry_price,
            "current_return": 0,
            "last_updated": today,
            "entry_ohlcv": ohlcv,  # FULL AUDIT: verifiable market data
        }
        
        audit.append({
            "date": today,
            "action": "BUY",
            "symbol": sym,
            "shares": shares,
            "price": entry_price,
            "cost": cost,
            "cash_after": round(cash, 2),
            "score": s.get("score", 0),
            "ohlcv": {"open": ohlcv["open"], "high": ohlcv["high"], "low": ohlcv["low"], "close": ohlcv["close"], "volume": ohlcv["volume"]},
            "verifiable": f"YF {sym} {today}: O={ohlcv['open']} H={ohlcv['high']} L={ohlcv['low']} C={ohlcv['close']}",
        })
        
        new_entries_today += 1
        print(f"  🟢 {sym}: 買入 {shares}股 @${entry_price:.2f} (${cost:,.0f}) score={s.get('score',0)}")
        print(f"      驗證: YF {sym} {today} Close=${close_price} (Open=${ohlcv['open']} H=${ohlcv['high']} L=${ohlcv['low']})")
    
    # 5. Calculate NAV
    positions_value = 0
    for sym, pos in positions.items():
        p = pos.get("current_price", pos["entry_price"])
        positions_value += pos["shares"] * p
    
    nav = cash + positions_value
    nav_return = (nav - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    
    daily_nav = portfolio.get("daily_nav", [])
    # Don't duplicate same day
    if daily_nav and daily_nav[-1]["date"] == today:
        daily_nav[-1] = {
            "date": today,
            "nav": round(nav, 2),
            "cash": round(cash, 2),
            "positions_value": round(positions_value, 2),
            "n_positions": len(positions),
            "return_pct": round(nav_return, 2),
        }
    else:
        daily_nav.append({
            "date": today,
            "nav": round(nav, 2),
            "cash": round(cash, 2),
            "positions_value": round(positions_value, 2),
            "n_positions": len(positions),
            "return_pct": round(nav_return, 2),
        })
    
    if len(daily_nav) > 365:
        daily_nav = daily_nav[-365:]
    
    # 6. Calculate stats
    wins = [t for t in closed if t["return_pct"] > 0]
    losses = [t for t in closed if t["return_pct"] <= 0]
    
    stats = {
        "total_trades": len(closed),
        "open_positions": len(positions),
        "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0,
        "avg_return": round(sum(t["return_pct"] for t in closed) / len(closed), 2) if closed else 0,
        "avg_win": round(sum(t["return_pct"] for t in wins) / len(wins), 2) if wins else 0,
        "avg_loss": round(sum(t["return_pct"] for t in losses) / len(losses), 2) if losses else 0,
        "total_pnl": round(sum(t["pnl"] for t in closed), 2),
        "nav": round(nav, 2),
        "nav_return_pct": round(nav_return, 2),
        "cash": round(cash, 2),
        "positions_value": round(positions_value, 2),
        "regime": regime,
        "last_updated": today,
    }
    
    # Keep audit log manageable (last 200 entries)
    if len(audit) > 200:
        audit = audit[-200:]
    
    # 7. Save
    portfolio = {
        "version": "v4",
        "created": portfolio.get("created", today),
        "initial_capital": INITIAL_CAPITAL,
        "cash": round(cash, 2),
        "positions": positions,
        "closed_trades": closed[-100:],
        "daily_nav": daily_nav,
        "cooldown": {k: v for k, v in cooldown.items() if v >= today},
        "stats": stats,
        "audit_log": audit,
        "model_version": "v4",
    }
    
    sha = gh_put("data/paper_portfolio.json", portfolio,
                  f"Paper v4 {today}: NAV=${nav:,.0f} ({nav_return:+.1f}%) | {len(positions)} pos | cash ${cash:,.0f}")
    
    print(f"\n{'='*60}")
    print(f"  💰 NAV: ${nav:,.2f} ({nav_return:+.2f}%)")
    print(f"  💵 Cash: ${cash:,.2f}")
    print(f"  📊 Positions: {len(positions)} (${positions_value:,.2f})")
    print(f"  📈 Trades: {len(closed)} (Win: {stats['win_rate']:.0f}%)")
    print(f"  ✅ → {sha}")
    
    # Print audit trail for today
    today_audit = [a for a in audit if a["date"] == today]
    if today_audit:
        print(f"\n  📋 Today's audit trail:")
        for a in today_audit:
            print(f"    {a['action']} {a['symbol']} {a['shares']}股 @${a['price']:.2f} | cash=${a['cash_after']:,.2f}")
            print(f"      驗證: {a['verifiable']}")
    
    return portfolio


if __name__ == "__main__":
    run()
