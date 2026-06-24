# scripts/all_listed_universe_a414.py
# A414: 국내 상장 전체 종목 유니버스 수집기
# KOSPI + KOSDAQ 전체 종목을 가져온 뒤, 네이버 종목 페이지/API가 확인되는 종목만 추천 분석 대상으로 저장한다.
# 네이버에 없는 종목은 제외한다.
# 목표가/뉴스/리포트/수급이 없으면 없음으로 명확히 표시한다.

import json, re, time, math
from pathlib import Path
from datetime import datetime
import requests
from bs4 import BeautifulSoup

DATA = Path("data")
DATA.mkdir(exist_ok=True)

OUT = DATA / "realtime_recommendations_a405.json"
CAND = DATA / "stock_candidates_ai_scored.json"
SUMMARY = DATA / "market_scanner_summary.json"
UNIVERSE_OUT = DATA / "all_listed_universe_a414.json"
DEBUG_OUT = DATA / "all_listed_universe_debug_a414.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 Chrome/124 Mobile Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
    "Referer": "https://m.stock.naver.com/",
}

SECTOR_MACRO = {
    "조선": ("조선 섹터는 선박 수주, LNG선, 방산/해양플랜트 사이클을 우호 요인으로 평가합니다.",72),
    "방산": ("방산 섹터는 국방비 확대, 수출 계약, 지정학 리스크 확대를 우호 요인으로 평가합니다.",75),
    "원전": ("원전/에너지 섹터는 전력 수요 증가, 원전 정책, 에너지 안보를 우호 요인으로 평가합니다.",70),
    "반도체": ("반도체 섹터는 AI 서버, 메모리 업황, 수출 회복을 핵심 변수로 평가합니다.",68),
    "로봇": ("로봇 섹터는 자동화 투자와 성장성은 우호적이나 밸류에이션 부담을 함께 평가합니다.",64),
    "2차전지": ("2차전지 섹터는 전기차 수요와 소재 가격 변동성이 커 중립 이하로 평가합니다.",55),
    "바이오": ("바이오 섹터는 임상/허가 이벤트 민감도가 높아 리스크와 이벤트를 함께 평가합니다.",58),
    "금융": ("금융 섹터는 금리, 배당, 자본환원 정책을 핵심 변수로 평가합니다.",62),
    "자동차": ("자동차 섹터는 환율, 수출, 관세, 전기차 전환 속도를 핵심 변수로 평가합니다.",60),
    "인터넷": ("인터넷 섹터는 광고 경기, AI 투자비, 플랫폼 규제 가능성을 함께 평가합니다.",58),
}

POSITIVE = ["수주","계약","상향","목표가","증가","흑자","호조","실적","수혜","매수","성장","증설","정책","방산","원전","AI","반도체","선박","LNG","전력","로봇","수출"]
NEGATIVE = ["하락","손실","적자","감소","리스크","부진","매도","하향","취소","소송","규제","경고","둔화","불확실","차질"]

def save(path, data):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default

def si(x):
    try:
        return int(float(str(x).replace(",","").replace("원","").replace("+","").strip()))
    except Exception:
        return 0

def sf(x):
    try:
        return float(str(x).replace("%","").replace(",","").strip())
    except Exception:
        return 0.0

def clamp(x):
    return max(0,min(100,int(round(x))))

def clean(t):
    return re.sub(r"\s+"," ",str(t or "")).strip()

def request_json(url):
    r = requests.get(url, headers=HEADERS, timeout=12)
    if r.status_code >= 400:
        raise RuntimeError(f"http {r.status_code}")
    return r.json()

def request_text(url):
    r = requests.get(url, headers=HEADERS, timeout=12)
    if r.status_code >= 400:
        raise RuntimeError(f"http {r.status_code}")
    return r.text

