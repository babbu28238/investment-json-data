# scripts/invalid_stop_cleanup_a254.py
# A254: 가격 검증 실패 종목의 잔여 목표가/차트 손절/가이드 제거
import json
from pathlib import Path
from datetime import datetime

DATA = Path("data")
CAND = DATA / "stock_candidates_ai_scored.json"
SUMMARY = DATA / "market_scanner_summary.json"
OUT = DATA / "invalid_stop_cleanup_a254.json"

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

def si(v, default=0):
    try:
        return int(float(str(v).replace(",", "").replace("원", "").strip()))
    except Exception:
        return default

run = datetime.now().isoformat(timespec="seconds")
cands = norm(load(CAND, []))
details = []
invalid_count = cleaned_count = normal_count = 0

for c in cands:
    if not isinstance(c, dict):
        continue

    code = str(c.get("code") or c.get("stockCode") or c.get("ticker") or "").zfill(6)
    name = str(c.get("name") or "")
    status = str(c.get("priceValidationStatus") or "")

    before = {
        "currentPrice": si(c.get("currentPrice")) or si(c.get("close")),
        "targetPrice": si(c.get("targetMedianPrice")),
        "chartStopPrice": si(c.get("chartStopPrice")),
        "stopTimingPrice": si(c.get("stopTimingPrice")),
    }

    if status == "검증필요":
        invalid_count += 1

        c["currentPrice"] = 0
        c["close"] = 0
        c["targetMedianPrice"] = 0
        c["realisticTargetPrice"] = 0
        c["observeTimingPrice"] = 0
        c["stopTimingPrice"] = 0
        c["targetUpsidePercent"] = 0.0
        c["reportTargetCount"] = 0
        c["reportTargetPricesText"] = ""
        c["reportTargetReason"] = f"{name} 현재가 검증 실패로 네이버 목표가와 상승여력은 표시하지 않습니다."
        c["chartStopPrice"] = 0
        c["chartStopReason"] = "현재가 검증 실패로 차트 손절선 미산출."
        c["stopGuideReason"] = "현재가 검증 실패 상태입니다. 가격 확인 후 손절 기준을 다시 산출해야 합니다."
        c["priceValidationStatus"] = "검증필요"
        if not c.get("priceValidationReason"):
            c["priceValidationReason"] = f"{name} 가격 데이터 검증 필요."
        cleaned_count += 1
    else:
        normal_count += 1

    c["targetEngineVersion"] = "A254"
    c["updatedAt"] = run

    after = {
        "currentPrice": si(c.get("currentPrice")) or si(c.get("close")),
        "targetPrice": si(c.get("targetMedianPrice")),
        "chartStopPrice": si(c.get("chartStopPrice")),
        "stopTimingPrice": si(c.get("stopTimingPrice")),
    }

    details.append({
        "code": code,
        "name": name,
        "status": c.get("priceValidationStatus", ""),
        "before": before,
        "after": after,
        "cleaned": status == "검증필요",
    })

save(CAND, cands)

summary = load(SUMMARY, {})
if not isinstance(summary, dict):
    summary = {}
summary.update({
    "version": "A254",
    "generatedAt": run,
    "status": "invalid_stop_cleanup",
    "candidateCount": len(cands),
    "invalidPriceCandidateCount": invalid_count,
    "invalidStopCleanedCount": cleaned_count,
    "normalCandidateCount": normal_count,
    "output": "stock_candidates_ai_scored.json",
})
save(SUMMARY, summary)
save(OUT, {"version": "A254", "generatedAt": run, "summary": summary, "details": details})
print(json.dumps(summary, ensure_ascii=False, indent=2))
