# AI-Investment-HQ

多人格 AI 股市大師解析系統

## 架構

```
AI-Investment-HQ/
├── personas/
│   └── config.json        # 大叔、辺的靈魂設定
├── agents/
│   └── analyst.py         # 大師解析核心腳本
├── workflows/
│   └── n8n_template.json  # 自動化流程模板（待補）
├── reports/               # 輸出報告存檔
└── README.md
```

## 快速開始

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=你的Key
python agents/analyst.py
```

## 目前支援大師

- **大叔 (Veteran Strategist)** — 現金流、股本稀釋、法說會潛台詞
- **辺 (Edge Insight)** — 供應鏈瓶頸、垂直整合、二線廠逆襲

## 集團子公司
- 投資經營探討事業部（本 repo）
- 行事曆軟體事業部（smart_life_calendar）
- 兒童影音創作事業部（待建）
