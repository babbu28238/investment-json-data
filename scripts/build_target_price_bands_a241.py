import json, re, statistics
from pathlib import Path
from datetime import datetime

DATA=Path("data")
CANDIDATES=DATA/"stock_candidates_ai_scored.json"
SUMMARY=DATA/"market_scanner_summary.json"
OUT=DATA/"target_price_bands_a241.json"
SCAN_PATTERNS=["*report*.json","*reports*.json","*research*.json","*target*.json","news_data.json","news_signals.json","stock_candidates_ai_scored.json"]
PATS=[
 re.compile(r"(?:목표주가|목표가|TP|target price)[^0-9]{0,20}([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,7})",re.I),
 re.compile(r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,7})\s*원[^\n]{0,15}(?:목표주가|목표가)",re.I)
]
def load(p,d):
    try: return json.loads(p.read_text(encoding="utf-8")) if p.exists() else d
    except Exception: return d
def save(p,x):
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding="utf-8")
def norm(raw):
    if isinstance(raw,list): return raw
    if isinstance(raw,dict):
        for k in ["candidates","data","items","stocks","top"]:
            if isinstance(raw.get(k),list): return raw[k]
    return []
def si(v,d=0):
    try: return int(float(str(v).replace(",","").replace("원","").strip()))
    except Exception: return d
def rp(v): return int(round(v/100.0)*100) if v>0 else 0
def extract(txt):
    out=[]
    for pat in PATS:
        for m in pat.findall(txt):
            p=si(m)
            if 1000<=p<=3000000: out.append(p)
    return out
def texts():
    seen=set(); out=[]
    for pattern in SCAN_PATTERNS:
        for p in DATA.glob(pattern):
            if p in seen or not p.exists(): continue
            seen.add(p)
            try: out.append((p.name,p.read_text(encoding="utf-8")))
            except Exception: pass
    return out
def aliases(c):
    code=str(c.get("code") or c.get("stockCode") or c.get("ticker") or "").zfill(6)
    name=str(c.get("name") or "")
    arr={code,name,name.replace(" ","")}
    if name.endswith("지주"): arr.add(name.replace("지주",""))
    return [x for x in arr if x]
run=datetime.now().isoformat(timespec="seconds")
cands=norm(load(CANDIDATES,[]))
tx=texts(); details=[]; updated=0
for c in cands:
    if not isinstance(c,dict): continue
    code=str(c.get("code") or c.get("stockCode") or c.get("ticker") or "").zfill(6)
    name=str(c.get("name") or "")
    found=[]; sources=[]
    for k in ["targetPrice","target","목표가","목표주가"]:
        p=si(c.get(k))
        if 1000<=p<=3000000:
            found.append(p); sources.append({"source":"candidate_field","price":p,"snippet":str(c.get(k))[:120]})
    for fname,txt in tx:
        if not any(a and a in txt for a in aliases(c)): continue
        for a in aliases(c):
            start=0
            while a:
                idx=txt.find(a,start)
                if idx==-1: break
                sn=txt[max(0,idx-300):idx+700]
                for p in extract(sn):
                    found.append(p); sources.append({"source":fname,"price":p,"snippet":sn[:220]})
                start=idx+len(a)
    uniq=[]
    for p in found:
        if p not in uniq: uniq.append(p)
    if uniq:
        med=int(statistics.median(uniq))
        realistic=rp(med*0.80); observe=rp(med*0.70); stop=rp(med*0.60)
        c["targetMedianPrice"]=med
        c["realisticTargetPrice"]=realistic
        c["observeTimingPrice"]=observe
        c["stopTimingPrice"]=stop
        c["reportTargetCount"]=len(uniq)
        c["reportTargetPricesText"]=", ".join(f"{p:,}원" for p in sorted(uniq))
        c["reportTargetReason"]=f"리포트 목표주가 {len(uniq)}건 중앙값 {med:,}원 기준: 현실목표 {realistic:,}원(80%), 관찰 {observe:,}원(70%), 손절 {stop:,}원(60%)."
        c["targetEngineVersion"]="A241"; c["updatedAt"]=run; updated+=1
        details.append({"code":code,"name":name,"prices":sorted(uniq),"median":med,"realisticTargetPrice":realistic,"observeTimingPrice":observe,"stopTimingPrice":stop,"sources":sources[:10]})
    else:
        c["targetEngineVersion"]="A241"
        details.append({"code":code,"name":name,"prices":[],"median":0,"message":"목표주가 추출 없음"})
cands=[x for x in cands if isinstance(x,dict)]
cands.sort(key=lambda x:int(x.get("score",0)), reverse=True)
save(CANDIDATES,cands)
summ=load(SUMMARY,{})
if not isinstance(summ,dict): summ={}
summ.update({"version":"A241","generatedAt":run,"status":"target_price_bands","candidateCount":len(cands),"targetPriceCandidateCount":updated,"output":"stock_candidates_ai_scored.json"})
save(SUMMARY,summ); save(OUT,{"version":"A241","generatedAt":run,"summary":summ,"details":details})
print(json.dumps(summ,ensure_ascii=False,indent=2))
