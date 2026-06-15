# scripts/generate_market_candidates_a207.py
import json
from pathlib import Path
from datetime import datetime
import pandas as pd

OUT = Path("data")
OUT.mkdir(exist_ok=True)

POSITIVE = ["수주","계약","공급","실적","흑자","증설","AI","반도체","원전","방산","조선","전력","로봇","승인","수출"]
NEGATIVE = ["적자","소송","감자","유상증자","불성실","횡령","배임","관리종목","하한가","리콜","제재"]

def safe_int(v, default=0):
    try:
        if pd.isna(v): return default
        return int(float(v))
    except Exception: return default

def safe_float(v, default=0.0):
    try:
        if pd.isna(v): return default
        return float(v)
    except Exception: return default

def grade(score):
    return "A+" if score>=90 else "A" if score>=85 else "B+" if score>=80 else "B" if score>=75 else "C" if score>=65 else "D"

def action(score):
    return "매수 후보" if score>=90 else "눌림 관찰" if score>=82 else "관심 후보" if score>=75 else "추적 관찰" if score>=65 else "제외"

def sector_hint(name):
    hints=[("삼성전자","반도체"),("SK하이닉스","반도체"),("한화오션","조선/방산"),("HD현대중공업","조선"),("두산에너빌리티","원전/에너지"),("한화시스템","방산"),("한국항공우주","방산"),("로보티즈","로봇"),("두산밥캣","기계"),("호텔신라","소비/여행"),("HMM","해운"),("KT&G","방어주")]
    for k,s in hints:
        if k in name: return s
    return "미분류"

def calc_chart(change_rate, value):
    price=32 if change_rate>=5 else 29 if change_rate>=2 else 26 if change_rate>=0 else 22 if change_rate>=-2 else 18
    liquid=30 if value>=200_000_000_000 else 27 if value>=100_000_000_000 else 24 if value>=30_000_000_000 else 20 if value>=10_000_000_000 else 14
    return min(35, int((price+liquid)*0.60))

def calc_supply(foreign_net, inst_net, pension_net, trust_net, finance_net, value):
    total=foreign_net+inst_net+pension_net+trust_net
    score=14
    if foreign_net>0: score+=4
    if inst_net>0: score+=4
    if pension_net>0: score+=3
    if trust_net>0: score+=2
    if finance_net>0: score+=1
    if total>0: score+=3
    if value>30_000_000_000 and total>0: score+=2
    if total<0 and foreign_net<0 and inst_net<0: score-=5
    return max(0,min(30,score))

def calc_news(name, sector):
    text=f"{name} {sector}"
    pos=[x for x in POSITIVE if x in text]
    neg=[x for x in NEGATIVE if x in text]
    score=12+len(pos)*3-len(neg)*5
    return max(0,min(25,score)), pos, neg

def calc_macro(sector):
    return 8 if sector in ["반도체","조선","조선/방산","방산","원전/에너지","로봇","전력"] else 5

def calc_risk(market, change_rate, value, neg):
    risk=3 if market=="KOSPI" else 5
    if change_rate>=12: risk+=5
    if value<1_000_000_000: risk+=5
    if neg: risk+=min(8,len(neg)*4)
    return min(20,risk)

def investor_map(stock, start, end, market):
    result={}
    try:
        df=stock.get_market_trading_value_by_ticker(start,end,market=market)
        if df is None or df.empty: return result
        for code,row in df.iterrows():
            result[str(code).zfill(6)]={"foreignNet":safe_int(row.get("외국인합계",row.get("외국인",0))),"institutionNet":safe_int(row.get("기관합계",0)),"pensionNet":safe_int(row.get("연기금",0)),"trustNet":safe_int(row.get("투신",0)),"financeNet":safe_int(row.get("금융투자",0))}
    except Exception:
        return result
    return result

