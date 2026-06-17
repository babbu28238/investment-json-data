# scripts/naver_target_chart_stop_a248.py
# A248: 중앙값 표현 제거, 네이버 목표가 + 차트 추천 손절선 병행 제공
import json
from pathlib import Path
from datetime import datetime

DATA = Path("data")
CAND = DATA / "stock_candidates_ai_scored.json"
SUMMARY = DATA / "market_scanner_summary.json"
OUT = DATA / "naver_target_chart_stop_a248.json"

def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default

def save(path, data):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def norm(raw):
    if isinstance(raw, list): return raw
    if isinstance(raw, dict):
        for k in ["candidates", "data", "items", "stocks", "top"]:
            if isinstance(raw.get(k), list): return raw[k]
    return []

def si(v, default=0):
    try: return int(float(str(v).replace(",", "").replace("원", "").strip()))
    except Exception: return default

def rd(v, unit=100):
    if v <= 0: return 0
    if v >= 100000: unit = 500
    elif v >= 10000: unit = 100
    else: unit = 10
    return int(round(v / unit) * unit)

def current_price(c):
    for k in ["currentPrice", "close", "price", "lastPrice"]:
        p = si(c.get(k))
        if p > 0: return p
    return 0

def chart_stop(c, cur):
    # 우선순위: 기존 stopLoss > 현재가 기반 차트 손절
    stop = si(c.get("stopLoss"))
    if stop > 0 and cur > 0 and cur * 0.75 <= stop <= cur:
        return stop, f"차트 추천 손절선: 기존 stopLoss {stop:,}원 사용."
    # 기술적 손절선 fallback: 현재가 대비 -8% 부근. 이후 실제 MA/저점 데이터 연결 가능.
    p = rd(cur * 0.92)
    return p, f"차트 추천 손절선: 현재가 {cur:,}원 기준 약 -8% 구간 {p:,}원. 실제 매도 판단 시 최근 저점/20일선 이탈 여부와 함께 확인."

run = datetime.now().isoformat(timespec="seconds")
cands = norm(load(CAND, []))
updated, target_count, chart_stop_count, upside_count = 0, 0, 0, 0
details = []

for c in cands:
    if not isinstance(c, dict): continue
    code = str(c.get("code") or "").zfill(6)
    name = str(c.get("name") or "")
    cur = current_price(c)
    target = si(c.get("targetMedianPrice"))
    if target > 0:
        c["targetPriceSourceLabel"] = "네이버 컨센서스 목표가"
        c["realisticTargetPrice"] = si(c.get("realisticTargetPrice")) or rd(target * 0.80)
        c["observeTimingPrice"] = si(c.get("observeTimingPrice")) or rd(target * 0.70)
        c["stopTimingPrice"] = si(c.get("stopTimingPrice")) or rd(target * 0.60)
        upside = ((target - cur) / cur * 100.0) if cur > 0 else 0.0
        c["targetUpsidePercent"] = round(upside, 1)
        c["reportTargetReason"] = (
            f"네이버 컨센서스 목표가 {target:,}원 기준. "
            f"현재가 {cur:,}원 대비 상승여력 {upside:.1f}%. "
            f"현실목표 {c['realisticTargetPrice']:,}원(80%), "
            f"관찰 {c['observeTimingPrice']:,}원(70%), "
            f"목표가 기준 손절 {c['stopTimingPrice']:,}원(60%)."
        )
        target_count += 1
        if upside > 0: upside_count += 1
    if cur > 0:
        cs, reason = chart_stop(c, cur)
        c["chartStopPrice"] = cs
        c["chartStopReason"] = reason
        chart_stop_count += 1
    c["targetEngineVersion"] = "A248"
    c["updatedAt"] = run
    updated += 1
    details.append({
        "code": code,
        "name": name,
        "currentPrice": cur,
        "naverTargetPrice": target,
        "targetUpsidePercent": c.get("targetUpsidePercent", 0),
        "targetBasedStopPrice": c.get("stopTimingPrice", 0),
        "chartStopPrice": c.get("chartStopPrice", 0),
        "chartStopReason": c.get("chartStopReason", ""),
    })

save(CAND, cands)
summary = load(SUMMARY, {})
if not isinstance(summary, dict): summary = {}
summary.update({
    "version": "A248",
    "generatedAt": run,
    "status": "naver_target_chart_stop",
    "candidateCount": len(cands),
    "targetPriceCandidateCount": target_count,
    "targetUpsideCandidateCount": upside_count,
    "chartStopCandidateCount": chart_stop_count,
    "targetSource": "naver_consensus_target",
    "stopGuide": "target_60_percent + chart_stop_price",
    "output": "stock_candidates_ai_scored.json",
})
save(SUMMARY, summary)
save(OUT, {"version": "A248", "generatedAt": run, "summary": summary, "details": details})
print(json.dumps(summary, ensure_ascii=False, indent=2))
