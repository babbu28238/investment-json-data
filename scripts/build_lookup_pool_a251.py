# scripts/build_lookup_pool_a251.py
# A251: 추천 후보/기본 종목 통합 조회 풀 확장
import json
from pathlib import Path
from datetime import datetime

DATA = Path("data")
CAND = DATA / "stock_candidates_ai_scored.json"
OUT = DATA / "all_stock_lookup_a251.json"
SUMMARY = DATA / "market_scanner_summary.json"

BASE = [
("005930","삼성전자","KOSPI","반도체"),("000660","SK하이닉스","KOSPI","반도체"),
("005490","POSCO홀딩스","KOSPI","철강/2차전지"),("373220","LG에너지솔루션","KOSPI","2차전지"),
("051910","LG화학","KOSPI","화학/2차전지"),("006400","삼성SDI","KOSPI","2차전지"),
("207940","삼성바이오로직스","KOSPI","바이오"),("068270","셀트리온","KOSPI","바이오"),
("042660","한화오션","KOSPI","조선/방산"),("272210","한화시스템","KOSPI","방산"),
("012450","한화에어로스페이스","KOSPI","방산/항공"),("047810","한국항공우주","KOSPI","방산"),
("064350","현대로템","KOSPI","방산/철도"),("329180","HD현대중공업","KOSPI","조선"),
("010140","삼성중공업","KOSPI","조선"),("010620","HD현대미포","KOSPI","조선"),
("009540","HD한국조선해양","KOSPI","조선지주"),("034020","두산에너빌리티","KOSPI","원전/에너지"),
("267260","HD현대일렉트릭","KOSPI","전력기기"),("010120","LS ELECTRIC","KOSPI","전력기기"),
("298040","효성중공업","KOSPI","전력기기"),("005380","현대차","KOSPI","자동차"),
("000270","기아","KOSPI","자동차"),("012330","현대모비스","KOSPI","자동차부품"),
("105560","KB금융","KOSPI","금융"),("055550","신한지주","KOSPI","금융"),
("086790","하나금융지주","KOSPI","금융"),("316140","우리금융지주","KOSPI","금융"),
("035420","NAVER","KOSPI","인터넷"),("035720","카카오","KOSPI","인터넷"),
("033780","KT&G","KOSPI","방어주"),("011200","HMM","KOSPI","해운"),
("008770","호텔신라","KOSPI","소비/여행"),("352820","하이브","KOSPI","엔터"),
("259960","크래프톤","KOSPI","게임"),("402340","SK스퀘어","KOSPI","지주/반도체"),
("006800","미래에셋증권","KOSPI","증권"),("003690","코리안리","KOSPI","보험"),
("078930","GS","KOSPI","지주/에너지"),("112610","씨에스윈드","KOSPI","풍력"),
("196170","알테오젠","KOSDAQ","바이오"),("247540","에코프로비엠","KOSDAQ","2차전지"),
("086520","에코프로","KOSDAQ","2차전지"),("108490","로보티즈","KOSDAQ","로봇"),
("277810","레인보우로보틱스","KOSDAQ","로봇"),("090360","로보스타","KOSDAQ","로봇"),
("277880","티로보틱스","KOSDAQ","로봇"),("039030","이오테크닉스","KOSDAQ","반도체장비"),
("322510","제이엘케이","KOSDAQ","AI의료"),("456190","큐라클","KOSDAQ","바이오")
]

def load(path, default):
    try: return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception: return default
def save(path, data):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
def norm(raw):
    if isinstance(raw, list): return raw
    if isinstance(raw, dict):
        for k in ["candidates","data","items","stocks","top"]:
            if isinstance(raw.get(k), list): return raw[k]
    return []

run = datetime.now().isoformat(timespec="seconds")
pool = {c: {"code": c, "name": n, "market": m, "sector": s, "source": "base"} for c,n,m,s in BASE}
for x in norm(load(CAND, [])):
    if isinstance(x, dict):
        code = str(x.get("code") or x.get("stockCode") or x.get("ticker") or "").zfill(6)
        name = str(x.get("name") or "")
        if code and code != "000000" and name:
            pool[code] = {"code": code, "name": name, "market": x.get("market",""), "sector": x.get("sector",""), "source": "candidate"}
items = sorted(pool.values(), key=lambda x: (x.get("market",""), x.get("name","")))
save(OUT, {"version": "A251", "generatedAt": run, "count": len(items), "items": items})
summary = load(SUMMARY, {})
if not isinstance(summary, dict): summary = {}
summary.update({"version": "A251", "generatedAt": run, "status": "lookup_pool_expand", "allStockLookupCount": len(items), "outputLookup": "all_stock_lookup_a251.json"})
save(SUMMARY, summary)
print(json.dumps(summary, ensure_ascii=False, indent=2))
