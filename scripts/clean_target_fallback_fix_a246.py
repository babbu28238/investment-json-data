# scripts/clean_target_fallback_fix_a246.py
# A246: A245에서 stock_candidates_ai_scored.json이 0개라 정제 실패한 문제 보정
# A244 target_price_bands_a244.json의 details를 직접 후보 소스로 사용한다.

import json, statistics
from pathlib import Path
from datetime import datetime

DATA = Path("data")
CAND = DATA / "stock_candidates_ai_scored.json"
SUMMARY = DATA / "market_scanner_summary.json"
A244 = DATA / "target_price_bands_a244.json"
OUT = DATA / "target_price_bands_a246.json"
AUDIT = DATA / "target_price_clean_audit_a246.json"

FALLBACK = {
    "042660": ("한화오션", "KOSPI", "조선/방산", 91, 128700),
    "329180": ("HD현대중공업", "KOSPI", "조선", 90, 300000),
    "034020": ("두산에너빌리티", "KOSPI", "원전/에너지", 89, 105250),
    "272210": ("한화시스템", "KOSPI", "방산", 88, 132671),
    "005930": ("삼성전자", "KOSPI", "반도체", 87, 297500),
    "000660": ("SK하이닉스", "KOSPI", "반도체", 86, 220000),
    "047810": ("한국항공우주", "KOSPI", "방산", 84, 70000),
    "241560": ("두산밥캣", "KOSPI", "기계", 82, 55000),
    "005380": ("현대차", "KOSPI", "자동차", 82, 250000),
    "000270": ("기아", "KOSPI", "자동차", 81, 115000),
    "105560": ("KB금융", "KOSPI", "금융", 80, 172000),
    "055550": ("신한지주", "KOSPI", "금융", 79, 60000),
    "086790": ("하나금융지주", "KOSPI", "금융", 79, 70000),
    "316140": ("우리금융지주", "KOSPI", "금융", 78, 16000),
    "035420": ("NAVER", "KOSPI", "인터넷", 78, 220000),
    "035720": ("카카오", "KOSPI", "인터넷", 76, 55000),
    "033780": ("KT&G", "KOSPI", "방어주", 76, 110000),
    "011200": ("HMM", "KOSPI", "해운", 75, 22000),
    "008770": ("호텔신라", "KOSPI", "소비/여행", 74, 50000),
    "108490": ("로보티즈", "KOSDAQ", "로봇", 74, 45000),
    "277810": ("레인보우로보틱스", "KOSDAQ", "로봇", 73, 170000),
    "247540": ("에코프로비엠", "KOSDAQ", "2차전지", 72, 130000),
    "086520": ("에코프로", "KOSDAQ", "2차전지", 71, 70000),
    "196170": ("알테오젠", "KOSDAQ", "바이오", 71, 300000),
    "039030": ("이오테크닉스", "KOSDAQ", "반도체장비", 70, 180000),
}

def load(p, d):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else d
    except Exception:
        return d

def save(p, x):
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(x, ensure_ascii=False, indent=2), encoding="utf-8")

def si(v, d=0):
    try:
        return int(float(str(v).replace(",", "").replace("원", "").strip()))
    except Exception:
        return d

def rp(v):
    if v <= 0:
        return 0
    unit = 500 if v >= 100000 else 100 if v >= 10000 else 10
    return int(round(v / unit) * unit)

def reject_reason(p, cur):
    if p in [2024, 2025, 2026, 2027]:
        return "연도 숫자 제거"
    if p < 10000:
        return "1만원 미만 잡음 제거"
    if cur > 0 and p < cur * 0.5:
        return "현재가 대비 과도하게 낮음"
    if cur > 0 and p > cur * 2.5:
        return "현재가 대비 과도하게 높음"
    return ""

def clean_prices(prices, cur):
    ok, bad = [], []
    for raw in prices:
        p = si(raw)
        if p <= 0:
            continue
        why = reject_reason(p, cur)
        if why:
            bad.append({"price": p, "reason": why})
        elif p not in ok:
            ok.append(p)
    return ok, bad

def a244_details():
    raw = load(A244, {})
    details = raw.get("details", []) if isinstance(raw, dict) else []
    return [d for d in details if isinstance(d, dict)]

