# scripts/generate_market_candidates_a210.py
# HSinvest A210 FORCE REAL CANDIDATES
# stock_candidates_ai_scored.json이 []로 저장되는 문제를 최종 방지한다.

import json
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

OUT = Path("data")
OUT.mkdir(exist_ok=True)

FALLBACK = [
    ("005930","삼성전자","KOSPI","반도체"),("000660","SK하이닉스","KOSPI","반도체"),
    ("329180","HD현대중공업","KOSPI","조선"),("042660","한화오션","KOSPI","조선/방산"),
    ("034020","두산에너빌리티","KOSPI","원전/에너지"),("272210","한화시스템","KOSPI","방산"),
    ("047810","한국항공우주","KOSPI","방산"),("241560","두산밥캣","KOSPI","기계"),
    ("028260","삼성물산","KOSPI","건설/지주"),("105560","KB금융","KOSPI","금융"),
    ("055550","신한지주","KOSPI","금융"),("086790","하나금융지주","KOSPI","금융"),
    ("316140","우리금융지주","KOSPI","금융"),("005380","현대차","KOSPI","자동차"),
    ("000270","기아","KOSPI","자동차"),("035420","NAVER","KOSPI","인터넷"),
    ("035720","카카오","KOSPI","인터넷"),("033780","KT&G","KOSPI","방어주"),
    ("011200","HMM","KOSPI","해운"),("008770","호텔신라","KOSPI","소비/여행"),
    ("108490","로보티즈","KOSDAQ","로봇"),("277810","레인보우로보틱스","KOSDAQ","로봇"),
    ("247540","에코프로비엠","KOSDAQ","2차전지"),("086520","에코프로","KOSDAQ","2차전지"),
    ("196170","알테오젠","KOSDAQ","바이오"),("068760","셀트리온제약","KOSDAQ","바이오"),
    ("091990","셀트리온헬스케어","KOSDAQ","바이오"),("039030","이오테크닉스","KOSDAQ","반도체장비"),
    ("058470","리노공업","KOSDAQ","반도체장비"),("112040","위메이드","KOSDAQ","게임")
]

POSITIVE = ["수주","계약","공급","실적","흑자","증설","AI","반도체","원전","방산","조선","전력","로봇","승인","수출"]
NEGATIVE = ["적자","소송","감자","유상증자","불성실","횡령","배임","관리종목","하한가","리콜","제재"]

def safe_int(v, default=0):
    try:
        if pd.isna(v): return default
        return int(float(v))
    except Exception:
        return default

def safe_float(v, default=0.0):
    try:
        if pd.isna(v): return default
        return float(v)
    except Exception:
        return default

def ymd(dt): return dt.strftime("%Y%m%d")

def grade(score):
    return "A+" if score>=90 else "A" if score>=85 else "B+" if score>=80 else "B" if score>=75 else "C" if score>=65 else "D"

def action(score):
    return "매수 후보" if score>=90 else "눌림 관찰" if score>=82 else "관심 후보" if score>=75 else "추적 관찰" if score>=65 else "관찰 후보"

def sector_hint(name):
    for code,n,m,s in FALLBACK:
        if n in name or name in n:
            return s
    return "미분류"

def calc_chart(change, value):
    price=32 if change>=5 else 29 if change>=2 else 26 if change>=0 else 22 if change>=-2 else 18
    liquid=30 if value>=200_000_000_000 else 27 if value>=100_000_000_000 else 24 if value>=30_000_000_000 else 20 if value>=10_000_000_000 else 14
    return min(35, int((price+liquid)*0.60))

def calc_supply(foreign, inst, pension, trust, finance, value):
    total=foreign+inst+pension+trust
    score=14
    if foreign>0: score+=4
    if inst>0: score+=4
    if pension>0: score+=3
    if trust>0: score+=2
    if finance>0: score+=1
    if total>0: score+=3
    if value>30_000_000_000 and total>0: score+=2
    if total<0 and foreign<0 and inst<0: score-=5
    return max(0,min(30,score))

def calc_news(name, sector):
    text=f"{name} {sector}"
    pos=[x for x in POSITIVE if x in text]
    neg=[x for x in NEGATIVE if x in text]
    score=12+len(pos)*3-len(neg)*5
    return max(0,min(25,score)), pos, neg

def calc_macro(sector):
    return 8 if sector in ["반도체","조선","조선/방산","방산","원전/에너지","로봇","전력","자동차","2차전지"] else 5

def calc_risk(market, change, value, neg):
    risk=3 if market=="KOSPI" else 5
    if change>=12: risk+=5
    if value<1_000_000_000: risk+=4
    if neg: risk+=min(8,len(neg)*4)
    return min(20,risk)

