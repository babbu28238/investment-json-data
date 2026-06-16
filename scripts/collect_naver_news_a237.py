import json, time
from pathlib import Path
from datetime import datetime
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup

DATA=Path("data")
CANDIDATES=DATA/"stock_candidates_ai_scored.json"
SUMMARY=DATA/"market_scanner_summary.json"
NEWS_DATA=DATA/"news_data.json"
DETAIL=DATA/"naver_news_detail_a237.json"
MERGE=DATA/"news_merge_summary_a237.json"
HEADERS={"User-Agent":"Mozilla/5.0","Referer":"https://search.naver.com/"}
POS=["수주","계약","공급","승인","실적","흑자","증가","상승","호재","목표가","매수","증설","수혜","협력","개선","턴어라운드","인상","신규","진출","강세"]
NEG=["하락","적자","감소","손실","리스크","소송","제재","경고","매도","부진","취소","지연","압박","과징금","악재","약세"]

def load(p,d):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else d
    except Exception:
        return d
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
def collect(name,code):
    url=f"https://search.naver.com/search.naver?where=news&query={quote(name+' 주식')}&sort=1"
    out=[]; errs=[]
    try:
        html=requests.get(url,headers=HEADERS,timeout=15).text
        soup=BeautifulSoup(html,"html.parser")
        links=soup.select("a.news_tit") or soup.select("a[href*='n.news.naver.com'], a[href*='finance.naver.com/news']")
        for a in links[:8]:
            title=a.get("title") or a.get_text(" ",strip=True)
            link=a.get("href","")
            parent=a.find_parent()
            summary=parent.get_text(" ",strip=True) if parent else title
            if title:
                out.append({"code":code,"name":name,"title":title[:160],"link":link,"summary":summary[:300],"source":"naver_search_news","collectedAt":datetime.now().isoformat(timespec="seconds")})
    except Exception as e:
        errs.append(str(e)[:300])
    return out, errs
def score(items):
    pos=neg=0; titles=[]
    for it in items:
        txt=json.dumps(it,ensure_ascii=False)
        pos+=sum(1 for w in POS if w in txt)
        neg+=sum(1 for w in NEG if w in txt)
        if it.get("title"): titles.append(it["title"])
    s=0
    if items:
        s+=min(6,len(items)); s+=min(12,pos*2); s-=min(8,neg*2)
    s=max(0,min(20,int(s)))
    reason = f"네이버뉴스 {len(items)}건 수집, 긍정 키워드 {pos}개, 부정 키워드 {neg}개" if items else "네이버뉴스 수집 결과 없음"
    if titles: reason += " / 주요: " + " | ".join(titles[:2])
    return s, reason, {"matchedCount":len(items),"positiveKeywordCount":pos,"negativeKeywordCount":neg,"titles":titles[:5],"source":"naver_search_news"}
def grade(t):
    return "A" if t>=85 else "B+" if t>=75 else "B" if t>=65 else "C+" if t>=55 else "C"
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
    news,errs=collect(name,code)
    all_news+=news
    ns,reason,ind=score(news)
    it["newsScore"]=ns
    it["newsReason"]=f"[뉴스 {ns}/20] {reason}"
    it["newsIndicators"]=ind
    it["newsEngineVersion"]="A237"
    it["updatedAt"]=run
    recalc(it)
    it["reasonDetail"]=f"{name}({code}) 최종점수 {it.get('score',0)}점({it.get('grade','')}). 산식: 차트 {it.get('chartScore',0)}/35 + 수급 {it.get('supplyScore',0)}/30 + 뉴스 {it.get('newsScore',0)}/20 + 기본 {it.get('fundamentalScore',it.get('macroScore',0))}/10 + 리스크 {it.get('riskScore',0)}/10. 뉴스 근거: {reason}. 수급 근거: {it.get('supplyReason','')}."
    it["detailReport"]=it["reasonDetail"]; it["reason"]=it["reasonDetail"]
    if news: collected+=1
    if ns>0: scored+=1
    details.append({"code":code,"name":name,"newsScore":ns,"reason":reason,"newsCount":len(news),"errors":errs,"items":news[:5],"totalScore":it.get("score",0),"grade":it.get("grade","")})
    time.sleep(0.2)
cands=[x for x in cands if isinstance(x,dict)]
cands.sort(key=lambda x:int(x.get("score",0)), reverse=True)
save(CANDIDATES,cands); save(NEWS_DATA,all_news); save(DETAIL,details)
summ=load(SUMMARY,{})
if not isinstance(summ,dict): summ={}
summ.update({"version":"A237","generatedAt":run,"status":"naver_news_collector","candidateCount":len(cands),"newsCollectedCandidateCount":collected,"newsItemCount":len(all_news),"newsScoreCount":scored,"output":"stock_candidates_ai_scored.json"})
save(SUMMARY,summ)
save(MERGE,{"version":"A237","generatedAt":run,"summary":summ,"details":details,"sample":all_news[:10]})
print(json.dumps(summ,ensure_ascii=False,indent=2))
