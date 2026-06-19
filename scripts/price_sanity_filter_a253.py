import json
from pathlib import Path
from datetime import datetime
DATA=Path("data")
CAND=DATA/"stock_candidates_ai_scored.json"
SUMMARY=DATA/"market_scanner_summary.json"
OUT=DATA/"price_sanity_a253.json"
RANGES={"005930":(30000,150000),"000660":(50000,500000),"042660":(30000,300000),"272210":(20000,250000),"329180":(100000,700000),"034020":(30000,250000),"005380":(100000,500000),"000270":(50000,250000),"105560":(50000,300000),"035420":(100000,500000),"035720":(20000,150000),"108490":(10000,200000)}
def load(p,d):
    try:return json.loads(p.read_text(encoding="utf-8")) if p.exists() else d
    except Exception:return d
def save(p,x):
    p.parent.mkdir(exist_ok=True); p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding="utf-8")
def norm(x):
    if isinstance(x,list):return x
    if isinstance(x,dict):
        for k in ["candidates","data","items","stocks","top"]:
            if isinstance(x.get(k),list):return x[k]
    return []
def si(v,d=0):
    try:return int(float(str(v).replace(",","").replace("원","").strip()))
    except Exception:return d
def rp(v):
    if v<=0:return 0
    unit=500 if v>=100000 else 100 if v>=10000 else 10
    return int(round(v/unit)*unit)
def in_range(code,p):
    lo,hi=RANGES.get(code,(1000,3000000))
    return lo<=p<=hi
def target_ok(p,t):
    if t<=0:return True
    if p<=0:return False
    return p*0.5<=t<=p*3.0
run=datetime.now().isoformat(timespec="seconds")
cands=norm(load(CAND,[]))
details=[]; valid_price=valid_target=price_fixed=target_fixed=0
for c in cands:
    if not isinstance(c,dict):continue
    code=str(c.get("code") or c.get("stockCode") or c.get("ticker") or "").zfill(6)
    name=str(c.get("name") or "")
    price=si(c.get("currentPrice")) or si(c.get("close"))
    target=si(c.get("targetMedianPrice"))
    issues=[]
    if price>0 and not in_range(code,price):
        issues.append(f"현재가 범위 이상: {price:,}원")
        c["priceValidationStatus"]="검증필요"; c["priceValidationReason"]=f"{name} 현재가 {price:,}원은 종목별 정상 범위를 벗어나 검증 필요."
        c["currentPrice"]=0; c["close"]=0; price=0; price_fixed+=1
    elif price>0:
        c["priceValidationStatus"]="정상"; c["priceValidationReason"]=f"{name} 현재가 {price:,}원은 검증 범위 내."; valid_price+=1
    if target>0 and not target_ok(price,target):
        issues.append(f"목표가 비율 이상: {target:,}원")
        c["targetMedianPrice"]=0;c["realisticTargetPrice"]=0;c["observeTimingPrice"]=0;c["stopTimingPrice"]=0;c["targetUpsidePercent"]=0.0
        c["reportTargetCount"]=0;c["reportTargetPricesText"]="";c["reportTargetReason"]=f"{name} 목표가는 현재가 대비 비정상 범위로 검증 제외."
        target_fixed+=1
    elif target>0:
        valid_target+=1
    if price>0:
        c["chartStopPrice"]=rp(price*0.92); c["chartStopReason"]=f"차트 기준 손절선: 검증 현재가 {price:,}원 기준 약 -8% 구간 {c['chartStopPrice']:,}원."
    c["targetEngineVersion"]="A253"; c["updatedAt"]=run
    details.append({"code":code,"name":name,"priceAfter":si(c.get("currentPrice")) or si(c.get("close")),"targetAfter":si(c.get("targetMedianPrice")),"status":c.get("priceValidationStatus",""),"issues":issues})
save(CAND,cands)
summary=load(SUMMARY,{})
if not isinstance(summary,dict):summary={}
summary.update({"version":"A253","generatedAt":run,"status":"price_sanity_filter","candidateCount":len(cands),"validPriceCount":valid_price,"validTargetCount":valid_target,"priceFixedCount":price_fixed,"targetFixedCount":target_fixed,"output":"stock_candidates_ai_scored.json"})
save(SUMMARY,summary); save(OUT,{"version":"A253","generatedAt":run,"summary":summary,"details":details})
print(json.dumps(summary,ensure_ascii=False,indent=2))
