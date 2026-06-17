import json, statistics
from pathlib import Path
from datetime import datetime

DATA=Path("data")
CAND=DATA/"stock_candidates_ai_scored.json"
SUMMARY=DATA/"market_scanner_summary.json"
A244=DATA/"target_price_bands_a244.json"
OUT=DATA/"target_price_bands_a245.json"
AUDIT=DATA/"target_price_clean_audit_a245.json"

FALLBACK_PRICE={
"042660":128700,"329180":300000,"034020":105250,"272210":132671,"005930":297500,
"000660":220000,"047810":70000,"241560":55000,"005380":250000,"000270":115000,
"105560":172000,"055550":60000,"086790":70000,"316140":16000,"035420":220000,
"035720":55000,"033780":110000,"011200":22000,"008770":50000,"108490":45000,
"277810":170000,"247540":130000,"086520":70000,"196170":300000,"039030":180000
}

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
def current(c):
    code=str(c.get("code") or c.get("stockCode") or c.get("ticker") or "").zfill(6)
    for k in ["currentPrice","close","price","lastPrice"]:
        p=si(c.get(k))
        if p>0:return p
    return FALLBACK_PRICE.get(code,0)
def detail_map():
    raw=load(A244,{})
    details=raw.get("details",[]) if isinstance(raw,dict) else []
    return {str(d.get("code","")).zfill(6):d for d in details if isinstance(d,dict)}
def reject_reason(p,cur):
    if p in [2024,2025,2026,2027]: return "연도 숫자 제거"
    if p<10000: return "1만원 미만 잡음 제거"
    if cur>0 and p<cur*0.5: return f"현재가 대비 과도하게 낮음({p:,} < {cur*0.5:,.0f})"
    if cur>0 and p>cur*2.5: return f"현재가 대비 과도하게 높음({p:,} > {cur*2.5:,.0f})"
    return ""
def clean(prices,cur):
    ok=[]; bad=[]
    for p in prices:
        p=si(p)
        if p<=0: continue
        why=reject_reason(p,cur)
        if why: bad.append({"price":p,"reason":why})
        elif p not in ok: ok.append(p)
    return ok,bad

run=datetime.now().isoformat(timespec="seconds")
cands=norm(load(CAND,[]))
mp=detail_map()
cleaned=0; reliable=0; details=[]
for c in cands:
    if not isinstance(c,dict): continue
    code=str(c.get("code") or c.get("stockCode") or c.get("ticker") or "").zfill(6)
    name=str(c.get("name") or "")
    cur=current(c)
    raw=[]
    if code in mp: raw += mp[code].get("prices",[]) or []
    txt=str(c.get("reportTargetPricesText","") or "")
    for part in txt.replace("원","").split(","):
        p=si(part)
        if p>0: raw.append(p)
    raw_unique=[]
    for p in raw:
        p=si(p)
        if p>0 and p not in raw_unique: raw_unique.append(p)
    accepted,rejected=clean(raw_unique,cur)
    if accepted:
        med=int(statistics.median(accepted))
        c["targetMedianPrice"]=med
        c["realisticTargetPrice"]=rp(med*.80)
        c["observeTimingPrice"]=rp(med*.70)
        c["stopTimingPrice"]=rp(med*.60)
        c["reportTargetCount"]=len(accepted)
        c["reportTargetPricesText"]=", ".join(f"{p:,}원" for p in sorted(accepted))
        c["reportTargetReason"]=f"정제 목표주가 {len(accepted)}건 중앙값 {med:,}원 기준: 현실목표 {c['realisticTargetPrice']:,}원(80%), 관찰 {c['observeTimingPrice']:,}원(70%), 손절 {c['stopTimingPrice']:,}원(60%)."
        cleaned+=1
        if len(accepted)>=2: reliable+=1
    else:
        c["targetMedianPrice"]=0;c["realisticTargetPrice"]=0;c["observeTimingPrice"]=0;c["stopTimingPrice"]=0
        c["reportTargetCount"]=0;c["reportTargetPricesText"]=""
        c["reportTargetReason"]="정제 후 유효 목표주가 없음."
    c["targetEngineVersion"]="A245"; c["updatedAt"]=run
    details.append({"code":code,"name":name,"currentPrice":cur,"rawPrices":sorted(raw_unique),"acceptedPrices":sorted(accepted),"rejected":rejected,"median":c.get("targetMedianPrice",0),"realisticTargetPrice":c.get("realisticTargetPrice",0),"observeTimingPrice":c.get("observeTimingPrice",0),"stopTimingPrice":c.get("stopTimingPrice",0),"targetCount":c.get("reportTargetCount",0)})
cands=[x for x in cands if isinstance(x,dict)]
cands.sort(key=lambda x:int(x.get("score",0)),reverse=True)
save(CAND,cands)
summ=load(SUMMARY,{})
if not isinstance(summ,dict):summ={}
summ.update({"version":"A245","generatedAt":run,"status":"target_clean_filter","candidateCount":len(cands),"targetPriceCandidateCount":cleaned,"reliableTargetCandidateCount":reliable,"filterRule":"currentPrice*0.5 <= target <= currentPrice*2.5, remove years and below 10000","source":"target_price_bands_a244","output":"stock_candidates_ai_scored.json"})
save(SUMMARY,summ); save(OUT,{"version":"A245","generatedAt":run,"summary":summ,"details":details}); save(AUDIT,{"version":"A245","generatedAt":run,"details":details})
print(json.dumps(summ,ensure_ascii=False,indent=2))
