# scripts/merge_naver_supply_into_candidates_a235.py
# HSinvest A235 SUPPLY MERGE FINAL
# A234에서 naver_supply_detail_a234.json은 성공했지만 앱이 읽는 stock_candidates_ai_scored.json에
# 수급 결과가 반영되지 않은 경우를 강제 해결한다.

import json
from pathlib import Path
from datetime import datetime

DATA = Path("data")
CANDIDATES = DATA / "stock_candidates_ai_scored.json"
NAVER_DETAIL = DATA / "naver_supply_detail_a234.json"
SUMMARY = DATA / "market_scanner_summary.json"
MERGE_SUMMARY = DATA / "supply_merge_summary_a235.json"

def safe_int(v, default=0):
    try:
        return int(float(str(v).replace(",", "")))
    except Exception:
        return default

def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def save_json(path, data):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def normalize_candidates(raw):
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ["candidates", "data", "items", "stocks", "top"]:
            if isinstance(raw.get(key), list):
                return raw[key]
    return []

def grade(total):
    if total >= 85:
        return "A"
    if total >= 75:
        return "B+"
    if total >= 65:
        return "B"
    if total >= 55:
        return "C+"
    return "C"

def recompute(item):
    chart = safe_int(item.get("chartScore", 0))
    supply = safe_int(item.get("supplyScore", 0))
    news = safe_int(item.get("newsScore", 0))
    fundamental = safe_int(item.get("fundamentalScore", item.get("macroScore", 0)))
    risk = safe_int(item.get("riskScore", 0))
    total = max(0, min(100, chart + supply + news + fundamental + risk))
    item["score"] = total
    item["grade"] = grade(total)

def main():
    run_id = datetime.now().isoformat(timespec="seconds")

    candidates_raw = load_json(CANDIDATES, [])
    candidates = normalize_candidates(candidates_raw)
    details = load_json(NAVER_DETAIL, [])

    if not isinstance(details, list):
        details = []

    detail_map = {}
    for d in details:
        if not isinstance(d, dict):
            continue
        code = str(d.get("code", "")).zfill(6)
        if code and code != "000000":
            detail_map[code] = d

    merged = 0
    positive = 0
    ok = 0
    missing = []

    for item in candidates:
        if not isinstance(item, dict):
            continue

        code = str(item.get("code") or item.get("stockCode") or item.get("ticker") or "").zfill(6)
        name = item.get("name", "")
        d = detail_map.get(code)

        if not d:
            missing.append(code)
            continue

        score = safe_int(d.get("supplyScore", 0))
        reason = str(d.get("reason", "") or "수급 근거 없음")
        indicators = d.get("indicators", {}) if isinstance(d.get("indicators", {}), dict) else {}

        item["supplyScore"] = score
        item["supplyReason"] = f"[수급 {score}/30] {reason} (네이버 투자자별 매매동향)"
        item["foreignNet"] = safe_int(indicators.get("foreign20", 0))
        item["institutionNet"] = safe_int(indicators.get("institution20", 0))
        item["pensionNet"] = safe_int(indicators.get("pension20", 0))
        item["trustNet"] = safe_int(indicators.get("trust20", 0))
        item["financeNet"] = safe_int(indicators.get("finance20", 0))
        item["supplyIndicators"] = indicators
        item["supplyEngineVersion"] = "A235"
        item["updatedAt"] = run_id

        recompute(item)

        item["reasonDetail"] = (
            f"{name}({code}) 최종점수 {item.get('score', 0)}점({item.get('grade', '')}). "
            f"산식: 차트 {item.get('chartScore', 0)}/35 + 수급 {item.get('supplyScore', 0)}/30 + "
            f"뉴스 {item.get('newsScore', 0)}/20 + 기본 {item.get('fundamentalScore', item.get('macroScore', 0))}/10 + "
            f"리스크 {item.get('riskScore', 0)}/10. 수급 근거: {reason}."
        )
        item["detailReport"] = item["reasonDetail"]
        item["reason"] = item["reasonDetail"]

        merged += 1
        if str(d.get("status", "")) == "ok":
            ok += 1
        if score > 0:
            positive += 1

    candidates = [x for x in candidates if isinstance(x, dict)]
    candidates.sort(key=lambda x: int(x.get("score", 0)), reverse=True)
    save_json(CANDIDATES, candidates)

    summary = load_json(SUMMARY, {})
    if not isinstance(summary, dict):
        summary = {}

    summary.update({
        "version": "A235",
        "generatedAt": run_id,
        "status": "supply_merge_final",
        "candidateCount": len(candidates),
        "supplyMergedCount": merged,
        "supplyOkCount": ok,
        "supplyScoreCount": positive,
        "supplySource": "naver_supply_detail_a234",
        "ready": merged >= 20 and ok >= 20,
        "output": "stock_candidates_ai_scored.json",
    })
    save_json(SUMMARY, summary)
    save_json(MERGE_SUMMARY, {
        "version": "A235",
        "generatedAt": run_id,
        "summary": summary,
        "missing": missing,
        "sample": candidates[:5],
    })

    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
