#!/usr/bin/env python3
"""
StockIQ Paper Trading Simulator
Tracks virtual positions based on signal system, calculates real-time P&L.
Runs daily after signals are generated.

Portfolio rules:
- Enter on BUY/SCALE_IN signal (limit buy -2%)
- Exit on SELL/AVOID signal, stop-loss, or take-profit
- Max 10% per position, max 10 positions
- ATR-based stop-loss

Output: data/paper_portfolio.json on gh-pages
"""
import os, json, base64, urllib.request, time
from datetime import datetime, timedelta, timezone
from collections import defaultdict

GH_TOKEN = os.environ.get("GH_TOKEN", "")
REPO = "smartlife-calendar/AI-Investment-HQ"
API = f"https://api.github.com/repos/{REPO}"
GH_H = {"Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github.v3+json"}
YF_H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# ── Config ──
INITIAL_CAPITAL = 30000  # $30K virtual
MAX_POSITIONS = 10
MAX_POSITION_PCT = 0.10   # 10% per stock
STOP_LOSS_DEFAULT = -0.08  # -8%
TAKE_PROFIT_T1 = 0.15     # +15% sell half
TAKE_PROFIT_T2 = 0.25     # +25% trailing stop
TRAILING_STOP = 0.20      # -20% from peak after T2
COOLDOWN_DAYS = 5          # Days after exit before re-entry
MIN_MCAP_B = 2.0           # Skip stocks < $2B


def gh_get(path):
    try:
        url = f"{API}/contents/{path}?ref=gh-pages"
        req = urllib.request.Request(url, headers=GH_H)
        resp = urllib.request.urlopen(req, timeout=15)
        d = json.loads(resp.read())
        if d.get("content"):
            return json.loads(base64.b64decode(d["content"]).decode()), d["sha"]
        # Too large - use download_url
        dl = d.get("download_url")
        if dl:
            req2 = urllib.request.Request(dl, headers=GH_H)
            return json.loads(urllib.request.urlopen(req2, timeout=15).read()), d["sha"]
    except:
        pass
    return None, None


def gh_put(path, data, msg):
    encoded = base64.b64encode(json.dumps(data, ensure_ascii=False, indent=2).encode()).decode()
    _, sha = gh_get(path)
    payload = {"message": msg, "content": encoded, "branch": "gh-pages"}
    if sha: payload["sha"] = sha
    req = urllib.request.Request(f"{API}/contents/{path}", data=json.dumps(payload).encode(),
        headers={**GH_H, "Content-Type": "application/json"}, method="PUT")
    r = json.loads(urllib.request.urlopen(req, timeout=30).read())
    return r.get("commit", {}).get("sha", "?")[:7]


