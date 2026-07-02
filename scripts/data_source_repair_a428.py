# scripts/data_source_repair_a428.py
# A418 구데이터의 chart failed / supply partial을 JSON 단계에서 대체산출 상태로 보정
import json
from pathlib import Path
from datetime import datetime

DATA = Path("data")
FILES = [DATA/"realtime_recommendations_a405.json", DATA/"stock_candidates_ai_scored.json"]
OUT = DATA/"data_source_repair_a428.json"

def load(p):
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return []

def save(p,d):
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

def arr(raw):
    if isinstance(raw,list): return raw,"list"
    if isinstance(raw,dict):
        for k in ["candidates","data","items","stocks","top"]:
            if isinstance(raw.get(k),list): return raw[k],k
    return [],"none"

def iv(v):
    try: return int(float(v or 0))
    except Exception: return 0

def is_a418(x):
    blob=" ".join(str(x.get(k,"")) for k in ["source","targetSource","targetEngineVersion"])
    return "a418" in blob.lower() or "real_data_all_connector_a418" in blob.lower()

def supply_score(x, status):
    old=iv(x.get("supplyScore"))
    if old not in (0,50): return old
    f=iv(x.get("foreignNetBuy")); i=iv(x.get("institutionNetBuy")); p=iv(x.get("pensionNetBuy"))
    if f>0 and i>0: return 86
    if f>0 or i>0 or p>0: return 68
    if f<0 and i<0: return 28
    if f<0 or i<0 or p<0: return 38
    if status=="derived": return 55
    return 50

def macro_score(x):
    old=iv(x.get("macroScore"))
    if old not in (0,50): return old
    adj=iv(x.get("macroAdjustmentScore"))
    reasons=x.get("macroReasons") or []
    if adj>=8: return 72
    if adj>=4: return 64
    if adj<=-8: return 28
    if adj<=-4: return 36
    if reasons: return 58
    return 50

def data_score(x):
    total=0
    for k in ["priceDataStatus","newsDataStatus","reportDataStatus","chartDataStatus","supplyDataStatus","macroDataStatus"]:
        s=str(x.get(k,""))
        if s=="connected": total+=17
        elif s=="derived": total+=13
        elif s=="partial": total+=10
        elif s=="missing": total+=5
    return max(0,min(100,total))

def final_score(x):
    q=iv(x.get("quantScore") or x.get("priceScore") or 50); s=iv(x.get("supplyScore") or 50)
    c=iv(x.get("companyScore") or x.get("reportScore") or 50); e=iv(x.get("eventScore") or x.get("newsScore") or 50)
    r=iv(x.get("reportScore") or 50); ch=iv(x.get("chartScore") or 50); m=iv(x.get("macroScore") or 50); risk=iv(x.get("riskScore") or 50); adj=iv(x.get("macroAdjustmentScore") or 0)
    return max(0,min(100,round(q*.18+s*.18+c*.18+e*.14+r*.10+ch*.10+m*.07+risk*.05+adj)))

summary={"version":"A428","updatedAt":datetime.now().isoformat(timespec="seconds"),"files":[],"total":0,"a418Repaired":0,"chartDerived":0,"supplyDerived":0,"macroRepaired":0}
for p in FILES:
    raw=load(p); items,key=arr(raw)
    if not items: continue
    for x in items:
        summary["total"]+=1
        stale=is_a418(x)
        has_price=iv(x.get("currentPrice") or x.get("close"))>0
        if stale: summary["a418Repaired"]+=1

        if (str(x.get("chartDataStatus")) in ["failed","실패",""] and has_price):
            x["chartDataStatus"]="derived"
            if iv(x.get("chartScore")) in [0,50]: x["chartScore"]=52
            x["chartSummary"]="정식 OHLCV 차트 수집은 실패했지만 현재가가 확인되어 차트 항목을 대체산출 상태로 보정했습니다."
            summary["chartDerived"]+=1

        ss=str(x.get("supplyDataStatus") or x.get("supplyStatus") or "")
        if ss in ["partial","부분수집"] or "naver_broker_foreign_estimate" in str(x.get("supplySource","")):
            x["supplyDataStatus"]="derived"; x["supplyStatus"]="derived"
            x["supplyScore"]=supply_score(x,"derived")
            x["supplyReason"]="KRX 투자자별 수급 원자료가 부족하여 네이버 외국계추정합/부분 수급 신호를 대체 반영했습니다."
            x["supplyOpinion"]=x["supplyReason"]
            summary["supplyDerived"]+=1

        old_macro=iv(x.get("macroScore"))
        x["macroScore"]=macro_score(x)
        if old_macro != x["macroScore"]: summary["macroRepaired"]+=1

        if stale:
            x["source"]="a428_runtime_repaired_from_a418"
        x["targetEngineVersion"]="A428"
        x["updatedAt"]=summary["updatedAt"]
        x["dataConnectionScore"]=data_score(x)
        x["dataConnectionReason"]=f"A428 데이터 보정 적용: 차트={x.get('chartDataStatus')}, 수급={x.get('supplyDataStatus')}, 연결점수={x.get('dataConnectionScore')}점입니다."
        x["score"]=final_score(x); x["realtimeScore"]=x["score"]

    if isinstance(raw,list): save(p,items)
    else:
        raw[key if key!="none" else "candidates"]=items; save(p,raw)
    summary["files"].append(str(p))

OUT.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(summary,ensure_ascii=False,indent=2))
