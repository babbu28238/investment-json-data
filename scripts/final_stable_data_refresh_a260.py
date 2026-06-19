# scripts/final_stable_data_refresh_a260.py
# A260: 최종 안정 데이터 정리
# - 검증필요 종목은 가격/목표가/손절선을 사용하지 않도록 유지
# - 정상 종목은 기존 목표가/손절 데이터를 보존
# - 앱 컴파일과 무관한 데이터 정리용 최종 Action

import json
from pathlib import Path
from datetime import datetime

DATA = Path("data")
CAND = DATA / "stock_candidates_ai_scored.json"
SUMMARY = DATA / "market_scanner_summary.json"
OUT = DATA / "final_stable_a260.json"

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

invalid = normal = target_count = price_count = 0
details = []

for c in cands:
    if not isinstance(c, dict):
        continue

    status = str(c.get("priceValidationStatus") or "")
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
        c["reportTargetReason"] = c.get("reportTargetReason") or "가격 검증 필요. 현재가 확인 전 목표가/상승여력/손절선을 사용하지 않습니다."
        c["chartStopReason"] = "현재가 검증 실패로 차트 손절선 미산출."
        c["stopGuideReason"] = "가격 검증 필요 상태입니다. 최신 가격 확인 후 다시 산출하세요."
        c["invalidPriceUxMessage"] = "가격 검증 필요"
    else:
        normal += 1
        if not status:
            c["priceValidationStatus"] = "정상"
        if int(c.get("currentPrice") or c.get("close") or 0) > 0:
            price_count += 1
        if int(c.get("targetMedianPrice") or 0) > 0:
            target_count += 1
        c["invalidPriceUxMessage"] = ""

    c["targetEngineVersion"] = "A260"
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
    "version": "A260",
    "generatedAt": run,
    "status": "final_stable",
    "candidateCount": len(cands),
    "normalCandidateCount": normal,
    "invalidPriceCandidateCount": invalid,
    "priceConnectedCount": price_count,
    "targetConnectedCount": target_count,
    "output": "stock_candidates_ai_scored.json",
})
save(SUMMARY, summary)
save(OUT, {"version": "A260", "generatedAt": run, "summary": summary, "details": details})
print(json.dumps(summary, ensure_ascii=False, indent=2))
