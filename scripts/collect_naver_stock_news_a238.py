# scripts/collect_naver_stock_news_a238.py
# HSinvest A238 NAVER STOCK NEWS
# search.naver.com 검색 뉴스가 0이면 finance.naver.com 종목별 뉴스 페이지를 직접 파싱한다.

import json, time
from pathlib import Path
from datetime import datetime
from io import StringIO

import pandas as pd
import requests
from bs4 import BeautifulSoup

DATA=Path("data")
CANDIDATES=DATA/"stock_candidates_ai_scored.json"
SUMMARY=DATA/"market_scanner_summary.json"
NEWS_DATA=DATA/"news_data.json"
DETAIL=DATA/"naver_stock_news_detail_a238.json"
MERGE=DATA/"news_merge_summary_a238.json"

HEADERS={"User-Agent":"Mozilla/5.0","Referer":"https://finance.naver.com/"}
POS=["수주","계약","공급","승인","실적","흑자","증가","상승","호재","목표가","매수","증설","수혜","협력","개선","턴어라운드","인상","신규","진출","강세","최대","확대"]
NEG=["하락","적자","감소","손실","리스크","소송","제재","경고","매도","부진","취소","지연","압박","과징금","악재","약세","우려"]

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
    try: return int(float(str(v).replace(",","")))
    except Exception: return d

def collect_stock_news(code, name, max_pages=4):
    items=[]; errors=[]
    for page in range(1, max_pages+1):
        url=f"https://finance.naver.com/item/news_news.naver?code={code}&page={page}&sm=title_entity_id.basic&clusterId="
        try:
            res=requests.get(url,headers=HEADERS,timeout=15)
            res.encoding="euc-kr"
            html=res.text
            soup=BeautifulSoup(html,"html.parser")
            # finance.naver old table links
            for a in soup.select("a"):
                title=a.get_text(" ",strip=True)
                href=a.get("href","")
                if not title or len(title)<6:
                    continue
                if "news_read.naver" not in href and "article" not in href and "office_id" not in href:
                    continue
                if href.startswith("/"):
                    link="https://finance.naver.com"+href
                else:
                    link=href
                text=a.find_parent().get_text(" ",strip=True) if a.find_parent() else title
                items.append({"code":code,"name":name,"title":title[:160],"link":link,"summary":text[:300],"source":"naver_finance_stock_news","collectedAt":datetime.now().isoformat(timespec="seconds")})
            # table fallback
            if not items:
                try:
                    tables=pd.read_html(StringIO(html), flavor="lxml")
                    for t in tables:
                        for _, row in t.iterrows():
                            txt=" ".join(str(x) for x in row.tolist() if str(x)!="nan")
                            if len(txt)>15 and name[:2] in txt:
                                items.append({"code":code,"name":name,"title":txt[:160],"link":url,"summary":txt[:300],"source":"naver_finance_stock_news_table","collectedAt":datetime.now().isoformat(timespec="seconds")})
                except Exception as te:
                    errors.append({"page":page,"tableError":str(te)[:200]})
        except Exception as e:
            errors.append({"page":page,"error":str(e)[:300]})
        time.sleep(0.15)
    # 중복 제거
    uniq=[]; seen=set()
    for it in items:
        key=(it.get("title",""),it.get("link",""))
        if key not in seen:
            seen.add(key); uniq.append(it)
    return uniq[:12], errors

def score_news(items):
    pos=neg=0; titles=[]
    for it in items:
        txt=json.dumps(it,ensure_ascii=False)
        pos+=sum(1 for w in POS if w in txt)
        neg+=sum(1 for w in NEG if w in txt)
        if it.get("title"): titles.append(it["title"])
    score=0
    if items:
        score+=min(8,len(items))
        score+=min(10,pos*2)
        score-=min(8,neg*2)
    score=max(0,min(20,int(score)))
    reason=f"네이버 종목뉴스 {len(items)}건 수집, 긍정 키워드 {pos}개, 부정 키워드 {neg}개" if items else "네이버 종목뉴스 수집 결과 없음"
    if titles: reason+=" / 주요: "+" | ".join(titles[:2])
    return score,reason,{"matchedCount":len(items),"positiveKeywordCount":pos,"negativeKeywordCount":neg,"titles":titles[:5],"source":"naver_finance_stock_news"}

def grade(t): return "A" if t>=85 else "B+" if t>=75 else "B" if t>=65 else "C+" if t>=55 else "C"
def recalc(it):
    total=max(0,min(100,si(it.get("chartScore"))+si(it.get("supplyScore"))+si(it.get("newsScore"))+si(it.get("fundamentalScore",it.get("macroScore",0)))+si(it.get("riskScore"))))
    it["score"]=total; it["grade"]=grade(total)

run=datetime.now().isoformat(timespec="seconds")
cands=norm(load(CANDIDATES,[]))
all_news=[]; details=[]; collected=0; scored=0
for it in cands:
    if not isinstance(it,dict): continue
    code=str(it.get("code") or it.get("stockCode") or it.get("ticker") or "").zfill(6)
    name=str(it.get("name") or "")
    if not code or code=="000000" or not name: continue
    news,errs=collect_stock_news(code,name)
    all_news+=news
    ns,reason,ind=score_news(news)
    it["newsScore"]=ns
    it["newsReason"]=f"[뉴스 {ns}/20] {reason}"
    it["newsIndicators"]=ind
    it["newsEngineVersion"]="A238"
    it["updatedAt"]=run
    recalc(it)
    it["reasonDetail"]=f"{name}({code}) 최종점수 {it.get('score',0)}점({it.get('grade','')}). 산식: 차트 {it.get('chartScore',0)}/35 + 수급 {it.get('supplyScore',0)}/30 + 뉴스 {it.get('newsScore',0)}/20 + 기본 {it.get('fundamentalScore',it.get('macroScore',0))}/10 + 리스크 {it.get('riskScore',0)}/10. 뉴스 근거: {reason}. 수급 근거: {it.get('supplyReason','')}."
    it["detailReport"]=it["reasonDetail"]; it["reason"]=it["reasonDetail"]
    if news: collected+=1
    if ns>0: scored+=1
    details.append({"code":code,"name":name,"newsScore":ns,"reason":reason,"newsCount":len(news),"errors":errs,"items":news[:5],"score":it.get("score",0),"grade":it.get("grade","")})
cands=[x for x in cands if isinstance(x,dict)]
cands.sort(key=lambda x:int(x.get("score",0)), reverse=True)
save(CANDIDATES,cands); save(NEWS_DATA,all_news); save(DETAIL,details)
summ=load(SUMMARY,{})
if not isinstance(summ,dict): summ={}
summ.update({"version":"A238","generatedAt":run,"status":"naver_stock_news","candidateCount":len(cands),"newsCollectedCandidateCount":collected,"newsItemCount":len(all_news),"newsScoreCount":scored,"output":"stock_candidates_ai_scored.json"})
save(SUMMARY,summ)
save(MERGE,{"version":"A238","generatedAt":run,"summary":summ,"details":details,"sample":all_news[:10]})
print(json.dumps(summ,ensure_ascii=False,indent=2))
