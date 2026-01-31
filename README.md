# Scanner_Agent

Scanner_Agent เป็นระบบสแกนตลาดหุ้นอัตโนมัติ (Market Scanner) ซึ่งเป็นส่วนหนึ่งของระบบ Multi-Agent Trading โดย Agent นี้ทำหน้าที่วิเคราะห์และคัดเลือกหุ้นที่น่าสนใจตามเงื่อนไขที่กำหนด ทั้งในด้านเทคนิคอลและปัจจัยพื้นฐาน

## การทำงานเชิงเทคนิค (Technical Logic)

### 1. การสแกนทางเทคนิค (Technical Scan - `/scan`)
ฟังก์ชัน `scan_market` ทำหน้าที่วิเคราะห์สัญญาณทางเทคนิคโดยใช้ข้อมูลจาก TradingView:
*   **แหล่งข้อมูล**: ใช้ไลบรารี `tradingview-ta` เพื่อดึงข้อมูลสรุป (Summary) ของอินดิเคเตอร์ทางเทคนิค
*   **การตั้งค่า**: สแกนที่ Timeframe 1 วัน (Interval.INTERVAL_1_DAY) โดยมีค่าเริ่มต้นสำหรับตลาดหุ้นไทย (Screener: thailand, Exchange: SET)
*   **เงื่อนไขการคัดเลือก**: จะเลือกเฉพาะหุ้นที่มีคำแนะนำ (Recommendation) เป็น **"BUY"** หรือ **"STRONG_BUY"** เท่านั้น
*   **ประสิทธิภาพ**: ใช้ `ThreadPoolExecutor` ในการดึงข้อมูลแบบขนาน (Parallel) สูงสุด 10 งานพร้อมกัน เพื่อความรวดเร็วในการสแกนหุ้นจำนวนมาก

### 2. การสแกนปัจจัยพื้นฐาน (Fundamental Scan - `/scan/fundamental`)
ฟังก์ชัน `scan_long_term` ทำหน้าที่วิเคราะห์ความแข็งแกร่งของบริษัทเพื่อการลงทุนระยะยาว:
*   **แหล่งข้อมูล**:
    *   `yfinance`: สำหรับดึงงบการเงินย้อนหลัง (Income Statement, Balance Sheet, Cash Flow)
    *   `alpaca-py`: สำหรับดึงราคาล่าสุดและตัวชี้วัดมูลค่า (Valuation Metrics)
*   **เกณฑ์การวิเคราะห์**:
    *   **Quality (คุณภาพ)**: วิเคราะห์ ROE, ROA, อัตราส่วนหนี้สินต่อทุน (D/E), กระแสเงินสดอิสระ (Free Cash Flow) และอัตรากำไร (Profit Margins)
    *   **Growth (การเติบโต)**: วิเคราะห์อัตราการเติบโตของรายได้ (Revenue CAGR) และการเติบโตของกำไรต่อหุ้น (EPS Growth)
    *   **Valuation (มูลค่า)**: วิเคราะห์ P/E Ratio, PEG Ratio และ P/B Ratio
*   **การประเมินผล**: ระบบจะคำนวณคะแนนรวม (Fundamental Score) และจัดเกรด (Grade) ตั้งแต่ S (ดีเยี่ยม) ไปจนถึง F (แย่มาก) พร้อมทั้งสร้างบทวิเคราะห์เบื้องต้น (Investment Thesis)

---

## API Endpoints

### 1. ตรวจสอบสถานะ (Health Check)
*   **URL**: `/health`
*   **Method**: `GET`
*   **รายละเอียด**: ใช้สำหรับตรวจสอบว่า Service ยังทำงานอยู่หรือไม่ (มักใช้กับ Docker Healthcheck)

### 2. สแกนทางเทคนิค (Technical Scan)
*   **URL**: `/scan`
*   **Method**: `POST`
*   **รายละเอียด**: รับรายชื่อหุ้นและส่งคืนเฉพาะหุ้นที่มีสัญญาณซื้อทางเทคนิค

### 3. สแกนปัจจัยพื้นฐาน (Fundamental Scan)
*   **URL**: `/scan/fundamental`
*   **Method**: `POST`
*   **รายละเอียด**: วิเคราะห์ปัจจัยพื้นฐานและส่งคืนรายชื่อหุ้นพร้อมคะแนนเฉลี่ย

---

## โครงสร้างข้อมูล (Schemas)

### ScanRequest (ข้อมูลนำเข้า)
| ฟิลด์ | ชนิดข้อมูล | คำอธิบาย |
| :--- | :--- | :--- |
| `symbols` | `List[str]` (Optional) | รายชื่อสัญลักษณ์หุ้นที่ต้องการสแกน (เช่น `["PTT", "CPALL"]`) หากไม่ระบุจะใช้รายชื่อหุ้นเริ่มต้น |

### StandardResponse (รูปแบบการตอบกลับมาตรฐาน)
| ฟิลด์ | ชนิดข้อมูล | คำอธิบาย |
| :--- | :--- | :--- |
| `agent` | `str` | ชื่อของ Agent (ค่าเริ่มต้นคือ "Scanner_Agent") |
| `status` | `str` | สถานะการทำงาน (`success`, `partial_success`, `failure`) |
| `timestamp` | `datetime` | เวลาที่ประมวลผลเสร็จสิ้น (UTC) |
| `data` | `ScanResult` \| `null` | ข้อมูลผลลัพธ์จากการสแกน |
| `errors` | `List[ErrorDetail]` \| `null` | รายการข้อผิดพลาดที่เกิดขึ้นระหว่างประมวลผลแต่ละหุ้น |

### ScanResult (ข้อมูลผลลัพธ์)
| ฟิลด์ | ชนิดข้อมูล | คำอธิบาย |
| :--- | :--- | :--- |
| `symbols` | `List[str]` | รายชื่อหุ้นที่ผ่านเกณฑ์การคัดเลือก |
| `score` | `float` \| `null` | คะแนนรวมเฉลี่ย (มีค่าเฉพาะการสแกนปัจจัยพื้นฐาน 0.0 - 1.0) |

---

## ตัวอย่างการใช้งาน (Examples)

### 1. การเรียกใช้งาน (Request)
```json
{
  "symbols": ["PTT", "ADVANC", "KBANK"]
}
```

### 2. ผลลัพธ์จากการสแกนทางเทคนิค (Response - /scan)
```json
{
  "agent": "Scanner_Agent",
  "status": "success",
  "timestamp": "2023-10-27T10:00:00Z",
  "data": {
    "symbols": ["PTT", "KBANK"],
    "score": null
  },
  "errors": null
}
```

### 3. ผลลัพธ์จากการสแกนปัจจัยพื้นฐาน (Response - /scan/fundamental)
```json
{
  "agent": "Scanner_Agent",
  "status": "partial_success",
  "timestamp": "2023-10-27T10:05:00Z",
  "data": {
    "symbols": ["ADVANC"],
    "score": 0.85
  },
  "errors": [
    {
      "symbol": "PTT",
      "error": "Missing essential financial or market data"
    }
  ]
}
```
