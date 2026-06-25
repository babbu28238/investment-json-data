# scripts/integrated_macro_supply_a417.py
# A417: 매크로 + 수급 실반영 통합 후처리
# - KRX/pykrx 수급 시도
# - 실패하면 기존 reportItems/reportSummary에 들어있는 네이버 거래원 문구에서 외국계추정합을 부분수급으로 복구
# - 매크로 조정점수를 종목별 점수에 반영
import json, re
from pathlib import Path
from datetime import datetime, timedelta

DATA = Path("data")
SRC = DATA / "realtime_recommendations_a405.json"
FALLBACK = DATA / "stock_candidates_ai_scored.json"
MACRO = DATA / "market_macro_environment.json"
OUT = DATA / "realtime_recommendations_a405.json"
CAND = DATA / "stock_candidates_ai_scored.json"
SUMMARY = DATA / "market_scanner_summary.json"
A417 = DATA / "integrated_macro_supply_a417.json"
DEBUG = DATA / "integrated_macro_supply_debug_a417.json"

def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default

def save(path, data):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def norm(raw):
    if isinstance(raw, list): return raw
    if isinstance(raw, dict):
        for k in ["candidates", "data", "items", "stocks", "top"]:
            if isinstance(raw.get(k), list): return raw[k]
    return []

def si(x):
    try: return int(float(str(x).replace(",", "").replace("+", "").replace("원", "").strip()))
    except Exception: return 0

def clamp(x): return max(0, min(100, int(round(x))))

def fallback_macro():
    return {
        "overallMacroScore": 54,
        "overallMarketView": "중립 / 관망",
        "macroItems": [
            {"category":"금리","score":60,"marketImpact":"장기금리 하락은 반도체, 바이오, 플랫폼 등 성장주 밸류에이션에 긍정적입니다.","favoredSectors":["반도체","바이오","플랫폼","2차전지"],"unfavorableSectors":["은행","보험"]},
            {"category":"환율","score":55,"marketImpact":"환율 상승은 수출주에는 긍정적이나 외국인 수급에는 부담입니다.","favoredSectors":["반도체","자동차","조선","방산"],"unfavorableSectors":["항공","여행"]},
            {"category":"수출입","score":60,"marketImpact":"반도체 수출 증가율 개선은 반도체 대형주와 장비주에 우호적입니다.","favoredSectors":["반도체","자동차","조선","IT부품"],"unfavorableSectors":["내수 방어주"]},
            {"category":"정책/중앙은행","score":60,"marketImpact":"정책 지원은 방산, 원전, AI, 로봇, 반도체 업종에 긍정적입니다.","favoredSectors":["방산","원전","AI","로봇","반도체"],"unfavorableSectors":["플랫폼"]}
        ]
    }

def date_range(days=10):
    end = datetime.now()
    start = end - timedelta(days=days)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

def pick_col(df, keys):
    for key in keys:
        for col in df.columns:
            if key in str(col):
                return col
    return None

def krx_supply(code):
    debug=[]
    try:
        from pykrx import stock
        start,end=date_range(10)
        for detail in [True, False]:
            try:
                df=stock.get_market_trading_value_by_date(start,end,code,detail=detail)
                debug.append({"method":f"value_detail_{detail}","ok":True,"rows":0 if df is None else len(df),"cols":[] if df is None else [str(c) for c in df.columns]})
                if df is None or len(df)==0: continue
                tail=df.tail(5)
                fc=pick_col(tail,["외국인합계","외국인"])
                ic=pick_col(tail,["기관합계","기관"])
                pc=pick_col(tail,["연기금","연기금등"])
                f=int(tail[fc].sum()) if fc else 0
                i=int(tail[ic].sum()) if ic else 0
                p=int(tail[pc].sum()) if pc else 0
                if f or i or p:
                    return f,i,p,"수집성공",f"pykrx:{start}-{end}:detail={detail}",debug
            except Exception as e:
                debug.append({"method":f"value_detail_{detail}","ok":False,"error":str(e)[:150]})
    except Exception as e:
        debug.append({"method":"pykrx_import","ok":False,"error":str(e)[:150]})
    return 0,0,0,"수집실패","pykrx",debug

def parse_foreign_from_report(c):
    blob = " ".join([str(c.get("reportSummary",""))] + [str(x) for x in c.get("reportItems",[])])
    # Example: 외국계추정합 9,162,492 -4,510,498 4,651,994
    # Use first signed number after 외국계추정합 as net estimate when available
    m = re.search(r'외국계추정합\s+[0-9,]+\s+([+\-]?[0-9,]+)\s+[0-9,]+', blob)
    if m:
        return si(m.group(1)), "네이버 거래원 정보의 외국계추정합 순매수 추정치를 부분 수급으로 반영했습니다."
    # Alternative: if context has 외국계추정합 and signed number anywhere close
    m = re.search(r'외국계추정합.{0,80}?([+\-][0-9,]+)', blob)
    if m:
        return si(m.group(1)), "네이버 거래원 정보의 외국계추정합 부호값을 부분 수급으로 반영했습니다."
    return 0, ""

def supply_score(f,i,p,status):
    if status == "수집실패": return 50
    score=50
    for v,w in [(f,18),(i,18),(p,12)]:
        if v>0: score+=w
        elif v<0: score-=w
    return clamp(score)

