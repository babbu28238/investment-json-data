import json
from pathlib import Path
from datetime import datetime
DATA=Path("data"); SRC=DATA/"realtime_recommendations_a405.json"; FALLBACK=DATA/"stock_candidates_ai_scored.json"; OUT=SRC; CAND=FALLBACK; SUMMARY=DATA/"market_scanner_summary.json"; DEBUG=DATA/"data_completeness_macro_a410.json"
SECTOR_MACRO={"조선":("조선 섹터는 선박 수주, LNG선, 방산/해양플랜트 사이클을 우호 요인으로 평가합니다.",72),"방산":("방산 섹터는 국방비 확대, 수출 계약, 지정학 리스크 확대를 우호 요인으로 평가합니다.",75),"원전":("원전/에너지 섹터는 전력 수요 증가, 원전 정책, 에너지 안보를 우호 요인으로 평가합니다.",70),"반도체":("반도체 섹터는 AI 서버, 메모리 업황, 수출 회복을 핵심 변수로 평가합니다.",68),"로봇":("로봇 섹터는 자동화 투자와 성장성은 우호적이나 밸류에이션 부담을 함께 평가합니다.",64),"2차전지":("2차전지 섹터는 전기차 수요와 소재 가격 변동성이 커 중립 이하로 평가합니다.",55),"바이오":("바이오 섹터는 임상/허가 이벤트 민감도가 높아 리스크와 이벤트를 함께 평가합니다.",58),"금융":("금융 섹터는 금리, 배당, 자본환원 정책을 핵심 변수로 평가합니다.",62),"자동차":("자동차 섹터는 환율, 수출, 관세, 전기차 전환 속도를 핵심 변수로 평가합니다.",60),"인터넷":("인터넷 섹터는 광고 경기, AI 투자비, 플랫폼 규제 가능성을 함께 평가합니다.",58)}
def load(p,d):
    try: return json.loads(p.read_text(encoding="utf-8")) if p.exists() else d
    except Exception: return d
def save(p,d): p.parent.mkdir(exist_ok=True); p.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding="utf-8")
def norm(x):
    if isinstance(x,list): return x
    if isinstance(x,dict):
        for k in ["candidates","data","items","stocks","top"]:
            if isinstance(x.get(k),list): return x[k]
    return []
def si(x):
    try: return int(float(str(x).replace(",","").replace("원","")))
    except Exception: return 0
def missing(t):
    t=str(t or "").strip(); return not t or "수집 결과 없음" in t or "수집 실패" in t
def macro_for(sector):
    sector=str(sector or "")
    for k,v in SECTOR_MACRO.items():
        if k in sector: return v
    return ("섹터/매크로 원자료가 충분하지 않아 중립 50점으로 평가했습니다.",50)
def main():
    run=datetime.now().isoformat(timespec="seconds"); data=norm(load(SRC,[])) or norm(load(FALLBACK,[])); out=[]; nf=rf=mf=sf=0
    for c in data:
        if not isinstance(c,dict): continue
        if missing(c.get("newsSummary")):
            c["newsSummary"]="최근 확인된 종목 관련 뉴스가 없습니다."; c["newsScore"]=si(c.get("newsScore")) or 50; c["newsScoreReason"]="최근 확인된 종목 관련 뉴스가 없어 뉴스 점수는 중립 50점으로 평가했습니다."; nf+=1
        if missing(c.get("reportSummary")):
            c["reportSummary"]="최근 확인된 증권사 리포트/목표가 문맥이 없습니다."; c["reportScore"]=si(c.get("reportScore")) or 50; c["reportScoreReason"]="최근 확인된 리포트/목표가 문맥이 없어 리포트 점수는 중립 50점으로 평가했습니다."; rf+=1
        if not c.get("macroOpinion") or si(c.get("macroScore"))==0:
            op,sc=macro_for(c.get("sector","")); c["macroOpinion"]=op; c["macroScore"]=sc; mf+=1
        if not c.get("supplyOpinion") or si(c.get("supplyScore"))==0:
            c["supplyOpinion"]="수급 원자료가 아직 충분하지 않아 중립 50점으로 처리했습니다."; c["supplyScore"]=50; sf+=1
        c.setdefault("eventOpinion","최근 뉴스/공시 이벤트가 충분하지 않으면 중립 평가로 처리합니다."); c.setdefault("expertSummary","퀀트, 수급, 기업분석, 뉴스/이벤트, 리포트, 차트, 매크로, 리스크 관점을 종합해 평가합니다.")
        c["updatedAt"]=run; c["targetEngineVersion"]="A410"; out.append(c)
    save(OUT,out); save(CAND,out); summary=load(SUMMARY,{}) if isinstance(load(SUMMARY,{}),dict) else {}
    summary.update({"version":"A410","generatedAt":run,"status":"data_completeness_macro","candidateCount":len(out),"newsMissingFilledCount":nf,"reportMissingFilledCount":rf,"macroFilledCount":mf,"supplyFilledCount":sf,"output":"realtime_recommendations_a405.json"})
    save(SUMMARY,summary); save(DEBUG,{"summary":summary,"items":out[:20]}); print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
