import json,re,statistics,time
from pathlib import Path
from datetime import datetime
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup
DATA=Path("data")
CAND=DATA/"stock_candidates_ai_scored.json"; SUM=DATA/"market_scanner_summary.json"
OUT=DATA/"target_price_bands_a243.json"; RAW=DATA/"report_target_prices_a243.json"
HEAD={"User-Agent":"Mozilla/5.0","Referer":"https://search.naver.com/"}
PATS=[re.compile(r"(?:목표주가|목표가|TP|target)[^0-9]{0,35}([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,7})",re.I),
      re.compile(r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,7})\s*원[^\n]{0,30}(?:목표주가|목표가|TP)",re.I)]
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
def rp(v):return int(round(v/100.0)*100) if v>0 else 0
def extract(txt):
    out=[]
    for pat in PATS:
        for m in pat.findall(txt):
            p=si(m)
            if 1000<=p<=3000000: out.append(p)
    return out
def collect(name,code):
    rows=[];errs=[]
    for q in [f"{name} 목표주가",f"{name} 리포트 목표주가",f"{name} 증권사 목표가"]:
        try:
            html=requests.get(f"https://search.naver.com/search.naver?where=news&query={quote(q)}&sort=1",headers=HEAD,timeout=15).text
            soup=BeautifulSoup(html,"html.parser")
            txt=soup.get_text(" ",strip=True)[:8000]
            for p in extract(txt):
                rows.append({"code":code,"name":name,"query":q,"price":p,"source":"naver_search","snippet":txt[:250]})
        except Exception as e: errs.append({"query":q,"error":str(e)[:200]})
        time.sleep(.2)
    return rows,errs
def existing(c):
    rows=[]
    for k in ["targetPrice","target","목표가","목표주가","consensusTargetPrice","reportTargetPrice","target_price","medianTargetPrice"]:
        p=si(c.get(k))
        if 1000<=p<=3000000: rows.append({"price":p,"source":"candidate_field","snippet":str(c.get(k))[:100]})
    for k in ["reason","detailReport","reasonDetail","newsReason","fundamentalReason","reportTargetReason"]:
        txt=str(c.get(k) or "")
        for p in extract(txt): rows.append({"price":p,"source":k,"snippet":txt[:200]})
    return rows
run=datetime.now().isoformat(timespec="seconds")
cands=norm(load(CAND,[])); details=[]; raw=[]; updated=0
for c in cands:
    if not isinstance(c,dict):continue
    code=str(c.get("code") or c.get("stockCode") or c.get("ticker") or "").zfill(6); name=str(c.get("name") or "")
    if not code or code=="000000" or not name:continue
    rows=existing(c); srch,errs=collect(name,code); rows+=srch; raw+=rows
    prices=[]
    for r in rows:
        p=si(r.get("price"))
        if 1000<=p<=3000000 and p not in prices:prices.append(p)
    if prices:
        med=int(statistics.median(prices)); real=rp(med*.8); obs=rp(med*.7); stop=rp(med*.6)
        c["targetMedianPrice"]=med; c["realisticTargetPrice"]=real; c["observeTimingPrice"]=obs; c["stopTimingPrice"]=stop
        c["reportTargetCount"]=len(prices); c["reportTargetPricesText"]=", ".join(f"{p:,}원" for p in sorted(prices))
        c["reportTargetReason"]=f"리포트/검색 목표주가 {len(prices)}건 중앙값 {med:,}원 기준: 현실목표 {real:,}원(80%), 관찰 {obs:,}원(70%), 손절 {stop:,}원(60%)."
        updated+=1
    c["targetEngineVersion"]="A243"; c["updatedAt"]=run
    details.append({"code":code,"name":name,"prices":sorted(prices),"median":c.get("targetMedianPrice",0),"realisticTargetPrice":c.get("realisticTargetPrice",0),"observeTimingPrice":c.get("observeTimingPrice",0),"stopTimingPrice":c.get("stopTimingPrice",0),"errors":errs,"sources":rows[:10]})
cands=[x for x in cands if isinstance(x,dict)]; cands.sort(key=lambda x:int(x.get("score",0)),reverse=True)
save(CAND,cands)
summ=load(SUM,{})
if not isinstance(summ,dict):summ={}
summ.update({"version":"A243","generatedAt":run,"status":"report_target_collector","candidateCount":len(cands),"targetPriceCandidateCount":updated,"rawTargetRows":len(raw),"output":"stock_candidates_ai_scored.json"})
save(SUM,summ); save(OUT,{"version":"A243","generatedAt":run,"summary":summ,"details":details}); save(RAW,{"version":"A243","generatedAt":run,"rows":raw[:500]})
print(json.dumps(summ,ensure_ascii=False,indent=2))