def build_base_candidate(code, detail):
    name, market, sector, score, price = FALLBACK.get(code, (detail.get("name", ""), "", "", 0, 0))
    return {
        "code": code,
        "name": detail.get("name") or name,
        "market": market,
        "sector": sector,
        "score": score,
        "grade": "B+",
        "currentPrice": price,
        "close": price,
        "reason": f"{detail.get('name') or name} A246 목표가 정제 후보",
        "chartScore": 0,
        "supplyScore": 0,
        "newsScore": 0,
        "fundamentalScore": 0,
        "riskScore": 0,
    }

def main():
    run = datetime.now().isoformat(timespec="seconds")
    details_in = a244_details()

    candidates, audit = [], []
    cleaned, reliable = 0, 0

    for d in details_in:
        code = str(d.get("code", "")).zfill(6)
        if not code or code == "000000":
            continue

        c = build_base_candidate(code, d)
        cur = si(c.get("currentPrice")) or si(d.get("currentPrice")) or FALLBACK.get(code, ("", "", "", 0, 0))[4]
        raw_prices = d.get("prices", []) or []
        accepted, rejected = clean_prices(raw_prices, cur)

        if accepted:
            med = int(statistics.median(accepted))
            c["targetMedianPrice"] = med
            c["realisticTargetPrice"] = rp(med * 0.80)
            c["observeTimingPrice"] = rp(med * 0.70)
            c["stopTimingPrice"] = rp(med * 0.60)
            c["reportTargetCount"] = len(accepted)
            c["reportTargetPricesText"] = ", ".join(f"{p:,}원" for p in sorted(accepted))
            c["reportTargetReason"] = (
                f"정제 목표주가 {len(accepted)}건 중앙값 {med:,}원 기준: "
                f"현실목표 {c['realisticTargetPrice']:,}원(80%), "
                f"관찰 {c['observeTimingPrice']:,}원(70%), "
                f"손절 {c['stopTimingPrice']:,}원(60%). "
                f"현재가 {cur:,}원 기준 0.5~2.5배 범위만 사용."
            )
            cleaned += 1
            if len(accepted) >= 2:
                reliable += 1
        else:
            c["targetMedianPrice"] = 0
            c["realisticTargetPrice"] = 0
            c["observeTimingPrice"] = 0
            c["stopTimingPrice"] = 0
            c["reportTargetCount"] = 0
            c["reportTargetPricesText"] = ""
            c["reportTargetReason"] = "정제 후 유효 목표주가 없음."

        c["targetEngineVersion"] = "A246"
        c["updatedAt"] = run
        candidates.append(c)

        audit.append({
            "code": code,
            "name": c.get("name"),
            "currentPrice": cur,
            "rawPrices": sorted([si(x) for x in raw_prices if si(x) > 0]),
            "acceptedPrices": sorted(accepted),
            "rejected": rejected,
            "median": c.get("targetMedianPrice", 0),
            "realisticTargetPrice": c.get("realisticTargetPrice", 0),
            "observeTimingPrice": c.get("observeTimingPrice", 0),
            "stopTimingPrice": c.get("stopTimingPrice", 0),
            "targetCount": c.get("reportTargetCount", 0),
        })

    candidates.sort(key=lambda x: int(x.get("score", 0)), reverse=True)
    save(CAND, candidates)

    summ = load(SUMMARY, {})
    if not isinstance(summ, dict):
        summ = {}
    summ.update({
        "version": "A246",
        "generatedAt": run,
        "status": "target_clean_fallback_fix",
        "candidateCount": len(candidates),
        "targetPriceCandidateCount": cleaned,
        "reliableTargetCandidateCount": reliable,
        "source": "target_price_bands_a244.details",
        "filterRule": "currentPrice*0.5 <= target <= currentPrice*2.5, remove years and below 10000",
        "output": "stock_candidates_ai_scored.json",
    })
    save(SUMMARY, summ)
    save(OUT, {"version": "A246", "generatedAt": run, "summary": summ, "details": audit})
    save(AUDIT, {"version": "A246", "generatedAt": run, "details": audit})
    print(json.dumps(summ, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
