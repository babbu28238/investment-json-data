# scripts/manual_price_review_a256.py
# A256: 검증필요 종목 수동 확인 리스트 생성
import json
from pathlib import Path
from datetime import datetime

DATA = Path("data")
CAND = DATA / "stock_candidates_ai_scored.json"
SUMMARY = DATA / "market_scanner_summary.json"
OUT = DATA / "manual_price_review_a256.json"

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
review = []

for c in cands:
    if not isinstance(c, dict):
        continue
    if c.get("priceValidationStatus") == "검증필요":
        review.append({
            "code": str(c.get("code", "")).zfill(6),
            "name": c.get("name", ""),
            "market": c.get("market", ""),
            "sector": c.get("sector", ""),
            "reason": c.get("priceValidationReason", "가격 검증 필요"),
            "action": "네이버증권/증권앱 현재가 확인 후 다음 가격 수집 단계에서 재검증",
            "naverUrl": f"https://m.stock.naver.com/domestic/stock/{str(c.get('code', '')).zfill(6)}/total"
        })

summary = load(SUMMARY, {})
if not isinstance(summary, dict):
    summary = {}
summary.update({
    "version": "A256",
    "generatedAt": run,
    "status": "manual_price_review",
    "candidateCount": len(cands),
    "manualReviewCount": len(review),
    "outputReview": "manual_price_review_a256.json"
})
save(SUMMARY, summary)
save(OUT, {"version": "A256", "generatedAt": run, "summary": summary, "details": review})
print(json.dumps(summary, ensure_ascii=False, indent=2))