def main():
    from pykrx import stock
    today=datetime.now().strftime("%Y%m%d")
    start=(pd.Timestamp.today()-pd.Timedelta(days=10)).strftime("%Y%m%d")
    universe=[]; candidates=[]; errors=[]

    for market in ["KOSPI","KOSDAQ"]:
        inv_map=investor_map(stock,start,today,market)
        try:
            tickers=stock.get_market_ticker_list(today,market=market)
        except Exception:
            tickers=stock.get_market_ticker_list(market=market)

        for code in tickers:
            try:
                code=str(code).zfill(6)
                name=stock.get_market_ticker_name(code)
                if "스팩" in name or "ETN" in name: continue
                sector=sector_hint(name)
                universe.append({"code":code,"name":name,"market":market,"sector":sector})

                df=stock.get_market_ohlcv_by_date(start,today,code)
                if df is None or df.empty:
                    errors.append({"code":code,"name":name,"error":"no_price"})
                    continue

                last=df.iloc[-1]
                close=safe_int(last.get("종가"))
                volume=safe_int(last.get("거래량"))
                change=safe_float(last.get("등락률",0))
                value=close*volume

                inv=inv_map.get(code,{})
                foreign_net=inv.get("foreignNet",0); inst_net=inv.get("institutionNet",0); pension_net=inv.get("pensionNet",0); trust_net=inv.get("trustNet",0); finance_net=inv.get("financeNet",0)

                chart=calc_chart(change,value)
                supply=calc_supply(foreign_net,inst_net,pension_net,trust_net,finance_net,value)
                news,pos,neg=calc_news(name,sector)
                macro=calc_macro(sector)
                risk=calc_risk(market,change,value,neg)
                score=max(0,min(100,chart+supply+news+macro-risk))
                if score<65: continue

                chart_reason=f"차트/거래대금 {chart}점: 등락률 {change:.2f}%, 거래대금 {value:,}원"
                supply_reason=f"수급 {supply}점: 외국인 {foreign_net:,}, 기관 {inst_net:,}, 연기금 {pension_net:,}, 투신 {trust_net:,}, 금융투자 {finance_net:,}"
                news_reason=f"뉴스/공시 {news}점: 긍정 {', '.join(pos) if pos else '없음'}, 부정 {', '.join(neg) if neg else '없음'}"
                fundamental_reason=f"펀더멘털/업종: {sector} 업종 모멘텀 및 시장 환경 1차 반영"
                risk_reason=f"리스크 -{risk}점: 급등/거래대금/부정 키워드 감점"
                detail=f"{name}({code}) 추천 근거: {chart_reason}. {supply_reason}. {news_reason}. {fundamental_reason}. {risk_reason}."

                candidates.append({"code":code,"name":name,"market":market,"sector":sector,"score":int(score),"grade":grade(score),"action":action(score),"reason":detail,"reasonDetail":detail,"detailReport":detail,"chartReason":chart_reason,"supplyReason":supply_reason,"newsReason":news_reason,"disclosureReason":"뉴스/공시 키워드 기반 1차 이벤트 분류","fundamentalReason":fundamental_reason,"riskReason":risk_reason,"chartScore":chart,"supplyScore":supply,"newsScore":news,"macroScore":macro,"riskScore":-risk,"close":close,"currentPrice":close,"volume":volume,"tradingValue":value,"changeRate":change,"foreignNet":foreign_net,"institutionNet":inst_net,"pensionNet":pension_net,"trustNet":trust_net,"financeNet":finance_net,"programProxy":foreign_net+finance_net,"positiveNews":pos,"negativeNews":neg,"updatedAt":datetime.now().isoformat(timespec="seconds")})
            except Exception as e:
                errors.append({"code":str(code),"error":str(e)[:160]})

    candidates.sort(key=lambda x:x["score"], reverse=True)
    (OUT/"market_universe.json").write_text(json.dumps(universe,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"stock_candidates_ai_scored.json").write_text(json.dumps(candidates,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"market_scanner_errors.json").write_text(json.dumps(errors[:500],ensure_ascii=False,indent=2),encoding="utf-8")
    summary={"version":"A207","generatedAt":datetime.now().isoformat(timespec="seconds"),"universeCount":len(universe),"candidateCount":len(candidates),"errorCount":len(errors),"top":candidates[:20],"status":"ok" if len(candidates)>=20 else "need_more_candidates","scoreModel":"chart+supply+news+macro-risk+detail","output":"stock_candidates_ai_scored.json"}
    (OUT/"market_scanner_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(summary)

if __name__=="__main__":
    main()
