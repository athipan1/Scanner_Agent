# Scanner_Agent

Scanner_Agent เป็น Market Discovery Agent ของระบบ Multi-Agent Trading ทำหน้าที่สร้าง universe, คัดกรองหุ้น, รวมหลักฐานจากหลายแหล่ง, จัดอันดับ candidate และส่งข้อมูลให้ `Manager_Agent` ตัดสินใจต่อ โดย Scanner ไม่ใช่ผู้ตัดสินใจซื้อขายขั้นสุดท้ายและไม่ส่งคำสั่งไป Broker โดยตรง

เวอร์ชันปัจจุบัน: **1.3.0**

## Data Sources

Scanner ใช้ข้อมูลหลายแหล่งและบันทึก provenance ของข้อมูลไว้ในผลลัพธ์

| แหล่งข้อมูล | ใช้ทำอะไร |
| --- | --- |
| NASDAQ Trader | รายชื่อหุ้น US ที่จดทะเบียนจริง (`nasdaqlisted.txt`, `otherlisted.txt`) |
| Wikipedia | fallback สำหรับ S&P 500 / Nasdaq-100 universe |
| Yahoo Finance (`yfinance`) | ราคา, Volume, Market Cap, ราคา 6 เดือน, Profile, Valuation, Growth, Quality และงบการเงิน |
| TradingView (`tradingview-ta`) | Recommendation, RSI, MACD, SMA50, SMA200, ATR, Volume, Relative Strength และ Technical indicators |
| Alpaca Market Data | Latest bid/ask quote, quote size, midpoint และ spread เมื่อมี API credentials |
| Scanner Backtest | หลักฐานผล Backtest ที่ใช้ประกอบ candidate score |
| Sector Rotation | เปรียบเทียบ Sector ETF กับ SPY |

ถ้า Alpaca credentials ไม่ได้ตั้งค่า Scanner จะไม่สร้าง client ที่ใช้ key ปลอม และจะใช้ข้อมูล Yahoo/TradingView ที่มีอยู่ต่อโดยระบุ `provider_status.alpaca = not_configured`

## Technical Scan (`POST /scan`)

Technical Scanner V5 ทำงานโดยประมาณดังนี้:

```text
NASDAQ Trader / explicit symbols
            ↓
Yahoo Finance Pre-filter
Price + Avg Volume + Market Cap
            ↓
Yahoo Finance Market Ranking
5D / 20D / 60D return + volume + trend
            ↓
TradingView Technical Analysis
RSI / MACD / SMA / ATR / momentum
            ↓
Fundamental + Sector + Backtest evidence
            ↓
Weighted Candidate Score
            ↓
BUY / STRONG_BUY candidates
            ↓
scanner-data-bundle.v1
            ↓
Manager_Agent
```

สำหรับตลาด US ที่ไม่ได้ส่ง `symbols` มา Scanner จะสร้าง broad universe แล้วทำ pre-filter/ranking ก่อนส่งหุ้นจำนวนจำกัดเข้า TradingView เพื่อควบคุม latency และ provider load

สำหรับ request ที่ส่ง `symbols` มาเอง Scanner จะใช้รายชื่อที่ผู้เรียกกำหนดโดยตรง

## Fundamental Scan (`POST /scan/fundamental`)

Fundamental Scanner วิเคราะห์:

- **Quality**: ROE, ROA, Debt/Equity, Free Cash Flow, Profit Margin
- **Growth**: Revenue CAGR, EPS Growth
- **Valuation**: P/E, PEG, P/B
- **Statements**: Annual/Quarterly Income Statement, Balance Sheet, Cash Flow
- **Market Snapshot**: latest price, market cap, liquidity, profile, valuation/growth/quality fields

ผลลัพธ์บอกด้วยว่างบชุดใดมีจริง ชุดใดหาย และ provider มี error ระหว่างโหลดหรือไม่

## Complete Candidate Data Bundle

