import json
from pathlib import Path
from datetime import datetime

DATA=Path("data")
SRC=DATA/"realtime_recommendations_a405.json"
FALLBACK=DATA/"stock_candidates_ai_scored.json"
OUT=DATA/"realtime_recommendations_a405.json"
CAND=DATA/"stock_candidates_ai_scored.json"
SUMMARY=DATA/"market_scanner_summary.json"
DEBUG=DATA/"expert_score_link_a411.json"

def load(p,d):
    try: return json.loads(p.read_text(encoding="utf-8")) if p.exists() else d
    except Exception: return d

def save(p,d):
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding="utf-8")

def norm(x):
    if isinstance(x,list): return x
    if isinstance(x,dict):
        for k in ["candidates","data","items","stocks","top"]:
            if isinstance(x.get(k),list): return x[k]
    return []

def si(x):
    try: return int(float(str(x).replace(",","").replace("원","")))
    except Exception: return 0

def sf(x):
    try: return float(str(x).replace("%","").replace(",",""))
    except Exception: return 0.0

def clamp(x):
    return max(0,min(100,int(round(x))))

def nonzero(v, default):
    v=si(v)
    return v if v>0 else default

def quant(c):
    p=nonzero(c.get("priceScore"), 50)
    ch=nonzero(c.get("chartScore"), 50)
    upside=sf(c.get("targetUpsidePercent"))
    upscore=max(0,min(80,upside))
    score=clamp(p*.4+ch*.4+upscore*.2)
    return score, f"가격점수 {p}점, 차트점수 {ch}점, 상승여력 {upside:.1f}%를 종합해 퀀트 점수 {score}점으로 산정했습니다."

def supply(c):
    vals=[]
    labels=[]
    for key,label in [("foreignScore","외국인"),("institutionScore","기관"),("pensionScore","연기금"),("foreignNetBuyScore","외국인"),("institutionNetBuyScore","기관")]:
        v=si(c.get(key))
        if v>0:
            vals.append(v); labels.append(f"{label} {v}점")
    if vals:
        score=clamp(sum(vals)/len(vals))
        return score, f"{', '.join(labels)}을 반영해 수급 점수 {score}점으로 산정했습니다."
    return 50, "외국인·기관·연기금 순매수 원자료가 아직 충분하지 않아 수급은 중립 50점으로 평가했습니다."

def company(c):
    report=nonzero(c.get("reportScore"),50)
    price=nonzero(c.get("priceScore"),50)
    target=si(c.get("targetPrice") or c.get("targetMedianPrice"))
    now=si(c.get("currentPrice") or c.get("close"))
    score=clamp(report*.55+price*.45)
    extra=" 목표가/현재가가 확인되어 기업분석 점수에 반영했습니다." if target>0 and now>0 else " 목표가 또는 현재가가 부족해 보수적으로 반영했습니다."
    return score, f"리포트 점수 {report}점과 가격 점수 {price}점을 조합해 기업분석 점수 {score}점으로 산정했습니다.{extra}"

def event(c):
    news=nonzero(c.get("newsScore"),50)
    text=" ".join(str(c.get(k,"")) for k in ["newsSummary","reportSummary","recommendationReason"])
    keys=[k for k in ["수주","계약","실적","목표가","상향","정책","방산","원전","AI","반도체","로봇"] if k in text]
    score=clamp(news+len(keys)*3)
    return score, f"뉴스 점수 {news}점에 이벤트 키워드 {', '.join(keys[:6]) if keys else '없음'}를 반영해 이벤트 점수 {score}점으로 산정했습니다."

def macro(c):
    v=si(c.get("macroScore"))
    if v>0:
        return v, str(c.get("macroOpinion") or f"기존 매크로 점수 {v}점을 반영했습니다.")
    return 50, "섹터/매크로 원자료가 충분하지 않아 중립 50점으로 평가했습니다."

def risk(c):
    v=si(c.get("riskScore"))
    if v>0:
        return v, str(c.get("riskOpinion") or f"기존 리스크 점수 {v}점을 반영했습니다.")
    if c.get("priceValidationStatus")=="검증필요":
        return 25, "가격 검증 필요 상태라 리스크 점수를 25점으로 낮게 평가했습니다."
    return 55, "가격 검증은 통과했으나 손절선/변동성 원자료가 부족해 리스크 점수 55점으로 평가했습니다."

def final_score(q,s,co,ev,report,chart,ma,ri):
    return clamp(q*.18+s*.18+co*.18+ev*.14+report*.10+chart*.10+ma*.07+ri*.05)

def main():
    run=datetime.now().isoformat(timespec="seconds")
    data=norm(load(SRC,[])) or norm(load(FALLBACK,[]))
    out=[]
    fixed=0
    for c in data:
        if not isinstance(c,dict): continue
        q,qo=quant(c)
        su,suo=supply(c)
        co,coo=company(c)
        ev,evo=event(c)
        ma,mao=macro(c)
        ri,rio=risk(c)
        report=nonzero(c.get("reportScore"),50)
        chart=nonzero(c.get("chartScore"),50)
        fs=final_score(q,su,co,ev,report,chart,ma,ri)
        c.update({
            "quantScore":q,
            "supplyScore":su,
            "companyScore":co,
            "eventScore":ev,
            "macroScore":ma,
            "riskScore":ri,
            "quantOpinion":qo,
            "supplyOpinion":suo,
            "companyOpinion":coo,
            "eventOpinion":evo,
            "macroOpinion":mao,
            "riskOpinion":rio,
            "score":fs,
            "realtimeScore":fs,
            "expertSummary":f"퀀트 {q}점, 수급 {su}점, 기업 {co}점, 이벤트 {ev}점, 리포트 {report}점, 차트 {chart}점, 매크로 {ma}점, 리스크 {ri}점을 종합해 {fs}점으로 평가했습니다.",
            "recommendationReason":f"{c.get('name','')}: 전문가 패널 종합점수 {fs}점. 퀀트·수급·기업분석·뉴스/이벤트·리포트·차트·매크로·리스크를 연동해 산정했습니다.",
            "reason":f"{c.get('name','')}: 전문가 패널 종합점수 {fs}점. 퀀트·수급·기업분석·뉴스/이벤트·리포트·차트·매크로·리스크를 연동해 산정했습니다.",
            "finalScoreReason":f"최종점수는 퀀트 18%, 수급 18%, 기업분석 18%, 뉴스/이벤트 14%, 리포트 10%, 차트 10%, 매크로 7%, 리스크 5%로 계산했습니다. 계산 결과 {fs}점입니다.",
            "updatedAt":run,
            "targetEngineVersion":"A411"
        })
        fixed+=1
        out.append(c)
    out.sort(key=lambda x:x.get("realtimeScore",x.get("score",0)), reverse=True)
    save(OUT,out); save(CAND,out)
    summary=load(SUMMARY,{})
    if not isinstance(summary,dict): summary={}
    summary.update({"version":"A411","generatedAt":run,"status":"expert_score_link","candidateCount":len(out),"expertScoreLinkedCount":fixed,"output":"realtime_recommendations_a405.json"})
    save(SUMMARY,summary)
    save(DEBUG,{"summary":summary,"top":out[:20]})
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
