# scripts/build_stop_guide_a249.py
# A249: 목표가 기준 손절과 차트 기준 손절을 구분해 판단 가이드 생성
import json
from pathlib import Path
from datetime import datetime

DATA = Path("data")
CAND = DATA / "stock_candidates_ai_scored.json"
SUMMARY = DATA / "market_scanner_summary.json"
OUT = DATA / "stop_guide_a249.json"

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

def rp(v):
    if v <= 0:
        return 0
    unit = 500 if v >= 100000 else 100 if v >= 10000 else 10
    return int(round(v / unit) * unit)

def current(c):
    for k in ["currentPrice", "close", "price", "lastPrice"]:
        p = si(c.get(k))
        if p > 0:
            return p
    return 0

def chart_stop(c, cur):
    existing = si(c.get("chartStopPrice"))
    if existing > 0:
        return existing
    stop_loss = si(c.get("stopLoss"))
    if stop_loss > 0 and cur > 0 and cur * 0.75 <= stop_loss <= cur:
        return stop_loss
    return rp(cur * 0.92) if cur > 0 else 0

run = datetime.now().isoformat(timespec="seconds")
cands = norm(load(CAND, []))
details = []
updated = 0

for c in cands:
    if not isinstance(c, dict):
        continue
    code = str(c.get("code") or "").zfill(6)
    name = str(c.get("name") or "")
    cur = current(c)
    target = si(c.get("targetMedianPrice"))
    target_stop = si(c.get("stopTimingPrice")) or (rp(target * 0.60) if target > 0 else 0)
    cstop = chart_stop(c, cur)

    if target_stop > 0:
        c["stopTimingPrice"] = target_stop
    if cstop > 0:
        c["chartStopPrice"] = cstop

    c["chartStopReason"] = (
        f"차트 기준 손절선: {cstop:,}원. 단기 매매에서는 이 기준을 우선 확인합니다."
        if cstop > 0 else
        "차트 기준 손절선 없음. 현재가 또는 stopLoss 데이터가 필요합니다."
    )
    c["stopGuideReason"] = (
        f"중장기 손절은 목표가 기준 {target_stop:,}원, 단기 손절은 차트 기준 {cstop:,}원입니다. "
        f"단기 매매는 차트 손절 우선, 중장기 보유는 목표가 기준 손절을 참고합니다."
        if target_stop > 0 or cstop > 0 else
        "손절 기준 산출 불가."
    )
    c["targetEngineVersion"] = "A249"
    c["updatedAt"] = run
    updated += 1

    details.append({
        "code": code,
        "name": name,
        "currentPrice": cur,
        "naverTargetPrice": target,
        "targetBasedStopPrice": target_stop,
        "chartStopPrice": cstop,
        "guide": c.get("stopGuideReason", "")
    })

save(CAND, cands)
summary = load(SUMMARY, {})
if not isinstance(summary, dict):
    summary = {}
summary.update({
    "version": "A249",
    "generatedAt": run,
    "status": "stop_guide_card",
    "candidateCount": len(cands),
    "stopGuideUpdatedCount": updated,
    "targetBasedStopCount": sum(1 for d in details if d["targetBasedStopPrice"] > 0),
    "chartStopCount": sum(1 for d in details if d["chartStopPrice"] > 0),
    "output": "stock_candidates_ai_scored.json",
})
save(SUMMARY, summary)
save(OUT, {"version": "A249", "generatedAt": run, "summary": summary, "details": details})
print(json.dumps(summary, ensure_ascii=False, indent=2))
