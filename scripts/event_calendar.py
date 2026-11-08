#!/usr/bin/env python3
"""
StockIQ Event Calendar & Political Strategy Module v1
Tracks: FOMC, earnings seasons, elections, options expiry, geopolitical events
Provides: historical patterns, sector allocation, event-driven signals

Output: data/event_calendar.json on gh-pages
Runs: weekly (Saturday)
"""
import os, sys, json, base64, urllib.request, time
from datetime import datetime, timedelta, timezone
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))

GH_TOKEN = os.environ.get("GH_TOKEN", "")
ANTHROPIC_KEY = os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
REPO = "smartlife-calendar/AI-Investment-HQ"
GH_HEADERS = {"Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github.v3+json"}
API = f"https://api.github.com/repos/{REPO}"
TW_TZ = timezone(timedelta(hours=8))

# ═══════════════════════════════════════════
# Known Events 2026-2027
# ═══════════════════════════════════════════

FOMC_MEETINGS = [
    # 2026
    {"date": "2026-10-29", "type": "fomc", "label": "FOMC 10月會議"},
    {"date": "2026-12-17", "type": "fomc", "label": "FOMC 12月會議"},
    # 2027
    {"date": "2027-01-28", "type": "fomc", "label": "FOMC 1月會議"},
    {"date": "2027-03-18", "type": "fomc", "label": "FOMC 3月會議"},
    {"date": "2027-05-06", "type": "fomc", "label": "FOMC 5月會議"},
    {"date": "2027-06-17", "type": "fomc", "label": "FOMC 6月會議"},
    {"date": "2027-07-29", "type": "fomc", "label": "FOMC 7月會議"},
    {"date": "2027-09-16", "type": "fomc", "label": "FOMC 9月會議"},
    {"date": "2027-10-28", "type": "fomc", "label": "FOMC 10月會議"},
    {"date": "2027-12-16", "type": "fomc", "label": "FOMC 12月會議"},
]

EARNINGS_SEASONS = [
    {"date": "2026-10-13", "end": "2026-11-15", "type": "earnings", "label": "Q3 財報季（10月中-11月中）"},
    {"date": "2027-01-12", "end": "2027-02-15", "type": "earnings", "label": "Q4 財報季（1月中-2月中）"},
    {"date": "2027-04-13", "end": "2027-05-15", "type": "earnings", "label": "Q1 財報季（4月中-5月中）"},
    {"date": "2027-07-12", "end": "2027-08-15", "type": "earnings", "label": "Q2 財報季（7月中-8月中）"},
]

POLITICAL_EVENTS = [
    {"date": "2026-11-03", "type": "election", "label": "🗳️ 美國期中選舉",
     "detail": "眾議院全部改選 + 參議院1/3改選",
     "historical": {
         "pattern": "選前3-6個月偏弱，選後6個月歷史平均+15-20%",
         "pre_election_avg": -2.5,
         "post_election_6m_avg": 16.8,
         "post_election_12m_avg": 22.3,
     }},
    # Debt ceiling / budget deadlines (estimated)
    {"date": "2026-12-31", "type": "fiscal", "label": "📋 聯邦預算截止日（估計）",
     "detail": "政府關門風險"},
]

# Options expiry (Triple/Quadruple Witching)
OPEX_DATES = [
    {"date": "2026-10-17", "type": "opex", "label": "10月選擇權到期"},
    {"date": "2026-11-21", "type": "opex", "label": "11月選擇權到期"},
    {"date": "2026-12-19", "type": "opex", "label": "12月四巫日（Quadruple Witching）"},
    {"date": "2027-01-16", "type": "opex", "label": "1月選擇權到期"},
    {"date": "2027-02-20", "type": "opex", "label": "2月選擇權到期"},
    {"date": "2027-03-19", "type": "opex", "label": "3月四巫日"},
]

# ═══════════════════════════════════════════
# Election Strategy Module
# ═══════════════════════════════════════════