def macro_adjust(c, macro):
    sector = f"{c.get('sector','')} {c.get('name','')}"
    adj=0
    reasons=[]
    for item in macro.get("macroItems",[]):
        cat=item.get("category","")
        score=si(item.get("score"))
        impact=item.get("marketImpact","")
        favored=item.get("favoredSectors",[]) or []
        unfav=item.get("unfavorableSectors",[]) or []
        if any(str(s) in sector for s in favored):
            add=8 if score>=80 else 5 if score>=60 else 2 if score>=40 else 0
            if add:
                adj+=add
                reasons.append(f"{cat}: {impact}")
        if any(str(s) in sector for s in unfav):
            minus=-8 if score<20 else -5 if score<40 else -2 if score<60 else 0
            if minus:
                adj+=minus
                reasons.append(f"{cat}: {impact}")
    view=macro.get("overallMarketView","")
    mode={"공격적 매수 가능":5,"선별 매수":2,"중립 / 관망":0,"방어적 운용":-5,"리스크 관리 우선":-10}.get(view,0)
    return max(-15,min(15,adj+mode)), list(dict.fromkeys(reasons))[:6]

def final_score(c):
    q=si(c.get("quantScore")) or 50
    s=si(c.get("supplyScore")) or 50
    co=si(c.get("companyScore")) or 50
    ev=si(c.get("eventScore")) or si(c.get("newsScore")) or 50
    report=si(c.get("reportScore")) or 50
    chart=si(c.get("chartScore")) or 50
    ma=si(c.get("macroScore")) or 50
    ri=si(c.get("riskScore")) or 50
    base=clamp(q*.18+s*.18+co*.18+ev*.14+report*.10+chart*.10+ma*.07+ri*.05)
    return clamp(base + si(c.get("macroAdjustmentScore")))

def main():
    run=datetime.now().isoformat(timespec="seconds")
    data=norm(load(SRC,[])) or norm(load(FALLBACK,[]))
    macro=load(MACRO, fallback_macro())
    if not isinstance(macro,dict): macro=fallback_macro()

    ok=partial=fail=0
    macro_applied=0
    debug=[]
    out=[]
    for c in data:
        if not isinstance(c,dict): continue
        code=str(c.get("code") or c.get("stockCode") or "").zfill(6)
        name=str(c.get("name") or c.get("stockName") or "")
        f,i,p,status,source,kdebug=krx_supply(code)
        note=""
        if status!="수집성공":
            f2,note=parse_foreign_from_report(c)
            if f2:
                f=f2; i=0; p=0; status="부분수집"; source="naver_broker_foreign_estimate"; partial+=1
            else:
                fail+=1
        else:
            ok+=1
        score=supply_score(f,i,p,status)
        c["foreignNetBuy"]=f
        c["institutionNetBuy"]=i
        c["pensionNetBuy"]=p
        c["supplyStatus"]=status
        c["supplySource"]=source
        c["supplyScore"]=score
        if status=="수집성공":
            c["supplyReason"]=f"최근 5거래일 KRX 기준 외국인 {f:,}, 기관 {i:,}, 연기금 {p:,}을 반영했습니다."
            c["supplyOpinion"]=f"최근 5거래일 KRX 기준 외국인 {f:,}, 기관 {i:,}, 연기금 {p:,}을 반영해 수급 점수 {score}점으로 평가했습니다."
        elif status=="부분수집":
            c["supplyReason"]=f"KRX 수급 수집 실패 후 {note} 외국계 추정 순매수 {f:,}을 반영했습니다. 기관·연기금은 원자료가 없어 0으로 처리했습니다."
            c["supplyOpinion"]=f"외국계 추정 순매수 {f:,}을 부분 반영해 수급 점수 {score}점으로 평가했습니다. 기관·연기금 원자료는 미수집 상태입니다."
        else:
            c["supplyReason"]="KRX 및 네이버 거래원 문구에서 수급 원자료를 확인하지 못했습니다."
            c["supplyOpinion"]="수급 원자료 수집 실패로 중립 50점으로 평가했습니다."

        adj,reasons=macro_adjust(c,macro)
        c["macroAdjustmentScore"]=adj
        c["macroReasons"]=reasons
        if reasons or adj!=0: macro_applied+=1
        c["score"]=final_score(c)
        c["realtimeScore"]=c["score"]
        c["recommendationReason"]=f"{name}: 수급({status})과 매크로 조정점수 {adj:+d}점을 반영한 전문가 패널 종합점수 {c['score']}점입니다."
        c["reason"]=c["recommendationReason"]
        c["updatedAt"]=run
        c["targetEngineVersion"]="A417"
        out.append(c)
        debug.append({"code":code,"name":name,"supplyStatus":status,"supplyScore":score,"foreignNetBuy":f,"institutionNetBuy":i,"pensionNetBuy":p,"macroAdjustmentScore":adj,"macroReasons":reasons,"source":source,"krxDebug":kdebug[:3]})

    out.sort(key=lambda x:x.get("realtimeScore",x.get("score",0)), reverse=True)
    save(OUT,out); save(CAND,out)

    summary=load(SUMMARY,{})
    if not isinstance(summary,dict): summary={}
    summary.update({
        "version":"A417",
        "generatedAt":run,
        "status":"integrated_macro_supply",
        "candidateCount":len(out),
        "krxSupplyCollectedCount":ok,
        "partialSupplyCollectedCount":partial,
        "supplyFailedCount":fail,
        "macroAppliedCount":macro_applied,
        "overallMacroScore": macro.get("overallMacroScore", 50),
        "overallMarketView": macro.get("overallMarketView", "중립 / 관망"),
        "output":"realtime_recommendations_a405.json"
    })
    save(SUMMARY,summary)
    save(A417,{"summary":summary,"top":out[:50]})
    save(DEBUG,{"summary":summary,"items":debug})
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
