# scripts/build_all_stock_lookup_a250.py
# A250: 추천 후보 외 종목 조회용 기본 유니버스 생성
import json
from pathlib import Path
from datetime import datetime

DATA = Path("data")
OUT = DATA / "all_stock_lookup_a250.json"
SUMMARY = DATA / "market_scanner_summary.json"
CAND = DATA / "stock_candidates_ai_scored.json"

BASE = [
("005930","삼성전자","KOSPI","반도체"),("000660","SK하이닉스","KOSPI","반도체"),
("042660","한화오션","KOSPI","조선/방산"),("272210","한화시스템","KOSPI","방산"),
("329180","HD현대중공업","KOSPI","조선"),("034020","두산에너빌리티","KOSPI","원전/에너지"),
("005380","현대차","KOSPI","자동차"),("000270","기아","KOSPI","자동차"),
("105560","KB금융","KOSPI","금융"),("055550","신한지주","KOSPI","금융"),
("086790","하나금융지주","KOSPI","금융"),("316140","우리금융지주","KOSPI","금융"),
("035420","NAVER","KOSPI","인터넷"),("035720","카카오","KOSPI","인터넷"),
("047810","한국항공우주","KOSPI","방산"),("011200","HMM","KOSPI","해운"),
("008770","호텔신라","KOSPI","소비/여행"),("033780","KT&G","KOSPI","방어주"),
("196170","알테오젠","KOSDAQ","바이오"),("247540","에코프로비엠","KOSDAQ","2차전지"),
("086520","에코프로","KOSDAQ","2차전지"),("108490","로보티즈","KOSDAQ","로봇"),
("277810","레인보우로보틱스","KOSDAQ","로봇"),("039030","이오테크닉스","KOSDAQ","반도체장비")
]

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

run = datetime.now().isoformat(timespec="seconds")
pool = {}
for c,n,m,s in BASE:
    pool[c] = {"code": c, "name": n, "market": m, "sector": s, "source": "base"}
for x in norm(load(CAND, [])):
    if isinstance(x, dict):
        code = str(x.get("code") or x.get("stockCode") or x.get("ticker") or "").zfill(6)
        name = str(x.get("name") or "")
        if code and code != "000000" and name:
            pool[code] = {
                "code": code,
                "name": name,
                "market": x.get("market", ""),
                "sector": x.get("sector", ""),
                "source": "candidate",
            }
items = sorted(pool.values(), key=lambda x: (x.get("market",""), x.get("name","")))
save(OUT, {"version": "A250", "generatedAt": run, "count": len(items), "items": items})
summary = load(SUMMARY, {})
if not isinstance(summary, dict): summary = {}
summary.update({
    "version": "A250",
    "generatedAt": run,
    "status": "all_stock_detail_search",
    "allStockLookupCount": len(items),
    "outputLookup": "all_stock_lookup_a250.json",
})
save(SUMMARY, summary)
print(json.dumps(summary, ensure_ascii=False, indent=2))
