import json,re,statistics,time
from pathlib import Path
from datetime import datetime
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup

DATA=Path("data")
CAND=DATA/"stock_candidates_ai_scored.json"; SUM=DATA/"market_scanner_summary.json"
OUT=DATA/"target_price_bands_a244.json"; RAW=DATA/"report_target_prices_a244.json"
HEAD={"User-Agent":"Mozilla/5.0","Referer":"https://search.naver.com/"}

FALLBACK=[
("042660","한화오션","KOSPI","조선/방산",91,128700),
("329180","HD현대중공업","KOSPI","조선",90,300000),
("034020","두산에너빌리티","KOSPI","원전/에너지",89,105250),
("272210","한화시스템","KOSPI","방산",88,132671),
("005930","삼성전자","KOSPI","반도체",87,297500),
("000660","SK하이닉스","KOSPI","반도체",86,220000),
("047810","한국항공우주","KOSPI","방산",84,70000),
("241560","두산밥캣","KOSPI","기계",82,55000),
("005380","현대차","KOSPI","자동차",82,250000),
("000270","기아","KOSPI","자동차",81,115000),
("105560","KB금융","KOSPI","금융",80,172000),
("055550","신한지주","KOSPI","금융",79,60000),
("086790","하나금융지주","KOSPI","금융",79,70000),
("316140","우리금융지주","KOSPI","금융",78,16000),
("035420","NAVER","KOSPI","인터넷",78,220000),
("035720","카카오","KOSPI","인터넷",76,55000),
("033780","KT&G","KOSPI","방어주",76,110000),
("011200","HMM","KOSPI","해운",75,22000),
("008770","호텔신라","KOSPI","소비/여행",74,50000),
("108490","로보티즈","KOSDAQ","로봇",74,45000),
("277810","레인보우로보틱스","KOSDAQ","로봇",73,170000),
("247540","에코프로비엠","KOSDAQ","2차전지",72,130000),
("086520","에코프로","KOSDAQ","2차전지",71,70000),
("196170","알테오젠","KOSDAQ","바이오",71,300000),
("039030","이오테크닉스","KOSDAQ","반도체장비",70,180000),
]
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
def valid(arr):
    out=[]
    for x in arr:
        if isinstance(x,dict):
            code=str(x.get("code") or x.get("stockCode") or x.get("ticker") or "").zfill(6)
            name=str(x.get("name") or "")
            if code and code!="000000" and name:
                y=dict(x); y["code"]=code; y["name"]=name; out.append(y)
    return out
def fallback():
    return [{"code":c,"name":n,"market":m,"sector":s,"score":sc,"currentPrice":p,"close":p,
             "reason":f"{n} 기본 후보. 목표가 수집용 fallback."} for c,n,m,s,sc,p in FALLBACK]
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
    rows=[]; errs=[]
    queries=[f"{name} 목표주가",f"{name} 리포트 목표주가",f"{name} 증권사 목표가",f"{name} 컨센서스 목표주가"]
    for q in queries:
        try:
            html=requests.get(f"https://search.naver.com/search.naver?where=news&query={quote(q)}&sort=1",headers=HEAD,timeout=15).text
            soup=BeautifulSoup(html,"html.parser")
            txt=soup.get_text(" ",strip=True)[:10000]
            for p in extract(txt):
                rows.append({"code":code,"name":name,"query":q,"price":p,"source":"naver_search","snippet":txt[:300]})
        except Exception as e:
            errs.append({"query":q,"error":str(e)[:200]})
        time.sleep(.15)
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
raw=norm(load(CAND,[])); cands=valid(raw)
source="stock_candidates_ai_scored.json"
if not cands:
    cands=fallback(); source="built_in_fallback_top25"
details=[]; raw_rows=[]; updated=0
for c in cands:
    code=str(c.get("code")).zfill(6); name=str(c.get("name"))
    rows=existing(c); srch,errs=collect(name,code); rows+=srch; raw_rows+=rows
    prices=[]
    for r in rows:
        p=si(r.get("price"))
        if 1000<=p<=3000000 and p not in prices: prices.append(p)
    if prices:
        med=int(statistics.median(prices)); real=rp(med*.8); obs=rp(med*.7); stop=rp(med*.6)
        c["targetMedianPrice"]=med; c["realisticTargetPrice"]=real; c["observeTimingPrice"]=obs; c["stopTimingPrice"]=stop
        c["reportTargetCount"]=len(prices); c["reportTargetPricesText"]=", ".join(f"{p:,}원" for p in sorted(prices))
        c["reportTargetReason"]=f"리포트/검색 목표주가 {len(prices)}건 중앙값 {med:,}원 기준: 현실목표 {real:,}원(80%), 관찰 {obs:,}원(70%), 손절 {stop:,}원(60%)."
        updated+=1
    c["targetEngineVersion"]="A244"; c["updatedAt"]=run
    details.append({"code":code,"name":name,"prices":sorted(prices),"median":c.get("targetMedianPrice",0),"realisticTargetPrice":c.get("realisticTargetPrice",0),"observeTimingPrice":c.get("observeTimingPrice",0),"stopTimingPrice":c.get("stopTimingPrice",0),"errors":errs,"sources":rows[:10]})
cands.sort(key=lambda x:int(x.get("score",0)), reverse=True)
save(CAND,cands)
summ=load(SUM,{})
if not isinstance(summ,dict): summ={}
summ.update({"version":"A244","generatedAt":run,"status":"target_fallback_candidates","candidateCount":len(cands),"candidateSource":source,"targetPriceCandidateCount":updated,"rawTargetRows":len(raw_rows),"output":"stock_candidates_ai_scored.json"})
save(SUM,summ); save(OUT,{"version":"A244","generatedAt":run,"summary":summ,"details":details}); save(RAW,{"version":"A244","generatedAt":run,"rows":raw_rows[:500]})
print(json.dumps(summ,ensure_ascii=False,indent=2))