ELECTION_STRATEGY = {
    "midterm_2026": {
        "date": "2026-11-03",
        "current_president": "Trump (R)",
        "current_congress": "R majority (slim)",
        "scenarios": [
            {
                "name": "紅色浪潮（共和黨大勝）",
                "probability": "中等",
                "impact": {
                    "bull_sectors": ["能源(XLE)", "金融(XLF)", "工業/基建(XLI)", "國防(ITA)", "小型股(IWM)"],
                    "bear_sectors": ["清潔能源(ICLN)", "大麻(MSOS)"],
                    "rationale": "減稅延續、放鬆監管、基建支出、軍費增加",
                    "tickers": {
                        "strong_buy": ["XOM", "CVX", "JPM", "GS", "CAT", "DE", "LMT", "RTX", "GD"],
                        "watch": ["TSLA", "NVDA"],  # TSLA benefits from Musk-Trump, NVDA from less China restriction?
                        "avoid": ["ENPH", "SEDG", "FSLR"],  # Clean energy subsidy risk
                    }
                }
            },
            {
                "name": "分裂政府（民主黨奪眾議院）",
                "probability": "中等",
                "impact": {
                    "bull_sectors": ["醫療(XLV)", "公用事業(XLU)", "必需消費(XLP)"],
                    "bear_sectors": ["金融(XLF)", "能源(XLE)"],
                    "rationale": "政策僵局→防禦板塊、大型科技監管風險降低（無法立法）",
                    "tickers": {
                        "strong_buy": ["JNJ", "PG", "KO", "NEE", "SO"],
                        "watch": ["AAPL", "GOOGL", "MSFT"],
                        "avoid": [],
                    }
                }
            },
        ],
        "timeline": [
            {"phase": "現在→選前1個月", "strategy": "降低倉位至70%，增加現金和防禦部位", "weeks_away": None},
            {"phase": "選前1個月", "strategy": "佈局選後受益股（分批進場），避免追高", "weeks_away": 4},
            {"phase": "選舉週", "strategy": "不做大動作，等結果", "weeks_away": 0},
            {"phase": "選後1-2週", "strategy": "根據結果加碼對應板塊", "weeks_away": -1},
            {"phase": "選後1-6個月", "strategy": "歷史最強時期，全力配置", "weeks_away": -4},
        ],
        "trump_policy_plays": {
            "基建": {"tickers": ["CAT", "DE", "VMC", "MLM", "URI"], "logic": "基礎建設法案推進"},
            "能源獨立": {"tickers": ["XOM", "CVX", "SLB", "HAL", "OXY"], "logic": "Drill baby drill，放鬆環保法規"},
            "金融放鬆": {"tickers": ["JPM", "GS", "MS", "BLK", "SCHW"], "logic": "放鬆銀行資本要求"},
            "國防": {"tickers": ["LMT", "RTX", "GD", "NOC", "HII"], "logic": "軍費佔GDP提升"},
            "關稅受益": {"tickers": ["NUE", "STLD", "CLF", "X"], "logic": "鋼鐵/製造回流"},
            "Musk_效應": {"tickers": ["TSLA"], "logic": "Musk與Trump關係→政策利好"},
        },
    }
}

# ═══════════════════════════════════════════
# Long-term vs Short-term Framework
# ═══════════════════════════════════════════

