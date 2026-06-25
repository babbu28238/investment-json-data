# A423 Robust Real Data Engine
# pykrx 전체 유니버스 실패 시 네이버 시장목록으로 fallback한다.
import json, re, time
from pathlib import Path
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup

DATA=Path("data"); DATA.mkdir(exist_ok=True)
OUT=DATA/"realtime_recommendations_a405.json"
CAND=DATA/"stock_candidates_ai_scored.json"
SUMMARY=DATA/"market_scanner_summary.json"
STATUS_OUT=DATA/"data_connection_status_a423.json"
DEBUG_OUT=DATA/"robust_real_data_debug_a423.json"
MACRO=DATA/"market_macro_environment.json"

HEADERS={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36","Accept-Language":"ko-KR,ko;q=0.9,en-US;q=0.8","Referer":"https://finance.naver.com/"}
POSITIVE=["수주","계약","상향","목표가","증가","흑자","호조","실적","수혜","매수","성장","증설","정책","방산","원전","AI","반도체","선박","LNG","전력","로봇","수출"]
NEGATIVE=["하락","손실","적자","감소","리스크","부진","매도","하향","취소","소송","규제","경고","둔화","불확실","차질"]

def load(p,d):
    try: return json.loads(p.read_text(encoding="utf-8")) if p.exists() else d
    except Exception: return d
def save(p,d):
    p.parent.mkdir(exist_ok=True); p.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding="utf-8")
def si(x):
    try: return int(float(str(x).replace(",","").replace("+","").replace("원","").strip()))
    except Exception: return 0
def clamp(x): return max(0,min(100,int(round(x))))
def clean(t): return re.sub(r"\s+"," ",str(t or "")).strip()
def req_text(url, timeout=12):
    r=requests.get(url,headers=HEADERS,timeout=timeout)
    if r.status_code>=400: raise RuntimeError(f"http {r.status_code}")
    return r.text
def req_json(url, timeout=12):
    r=requests.get(url,headers=HEADERS,timeout=timeout)
    if r.status_code>=400: raise RuntimeError(f"http {r.status_code}")
    return r.json()

def latest_krx_date():
    try:
        from pykrx import stock
        today=datetime.now()
        debug=[]
        for d in range(0,45):
            day=(today-timedelta(days=d)).strftime("%Y%m%d")
            try:
                tickers=stock.get_market_ticker_list(day, market="KOSPI")
                debug.append({"date":day,"count":len(tickers)})
                if len(tickers)>100:
                    return day,debug
            except Exception as e:
                debug.append({"date":day,"error":str(e)[:80]})
        return today.strftime("%Y%m%d"),debug
    except Exception as e:
        return datetime.now().strftime("%Y%m%d"),[{"error":str(e)[:120]}]

def get_universe_pykrx():
    try:
        from pykrx import stock
        date,dbg=latest_krx_date()
        rows=[]
        # Try dated first
        for market in ["KOSPI","KOSDAQ"]:
            tickers=stock.get_market_ticker_list(date, market=market)
            for code in tickers:
                name=stock.get_market_ticker_name(code)
                if code and name: rows.append({"code":code,"name":name,"market":market})
        if len(rows)>1000:
            return rows,f"pykrx:{date}",{"dateDebug":dbg[:10],"count":len(rows)}
        # Try current no-date fallback
        rows=[]
        for market in ["KOSPI","KOSDAQ"]:
            tickers=stock.get_market_ticker_list(market=market)
            for code in tickers:
                name=stock.get_market_ticker_name(code)
                if code and name: rows.append({"code":code,"name":name,"market":market})
        if len(rows)>1000:
            return rows,"pykrx:current",{"dateDebug":dbg[:10],"count":len(rows)}
        return rows,"pykrx_too_small",{"dateDebug":dbg[:10],"count":len(rows)}
    except Exception as e:
        return [],"pykrx_failed",{"error":str(e)[:200]}