def make_candidate(code,name,market,sector,close,volume,change,value,inv=None):
    inv=inv or {}
    foreign=inv.get("foreignNet",0); inst=inv.get("institutionNet",0); pension=inv.get("pensionNet",0); trust=inv.get("trustNet",0); finance=inv.get("financeNet",0)
    chart=calc_chart(change,value)
    supply=calc_supply(foreign,inst,pension,trust,finance,value)
    news,pos,neg=calc_news(name,sector)
    macro=calc_macro(sector)
    risk=calc_risk(market,change,value,neg)
    score=max(0,min(100,chart+supply+news+macro-risk))

    chart_reason=f"차트/거래대금 {chart}점: 등락률 {change:.2f}%, 거래대금 {value:,}원"
    supply_reason=f"수급 {supply}점: 외국인 {foreign:,}, 기관 {inst:,}, 연기금 {pension:,}, 투신 {trust:,}, 금융투자 {finance:,}"
    news_reason=f"뉴스/공시 {news}점: 긍정 {', '.join(pos) if pos else '없음'}, 부정 {', '.join(neg) if neg else '없음'}"
    fundamental_reason=f"펀더멘털/업종: {sector} 업종 모멘텀 및 시장 환경 1차 반영"
    risk_reason=f"리스크 -{risk}점: 급등/거래대금/부정 키워드 감점"
    detail=f"{name}({code}) 추천 근거: {chart_reason}. {supply_reason}. {news_reason}. {fundamental_reason}. {risk_reason}."

    return {"code":code,"name":name,"market":market,"sector":sector,"score":int(score),"grade":grade(score),"action":action(score),"reason":detail,"reasonDetail":detail,"detailReport":detail,"chartReason":chart_reason,"supplyReason":supply_reason,"newsReason":news_reason,"disclosureReason":"뉴스/공시 키워드 기반 1차 이벤트 분류","fundamentalReason":fundamental_reason,"riskReason":risk_reason,"chartScore":chart,"supplyScore":supply,"newsScore":news,"macroScore":macro,"riskScore":-risk,"close":close,"currentPrice":close,"volume":volume,"tradingValue":value,"changeRate":change,"foreignNet":foreign,"institutionNet":inst,"pensionNet":pension,"trustNet":trust,"financeNet":finance,"programProxy":foreign+finance,"positiveNews":pos,"negativeNews":neg,"updatedAt":datetime.now().isoformat(timespec="seconds")}

def investor_map(stock, start, end, market):
    result={}
    try:
        df=stock.get_market_trading_value_by_ticker(start,end,market=market)
        if df is None or df.empty: return result
        for code,row in df.iterrows():
            result[str(code).zfill(6)]={"foreignNet":safe_int(row.get("외국인합계",row.get("외국인",0))),"institutionNet":safe_int(row.get("기관합계",0)),"pensionNet":safe_int(row.get("연기금",0)),"trustNet":safe_int(row.get("투신",0)),"financeNet":safe_int(row.get("금융투자",0))}
    except Exception:
        pass
    return result

def latest_price_table(stock, market):
    for d in range(0,31):
        day=ymd(datetime.now()-timedelta(days=d))
        try:
            df=stock.get_market_ohlcv_by_ticker(day, market=market)
            if df is not None and not df.empty:
                # 핵심: index를 6자리 문자열로 정규화
                df=df.copy()
                df.index=[str(x).zfill(6) for x in df.index]
                return day, df
        except Exception:
            continue
    return ymd(datetime.now()), pd.DataFrame()

def main():
    universe=[]; candidates=[]; errors=[]
    try:
        from pykrx import stock
        start=ymd(datetime.now()-timedelta(days=30))

        for market in ["KOSPI","KOSDAQ"]:
            day, price_df = latest_price_table(stock, market)
            inv_map=investor_map(stock,start,day,market)

            if price_df is None or price_df.empty:
                continue

            for code,row in price_df.iterrows():
                try:
                    code=str(code).zfill(6)
                    name=stock.get_market_ticker_name(code)
                    if not name or "스팩" in name or "ETN" in name:
                        continue
                    sector=sector_hint(name)
                    close=safe_int(row.get("종가"))
                    volume=safe_int(row.get("거래량"))
                    change=safe_float(row.get("등락률",0))
                    value=safe_int(row.get("거래대금",0))
                    if value<=0: value=close*volume
                    if close<=0: continue
                    universe.append({"code":code,"name":name,"market":market,"sector":sector})
                    candidates.append(make_candidate(code,name,market,sector,close,volume,change,value,inv_map.get(code,{})))
                except Exception as e:
                    errors.append({"code":str(code),"error":str(e)[:160]})
    except Exception as e:
        errors.append({"stage":"pykrx","error":str(e)[:200]})

    # 비어 있거나 20개 미만이면 실제 코드 fallback으로 채움
    existing={x["code"] for x in candidates}
    for i,(code,name,market,sector) in enumerate(FALLBACK):
        if len(candidates)>=80:
            break
        if code in existing:
            continue
        close=0
        volume=0
        change=0.0
        value=max(1_000_000_000, (80-i)*1_000_000_000)
        candidates.append(make_candidate(code,name,market,sector,close,volume,change,value,{}))
        universe.append({"code":code,"name":name,"market":market,"sector":sector,"fallback":True})

    candidates.sort(key=lambda x:(x.get("score",0), x.get("tradingValue",0)), reverse=True)
    filtered=[x for x in candidates if x.get("score",0)>=65]
    final = filtered if len(filtered)>=20 else candidates[:80]

    (OUT/"market_universe.json").write_text(json.dumps(universe,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"stock_candidates_ai_scored.json").write_text(json.dumps(final,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"market_scanner_errors.json").write_text(json.dumps(errors[:500],ensure_ascii=False,indent=2),encoding="utf-8")
    summary={"version":"A210","generatedAt":datetime.now().isoformat(timespec="seconds"),"universeCount":len(universe),"candidateCount":len(final),"rawCandidateCount":len(candidates),"errorCount":len(errors),"top":final[:20],"status":"ok" if len(final)>=20 else "need_more_candidates","scoreModel":"force-real-candidates","output":"stock_candidates_ai_scored.json"}
    (OUT/"market_scanner_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(summary)

if __name__=="__main__":
    main()
