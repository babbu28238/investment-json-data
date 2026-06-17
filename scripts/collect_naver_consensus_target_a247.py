# scripts/collect_naver_consensus_target_a247.py
# A247: 네이버증권 모바일 종목 페이지 컨센서스 목표주가 수집
import json, re, time
from pathlib import Path
from datetime import datetime
import requests
from bs4 import BeautifulSoup

DATA = Path("data")
CAND = DATA / "stock_candidates_ai_scored.json"
SUMMARY = DATA / "market_scanner_summary.json"
OUT = DATA / "naver_consensus_target_a247.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Referer": "https://m.stock.naver.com/",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

FALLBACK = [
("042660","한화오션","KOSPI","조선/방산",91,128700),
("329180","HD현대중공업","KOSPI","조선",90,300000),
("034020","두산에너빌리티","KOSPI","원전/에너지",89,105250),
("272210","한화시스템","KOSPI","방산",88,105300),
("005930","삼성전자","KOSPI","반도체",87,297500),
("000660","SK하이닉스","KOSPI","반도체",86,220000),
("047810","한국항공우주","KOSPI","방산",84,70000),
("241560","두산밥캣","KOSPI","기계",82,55000),
("005380","현대차","KOSPI","자동차",82,250000),
("000270","기아","KOSPI","자동차",81,115000),
("105560","KB금융","KOSPI","금융",80,172000),
("055550","신한지주","KOSPI","금융",79,60000),
("086790","하나금융지주","KOSPI","금융",79,70000),
("316140","우리금융지주","KOSPI","금융",78,16000),
("035420","NAVER","KOSPI","인터넷",78,220000),
("035720","카카오","KOSPI","인터넷",76,55000),
("033780","KT&G","KOSPI","방어주",76,110000),
("011200","HMM","KOSPI","해운",75,22000),
("008770","호텔신라","KOSPI","소비/여행",74,50000),
("108490","로보티즈","KOSDAQ","로봇",74,45000),
("277810","레인보우로보틱스","KOSDAQ","로봇",73,170000),
("247540","에코프로비엠","KOSDAQ","2차전지",72,130000),
("086520","에코프로","KOSDAQ","2차전지",71,70000),
("196170","알테오젠","KOSDAQ","바이오",71,300000),
("039030","이오테크닉스","KOSDAQ","반도체장비",70,180000),
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
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ["candidates", "data", "items", "stocks", "top"]:
            if isinstance(raw.get(key), list):
                return raw[key]
    return []

def valid_candidates():
    raw = norm(load(CAND, []))
    out = []
    for x in raw:
        if isinstance(x, dict):
            code = str(x.get("code") or x.get("stockCode") or x.get("ticker") or "").zfill(6)
            name = str(x.get("name") or "")
            if code and code != "000000" and name:
                y = dict(x)
                y["code"] = code
                y["name"] = name
                out.append(y)
    if out:
        return out, "stock_candidates_ai_scored.json"
    return [
        {"code": c, "name": n, "market": m, "sector": s, "score": sc, "currentPrice": p, "close": p}
        for c, n, m, s, sc, p in FALLBACK
    ], "built_in_fallback_top25"

def si(v, default=0):
    try:
        return int(float(str(v).replace(",", "").replace("원", "").strip()))
    except Exception:
        return default

def round_price(v):
    if v <= 0:
        return 0
    unit = 500 if v >= 100000 else 100 if v >= 10000 else 10
    return int(round(v / unit) * unit)

def current_price(c):
    for key in ["currentPrice", "close", "price", "lastPrice"]:
        p = si(c.get(key))
        if p > 0:
            return p
    return 0

def extract_target_from_text(text, cur):
    # 컨센서스 또는 목표주가 주변 숫자 우선
    candidates = []
    patterns = [
        r"목표주가[^0-9]{0,60}([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{5,7})",
        r"목표가[^0-9]{0,60}([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{5,7})",
        r"컨센서스[^0-9]{0,120}목표주가[^0-9]{0,60}([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{5,7})",
        r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{5,7})\s*원[^\\n]{0,80}목표주가",
    ]
    for pat in patterns:
        for m in re.findall(pat, text, re.I):
            p = si(m)
            if p >= 10000:
                candidates.append(p)
    # 현재가 대비 0.5~3.0배 범위
    good = []
    for p in candidates:
        if cur > 0 and not (cur * 0.5 <= p <= cur * 3.0):
            continue
        if p not in good:
            good.append(p)
    if not good:
        return 0, candidates
    # 네이버 컨센서스는 평균값 하나가 많으므로 후보 중 현재가보다 큰 값 우선, 없으면 첫 값
    upside = [p for p in good if cur <= 0 or p >= cur * 0.8]
    return (upside[0] if upside else good[0]), candidates