def get_universe_naver():
    rows=[]; debug=[]
    # KOSPI=0, KOSDAQ=1
    for sosok,market in [("0","KOSPI"),("1","KOSDAQ")]:
        for page in range(1,80):
            url=f"https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}"
            try:
                html=req_text(url,10)
                soup=BeautifulSoup(html,"html.parser")
                found=0
                for a in soup.select("a.tltle"):
                    name=a.get_text(strip=True)
                    href=a.get("href","")
                    m=re.search(r"code=(\\d{6})",href)
                    if m and name:
                        rows.append({"code":m.group(1),"name":name,"market":market})
                        found+=1
                debug.append({"market":market,"page":page,"found":found})
                if found==0 and page>3:
                    break
                time.sleep(0.05)
            except Exception as e:
                debug.append({"market":market,"page":page,"error":str(e)[:80]})
                if page>3: break
    # dedup
    seen=set(); out=[]
    for r in rows:
        if r["code"] not in seen:
            seen.add(r["code"]); out.append(r)
    return out,"naver_market_sum",{"debug":debug[:20],"count":len(out)}

def get_universe_existing():
    old=load(CAND,[])
    rows=[]
    if isinstance(old,list):
        for x in old:
            code=str(x.get("code") or "").zfill(6); name=str(x.get("name") or "")
            if code and name: rows.append({"code":code,"name":name,"market":x.get("market","")})
    return rows,"existing_json",{"count":len(rows)}

def get_universe():
    rows,src,dbg=get_universe_pykrx()
    if len(rows)>1000: return rows,src,dbg
    rows2,src2,dbg2=get_universe_naver()
    if len(rows2)>1000:
        dbg["pykrxFallbackReason"]=src
        dbg["naver"]=dbg2
        return rows2,src2,dbg
    rows3,src3,dbg3=get_universe_existing()
    return rows3,src3,{"pykrx":dbg,"naver":dbg2,"existing":dbg3}

def sentiment(text,base=50):
    score=base
    for k in POSITIVE:
        if k in text: score+=4
    for k in NEGATIVE:
        if k in text: score-=5
    return clamp(score)
def dedup(items):
    seen=set(); out=[]
    for x in items:
        x=clean(x)
        if len(x)<5: continue
        key=re.sub(r"[^가-힣A-Za-z0-9]","",x)[:80]
        if key not in seen:
            seen.add(key); out.append(x)
    return out

def fetch_price_naver(code):
    debug=[]
    for url in [f"https://m.stock.naver.com/api/stock/{code}/basic",f"https://m.stock.naver.com/api/stock/{code}/integration",f"https://finance.naver.com/item/main.naver?code={code}"]:
        try:
            text=json.dumps(req_json(url),ensure_ascii=False) if "/api/" in url else req_text(url)
            debug.append({"url":url,"ok":True})
            for pat in [r'"closePrice"\\s*:\\s*"([0-9,]+)"',r'"now"\\s*:\\s*"([0-9,]+)"',r'"tradePrice"\\s*:\\s*([0-9]+)',r'현재가\\s*([0-9,]+)']:
                m=re.search(pat,text)
                if m and si(m.group(1))>0: return si(m.group(1)),"connected",url,"네이버 현재가 연결",debug
        except Exception as e:
            debug.append({"url":url,"ok":False,"error":str(e)[:80]})
    return 0,"failed","","현재가 연결 실패",debug

def fetch_price_krx(code,date):
    try:
        from pykrx import stock
        df=stock.get_market_ohlcv_by_date(date,date,code)
        if df is not None and len(df)>0:
            close=int(df.iloc[-1]["종가"])
            if close>0: return close,"connected",f"pykrx_ohlcv:{date}","KRX 종가 연결",[]
    except Exception as e:
        return 0,"failed","pykrx",str(e)[:80],[]
    return 0,"failed","pykrx","KRX 종가 없음",[]

def fetch_price(code,date,usource):
    if usource.startswith("pykrx"):
        p,st,src,reason,dbg=fetch_price_krx(code,date)
        if p>0: return p,st,src,reason,dbg
    return fetch_price_naver(code)

