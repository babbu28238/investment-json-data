import json
from pathlib import Path
from datetime import datetime
DATA=Path("data"); DATA.mkdir(exist_ok=True)
FILES=[DATA/"realtime_recommendations_a405.json",DATA/"stock_candidates_ai_scored.json"]
OUT=DATA/"data_source_audit_a427.json"
def load(p):
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return []
def save(p,d): p.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding="utf-8")
def arr(raw):
    if isinstance(raw,list): return raw,"list"
    if isinstance(raw,dict):
        for k in ["candidates","data","items","stocks","top"]:
            if isinstance(raw.get(k),list): return raw[k],k
    return [],"none"
def iv(v):
    try: return int(float(v or 0))
    except Exception: return 0
def stale(x):
    blob=" ".join(str(x.get(k,"")) for k in ["source","targetSource","targetEngineVersion"])
    return "a418" in blob.lower() or "real_data_all_connector_a418" in blob.lower()
def supply(x):
    old=iv(x.get("supplyScore"))
    if old not in (0,50): return old
    f=iv(x.get("foreignNetBuy")); i=iv(x.get("institutionNetBuy")); p=iv(x.get("pensionNetBuy"))
    if f>0 and i>0: return 86
    if f>0 or i>0 or p>0: return 68
    if f<0 and i<0: return 28
    if f<0 or i<0 or p<0: return 38
    if str(x.get("supplyDataStatus") or x.get("supplyStatus") or "") in ["partial","부분수집"]: return 55
    return 50
def macro(x):
    old=iv(x.get("macroScore"))
    if old not in (0,50): return old
    adj=iv(x.get("macroAdjustmentScore")); reasons=x.get("macroReasons") or []
    if adj>=8: return 72
    if adj>=4: return 64
    if adj<=-8: return 28
    if adj<=-4: return 36
    if reasons: return 58
    return 50
def final(x):
    q=iv(x.get("quantScore") or x.get("priceScore") or 50); s=iv(x.get("supplyScore") or 50)
    c=iv(x.get("companyScore") or x.get("reportScore") or 50); e=iv(x.get("eventScore") or x.get("newsScore") or 50)
    r=iv(x.get("reportScore") or 50); ch=iv(x.get("chartScore") or 50); m=iv(x.get("macroScore") or 50); risk=iv(x.get("riskScore") or 50); adj=iv(x.get("macroAdjustmentScore") or 0)
    return max(0,min(100,round(q*.18+s*.18+c*.18+e*.14+r*.10+ch*.10+m*.07+risk*.05+adj)))
summary={"version":"A427","updatedAt":datetime.now().isoformat(timespec="seconds"),"files":[],"total":0,"a418StaleCount":0,"chartFailedCount":0,"supplyPartialCount":0,"supplyFailedCount":0,"supplyChanged":0,"macroChanged":0}
for p in FILES:
    raw=load(p); items,key=arr(raw)
    if not items: continue
    for x in items:
        summary["total"]+=1
        if stale(x): summary["a418StaleCount"]+=1
        if str(x.get("chartDataStatus",""))=="failed": summary["chartFailedCount"]+=1
        if str(x.get("supplyDataStatus",""))=="partial" or str(x.get("supplyStatus","")) in ["partial","부분수집"]: summary["supplyPartialCount"]+=1
        if str(x.get("supplyDataStatus",""))=="failed" or str(x.get("supplyStatus","")) in ["failed","수집실패"]: summary["supplyFailedCount"]+=1
        os=iv(x.get("supplyScore")); om=iv(x.get("macroScore"))
        ns=supply(x); nm=macro(x); x["supplyScore"]=ns; x["macroScore"]=nm
        if os!=ns: summary["supplyChanged"]+=1
        if om!=nm: summary["macroChanged"]+=1
        x["supplyOpinion"]="외국인·기관·연기금 수급 원자료가 충분하지 않아 중립 50점으로 유지했습니다." if ns==50 else f"수급 신호를 반영해 수급 점수를 {ns}점으로 보정했습니다."
        x["macroOpinion"]="종목 업종과 직접 연결되는 매크로 요인이 부족해 중립 50점으로 유지했습니다." if nm==50 else f"매크로 요인을 반영해 매크로 점수를 {nm}점으로 보정했습니다."
        x["score"]=final(x); x["realtimeScore"]=x["score"]; x["targetEngineVersion"]="A427"; x["updatedAt"]=summary["updatedAt"]
        if stale(x): x["source"]="a427_repaired_from_a418_stale"
    if isinstance(raw,list): save(p,items)
    else:
        raw[key if key!="none" else "candidates"]=items; save(p,raw)
    summary["files"].append(str(p))
OUT.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(summary,ensure_ascii=False,indent=2))
