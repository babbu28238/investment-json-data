# scripts/final_complete_data_refresh_a270.py
# A270: 최종 완성본 데이터 정리
# 안정 실행 기준을 유지하면서 summary/version만 최종 완성 상태로 정리한다.

import json
from pathlib import Path
from datetime import datetime

DATA = Path("data")
CAND = DATA / "stock_candidates_ai_scored.json"
SUMMARY = DATA / "market_scanner_summary.json"
OUT = DATA / "final_complete_a270.json"

def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default

def save(path, data):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def norm(raw):
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for k in ["candidates", "data", "items", "stocks", "top"]:
            if isinstance(raw.get(k), list):
                return raw[k]
    return []

run = datetime.now().isoformat(timespec="seconds")
cands = norm(load(CAND, []))

normal = invalid = price_count = target_count = chart_stop_count = 0
details = []

for c in cands:
    if not isinstance(c, dict):
        continue

    status = str(c.get("priceValidationStatus") or "")
    price = int(c.get("currentPrice") or c.get("close") or 0)
    target = int(c.get("targetMedianPrice") or 0)
    chart_stop = int(c.get("chartStopPrice") or 0)

    if status == "검증필요":
        invalid += 1
        c["currentPrice"] = 0
        c["close"] = 0
        c["targetMedianPrice"] = 0
        c["realisticTargetPrice"] = 0
        c["observeTimingPrice"] = 0
        c["stopTimingPrice"] = 0
        c["targetUpsidePercent"] = 0.0
        c["chartStopPrice"] = 0
        c["invalidPriceUxMessage"] = "가격 검증 필요"
    else:
        normal += 1
        if not status:
            c["priceValidationStatus"] = "정상"
        if price > 0:
            price_count += 1
        if target > 0:
            target_count += 1
        if chart_stop > 0:
            chart_stop_count += 1
        c["invalidPriceUxMessage"] = ""

    c["targetEngineVersion"] = "A270"
    c["updatedAt"] = run

    details.append({
        "code": str(c.get("code", "")).zfill(6),
        "name": c.get("name", ""),
        "priceValidationStatus": c.get("priceValidationStatus", ""),
        "currentPrice": c.get("currentPrice", 0) or c.get("close", 0),
        "targetMedianPrice": c.get("targetMedianPrice", 0),
        "chartStopPrice": c.get("chartStopPrice", 0),
    })

save(CAND, cands)

summary = load(SUMMARY, {})
if not isinstance(summary, dict):
    summary = {}

summary.update({
    "version": "A270",
    "generatedAt": run,
    "status": "final_complete",
    "candidateCount": len(cands),
    "normalCandidateCount": normal,
    "invalidPriceCandidateCount": invalid,
    "priceConnectedCount": price_count,
    "targetConnectedCount": target_count,
    "chartStopConnectedCount": chart_stop_count,
    "output": "stock_candidates_ai_scored.json"
})

save(SUMMARY, summary)
save(OUT, {
    "version": "A270",
    "generatedAt": run,
    "summary": summary,
    "details": details
})

print(json.dumps(summary, ensure_ascii=False, indent=2))
