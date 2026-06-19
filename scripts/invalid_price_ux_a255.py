# scripts/invalid_price_ux_a255.py
# A255: 검증필요 종목 UX 안내 필드 정리
import json
from pathlib import Path
from datetime import datetime

DATA = Path("data")
CAND = DATA / "stock_candidates_ai_scored.json"
SUMMARY = DATA / "market_scanner_summary.json"
OUT = DATA / "invalid_price_ux_a255.json"

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
invalid = normal = 0
details = []

for c in cands:
    if not isinstance(c, dict):
        continue

    code = str(c.get("code") or c.get("stockCode") or c.get("ticker") or "").zfill(6)
    name = str(c.get("name") or "")
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
        c["reportTargetReason"] = f"{name} 가격 검증 필요. 현재가 확인 전 목표가/상승여력/손절선은 표시하지 않습니다."
        c["chartStopReason"] = "현재가 검증 실패로 차트 손절선 미산출."
        c["stopGuideReason"] = "가격 검증 필요 상태입니다. 최신 가격 새로고침 후 다시 확인하세요."
        c["invalidPriceUxMessage"] = "가격 검증 필요: 현재가/목표가/손절선 미산출"
    else:
        normal += 1
        if not status:
            c["priceValidationStatus"] = "정상"
        c["invalidPriceUxMessage"] = ""

    c["targetEngineVersion"] = "A255"
    c["updatedAt"] = run

    details.append({
        "code": code,
        "name": name,
        "priceValidationStatus": c.get("priceValidationStatus", ""),
        "invalidPriceUxMessage": c.get("invalidPriceUxMessage", ""),
        "currentPrice": c.get("currentPrice", 0),
        "targetMedianPrice": c.get("targetMedianPrice", 0),
        "chartStopPrice": c.get("chartStopPrice", 0),
    })

save(CAND, cands)

summary = load(SUMMARY, {})
if not isinstance(summary, dict):
    summary = {}
summary.update({
    "version": "A255",
    "generatedAt": run,
    "status": "invalid_price_ux",
    "candidateCount": len(cands),
    "invalidPriceCandidateCount": invalid,
    "normalCandidateCount": normal,
    "output": "stock_candidates_ai_scored.json",
})
save(SUMMARY, summary)
save(OUT, {"version": "A255", "generatedAt": run, "summary": summary, "details": details})
print(json.dumps(summary, ensure_ascii=False, indent=2))