Candidate ที่ออกจาก Scanner จะมีข้อมูล `metadata.details.data_bundle` ใช้ schema:

```text
scanner-data-bundle.v1
```

ตัวอย่างโครงสร้าง:

```json
{
  "schema_version": "scanner-data-bundle.v1",
  "symbol": "AAPL",
  "sources": [
    "tradingview",
    "alpaca_latest_quote",
    "reused_yfinance_info",
    "yfinance_history",
    "yfinance_fundamentals",
    "sector_rotation",
    "scanner_backtest"
  ],
  "market_snapshot": {
    "currentPrice": 230.1,
    "marketCap": 3400000000000,
    "averageVolume": 52000000,
    "sector": "Technology",
    "industry": "Consumer Electronics",
    "trailingPE": 31.0,
    "forwardPE": 27.0,
    "pegRatio": 2.1,
    "priceToBook": 45.0,
    "revenueGrowth": 0.08,
    "earningsGrowth": 0.11,
    "returnOnEquity": 1.45,
    "returnOnAssets": 0.24,
    "debtToEquity": 135.0,
    "profitMargins": 0.27,
    "freeCashflow": 100000000000,
    "provider_status": {
      "alpaca": "success",
      "yfinance": "reused"
    }
  },
  "technical": {},
  "market_rank": {},
  "fundamental": {},
  "sector_rotation": {},
  "backtest": {},
  "data_quality": {
    "status": "partial",
    "coverage_ratio": 0.91,
    "complete_components": [],
    "partial_components": [],
    "missing_components": [],
    "market_missing_fields": []
  }
}
```

### Market data groups

`market_snapshot.data_quality.groups` แยก coverage เป็นกลุ่ม:

- `quote`
- `liquidity`
- `profile`
- `valuation`
- `growth`
- `quality`

Scanner จะไม่ตีความว่า field ที่ provider ไม่มีเป็นศูนย์ และจะไม่ตัด candidate เพียงเพราะ optional field หาย แต่จะแสดง `missing_fields` และ `coverage_ratio` ให้ Manager/Risk ใช้ประกอบการตัดสินใจ

## Provider Priority

ราคาใช้ลำดับความสำคัญดังนี้:

1. Alpaca latest ask/bid quote เมื่อ credentials พร้อม
2. Yahoo Finance current/regular market price
3. Yahoo Finance previous close fallback

ข้อมูล fundamental ที่ Scanner ดึงระหว่าง scoring จะถูก reuse ตอนสร้าง final candidate bundle เพื่อหลีกเลี่ยงการยิง Yahoo Finance ซ้ำโดยไม่จำเป็น

## API Endpoints

### `GET /health`
ตรวจสอบ process health และ runtime metadata

### `GET /ready`
ตรวจสอบว่า runtime พร้อมทำงานและไม่มี unsafe dev fallback ใน LIVE mode

### `GET /version`
คืน API/service version และ contract metadata

### `POST /scan`
Technical + multi-factor candidate discovery

ตัวอย่าง request:

```json
{
  "symbols": ["AAPL", "MSFT", "NVDA"],
  "screener": "america",
  "exchange": "NASDAQ"
}
```

### `POST /scan/fundamental`
Fundamental analysis สำหรับรายการ symbol ที่กำหนด

### `POST /discover-best-fundamentals`
ค้นหา candidate พื้นฐานเด่นจาก broad US universe

## Safety Boundary

Scanner_Agent มีหน้าที่ **ค้นหาและส่งหลักฐาน** เท่านั้น

```text
Scanner_Agent
     ↓ candidate + evidence
Manager_Agent
     ↓
Technical / Fundamental / Portfolio / Profit / other evidence
     ↓
Risk_Agent
     ↓ approved only
Execution_Agent
```

Scanner ห้ามใช้ recommendation ของตัวเองเป็นคำสั่งซื้อขายโดยตรง และ `Risk_Agent` ยังคงเป็น safety gate ก่อน Execution เสมอ