TIMEFRAME_FRAMEWORK = {
    "long_term": {
        "label": "長線配置（季度調整）",
        "horizon": "3-12個月",
        "criteria": [
            "Alpha框架信心 ≥ medium",
            "投資論點完整（thesis_intact=true）",
            "季度營收趨勢穩定或向上",
            "所屬板塊符合宏觀環境",
        ],
        "position_sizing": "單一持股不超過10%，板塊不超過30%",
        "rebalance": "每季財報後調整",
        "exit_rules": [
            "論點崩壞（thesis_intact=false 連續2週）",
            "營收連續2季衰退",
            "股價跌破季度ATR停損",
            "板塊輪動出局（連續2月弱於SPY）",
        ],
    },
    "short_term": {
        "label": "短線機會（事件驅動）",
        "horizon": "1-4週",
        "criteria": [
            "事件催化（財報、FOMC、選舉）",
            "技術面突破（BB squeeze、黃金交叉）",
            "情緒急轉（sentiment reversal）",
            "同業聯動機會（peer contagion reversal）",
        ],
        "position_sizing": "單一持股不超過5%，總短線倉位不超過20%",
        "exit_rules": [
            "事件結束後3天內評估",
            "達到目標價或停損",
            "情緒恢復中性",
        ],
    },
}


# ═══════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════