def fetch_total_page(code, cur):
    url = f"https://m.stock.naver.com/domestic/stock/{code}/total"
    try:
        res = requests.get(url, headers=HEADERS, timeout=20)
        text = res.text
        soup = BeautifulSoup(text, "html.parser")
        page_text = soup.get_text(" ", strip=True)
        combined = page_text + " " + text[:200000]
        target, raw = extract_target_from_text(combined, cur)
        return {
            "url": url,
            "ok": res.status_code == 200,
            "statusCode": res.status_code,
            "targetPrice": target,
            "rawCandidates": raw[:20],
            "snippet": page_text[:500],
        }
    except Exception as e:
        return {"url": url, "ok": False, "error": str(e)[:300], "targetPrice": 0, "rawCandidates": []}

def main():
    run = datetime.now().isoformat(timespec="seconds")
    cands, source = valid_candidates()

    updated = 0
    upside_count = 0
    rows = []

    for c in cands:
        code = str(c.get("code")).zfill(6)
        name = str(c.get("name"))
        cur = current_price(c)
        r = fetch_total_page(code, cur)
        target = si(r.get("targetPrice"))

        if target > 0:
            realistic = round_price(target * 0.80)
            observe = round_price(target * 0.70)
            stop = round_price(target * 0.60)
            upside = ((target - cur) / cur * 100.0) if cur > 0 else 0.0

            c["targetMedianPrice"] = target
            c["realisticTargetPrice"] = realistic
            c["observeTimingPrice"] = observe
            c["stopTimingPrice"] = stop
            c["reportTargetCount"] = 1
            c["reportTargetPricesText"] = f"{target:,}원"
            c["targetUpsidePercent"] = round(upside, 1)
            c["reportTargetReason"] = (
                f"네이버증권 컨센서스 목표주가 {target:,}원 기준. "
                f"현재가 {cur:,}원 대비 상승여력 {upside:.1f}%. "
                f"현실목표 {realistic:,}원(80%), 관찰 {observe:,}원(70%), 손절 {stop:,}원(60%)."
            )
            updated += 1
            if upside > 0:
                upside_count += 1
        c["targetEngineVersion"] = "A247"
        c["updatedAt"] = run

        rows.append({
            "code": code,
            "name": name,
            "currentPrice": cur,
            "targetPrice": target,
            "upsidePercent": round(((target - cur) / cur * 100.0), 1) if target and cur else 0,
            "realisticTargetPrice": c.get("realisticTargetPrice", 0),
            "observeTimingPrice": c.get("observeTimingPrice", 0),
            "stopTimingPrice": c.get("stopTimingPrice", 0),
            "source": r.get("url"),
            "rawCandidates": r.get("rawCandidates", []),
            "ok": r.get("ok", False),
            "statusCode": r.get("statusCode", 0),
            "error": r.get("error", ""),
        })
        time.sleep(0.2)

    cands.sort(key=lambda x: int(x.get("score", 0)), reverse=True)
    save(CAND, cands)

    summary = load(SUMMARY, {})
    if not isinstance(summary, dict):
        summary = {}
    summary.update({
        "version": "A247",
        "generatedAt": run,
        "status": "naver_consensus_target",
        "candidateCount": len(cands),
        "targetPriceCandidateCount": updated,
        "targetUpsideCandidateCount": upside_count,
        "candidateSource": source,
        "targetSource": "m.stock.naver.com/domestic/stock/{code}/total",
        "output": "stock_candidates_ai_scored.json",
    })
    save(SUMMARY, summary)
    save(OUT, {"version": "A247", "generatedAt": run, "summary": summary, "details": rows})
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
