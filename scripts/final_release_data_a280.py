# scripts/final_release_data_a280.py
# A280: 최종 릴리즈 상태 요약 생성
import json
from pathlib import Path
from datetime import datetime

DATA = Path("data")
CAND = DATA / "stock_candidates_ai_scored.json"
SUMMARY = DATA / "market_scanner_summary.json"
OUT = DATA / "final_release_a280.json"

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
price = target = stop = invalid = 0

for c in cands:
    if not isinstance(c, dict):
        continue
    if int(c.get("currentPrice") or c.get("close") or 0) > 0:
        price += 1
    if int(c.get("targetMedianPrice") or 0) > 0:
        target += 1
    if int(c.get("chartStopPrice") or c.get("stopTimingPrice") or 0) > 0:
        stop += 1
    if c.get("priceValidationStatus") == "검증필요":
        invalid += 1

summary = load(SUMMARY, {})
if not isinstance(summary, dict):
    summary = {}

summary.update({
    "version": "A280",
    "generatedAt": run,
    "status": "final_release",
    "candidateCount": len(cands),
    "priceConnectedCount": price,
    "targetConnectedCount": target,
    "stopGuideConnectedCount": stop,
    "invalidPriceCandidateCount": invalid,
    "releaseName": "HSinvest Android A280 Final Release"
})

save(SUMMARY, summary)
save(OUT, {
    "version": "A280",
    "generatedAt": run,
    "summary": summary
})
print(json.dumps(summary, ensure_ascii=False, indent=2))