def fetch_chart(code,date,usource):
    if usource.startswith("pykrx"):
        try:
            from pykrx import stock
            end=datetime.strptime(date,"%Y%m%d") if date.isdigit() else datetime.now()
            start=(end-timedelta(days=140)).strftime("%Y%m%d")
            ed=end.strftime("%Y%m%d")
            df=stock.get_market_ohlcv_by_date(start,ed,code)
            if df is not None and len(df)>=20:
                closes=[int(x) for x in df["종가"].tail(60).tolist() if int(x)>0]
                ma5=sum(closes[-5:])/5; ma20=sum(closes[-20:])/20; ma60=sum(closes[-60:])/60 if len(closes)>=60 else ma20; last=closes[-1]
                score=50; reasons=[]
                if last>ma5>ma20: score+=20; reasons.append("현재가가 5일선 위이고 5일선이 20일선 위")
                if last>ma20: score+=10; reasons.append("현재가가 20일선 위")
                if ma20>ma60: score+=10; reasons.append("20일선이 60일선 위")
                if last<ma20: score-=15; reasons.append("현재가가 20일선 아래")
                return f"KRX 기준 현재가 {last:,}원, MA5 {ma5:,.0f}, MA20 {ma20:,.0f}, MA60 {ma60:,.0f}. "+", ".join(reasons),clamp(score),{"ma5":round(ma5),"ma20":round(ma20),"ma60":round(ma60),"last":last},"connected","KRX OHLCV 이동평균"
        except Exception as e:
            pass
    return "차트 지표를 충분히 수집하지 못했습니다.",50,{},"failed","차트 배열 부족"

def fetch_news(code,name):
    items=[]; debug=[]
    for url in [f"https://m.stock.naver.com/api/news/stock/{code}?pageSize=10&page=1",f"https://api.stock.naver.com/news/stock/{code}?pageSize=10&page=1",f"https://search.naver.com/search.naver?where=news&query={requests.utils.quote(name)}"]:
        try:
            if "/api/" in url:
                stack=[req_json(url)]
                while stack:
                    obj=stack.pop()
                    if isinstance(obj,dict):
                        title=obj.get("title") or obj.get("headline") or obj.get("subject")
                        if title: items.append(str(title))
                        stack.extend([v for v in obj.values() if isinstance(v,(dict,list))])
                    elif isinstance(obj,list): stack.extend(obj)
            else:
                soup=BeautifulSoup(req_text(url),"html.parser")
                for sel in ["a.news_tit","a.api_txt_lines","a.link_tit","a"]:
                    for a in soup.select(sel)[:40]:
                        t=a.get_text(" ",strip=True)
                        if name in t or any(k in t for k in POSITIVE+NEGATIVE): items.append(t)
                    if len(items)>=5: break
            debug.append({"url":url,"ok":True,"count":len(items)})
        except Exception as e:
            debug.append({"url":url,"ok":False,"error":str(e)[:80]})
        if len(items)>=5: break
    items=dedup(items)[:8]
    if items:
        summary=" / ".join(items[:3])[:320]
        return summary,sentiment(summary),items,"connected","뉴스 연결",debug
    return "최근 확인된 종목 관련 뉴스가 없습니다.",50,[],"missing","최근 뉴스 없음",debug

def money_values(text):
    vals=[]
    for m in re.findall(r'([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,8})\\s*원',text):
        v=si(m)
        if v>1000: vals.append(v)
    return vals