def fetch_price(sym):
    """Get current price."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=5d&interval=1d"
        req = urllib.request.Request(url, headers=YF_H)
        d = json.loads(urllib.request.urlopen(req, timeout=8).read())
        meta = d["chart"]["result"][0]["meta"]
        return meta.get("regularMarketPrice", 0)
    except:
        return 0


def run():
    now = datetime.now(timezone(timedelta(hours=8)))
    today = now.strftime("%Y-%m-%d")
    print(f"💰 Paper Trading — {now.strftime('%Y/%m/%d %H:%M')}")
    
    # 1. Load current portfolio
    portfolio, _ = gh_get("data/paper_portfolio.json")
    if not portfolio:
        portfolio = {
            "created": today,
            "initial_capital": INITIAL_CAPITAL,
            "cash": INITIAL_CAPITAL,
            "positions": {},  # {sym: {entry_date, entry_price, shares, stop_loss, peak_price, t1_hit, ...}}
            "closed_trades": [],  # [{sym, entry_date, exit_date, entry_price, exit_price, return_pct, reason}]
            "daily_nav": [],  # [{date, nav, cash, positions_value}]
            "cooldown": {},  # {sym: re_entry_date}
            "stats": {},
        }
        print("  📝 New portfolio created")
    
    # 2. Load current signals
    signals, _ = gh_get("data/signals.json")
    if not signals:
        print("  ❌ Cannot load signals")
        return
    
    regime = signals.get("market_regime", {}).get("regime", "NEUTRAL")
    sig_map = {s["symbol"]: s for s in signals.get("signals", [])}
    
    # Load earnings data for mcap
    earnings, _ = gh_get("data/earnings_roe.json")
    mcap_map = {}
    if earnings:
        for sym, info in earnings.items():
            if isinstance(info, dict) and info.get("market_cap"):
                mcap_map[sym] = info["market_cap"] / 1e9
    
    # 3. Update existing positions
    positions = portfolio.get("positions", {})
    cash = portfolio.get("cash", INITIAL_CAPITAL)
    closed = portfolio.get("closed_trades", [])
    cooldown = portfolio.get("cooldown", {})
    
    # Fetch current prices for all held positions
    print(f"\n  Positions: {len(positions)}, Cash: ${cash:,.0f}")
    
    exits = []
    for sym, pos in list(positions.items()):
        price = fetch_price(sym)
        if not price:
            continue
        time.sleep(0.3)
        
        entry_price = pos["entry_price"]
        shares = pos["shares"]
        ret = (price - entry_price) / entry_price
        peak = max(pos.get("peak_price", entry_price), price)
        pos["peak_price"] = peak
        pos["current_price"] = price
        pos["current_return"] = round(ret * 100, 2)
        
        sig = sig_map.get(sym, {})
        action = sig.get("action", "NEUTRAL")
        
        exit_reason = None
        exit_shares = shares
        
        # Check exit conditions
        # a. Signal turned SELL/AVOID
        if action in ("SELL", "AVOID"):
            exit_reason = f"訊號轉{action}"
        
        # b. Stop loss
        elif ret <= STOP_LOSS_DEFAULT:
            exit_reason = f"停損 {ret*100:.1f}%"
        
        # c. Take profit T1 (sell half)
        elif ret >= TAKE_PROFIT_T1 and not pos.get("t1_hit"):
            exit_shares = shares // 2
            pos["t1_hit"] = True
            pos["t1_date"] = today
            exit_reason = f"T1停利 +{ret*100:.1f}%（賣半）"
        
        # d. Trailing stop after T2
        elif ret >= TAKE_PROFIT_T2:
            pos["t2_hit"] = True
            drawdown = (price - peak) / peak
            if drawdown <= -TRAILING_STOP:
                exit_reason = f"追蹤停利 (從高點{peak:.2f}回落{drawdown*100:.1f}%)"
        
        # e. Signal turned REDUCE
        elif action == "REDUCE":
            exit_shares = shares // 2
            exit_reason = f"訊號轉REDUCE（減碼半）"
        
        if exit_reason:
            value = exit_shares * price
            cash += value
            pnl = (price - entry_price) * exit_shares
            pnl_pct = (price - entry_price) / entry_price * 100
            
            closed.append({
                "symbol": sym,
                "entry_date": pos["entry_date"],
                "exit_date": today,
                "entry_price": round(entry_price, 2),
                "exit_price": round(price, 2),
                "shares": exit_shares,
                "return_pct": round(pnl_pct, 2),
                "pnl": round(pnl, 2),
                "reason": exit_reason,
            })
            
            remaining = shares - exit_shares
            if remaining > 0:
                pos["shares"] = remaining
                print(f"  📉 {sym}: 部分出場 {exit_shares}股 @${price:.2f} ({pnl_pct:+.1f}%) — {exit_reason}")
            else:
                del positions[sym]
                cooldown[sym] = (now + timedelta(days=COOLDOWN_DAYS)).strftime("%Y-%m-%d")
                print(f"  🚪 {sym}: 全部出場 @${price:.2f} ({pnl_pct:+.1f}%) — {exit_reason}")
    
    # 4. Check for new entries
    buys = [s for s in signals.get("signals", []) if s.get("action") in ("BUY", "SCALE_IN")]
    
    # Filter: not already held, not in cooldown, mcap >= $2B
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
        
        # Check regime allows entry
        if regime in ("BEAR",):
            continue
        if regime == "CAUTION" and s.get("score", 0) < 8:
            continue
        
        price = fetch_price(sym)
        if not price:
            continue
        time.sleep(0.3)
        
        # Calculate position size
        position_value = min(cash, INITIAL_CAPITAL * MAX_POSITION_PCT)
        if position_value < 100:  # Too small
            continue
        
        # Limit buy at -2%
        entry_price = round(price * 0.98, 2)
        shares = int(position_value / entry_price)
        if shares < 1:
            continue
        
        cost = shares * entry_price
        cash -= cost
        
        positions[sym] = {
            "entry_date": today,
            "entry_price": entry_price,
            "shares": shares,
            "cost": round(cost, 2),
            "score": s.get("score", 0),
            "action": s.get("action"),
            "stop_loss": round(entry_price * (1 + STOP_LOSS_DEFAULT), 2),
            "peak_price": entry_price,
            "t1_hit": False,
            "t2_hit": False,
            "current_price": price,
            "current_return": round((price - entry_price) / entry_price * 100, 2),
        }
        
        print(f"  🟢 {sym}: 買入 {shares}股 @${entry_price:.2f} (${cost:,.0f}) score={s.get('score',0)}")
    
    # 5. Calculate NAV
    positions_value = 0
    for sym, pos in positions.items():
        p = pos.get("current_price", pos["entry_price"])
        positions_value += pos["shares"] * p
    
    nav = cash + positions_value
    nav_return = (nav - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    
    daily_nav = portfolio.get("daily_nav", [])
    daily_nav.append({
        "date": today,
        "nav": round(nav, 2),
        "cash": round(cash, 2),
        "positions_value": round(positions_value, 2),
        "n_positions": len(positions),
        "return_pct": round(nav_return, 2),
    })
    # Keep last 180 days
    if len(daily_nav) > 180:
        daily_nav = daily_nav[-180:]
    
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
        "regime": regime,
        "last_updated": today,
    }
    
    # 7. Save
    portfolio = {
        "created": portfolio.get("created", today),
        "initial_capital": INITIAL_CAPITAL,
        "cash": round(cash, 2),
        "positions": positions,
        "closed_trades": closed[-100:],  # Keep last 100
        "daily_nav": daily_nav,
        "cooldown": {k: v for k, v in cooldown.items() if v >= today},
        "stats": stats,
    }
    
    sha = gh_put("data/paper_portfolio.json", portfolio,
                  f"Paper trading {today}: NAV=${nav:,.0f} ({nav_return:+.1f}%) | {len(positions)} pos | {len(closed)} trades")
    
    print(f"\n{'='*60}")
    print(f"  💰 NAV: ${nav:,.2f} ({nav_return:+.2f}%)")
    print(f"  💵 Cash: ${cash:,.2f}")
    print(f"  📊 Positions: {len(positions)}")
    print(f"  📈 Trades: {len(closed)} (Win: {stats['win_rate']:.0f}%)")
    print(f"  ✅ → {sha}")
    
    return portfolio


if __name__ == "__main__":
    run()
