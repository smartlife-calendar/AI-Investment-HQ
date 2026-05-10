# 帳號/收費/邀請碼系統設計

## 技術選型（全免費）

| 功能 | 技術 | 原因 |
|---|---|---|
| 登入 | Firebase Authentication | Google/GitHub OAuth，免費，超簡單 |
| 資料庫 | Firebase Firestore | 存用戶資料/次數，免費額度夠用 |
| 收費 | Stripe | 最主流，台灣可用，3% 手續費 |
| 機器人驗證 | Cloudflare Turnstile | 免費，比 reCAPTCHA 更輕量 |

## 資料庫結構（Firestore）

```
users/{uid}/
  email: string
  plan: "free" | "pro"
  plan_expires: timestamp
  monthly_credits: number      # 本月剩餘次數
  total_used: number          # 歷史總使用
  invite_code_used: string    # 使用的邀請碼
  created_at: timestamp

usage_logs/{auto_id}/
  uid: string
  ticker: string
  persona: string
  timestamp: timestamp

invite_codes/{code}/
  created_by: string          # "admin" or uid
  bonus_credits: number       # 使用後獲得的次數
  max_uses: number
  used_count: number
  expires_at: timestamp
```

## 方案設計

| 方案 | 次數/月 | 框架 | 廣告 | 價格 |
|---|---|---|---|---|
| 免費 | 30次 | 3個（基本面/技術/Graham） | 有 | $0 |
| Pro | 150次 | 全9個 + 子板塊 | 無 | $9.9/月 |
| 加購 | +100次 | 依方案 | 依方案 | $2 |

## 邀請碼系統

- 邀請碼格式：`INVEST-XXXXX`（6位隨機）
- 使用後：免費用戶獲得額外 30次（相當於多一個月）
- 可設到期日、最多使用次數
- 你可以從後台創建邀請碼
- 用途：給早期用戶、KOL推廣、活動獎勵

## 機器人驗證

- 分析按鈕第一次點擊前驗證
- 使用 Cloudflare Turnstile（完全免費）
- 比 Google reCAPTCHA 更不干擾用戶

## 實作順序

1. Firebase 設定（2小時）
   - 建立 Firebase project
   - 開啟 Google 登入
   - 建立 Firestore 集合

2. 前端登入按鈕（1小時）
   - 右上角 "登入" 按鈕
   - 點擊 → Google OAuth
   - 登入後顯示頭像 + 剩餘次數

3. 後端驗證 Firebase JWT（2小時）
   - 每次 /analyze 請求帶 Firebase ID Token
   - Railway 驗證 token → 從 Firestore 扣次數

4. Stripe 付款（3小時）
   - Stripe Checkout（最簡單）
   - 付款成功 → 更新 Firestore plan 欄位

5. 邀請碼（1小時）
   - 前端輸入邀請碼框
   - 後端驗證 → 加次數

6. Cloudflare Turnstile（30分鐘）
   - 替換「開始解析」按鈕的第一次點擊