def fetch_report_target(code,name,current):
    items=[]; targets=[]; debug=[]
    urls=[f"https://finance.naver.com/item/coinfo.naver?code={code}",f"https://finance.naver.com/item/main.naver?code={code}",f"https://m.stock.naver.com/domestic/stock/{code}/research",f"https://search.naver.com/search.naver?query={requests.utils.quote(name+' 목표가 증권사 리포트')}",f"https://search.naver.com/search.naver?query={requests.utils.quote(name+' 컨센서스 목표가')}"]
    for url in urls:
        try:
            html=req_text(url); text=BeautifulSoup(html,"html.parser").get_text(" ",strip=True); blob=html+" "+text
            debug.append({"url":url,"ok":True,"chars":len(html)})
            for pat in [r'"targetPrice"\\s*:\\s*"?([0-9,]+)"?',r'"consensusTargetPrice"\\s*:\\s*"?([0-9,]+)"?',r'목표가\\s*([0-9,]+)\\s*원',r'목표주가\\s*([0-9,]+)\\s*원',r'컨센서스\\s*([0-9,]+)\\s*원']:
                targets += [si(m) for m in re.findall(pat,blob)]
            for ctx in re.findall(r'[^.。\\n]{0,40}(?:목표가|목표주가|컨센서스|투자의견|매수|리포트|거래원 정보)[^.。\\n]{0,160}',text):
                items.append(clean(ctx)); targets += money_values(ctx)
        except Exception as e:
            debug.append({"url":url,"ok":False,"error":str(e)[:80]})
        if len(items)>=5 and targets: break
    items=dedup(items)[:8]
    valid=[v for v in targets if v>1000 and (current<=0 or current*0.45<=v<=current*3.2)]
    target=sorted(valid)[len(valid)//2] if valid else 0
    summary=" / ".join(items[:3])[:320] if items else "최근 확인된 증권사 리포트/목표가 문맥이 없습니다."
    status="connected" if items and target else "partial" if items or target else "missing"
    return target,summary,sentiment(summary),items,status,"리포트/목표가 연결" if status=="connected" else "리포트 또는 목표가 일부만 확인" if status=="partial" else "리포트/목표가 없음",debug

def pick_col(df,keys):
    for key in keys:
        for col in df.columns:
            if key in str(col): return col
    return None
def supply_score(f,i,p,status):
    if status=="failed": return 50
    score=50
    for v,w in [(f,18),(i,18),(p,12)]:
        if v>0: score+=w
        elif v<0: score-=w
    return clamp(score)

def fetch_supply(code,date,usource,report_items,report_summary):
    debug=[]
    if usource.startswith("pykrx") and date.isdigit():
        try:
            from pykrx import stock
            end=datetime.strptime(date,"%Y%m%d"); start=(end-timedelta(days=20)).strftime("%Y%m%d")
            for detail in [True,False]:
                try:
                    df=stock.get_market_trading_value_by_date(start,date,code,detail=detail)
                    debug.append({"method":f"value_detail_{detail}","ok":True,"rows":0 if df is None else len(df)})
                    if df is None or len(df)==0: continue
                    tail=df.tail(5); fc=pick_col(tail,["외국인합계","외국인"]); ic=pick_col(tail,["기관합계","기관"]); pc=pick_col(tail,["연기금","연기금등"])
                    f=int(tail[fc].sum()) if fc else 0; i=int(tail[ic].sum()) if ic else 0; p=int(tail[pc].sum()) if pc else 0
                    if f or i or p:
                        return f,i,p,supply_score(f,i,p,"connected"),"connected",f"최근 5거래일 KRX 기준 외국인 {f:,}, 기관 {i:,}, 연기금 {p:,} 반영",f"pykrx:{start}-{date}",debug
                except Exception as e: debug.append({"method":f"value_detail_{detail}","ok":False,"error":str(e)[:80]})
        except Exception as e: debug.append({"method":"pykrx_import","ok":False,"error":str(e)[:80]})
    blob=" ".join([str(report_summary)]+[str(x) for x in report_items])
    m=re.search(r'외국계추정합\\s+[0-9,]+\\s+([+\\-]?[0-9,]+)\\s+[0-9,]+',blob) or re.search(r'외국계추정합.{0,80}?([+\\-][0-9,]+)',blob)
    if m:
        f=si(m.group(1)); return f,0,0,supply_score(f,0,0,"partial"),"partial",f"네이버 외국계추정합 {f:,} 부분 반영","naver_broker_foreign_estimate",debug
    return 0,0,0,50,"failed","수급 원자료 확인 실패","none",debug

def load_macro():
    m=load(MACRO,{})
    return m if isinstance(m,dict) and m.get("macroItems") else {"overallMacroScore":50,"overallMarketView":"중립 / 관망","macroItems":[]}
def macro_adjust(c,macro):
    sector=f"{c.get('sector','')} {c.get('name','')}"; adj=0; reasons=[]
    for item in macro.get("macroItems",[]):
        cat=item.get("category",""); score=si(item.get("score")); impact=item.get("marketImpact","")
        if any(str(s) and str(s) in sector for s in item.get("favoredSectors",[]) or []):
            add=8 if score>=80 else 5 if score>=60 else 2 if score>=40 else 0
            if add: adj+=add; reasons.append(f"{cat}: {impact}")
        if any(str(s) and str(s) in sector for s in item.get("unfavorableSectors",[]) or []):
            minus=-8 if score<20 else -5 if score<40 else -2 if score<60 else 0
            if minus: adj+=minus; reasons.append(f"{cat}: {impact}")
    mode={"공격적 매수 가능":5,"선별 매수":2,"중립 / 관망":0,"방어적 운용":-5,"리스크 관리 우선":-10}.get(macro.get("overallMarketView",""),0)
    return max(-15,min(15,adj+mode)),list(dict.fromkeys(reasons))[:6]
def price_score(price,target):
    if price<=0: return 0
    if target<=0: return 45
    up=(target-price)/price*100
    return 90 if up>=50 else 80 if up>=30 else 65 if up>=15 else 55 if up>=5 else 40
def final_score(c):
    q=si(c.get("quantScore")) or 50; s=si(c.get("supplyScore")) or 50; co=si(c.get("companyScore")) or 50; ev=si(c.get("eventScore")) or si(c.get("newsScore")) or 50
    report=si(c.get("reportScore")) or 50; chart=si(c.get("chartScore")) or 50; ma=si(c.get("macroScore")) or 50; ri=si(c.get("riskScore")) or 50
    return clamp(clamp(q*.18+s*.18+co*.18+ev*.14+report*.10+chart*.10+ma*.07+ri*.05)+si(c.get("macroAdjustmentScore")))
def data_score(statuses):
    val=0
    for s in statuses: val+=17 if s=="connected" else 10 if s=="partial" else 5 if s=="missing" else 0
    return min(100,val)
def round_price(v):
    if v<=0: return 0
    unit=500 if v>=100000 else 100 if v>=10000 else 10
    return int(round(v/unit)*unit)
def infer_sector(name,market):
    sector=market
    mp={"반도체":["삼성전자","SK하이닉스","이오테크닉스","한미반도체"],"조선":["조선","한화오션","HD현대중공업","HD한국조선해양"],"방산":["한화시스템","현대로템","한국항공우주","LIG넥스원"],"바이오":["바이오","셀트리온","알테오젠"],"증권":["증권"],"자동차":["현대차","기아"]}
    for k,arr in mp.items():
        if any(x in name for x in arr): sector+=" "+k
    return sector

def main():
    run=datetime.now().isoformat(timespec="seconds")
    universe,usource,udebug=get_universe()
    macro=load_macro(); out=[]; debug=[]
    counts={k:0 for k in ["priceConnected","newsConnected","reportConnected","chartConnected","supplyConnected","supplyPartial","macroApplied","naverMissing"]}
    date=usource.split(":")[-1] if usource.startswith("pykrx:") else datetime.now().strftime("%Y%m%d")
    # keep action time reasonable: still process all, but can be slow. 
    for idx,row in enumerate(universe):
        code=row["code"]; name=row["name"]; market=row.get("market","")
        price,ps,psrc,preason,pdbg=fetch_price(code,date,usource)
        if ps!="connected":
            counts["naverMissing"]+=1; debug.append({"code":code,"name":name,"status":"price_failed","priceDebug":pdbg}); continue
        counts["priceConnected"]+=1
        news,news_sc,news_items,ns,nreason,ndbg=fetch_news(code,name)
        if ns=="connected": counts["newsConnected"]+=1
        target,report,report_sc,report_items,rs,rreason,rdbg=fetch_report_target(code,name,price)
        if rs in ["connected","partial"]: counts["reportConnected"]+=1
        chart,chart_sc,chart_ind,cs,creason=fetch_chart(code,date,usource)
        if cs=="connected": counts["chartConnected"]+=1
        f,i,p,supply_sc,ss,sreason,ssource,sdbg=fetch_supply(code,date,usource,report_items,report)
        if ss=="connected": counts["supplyConnected"]+=1
        if ss=="partial": counts["supplyPartial"]+=1
        sector=infer_sector(name,market)
        pscore=price_score(price,target); up=round((target-price)/price*100,1) if target else 0.0
        quant=clamp(pscore*.4+chart_sc*.4+min(max(up,0),80)*.2); company=clamp(report_sc*.55+pscore*.45); event=news_sc; macro_sc=50; risk=60
        adj,reasons=macro_adjust({"name":name,"sector":sector},macro)
        if reasons or adj!=0: counts["macroApplied"]+=1
        statuses=[ps,ns,rs,cs,ss,"connected" if macro else "missing"]; dscore=data_score(statuses)
        item={"code":code,"name":name,"market":market,"sector":sector,"currentPrice":price,"close":price,"targetPrice":target,"targetMedianPrice":target,"targetStatus":"수집성공" if target else "수집실패","targetSource":"robust_real_data_engine_a423","targetReason":f"목표가 {target:,}원을 수집했습니다." if target else "최근 확인된 리포트/컨센서스 목표가가 없습니다.","realisticTargetPrice":round_price(target*.8) if target else 0,"observeTimingPrice":round_price(target*.7) if target else 0,"stopTimingPrice":round_price(target*.6) if target else 0,"chartStopPrice":round_price(price*.92),"targetUpsidePercent":up,"priceValidationStatus":"정상","priceValidationReason":preason,"newsSummary":news,"newsScore":news_sc,"newsItems":news_items,"reportSummary":report,"reportScore":report_sc,"reportItems":report_items,"chartSummary":chart,"chartScore":chart_sc,"chartIndicators":chart_ind,"priceScore":pscore,"foreignNetBuy":f,"institutionNetBuy":i,"pensionNetBuy":p,"supplyScore":supply_sc,"supplyStatus":ss,"supplySource":ssource,"supplyReason":sreason,"supplyOpinion":sreason,"quantScore":quant,"companyScore":company,"eventScore":event,"macroScore":macro_sc,"riskScore":risk,"quantOpinion":f"가격점수 {pscore}점, 차트점수 {chart_sc}점, 상승여력 {up:.1f}%를 조합했습니다.","companyOpinion":f"리포트 점수 {report_sc}점과 가격 점수 {pscore}점을 조합했습니다.","eventOpinion":f"뉴스 점수 {news_sc}점을 이벤트 관점에 반영했습니다.","macroOpinion":"매크로 시장환경 JSON을 종목 업종과 연결해 조정점수를 산정했습니다.","riskOpinion":"가격 연결 상태와 손절 기준을 반영했습니다.","macroAdjustmentScore":adj,"macroReasons":reasons,"priceDataStatus":ps,"newsDataStatus":ns,"reportDataStatus":rs,"chartDataStatus":cs,"supplyDataStatus":ss,"macroDataStatus":"connected" if macro else "missing","dataConnectionScore":dscore,"dataConnectionReason":f"주가 {ps}, 뉴스 {ns}, 리포트 {rs}, 차트 {cs}, 수급 {ss}, 매크로 connected 기준 연결점수 {dscore}점입니다.","updatedAt":run,"targetEngineVersion":"A423","source":"robust_real_data_engine"}
        item["score"]=final_score(item); item["realtimeScore"]=item["score"]; item["expertSummary"]=f"퀀트 {quant}점, 수급 {supply_sc}점, 기업 {company}점, 이벤트 {event}점, 매크로 {macro_sc}점, 리스크 {risk}점을 종합했습니다."; item["recommendationReason"]=f"{name}: 주가·뉴스·리포트·차트·수급·매크로 연결상태 {dscore}점, 매크로 조정 {adj:+d}점을 반영한 종합점수 {item['score']}점입니다."; item["reason"]=item["recommendationReason"]; item["finalScoreReason"]="최종점수는 퀀트 18%, 수급 18%, 기업분석 18%, 뉴스/이벤트 14%, 리포트 10%, 차트 10%, 매크로 7%, 리스크 5%와 매크로 조정점수를 반영합니다."
        out.append(item); debug.append({"code":code,"name":name,"statuses":statuses,"dataConnectionScore":dscore,"priceSource":psrc,"chartReason":creason,"supplySource":ssource,"priceDebug":pdbg[:2],"newsDebug":ndbg[:2],"reportDebug":rdbg[:2],"supplyDebug":sdbg[:2]})
        if idx%100==0: print(f"processed {idx}/{len(universe)} kept={len(out)}")
        time.sleep(0.01)
    out.sort(key=lambda x:x.get("realtimeScore",0),reverse=True)
    save(OUT,out); save(CAND,out)
    summary={"version":"A423","generatedAt":run,"status":"robust_real_data_engine","universeSource":usource,"universeCount":len(universe),"includedCount":len(out),**counts,"averageDataConnectionScore":round(sum(x.get("dataConnectionScore",0) for x in out)/len(out),1) if out else 0,"overallMacroScore":macro.get("overallMacroScore",50),"overallMarketView":macro.get("overallMarketView","중립 / 관망"),"output":"realtime_recommendations_a405.json","universeDebug":udebug}
    save(SUMMARY,summary); save(STATUS_OUT,{"summary":summary,"top":out[:50]}); save(DEBUG_OUT,{"summary":summary,"debug":debug[:1000]})
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=="__main__": main()