def get_all_listed():
    # pykrx 우선. 실패하면 기존 JSON/핵심 샘플로 fallback.
    try:
        from pykrx import stock
        today = datetime.now().strftime("%Y%m%d")
        rows = []
        for market in ["KOSPI","KOSDAQ"]:
            tickers = stock.get_market_ticker_list(today, market=market)
            for code in tickers:
                name = stock.get_market_ticker_name(code)
                if code and name:
                    rows.append({"code":code, "name":name, "market":market})
        if rows:
            return rows, "pykrx"
    except Exception as e:
        err = str(e)[:120]
    old = load(CAND, [])
    if isinstance(old, list) and old:
        rows = []
        for x in old:
            code = str(x.get("code") or x.get("stockCode") or "").zfill(6)
            name = str(x.get("name") or x.get("stockName") or "")
            market = str(x.get("market") or "")
            if code and name:
                rows.append({"code":code,"name":name,"market":market})
        return rows, "fallback_existing_json"
    return [
        {"code":"005930","name":"삼성전자","market":"KOSPI"},
        {"code":"000660","name":"SK하이닉스","market":"KOSPI"},
        {"code":"042660","name":"한화오션","market":"KOSPI"},
        {"code":"034020","name":"두산에너빌리티","market":"KOSPI"},
        {"code":"272210","name":"한화시스템","market":"KOSPI"},
    ], "fallback_minimal"

def naver_basic(code):
    urls = [
        f"https://m.stock.naver.com/api/stock/{code}/basic",
        f"https://m.stock.naver.com/api/stock/{code}/integration",
        f"https://m.stock.naver.com/domestic/stock/{code}/total",
    ]
    debug = []
    for url in urls:
        try:
            if "/api/" in url:
                data = request_json(url)
                txt = json.dumps(data, ensure_ascii=False)
            else:
                txt = request_text(url)
                data = {}
            debug.append({"url":url,"ok":True})
            price = 0
            for pat in [
                r'"closePrice"\s*:\s*"([0-9,]+)"',
                r'"now"\s*:\s*"([0-9,]+)"',
                r'"tradePrice"\s*:\s*([0-9]+)',
            ]:
                m = re.search(pat, txt)
                if m:
                    price = si(m.group(1))
                    break
            sector = ""
            for key in ["industryCodeType", "industry", "sectorName", "stockExchangeType"]:
                if isinstance(data, dict) and data.get(key):
                    sector = str(data.get(key))
            if not sector:
                soup = BeautifulSoup(txt, "html.parser")
                body = soup.get_text(" ", strip=True)
                for k in SECTOR_MACRO.keys():
                    if k in body:
                        sector = k
                        break
            if price > 0:
                return True, price, sector, url, debug
        except Exception as e:
            debug.append({"url":url,"ok":False,"error":str(e)[:80]})
    return False, 0, "", "", debug

def sentiment(text, base=50):
    score = base
    for k in POSITIVE:
        if k in text: score += 4
    for k in NEGATIVE:
        if k in text: score -= 5
    return clamp(score)

def dedup(items):
    seen=set(); out=[]
    for x in items:
        x=clean(x)
        if len(x)<8: continue
        key=re.sub(r"[^가-힣A-Za-z0-9]","",x)[:80]
        if key not in seen:
            seen.add(key); out.append(x)
    return out

def fetch_news(code,name):
    items=[]; debug=[]
    urls=[
        f"https://m.stock.naver.com/api/news/stock/{code}?pageSize=10&page=1",
        f"https://api.stock.naver.com/news/stock/{code}?pageSize=10&page=1",
        f"https://search.naver.com/search.naver?where=news&query={requests.utils.quote(name)}",
    ]
    for url in urls:
        try:
            if "/api/" in url:
                data=request_json(url)
                stack=[data]
                while stack:
                    obj=stack.pop()
                    if isinstance(obj,dict):
                        title=obj.get("title") or obj.get("headline") or obj.get("subject")
                        if title: items.append(str(title))
                        for v in obj.values():
                            if isinstance(v,(dict,list)): stack.append(v)
                    elif isinstance(obj,list):
                        stack.extend(obj)
            else:
                html=request_text(url)
                soup=BeautifulSoup(html,"html.parser")
                for sel in ["a.news_tit","a.api_txt_lines","a.link_tit","a"]:
                    for a in soup.select(sel)[:40]:
                        t=a.get_text(" ",strip=True)
                        if name in t or any(k in t for k in POSITIVE+NEGATIVE):
                            items.append(t)
                    if len(items)>=5: break
            debug.append({"url":url,"ok":True,"count":len(items)})
        except Exception as e:
            debug.append({"url":url,"ok":False,"error":str(e)[:80]})
        if len(items)>=5: break
    items=dedup(items)[:8]
    if not items:
        return "최근 확인된 종목 관련 뉴스가 없습니다.", 50, [], debug
    summary=" / ".join(items[:3])
    return summary[:320], sentiment(summary), items, debug