def gh_push(path, content, msg="update", branch="gh-pages"):
    url = f"{API}/contents/{path}?ref={branch}"
    req = urllib.request.Request(url, headers=GH_HEADERS)
    sha = None
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            sha = json.loads(r.read()).get("sha")
    except:
        pass

    payload = {
        "message": msg,
        "content": base64.b64encode(json.dumps(content, ensure_ascii=False, default=str).encode()).decode(),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    req = urllib.request.Request(
        f"{API}/contents/{path}",
        data=json.dumps(payload).encode(),
        headers={**GH_HEADERS, "Content-Type": "application/json"},
        method="PUT",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status


def compute_event_proximity(events, today=None):
    """Calculate days until each event, add urgency markers."""
    if today is None:
        today = datetime.now(TW_TZ).date()
    elif isinstance(today, str):
        today = datetime.strptime(today, "%Y-%m-%d").date()
    
    upcoming = []
    for evt in events:
        evt_date = datetime.strptime(evt["date"], "%Y-%m-%d").date()
        days_away = (evt_date - today).days
        
        if days_away < -30:
            continue  # Skip past events older than 30 days
        
        urgency = "past"
        if days_away > 30:
            urgency = "normal"
        elif days_away > 7:
            urgency = "approaching"
        elif days_away > 0:
            urgency = "imminent"
        elif days_away >= -7:
            urgency = "just_passed"
        
        entry = {**evt, "days_away": days_away, "urgency": urgency}
        upcoming.append(entry)
    
    return sorted(upcoming, key=lambda x: x["days_away"])


def generate_current_strategy(today=None):
    """Generate current allocation strategy based on upcoming events."""
    if today is None:
        today = datetime.now(TW_TZ).date()
    elif isinstance(today, str):
        today = datetime.strptime(today, "%Y-%m-%d").date()
    
    election_date = datetime.strptime("2026-11-03", "%Y-%m-%d").date()
    days_to_election = (election_date - today).days
    
    # Find next upcoming major event for the banner
    next_event_label = "期中選舉"
    next_event_days = days_to_election
    if days_to_election < 0:
        # Election passed — find next major event
        all_major = FOMC_MEETINGS + OPEX_DATES + POLITICAL_EVENTS
        future = []
        for ev in all_major:
            ev_date = datetime.strptime(ev["date"], "%Y-%m-%d").date()
            d = (ev_date - today).days
            if d > 0:
                future.append({"label": ev.get("label", ev.get("name", "")), "days": d, "type": ev.get("type", "")})
        future.sort(key=lambda x: x["days"])
        if future:
            next_event_label = future[0]["label"]
            next_event_days = future[0]["days"]

    strategy = {
        "date": today.strftime("%Y-%m-%d"),
        "election_countdown": days_to_election,
        "next_event": next_event_label,
        "next_event_days": next_event_days,
    }
    
    if days_to_election > 90:
        strategy["phase"] = "早期佈局"
        strategy["equity_allocation"] = "80%"
        strategy["action"] = "正常配置，開始研究選舉受益股"
        strategy["focus"] = "基本面選股為主"
    elif days_to_election > 30:
        strategy["phase"] = "選前減倉期"
        strategy["equity_allocation"] = "70%"
        strategy["action"] = "逐步降低投機部位，增加防禦板塊"
        strategy["focus"] = "增加 XLV/XLU/XLP，減少高Beta"
    elif days_to_election > 7:
        strategy["phase"] = "選前最後衝刺"
        strategy["equity_allocation"] = "65%"
        strategy["action"] = "分批建立選後受益股倉位（小部位）"
        strategy["focus"] = "能源/金融/基建 小部位試水"
    elif days_to_election > 0:
        strategy["phase"] = "選舉週"
        strategy["equity_allocation"] = "65%"
        strategy["action"] = "不做大動作，等待結果"
        strategy["focus"] = "現金為王"
    elif days_to_election > -14:
        strategy["phase"] = "選後佈局期"
        strategy["equity_allocation"] = "80-90%"
        strategy["action"] = "根據結果加碼對應板塊"
        strategy["focus"] = "選舉結果明朗後積極加倉"
    elif days_to_election > -180:
        strategy["phase"] = "選後黃金期"
        strategy["equity_allocation"] = "90-100%"
        strategy["action"] = "歷史最強時段，全力配置"
        strategy["focus"] = "板塊動量 + 基本面雙驅動"
    else:
        strategy["phase"] = "正常市場"
        strategy["equity_allocation"] = "按模型"
        strategy["action"] = "回歸常規策略"
        strategy["focus"] = "基本面為主"
    
    # Add FOMC proximity impact
    all_events = FOMC_MEETINGS + [e for e in POLITICAL_EVENTS] + OPEX_DATES
    upcoming = compute_event_proximity(all_events, today)
    
    imminent = [e for e in upcoming if e["urgency"] in ("imminent", "approaching") and e["days_away"] > 0]
    if imminent:
        strategy["upcoming_events"] = [
            {"label": e["label"], "days": e["days_away"], "type": e["type"]}
            for e in imminent[:5]
        ]
        
        # FOMC within 7 days = reduce position
        fomc_imminent = [e for e in imminent if e["type"] == "fomc" and e["days_away"] <= 7]
        if fomc_imminent:
            strategy["fomc_warning"] = "FOMC會議即將召開，考慮降低高Beta部位"
    
    return strategy


# ═══════════════════════════════════════════
# Main
# ═══════════════════════════════════════════

def run():
    print("=" * 60)
    print(f"StockIQ Event Calendar — {datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    
    today = datetime.now(TW_TZ).date()
    
    # Build event timeline
    all_events = FOMC_MEETINGS + EARNINGS_SEASONS + POLITICAL_EVENTS + OPEX_DATES
    timeline = compute_event_proximity(all_events, today)
    
    print(f"\n[1] Event Timeline ({len(timeline)} events)")
    for evt in timeline[:10]:
        marker = {"imminent": "🔴", "approaching": "🟡", "normal": "⚪", "just_passed": "✅", "past": "⬜"}.get(evt["urgency"], "")
        print(f"  {marker} {evt['date']} ({evt['days_away']:+d}d) {evt['label']}")
    
    # Current strategy
    print(f"\n[2] Current Strategy")
    strategy = generate_current_strategy(today)
    for k, v in strategy.items():
        if k != "upcoming_events":
            print(f"  {k}: {v}")
    
    # Build output
    output = {
        "generated_at": datetime.now(TW_TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "timeline": timeline,
        "current_strategy": strategy,
        "election_strategy": ELECTION_STRATEGY,
        "timeframe_framework": TIMEFRAME_FRAMEWORK,
        "trump_plays": ELECTION_STRATEGY["midterm_2026"]["trump_policy_plays"],
    }
    
    # Push
    print(f"\n[3] Pushing to gh-pages...")
    gh_push("data/event_calendar.json", output, "Event calendar update")
    print("✅ Done")


if __name__ == "__main__":
    run()
