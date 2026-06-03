#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V251 REAL DATA QUALITY CHECK+

목적:
- V250 이후 stock_candidates.json에 들어간 값이 실제 데이터인지, 보정값인지 점검
- 앱의 '데이터 품질 현실 점검'과 같은 관점으로 GitHub에서도 품질 확인
"""

import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()

CANDIDATES_JSON = ROOT / "stock_candidates.json"
REPORT_JSON = ROOT / "v251_real_data_quality_report.json"
REPORT_TXT = ROOT / "v251_real_data_quality_report.txt"

PLACEHOLDERS = [
    "수급 미연결",
    "차트 확인 필요",
    "일봉 확인 필요",
    "RSI 확인 필요",
    "MACD 확인 필요",
    "거래량 확인 필요",
    "리포트 확인 필요",
    "뉴스 확인 필요",
    "후보 사유 기반 검토 필요",
    "손절 기준 확인 필요",
    "진입 기준 확인 필요",
    "목표 기준 확인 필요",
    "-",
    "",
]

def now_text():
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

def unwrap(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ["candidates", "items", "data", "results", "stocks"]:
            if isinstance(data.get(key), list):
                return data[key]
    return []

def value(row, key):
    v = row.get(key, "-")
    if v is None:
        return "-"
    return str(v).strip()

def is_real(v):
    text = str(v).strip()
    if text in PLACEHOLDERS:
        return False
    return not any(p in text for p in PLACEHOLDERS if p not in ["", "-"])

def has_any_real(row, keys):
    return any(is_real(value(row, k)) for k in keys)

def main():
    if not CANDIDATES_JSON.exists():
        raise SystemExit("stock_candidates.json 파일이 없습니다.")

    raw = json.loads(CANDIDATES_JSON.read_text(encoding="utf-8"))
    candidates = [x for x in unwrap(raw) if isinstance(x, dict)]

    total = len(candidates)

    chart_keys = ["weeklyCloud", "dailySignal", "rsi", "macd", "volumeSignal"]
    supply_keys = [
        "foreign5D", "foreign20D", "foreign60D",
        "pension5D", "pension20D", "pension60D",
        "trust5D", "trust20D", "trust60D",
        "finance5D", "finance20D", "finance60D",
    ]
    report_keys = ["reportSignal", "newsSignal", "riskMemo"]
    trade_keys = ["entryPrice", "stopLoss", "targetPrice"]

    chart_count = sum(1 for r in candidates if has_any_real(r, chart_keys))
    supply_count = sum(1 for r in candidates if has_any_real(r, supply_keys))
    report_count = sum(1 for r in candidates if has_any_real(r, report_keys))
    trade_count = sum(1 for r in candidates if all(is_real(value(r, k)) for k in trade_keys))

    weak_items = []
    for r in candidates:
        missing = []
        if not has_any_real(r, chart_keys):
            missing.append("chart")
        if not has_any_real(r, supply_keys):
            missing.append("supply")
        if not has_any_real(r, report_keys):
            missing.append("report")
        if not all(is_real(value(r, k)) for k in trade_keys):
            missing.append("tradePlan")

        if missing:
            weak_items.append({
                "name": value(r, "name"),
                "code": value(r, "code"),
                "score": value(r, "score"),
                "missing": missing
            })

    result = {
        "version": "V251_REAL_DATA_QUALITY_CHECK",
        "updatedAt": now_text(),
        "candidateCount": total,
        "realChartCount": chart_count,
        "realSupplyCount": supply_count,
        "realReportCount": report_count,
        "realTradePlanCount": trade_count,
        "qualityScore": {
            "chart": f"{chart_count}/{total}",
            "supply": f"{supply_count}/{total}",
            "report": f"{report_count}/{total}",
            "tradePlan": f"{trade_count}/{total}",
        },
        "weakItemsTop20": weak_items[:20],
        "message": "실데이터 품질 점검 완료"
    }

    REPORT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "V251 REAL DATA QUALITY CHECK",
        f"updatedAt: {result['updatedAt']}",
        f"candidateCount: {total}",
        f"realChartCount: {chart_count}/{total}",
        f"realSupplyCount: {supply_count}/{total}",
        f"realReportCount: {report_count}/{total}",
        f"realTradePlanCount: {trade_count}/{total}",
        "",
        "Weak Items Top 20:",
    ]

    for item in weak_items[:20]:
        lines.append(f"- {item['name']} ({item['code']}): missing {', '.join(item['missing'])}")

    REPORT_TXT.write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
