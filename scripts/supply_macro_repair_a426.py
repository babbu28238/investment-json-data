# scripts/supply_macro_repair_a426.py
# 수급/매크로가 50점에 고정되는 문제를 후처리로 보정한다.
import json
from pathlib import Path
from datetime import datetime

DATA = Path("data")
FILES = [
    DATA / "realtime_recommendations_a405.json",
    DATA / "stock_candidates_ai_scored.json",
]

def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def intval(v):
    try:
        return int(float(v or 0))
    except Exception:
        return 0

def score_supply(x):
    current = intval(x.get("supplyScore"))
    f = intval(x.get("foreignNetBuy"))
    i = intval(x.get("institutionNetBuy"))
    p = intval(x.get("pensionNetBuy"))
    status = str(x.get("supplyStatus") or x.get("supplyDataStatus") or "")
    if current not in (0, 50):
        return current, x.get("supplyOpinion") or x.get("supplyReason") or ""
    if f > 0 and i > 0:
        return 86, f"외국인 {f:,}, 기관 {i:,} 순매수를 반영해 수급 점수 86점으로 보정했습니다."
    if f > 0 or i > 0 or p > 0:
        return 68, f"외국인 {f:,}, 기관 {i:,}, 연기금 {p:,} 중 순매수 주체가 있어 수급 점수 68점으로 보정했습니다."
    if f < 0 and i < 0:
        return 28, f"외국인 {f:,}, 기관 {i:,} 순매도를 반영해 수급 점수 28점으로 보정했습니다."
    if f < 0 or i < 0 or p < 0:
        return 38, f"외국인 {f:,}, 기관 {i:,}, 연기금 {p:,} 중 순매도 주체가 있어 수급 점수 38점으로 보정했습니다."
    if "부분" in status or status == "partial":
        return 55, "수급 원자료가 일부만 확인되어 중립보다 약간 높은 55점으로 보정했습니다."
    return 50, "외국인·기관·연기금 수급 원자료가 충분하지 않아 중립 50점으로 유지했습니다."

def score_macro(x):
    current = intval(x.get("macroScore"))
    adj = intval(x.get("macroAdjustmentScore"))
    reasons = x.get("macroReasons") or []
    if current not in (0, 50):
        return current, x.get("macroOpinion") or ""
    if adj >= 8:
        return 72, f"종목 업종에 유리한 매크로 조정점수 +{adj}점을 반영해 매크로 점수 72점으로 보정했습니다."
    if adj >= 4:
        return 64, f"종목 업종에 유리한 매크로 조정점수 +{adj}점을 반영해 매크로 점수 64점으로 보정했습니다."
    if adj <= -8:
        return 28, f"종목 업종에 불리한 매크로 조정점수 {adj}점을 반영해 매크로 점수 28점으로 보정했습니다."
    if adj <= -4:
        return 36, f"종목 업종에 불리한 매크로 조정점수 {adj}점을 반영해 매크로 점수 36점으로 보정했습니다."
    if reasons:
        return 58, "종목에 적용된 매크로 요인이 있어 중립보다 약간 높은 58점으로 보정했습니다."
    return 50, "종목 업종과 직접 연결되는 매크로 요인이 부족해 중립 50점으로 유지했습니다."

def final_score(x):
    q = intval(x.get("quantScore") or x.get("priceScore") or 50)
    s = intval(x.get("supplyScore") or 50)
    c = intval(x.get("companyScore") or x.get("reportScore") or 50)
    e = intval(x.get("eventScore") or x.get("newsScore") or 50)
    r = intval(x.get("reportScore") or 50)
    ch = intval(x.get("chartScore") or 50)
    m = intval(x.get("macroScore") or 50)
    risk = intval(x.get("riskScore") or 50)
    adj = intval(x.get("macroAdjustmentScore") or 0)
    return max(0, min(100, round(q*.18+s*.18+c*.18+e*.14+r*.10+ch*.10+m*.07+risk*.05+adj)))

def normalize(raw):
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for k in ["candidates", "data", "items", "stocks", "top"]:
            if isinstance(raw.get(k), list):
                return raw[k]
    return []

def main():
    summary = {
        "version": "A426",
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "files": [],
        "supplyChanged": 0,
        "macroChanged": 0
    }
    for path in FILES:
        raw = load(path)
        arr = normalize(raw)
        if not arr:
            continue
        for x in arr:
            old_s = intval(x.get("supplyScore"))
            old_m = intval(x.get("macroScore"))
            new_s, s_op = score_supply(x)
            new_m, m_op = score_macro(x)
            x["supplyScore"] = new_s
            x["macroScore"] = new_m
            x["supplyOpinion"] = s_op
            x["macroOpinion"] = m_op
            if old_s != new_s:
                summary["supplyChanged"] += 1
            if old_m != new_m:
                summary["macroChanged"] += 1
            x["score"] = final_score(x)
            x["realtimeScore"] = x["score"]
            x["targetEngineVersion"] = "A426"
            x["updatedAt"] = summary["updatedAt"]
        if isinstance(raw, list):
            save(path, arr)
        else:
            # preserve simple wrapper if any
            raw["candidates"] = arr
            save(path, raw)
        summary["files"].append(str(path))
    DATA.mkdir(exist_ok=True)
    (DATA / "supply_macro_repair_summary_a426.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
