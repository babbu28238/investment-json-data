# scripts/strict_real_data_a429.py
# 실제 원자료 connected와 derived/partial을 엄격히 분리한다.
import json
from pathlib import Path
from datetime import datetime

DATA = Path("data")
FILES = [DATA/"realtime_recommendations_a405.json", DATA/"stock_candidates_ai_scored.json"]
OUT = DATA/"strict_real_data_status_a429.json"

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

def real(status):
    return str(status) in ["connected","연결"]

def display(status):
    s=str(status or "")
    if s in ["connected","연결"]: return "연결"
    if s=="derived": return "실데이터 미연결"
    if s in ["partial","부분","부분수집"]: return "부분"
    if s in ["failed","실패"]: return "실패"
    if s in ["missing","없음"]: return "없음"
    return "실데이터 미연결"

def score(x):
    total=0
    for k in ["priceDataStatus","newsDataStatus","reportDataStatus","chartDataStatus","supplyDataStatus","macroDataStatus"]:
        s=str(x.get(k,""))
        if s=="connected": total+=17
        elif s=="partial": total+=8
        elif s=="derived": total+=4
        elif s=="missing": total+=2
    return max(0,min(100,total))

def stale(x):
    blob=" ".join(str(x.get(k,"")) for k in ["source","targetSource","targetEngineVersion"])
    return "a418" in blob.lower() or "real_data_all_connector_a418" in blob.lower()

summary={"version":"A429","updatedAt":datetime.now().isoformat(timespec="seconds"),"files":[],"total":0,"chartRealConnected":0,"supplyRealConnected":0,"chartNotReal":0,"supplyNotReal":0,"a418Stale":0}
for p in FILES:
    raw=load(p); items,key=arr(raw)
    if not items: continue
    for x in items:
        summary["total"]+=1
        chart_real=real(x.get("chartDataStatus"))
        supply_real=real(x.get("supplyDataStatus")) or real(x.get("supplyStatus"))
        if chart_real: summary["chartRealConnected"]+=1
        else: summary["chartNotReal"]+=1
        if supply_real: summary["supplyRealConnected"]+=1
        else: summary["supplyNotReal"]+=1
        if stale(x): summary["a418Stale"]+=1
        x["strictRealDataStatus"]={
            "price": display(x.get("priceDataStatus")),
            "news": display(x.get("newsDataStatus")),
            "report": display(x.get("reportDataStatus")),
            "chart": display(x.get("chartDataStatus")),
            "supply": display(x.get("supplyDataStatus") or x.get("supplyStatus")),
            "macro": display(x.get("macroDataStatus")),
            "chartRealConnected": chart_real,
            "supplyRealConnected": supply_real
        }
        x["dataConnectionScore"]=score(x)
        x["dataConnectionReason"]=(
            f"실제 원자료 기준: 차트={x['strictRealDataStatus']['chart']}, "
            f"수급={x['strictRealDataStatus']['supply']}. "
            f"derived/대체산출은 실제 원자료 연결이 아니며 참고용입니다. "
            f"실제 원자료 기준 연결점수 {x['dataConnectionScore']}점입니다."
        )
        x["targetEngineVersion"]="A429"
        x["updatedAt"]=summary["updatedAt"]
    if isinstance(raw,list): save(p,items)
    else:
        raw[key if key!="none" else "candidates"]=items; save(p,raw)
    summary["files"].append(str(p))
OUT.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(summary,ensure_ascii=False,indent=2))
