# 全方位多模型股市分析系統 — 系統架構文件

> 版本：v3.2.0 | 最後更新：2026-05-10

---

## 系統概覽

```
使用者輸入股票代號
    ↓
前端 (GitHub Pages)
    ↓ POST /analyze
後端 API (Railway · FastAPI)
    ↓
數據抓取層 (A→B→C→D→E→F)
    ↓
AI 分析引擎 (7個框架 · Opus 4.5)
    ↓
結果輸出 (對比表 + 完整報告)
```

---

## 架構層次

### 1. 前端層 (Frontend)

| 項目 | 技術 | 說明 |
|---|---|---|
| 部署位置 | GitHub Pages (gh-pages branch) | `smartlife-calendar.github.io/AI-Investment-HQ/` |
| 框架 | HTML5 + Tailwind CSS + marked.js | 單頁應用，無 Node.js 環境依賴 |
| 股票選單 | 7 個分析框架 + 全模型對比 | 含技術面、基本面、量化框架 |
| 錯誤處理 | 查無代碼 → 顯示友善錯誤訊息 | 防止錯誤代碼進入分析流程 |

---

### 2. 後端 API 層 (Backend)

| 項目 | 說明 |
|---|---|
| 部署 | Railway · `ai-investment-hq-production.up.railway.app` |
| 框架 | FastAPI (Python) |
| 主要端點 | `POST /analyze` · `GET /personas` · `GET /health` |
| Rate Limiting | 50 次/小時/IP（開發模式，上線後降為 5 次） |
| 驗證 | Ticker 輸入驗證 → 查無代碼直接回 404 |

---

### 3. 數據抓取層 (Data Pipeline)

| 步驟 | 來源 | 內容 | 文件 |
|---|---|---|---|
| A | Yahoo Finance Chart v8 | 即時股價、52週高低、成交量 | `data_fetcher.py` |
| B | SEC EDGAR XBRL | 美股財務報表（Revenue、GP、NI、OCF、CapEx 等 13 項） | `data_fetcher.py` |
| C | FinMind / TWSE | 台股財務報表、P/E、P/B、殖利率 | `tw_fetcher.py` |
| D | 技術指標計算 | RSI、布林通道、MACD、MA20/50/200、成交量比 | `technical_fetcher.py` |
| E | SEC EDGAR full-text | 10-Q/10-K 財報原文（MD&A、風險因素） | `sec_fetcher.py` |
| F | 市場情緒指標 | VIX、10年債、DXY、板塊ETF、貪婪/恐懼指數、熱門股 | `market_context_fetcher.py` |

**數據品質機制：**
- 多年數據（prev_year）確保 YoY 比較準確
- 新上市公司（如 SNDK）自動使用最新 10-Q 季報
- GrossProfit 缺失時自動計算（Revenue - COGS）
- 台股 Equity 使用正確 FinMind key（`Equity`）
- Ticker 驗證：輸入前先確認代碼存在

---

### 4. AI 分析引擎 (Analysis Engine)

| 框架 ID | 名稱 | 核心邏輯 |
|---|---|---|
| `financial_structure` | 財務結構分析 | FCF、SBC%、商譽比、Book-to-Bill、法說會潛台詞 |
| `supply_chain_structure` | 供應鏈結構分析 | 內供率、CapEx時間差、客戶集中度 |
| `benjamin_graham` | Benjamin Graham | Graham Number、NCAV、安全邊際、P/E×P/B |
| `peter_lynch` | Peter Lynch GARP | PEG、Lynch 合理價、存貨vs營收成長 |
| `cathie_wood` | Cathie Wood 破壞性創新 | CAGR、R&D佔比、TAM、5年回報倍數 |
| `piotroski_fscore` | Piotroski F-Score | F1-F9 逐項評分，9分量化財務健康 |
| `technical_analysis` | 技術面分析 | RSI、布林通道%B、MACD交叉、均線排列、量比 |

**LLM：** `claude-opus-4-5`（Anthropic）  
**輸出格式（5段強制）：**
1. 核心計算
2. 指標評分表
3. 市場情緒評估
4. 主要風險
5. 估值結論（悲觀/基準/樂觀目標價 + 評級）

---

### 5. 靈魂素材庫 (Persona Sources)

| 文件 | 說明 |
|---|---|
| `personas/config.json` | 7 個分析框架完整定義 |
| `personas/sources/uncle_*.md` | 真實財報分析文章（ANET/NVTS/RDW/RMBS/SMR/TER/TMDX/VICR） |

---

## 已知限制

| 問題 | 說明 | 解決方向 |
|---|---|---|
| LITE（小公司）XBRL 不完整 | 7/13 指標可用 | 加 FMP fallback |
| USAR 新上市 | 缺 CapEx/LTDebt | 等 SEC 數據累積 |
| GOOGL/VST 無 GrossProfit XBRL | 用 Revenue-COGS 補算 | 已實作 |
| 台股 TotalEquity 改用 `Equity` key | FinMind schema | 已修正 |
| Reddit 熱度 | 403 Forbidden 免費版 | 用 volume ratio 替代 |
| 貪婪/恐懼指數 | alternative.me (Crypto F&G) | 待接股票版 CNN F&G |

---

## 環境變數

| 變數名 | 說明 | 位置 |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude API Key | Railway Variables |
| `FMP_API_KEY` | Financial Modeling Prep | Railway Variables |

---

## 文件結構

```
AI-Investment-HQ/
├── api/
│   └── main.py              # FastAPI 後端入口
├── agents/
│   ├── analyst.py           # AI 分析引擎（7框架）
│   ├── data_fetcher.py      # 美股數據（Yahoo/SEC XBRL）
│   ├── tw_fetcher.py        # 台股數據（FinMind/TWSE）
│   ├── technical_fetcher.py # 技術指標計算
│   ├── sec_fetcher.py       # SEC 10-Q/10-K 財報文字
│   ├── fmp_fetcher.py       # FMP 數據
│   ├── news_fetcher.py      # 新聞爬蟲
│   ├── market_context_fetcher.py # 市場情緒指標
│   └── full_pipeline.py     # 數據整合主流程
├── personas/
│   ├── config.json          # 7個分析框架定義
│   └── sources/             # 靈魂素材文章
├── frontend/
│   └── index.html           # 前端頁面（gh-pages）
├── reports/                 # 分析報告存檔
├── railway.toml             # Railway 部署設定
├── requirements.txt
├── README.md
├── ARCHITECTURE.md          # 本文件
└── FUNCTIONS.md             # 功能清單
```
