import json
from pathlib import Path
from datetime import datetime

DATA=Path("data")
CAND=DATA/"stock_candidates_ai_scored.json"
SUMMARY=DATA/"market_scanner_summary.json"
OUT=DATA/"stable_invalid_price_ux_a255.json"

def load(p,d):
    try:return json.loads(p.read_text(encoding="utf-8")) if p.exists() else d
    except Exception:return d
def save(p,x):
    p.parent.mkdir(exist_ok=True); p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding="utf-8")
def norm(x):
    if isinstance(x,list): return x
    if isinstance(x,dict):
        for k in ["candidates","data","items","stocks","top"]:
            if isinstance(x.get(k),list): return x[k]
    return []

run=datetime.now().isoformat(timespec="seconds")
cands=norm(load(CAND,[]))
invalid=normal=0
details=[]
for c in cands:
    if not isinstance(c,dict): continue
    status=str(c.get("priceValidationStatus") or "")
    name=str(c.get("name") or "")
    code=str(c.get("code") or "").zfill(6)
    if status=="검증필요":
        invalid+=1
        c["invalidPriceUxMessage"]="가격 검증 필요: 현재가/목표가/손절선은 검증 후 사용"
        c["reportTargetReason"]=c.get("reportTargetReason") or f"{name} 가격 검증 필요. 최신 가격 확인 후 다시 산출합니다."
        c["chartStopReason"]=c.get("chartStopReason") or "현재가 검증 실패로 차트 손절선 미산출."
        c["stopGuideReason"]=c.get("stopGuideReason") or "가격 검증 필요 상태입니다."
    else:
        normal+=1
        if not status:
            c["priceValidationStatus"]="정상"
        c["invalidPriceUxMessage"]=""
    c["targetEngineVersion"]="A255-FIX2"
    c["updatedAt"]=run
    details.append({"code":code,"name":name,"priceValidationStatus":c.get("priceValidationStatus",""),"invalidPriceUxMessage":c.get("invalidPriceUxMessage","")})
save(CAND,cands)
summary=load(SUMMARY,{})
if not isinstance(summary,dict): summary={}
summary.update({"version":"A255-FIX2","generatedAt":run,"status":"stable_invalid_price_ux","candidateCount":len(cands),"invalidPriceCandidateCount":invalid,"normalCandidateCount":normal,"output":"stock_candidates_ai_scored.json"})
save(SUMMARY,summary)
save(OUT,{"version":"A255-FIX2","generatedAt":run,"summary":summary,"details":details})
print(json.dumps(summary,ensure_ascii=False,indent=2))
