# 全方位多模型股市分析系統 — 項目狀態清單
> 最後更新：2026-05-10

---

## 🌐 系統資訊

| 項目 | 值 |
|---|---|
| 前端網址 | https://smartlife-calendar.github.io/AI-Investment-HQ/ |
| 後端 API | https://ai-investment-hq-production.up.railway.app |
| GitHub Repo | smartlife-calendar/AI-Investment-HQ |
| 當前版本 | v3.7.1 |
| 分析模型 | claude-sonnet-4-5（預設）/ claude-opus-4-5（可切換） |

---

## ✅ 已完成功能

### 數據層
- [x] 美股 SEC XBRL（Revenue, GP, NI, OCF, CapEx, Assets, Equity 等 13+ 指標）
- [x] 台股 FinMind（損益表、現金流、資產負債表）
- [x] TWSE 即時估值（P/E, P/B, 殖利率）
- [x] Yahoo Finance Chart v8（即時股價、52W高低）
- [x] TTM EPS（過去12個月滾動計算）
- [x] 最新季度 Gross Margin（非年度平均）
- [x] QoQ 季對季比較數據
- [x] Forward P/E（最新季 × 4 年化）
- [x] PEG Ratio
- [x] EV/EBITDA
- [x] Rule of 40
- [x] Balance Sheet 最新季度快照（非僅年報）
- [x] Taiwan 個股 OCF/CapEx YTD 差值推算

### 分析框架（9種）
- [x] 財務結構分析（FCF, SBC%, Goodwill, 法說會解讀）
- [x] 供應鏈結構分析（內供率, 時間差, 瓶頸）
- [x] Benjamin Graham 價值防禦
- [x] Peter Lynch GARP 成長
- [x] Cathie Wood 破壞性創新
- [x] Piotroski F-Score 量化（F1-F9）
- [x] 技術面分析（RSI, 布林通道, MACD, 均線, 成交量）
- [x] Howard Marks 宏觀週期
- [x] Bill Ackman 激進價值

### 市場情緒
- [x] VIX 恐慌指數
- [x] 10年期美債殖利率
- [x] 美元指數 DXY
- [x] S&P 500 趨勢
- [x] 貪婪/恐懼指數（-100 到 +100 綜合評分）
- [x] 板塊 ETF 52W 表現（11個大板塊）
- [x] 子板塊追蹤（半導體, 軟體, AI, 機器人, 太空, 生技 等 18個）
- [x] 今日熱門股（Yahoo Trending）
- [x] 週對週動能柱狀圖（可展開）

### 介面
- [x] 🇺🇸/🇹🇼 市場切換按鈕
- [x] 台股自動補 .TW 後綴
- [x] 下拉選單分組（基本面/價值/成長宏觀/技術面）
- [x] 分析後自動顯示個股板塊脈絡
- [x] 廣告橫幅（分析等待期間）
- [x] 行動裝置優化（垂直堆疊）
- [x] 成績單系統（Python 計算，非 AI 推算）
- [x] 分析快取（6小時，減少 API 呼叫）
- [x] Rate Limiting（50次/小時/IP）
- [x] 查詢次數統計（/trending 端點）
- [x] 查無此代碼友善錯誤

### 數據品質保證
- [x] 10-K vs 10-Q 時效性判斷（9個月規則）
- [x] OCF/CapEx 從 YTD 差值推算（SNDK 類公司）
- [x] SNDK 等新上市公司使用最新 10-Q 而非舊 10-K
- [x] 台股 Equity 使用正確 FinMind key
- [x] 目標價合理性驗證（plausibility check）
- [x] 評級提取避免觸發條件干擾

---

## 🔴 已知問題 / 待修復

| 優先級 | 問題 | 狀態 |
|---|---|---|
| 高 | 台股框架適用性偵測（虧損股隱藏 Graham 等） | ⏳ 待做 |
| 高 | LITE/USAR 部分 XBRL 數據不完整 | ⚠️ 已知 |
| 中 | EPS TTM：部分公司缺少 CY2025Q3 季度 | ⚠️ 已知 |
| 中 | 板塊子項目缺少週對週柱狀圖 | ⏳ 待做 |
| 低 | Reddit/Twitter 個股熱度（需付費 API） | ❌ 跳過 |

---

## 💰 商業模式規劃

| 方案 | 限制 | 價格 |
|---|---|---|
| 免費 | 5次/天，3個框架，有廣告 | $0 |
| Pro | 150次/月，全9個框架，無廣告 | $9.9/月 |
| 加購 | 100次 | $2 |
| 企業 | 無限次，API 存取，白標 | $99+/月 |

**待實作：**
- [ ] Google OAuth 登入
- [ ] Stripe 付款串接
- [ ] 使用次數計數（按用戶）
- [ ] Pro 解鎖邏輯
- [ ] Google AdSense 串接（目前只有佔位符）

---

## 🔐 安全事項

| 項目 | 狀態 | 備注 |
|---|---|---|
| Anthropic API Key | ⚠️ 暴露過 | 建議建立第二個 key 專供 Railway |
| FMP API Key | ⚠️ 暴露過 | 建議更換 |
| GitHub PAT | ⚠️ 暴露過 | 建議更換 |
| Railway 環境變數 | ✅ 安全 | 未曾公開 |
| Rate Limiting | ✅ 50次/小時 | 防惡意爬取 |

---

## 📁 重要檔案

```
AI-Investment-HQ/
├── api/main.py              # FastAPI 後端（Rate limit, 路由）
├── agents/
│   ├── analyst.py           # 9個框架分析引擎（claude-sonnet/opus）
│   ├── data_fetcher.py      # 美股數據（Yahoo + SEC XBRL）
│   ├── tw_fetcher.py        # 台股數據（FinMind + TWSE）
│   ├── technical_fetcher.py # RSI/MACD/布林計算
│   ├── scorecard_engine.py  # Python 確定性成績單
│   ├── macro_fetcher.py     # 宏觀+板塊數據（帶快取）
│   ├── market_context_fetcher.py # VIX/F&G/情緒評分
│   └── full_pipeline.py    # 數據整合主流程
├── personas/
│   ├── config.json          # 9個分析框架定義
│   └── sources/             # 靈魂素材（大叔文章等）
├── frontend/index.html      # 前端（GitHub Pages）
├── ARCHITECTURE.md          # 系統架構文件
├── FUNCTIONS.md             # 功能清單
└── railway.toml             # Railway 部署設定
```