def money_candidates(text):
    vals=[]
    for m in re.findall(r'([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,7})\s*원', text):
        v=si(m)
        if v>1000: vals.append(v)
    return vals

def fetch_target_report(code,name,current):
    items=[]; targets=[]; debug=[]
    urls=[
        f"https://finance.naver.com/item/coinfo.naver?code={code}",
        f"https://finance.naver.com/item/main.naver?code={code}",
        f"https://m.stock.naver.com/domestic/stock/{code}/research",
        f"https://search.naver.com/search.naver?query={requests.utils.quote(name+' 목표가 증권사 리포트')}",
        f"https://search.naver.com/search.naver?query={requests.utils.quote(name+' 컨센서스 목표가')}",
    ]
    for url in urls:
        try:
            html=request_text(url)
            soup=BeautifulSoup(html,"html.parser")
            text=soup.get_text(" ",strip=True)
            debug.append({"url":url,"ok":True,"chars":len(html)})
            blob=html+" "+text
            for pat in [
                r'"targetPrice"\s*:\s*"?([0-9,]+)"?',
                r'"consensusTargetPrice"\s*:\s*"?([0-9,]+)"?',
                r'목표가\s*([0-9,]+)\s*원',
                r'목표주가\s*([0-9,]+)\s*원',
                r'컨센서스\s*([0-9,]+)\s*원',
            ]:
                for m in re.findall(pat, blob):
                    v=si(m)
                    if v>1000: targets.append(v)
            for ctx in re.findall(r'[^.。\n]{0,30}(?:목표가|목표주가|컨센서스|투자의견|매수|리포트)[^.。\n]{0,100}', text):
                items.append(clean(ctx))
                targets += money_candidates(ctx)
        except Exception as e:
            debug.append({"url":url,"ok":False,"error":str(e)[:80]})
        if len(items)>=5 and targets: break
    items=dedup(items)[:8]
    valid=[]
    for v in targets:
        if current>0:
            if current*0.5 <= v <= current*3.0: valid.append(v)
        else:
            valid.append(v)
    target=0
    if valid:
        valid=sorted(valid)
        target=valid[len(valid)//2]
    summary=" / ".join(items[:3]) if items else "최근 확인된 증권사 리포트/목표가 문맥이 없습니다."
    score=sentiment(summary,50)
    return target, summary[:320], score, items, debug

def fetch_supply(code,name):
    debug=[]; f=i=p=0
    urls=[
        f"https://finance.naver.com/item/frgn.naver?code={code}",
        f"https://finance.naver.com/item/sise.naver?code={code}",
        f"https://m.stock.naver.com/api/stock/{code}/integration",
        f"https://m.stock.naver.com/api/stock/{code}/investor",
    ]
    for url in urls:
        try:
            txt=request_text(url)
            text=BeautifulSoup(txt,"html.parser").get_text(" ",strip=True)
            blob=txt+" "+text
            debug.append({"url":url,"ok":True,"chars":len(txt)})
            for key,var in [
                ("foreignNetBuy","f"),("foreignerPureBuy","f"),
                ("institutionNetBuy","i"),("organNetBuy","i"),
                ("pensionNetBuy","p")
            ]:
                m=re.search(rf'"{key}"\s*:\s*"?([+\-]?[0-9,]+)"?', blob)
                if m:
                    val=si(m.group(1))
                    if var=="f": f=f or val
                    if var=="i": i=i or val
                    if var=="p": p=p or val
        except Exception as e:
            debug.append({"url":url,"ok":False,"error":str(e)[:80]})
    if f or i or p:
        vals=[x for x in [f,i,p] if x!=0]
        pos=sum(1 for x in vals if x>0); neg=sum(1 for x in vals if x<0)
        score=clamp(50+pos*12-neg*12)
        opinion=f"외국인 {f:,}, 기관 {i:,}, 연기금 {p:,} 순매수 데이터를 반영해 수급 점수 {score}점으로 평가했습니다."
        return f,i,p,score,opinion,"수집성공",debug
    return 0,0,0,50,"수급 원자료가 아직 충분하지 않아 중립 50점으로 처리했습니다.","수집실패",debug

def fetch_chart(code,current):
    try:
        data=request_json(f"https://m.stock.naver.com/api/stock/{code}/price?pageSize=60&page=1")
        rows=data if isinstance(data,list) else data.get("priceInfos",[]) or data.get("data",[])
        prices=[]
        for row in rows:
            close=si(row.get("closePrice") or row.get("close") or row.get("tradePrice"))
            if close>0: prices.append(close)
        prices=list(reversed(prices[-60:]))
        if len(prices)>=20:
            ma5=sum(prices[-5:])/5
            ma20=sum(prices[-20:])/20
            ma60=sum(prices[-60:])/60 if len(prices)>=60 else ma20
            last=prices[-1]
            score=50
            reasons=[]
            if last>ma5>ma20: score+=20; reasons.append("5일선이 20일선 위")
            if last>ma20: score+=10; reasons.append("현재가가 20일선 위")
            if ma20>ma60: score+=10; reasons.append("20일선이 60일선 위")
            if last<ma20: score-=15; reasons.append("현재가가 20일선 아래")
            return f"현재가 {last:,}원, MA5 {ma5:,.0f}, MA20 {ma20:,.0f}. " + ", ".join(reasons), clamp(score), {"ma5":round(ma5),"ma20":round(ma20),"ma60":round(ma60)}
    except Exception:
        pass
    return "차트 지표를 충분히 수집하지 못했습니다.", 50, {}

def macro_for(sector,name):
    text=str(sector)+" "+str(name)
    for k,(op,sc) in SECTOR_MACRO.items():
        if k in text: return sc,op
    return 50,"섹터/매크로 원자료가 충분하지 않아 중립 50점으로 평가했습니다."

def price_score(price,target):
    if price<=0: return 0
    if target<=0: return 45
    up=(target-price)/price*100
    if up>=50: return 90
    if up>=30: return 80
    if up>=15: return 65
    if up>=5: return 55
    return 40

def risk_score(status,price,stop):
    if status!="정상" or price<=0: return 25,"가격 검증 필요로 리스크를 낮게 평가했습니다."
    if stop<=0: return 55,"손절선 원자료가 부족해 중립에 가깝게 평가했습니다."
    gap=(price-stop)/price*100
    if gap<=8: return 72,f"손절선 이격 {gap:.1f}%로 손실 통제 구간이 명확합니다."
    if gap<=15: return 60,f"손절선 이격 {gap:.1f}%로 보통 수준 리스크입니다."
    return 45,f"손절선 이격 {gap:.1f}%로 손절폭이 커 리스크가 높습니다."

def round_price(v):
    if v<=0: return 0
    unit=500 if v>=100000 else 100 if v>=10000 else 10
    return int(round(v/unit)*unit)

def main():
    run=datetime.now().isoformat(timespec="seconds")
    universe, source=get_all_listed()
    result=[]; debug=[]
    naver_missing=0
    for idx, row in enumerate(universe):
        code=row["code"]; name=row["name"]; market=row.get("market","")
        exists, price, sector, price_source, basic_debug=naver_basic(code)
        if not exists:
            naver_missing+=1
            debug.append({"code":code,"name":name,"status":"naver_missing","basicDebug":basic_debug})
            continue

        news_summary,news_sc,news_items,news_debug=fetch_news(code,name)
        target,report_summary,report_sc,report_items,report_debug=fetch_target_report(code,name,price)
        f,i,p,supply_sc,supply_opinion,supply_status,supply_debug=fetch_supply(code,name)
        chart_summary,chart_sc,chart_ind=fetch_chart(code,price)
        macro_sc,macro_op=macro_for(sector,name)

        pscore=price_score(price,target)
        realistic=round_price(target*0.80) if target else 0
        observe=round_price(target*0.70) if target else 0
        stop=round_price(target*0.60) if target else 0
        chart_stop=round_price(price*0.92) if price else 0
        up=round((target-price)/price*100,1) if price and target else 0.0
        rscore,rop=risk_score("정상",price,chart_stop)

        quant=clamp(pscore*.4+chart_sc*.4+min(max(up,0),80)*.2)
        company=clamp(report_sc*.55+pscore*.45)
        event=clamp(news_sc)
        final=clamp(quant*.18+supply_sc*.18+company*.18+event*.14+report_sc*.10+chart_sc*.10+macro_sc*.07+rscore*.05)

        item={
            "code":code,"name":name,"market":market,"sector":sector,
            "currentPrice":price,"close":price,
            "targetPrice":target,"targetMedianPrice":target,
            "targetStatus":"수집성공" if target>0 else "수집실패",
            "targetSource":"naver/search" if target>0 else "",
            "targetReason":f"목표가 {target:,}원을 수집했습니다." if target>0 else "최근 확인된 리포트/컨센서스 목표가가 없습니다.",
            "realisticTargetPrice":realistic,
            "observeTimingPrice":observe,
            "stopTimingPrice":stop,
            "chartStopPrice":chart_stop,
            "targetUpsidePercent":up,
            "priceValidationStatus":"정상",
            "priceValidationReason":"네이버 종목 가격 확인",
            "newsSummary":news_summary,"newsScore":news_sc,"newsItems":news_items,
            "reportSummary":report_summary,"reportScore":report_sc,"reportItems":report_items,
            "chartSummary":chart_summary,"chartScore":chart_sc,"chartIndicators":chart_ind,
            "priceScore":pscore,
            "foreignNetBuy":f,"institutionNetBuy":i,"pensionNetBuy":p,
            "supplyScore":supply_sc,"supplyOpinion":supply_opinion,
            "supplyStatus":supply_status,"supplySource":"naver_public" if supply_status=="수집성공" else "",
            "supplyReason":supply_opinion,
            "quantScore":quant,
            "supplyScore":supply_sc,
            "companyScore":company,
            "eventScore":event,
            "macroScore":macro_sc,
            "riskScore":rscore,
            "quantOpinion":f"가격점수 {pscore}점, 차트점수 {chart_sc}점, 상승여력 {up:.1f}%를 조합했습니다.",
            "companyOpinion":f"리포트 점수 {report_sc}점과 가격 점수 {pscore}점을 조합했습니다.",
            "eventOpinion":f"뉴스 점수 {news_sc}점을 이벤트 관점에 반영했습니다.",
            "macroOpinion":macro_op,
            "riskOpinion":rop,
            "expertSummary":f"퀀트 {quant}점, 수급 {supply_sc}점, 기업 {company}점, 이벤트 {event}점, 매크로 {macro_sc}점, 리스크 {rscore}점을 종합했습니다.",
            "score":final,"realtimeScore":final,
            "recommendationReason":f"{name}: 전체 국내 상장 종목 유니버스에서 전문가 패널 종합점수 {final}점으로 산출했습니다.",
            "reason":f"{name}: 전체 국내 상장 종목 유니버스에서 전문가 패널 종합점수 {final}점으로 산출했습니다.",
            "finalScoreReason":"최종점수는 퀀트 18%, 수급 18%, 기업분석 18%, 뉴스/이벤트 14%, 리포트 10%, 차트 10%, 매크로 7%, 리스크 5%로 계산했습니다.",
            "updatedAt":run,"targetEngineVersion":"A414","source":"all_listed_universe"
        }
        result.append(item)
        debug.append({"code":code,"name":name,"status":"ok","price":price,"target":target,"supplyStatus":supply_status,"newsCount":len(news_items),"reportCount":len(report_items)})
        if idx % 50 == 0:
            print(f"processed {idx}/{len(universe)} kept={len(result)}")
        time.sleep(0.05)

    result.sort(key=lambda x:x.get("realtimeScore",0), reverse=True)
    save(OUT,result); save(CAND,result)
    summary={
        "version":"A414",
        "generatedAt":run,
        "status":"all_listed_universe",
        "universeSource":source,
        "universeCount":len(universe),
        "naverIncludedCount":len(result),
        "naverMissingExcludedCount":naver_missing,
        "targetCollectedCount":sum(1 for x in result if x.get("targetPrice",0)>0),
        "supplyCollectedCount":sum(1 for x in result if x.get("supplyStatus")=="수집성공"),
        "newsAvailableCount":sum(1 for x in result if x.get("newsItems")),
        "reportAvailableCount":sum(1 for x in result if x.get("reportItems")),
        "output":"realtime_recommendations_a405.json"
    }
    save(SUMMARY,summary)
    save(UNIVERSE_OUT,{"summary":summary,"top":result[:50]})
    save(DEBUG_OUT,{"summary":summary,"debug":debug[:500]})
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
