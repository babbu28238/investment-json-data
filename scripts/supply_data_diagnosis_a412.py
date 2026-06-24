import json
from pathlib import Path
from datetime import datetime

DATA=Path("data")
SRC=DATA/"realtime_recommendations_a405.json"
OUT=DATA/"realtime_recommendations_a405.json"
CAND=DATA/"stock_candidates_ai_scored.json"
SUMMARY=DATA/"market_scanner_summary.json"
DEBUG=DATA/"supply_data_diagnosis_a412.json"

def load(p,d):
    try: return json.loads(p.read_text(encoding="utf-8")) if p.exists() else d
    except Exception: return d
def save(p,d):
    p.parent.mkdir(exist_ok=True); p.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding="utf-8")
def norm(x):
    if isinstance(x,list): return x
    if isinstance(x,dict):
        for k in ["candidates","data","items","stocks","top"]:
            if isinstance(x.get(k),list): return x[k]
    return []
def si(x):
    try: return int(float(str(x).replace(",","")))
    except Exception: return 0

def main():
    run=datetime.now().isoformat(timespec="seconds")
    data=norm(load(SRC,[]))
    real=neutral=missing=0
    rows=[]
    for c in data:
        if not isinstance(c,dict): continue
        vals=[si(c.get(k)) for k in ["foreignScore","institutionScore","pensionScore","foreignNetBuyScore","institutionNetBuyScore"] if si(c.get(k))>0]
        if vals:
            score=round(sum(vals)/len(vals))
            c["supplyScore"]=score
            c["supplyOpinion"]=f"외국인/기관/연기금 수급 원자료 {vals}를 반영해 수급 점수 {score}점으로 평가했습니다."
            status="real"
            real+=1
        else:
            c["supplyScore"]=si(c.get("supplyScore")) or 50
            c["supplyOpinion"]="수급 원자료가 아직 충분하지 않아 중립 50점으로 처리했습니다."
            status="neutral"
            neutral+=1
        rows.append({"code":c.get("code"),"name":c.get("name"),"status":status,"supplyScore":c.get("supplyScore"),"supplyOpinion":c.get("supplyOpinion")})
        c["updatedAt"]=run
        c["targetEngineVersion"]="A412"
    save(OUT,data); save(CAND,data)
    summary=load(SUMMARY,{})
    if not isinstance(summary,dict): summary={}
    summary.update({"version":"A412","generatedAt":run,"status":"supply_data_diagnosis","candidateCount":len(data),"realSupplyCount":real,"neutralSupplyCount":neutral,"output":"supply_data_diagnosis_a412.json"})
    save(SUMMARY,summary)
    save(DEBUG,{"summary":summary,"items":rows})
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
