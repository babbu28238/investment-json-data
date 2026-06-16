# scripts/build_naver_supply_engine_a233.py
# HSinvest A233 NAVER SUPPLY ENGINE
# pykrx 수급 API가 GitHub에서 모두 empty인 경우 네이버 종목별 외국인/기관 순매매 페이지를 파싱한다.

import json
import time
from pathlib import Path
from datetime import datetime

import pandas as pd
import requests

DATA = Path("data")
CANDIDATES = DATA / "stock_candidates_ai_scored.json"
SUMMARY = DATA / "market_scanner_summary.json"
DETAIL = DATA / "naver_supply_detail_a233.json"
PIPE = DATA / "full_pipeline_summary_a233.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://finance.naver.com/",
}

def safe_int(v, default=0):
    try:
        if pd.isna(v):
            return default
        s = str(v).replace(",", "").replace("+", "").strip()
        if s in ["", "-", "nan"]:
            return default
        return int(float(s))
    except Exception:
        return default

def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def save_json(path, data):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def normalize_candidates(raw):
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ["candidates", "data", "items", "stocks", "top"]:
            if isinstance(raw.get(key), list):
                return raw[key]
    return []

def find_col(cols, keys):
    for key in keys:
        for c in cols:
            if key in str(c):
                return c
    return None

def read_naver_frgn_table(code, max_pages=8):
    rows = []
    errors = []

    for page in range(1, max_pages + 1):
        url = f"https://finance.naver.com/item/frgn.naver?code={code}&page={page}"
        try:
            html = requests.get(url, headers=HEADERS, timeout=15).text
            tables = pd.read_html(html)
            hit = None
            for t in tables:
                cols = [str(c) for c in t.columns]
                if any("기관" in c for c in cols) and any("외국인" in c for c in cols):
                    hit = t.copy()
                    break
            if hit is None:
                errors.append({"page": page, "error": "table_not_found"})
                continue

            # 날짜 없는 행 제거
            first_col = hit.columns[0]
            hit = hit[hit[first_col].notna()]
            rows.append(hit)
        except Exception as e:
            errors.append({"page": page, "error": str(e)[:200]})

        time.sleep(0.15)

    if not rows:
        return pd.DataFrame(), errors

    df = pd.concat(rows, ignore_index=True)
    return df, errors

def calc_supply_from_naver(code):
    df, errors = read_naver_frgn_table(code)

    if df is None or df.empty:
        return {
            "status": "fail",
            "score": 0,
            "reason": "네이버 수급 테이블 조회 실패",
            "indicators": {},
            "errors": errors,
            "rows": 0,
        }

    cols = list(df.columns)
    inst_col = find_col(cols, ["기관"])
    foreign_col = find_col(cols, ["외국인 순매매", "외국인"])

    if inst_col is None or foreign_col is None:
        return {
            "status": "fail",
            "score": 0,
            "reason": "네이버 수급 컬럼 매칭 실패",
            "indicators": {"columns": [str(c) for c in cols]},
            "errors": errors,
            "rows": len(df),
        }

    # 최신순 테이블 기준 앞쪽이 최근
    inst = [safe_int(x) for x in df[inst_col].tolist()]
    foreign = [safe_int(x) for x in df[foreign_col].tolist()]

    def sum_n(arr, n):
        return int(sum(arr[:n]))

    foreign5 = sum_n(foreign, 5)
    foreign20 = sum_n(foreign, 20)
    foreign60 = sum_n(foreign, 60)
    inst5 = sum_n(inst, 5)
    inst20 = sum_n(inst, 20)
    inst60 = sum_n(inst, 60)

    score = 0
    reasons = []

    if foreign20 > 0:
        score += 8; reasons.append(f"외국인 20일 순매수 {foreign20:,}주")
    if foreign5 > 0:
        score += 4; reasons.append(f"외국인 5일 순매수 {foreign5:,}주")
    if foreign60 > 0:
        score += 2; reasons.append("외국인 60일 누적 순매수")

    if inst20 > 0:
        score += 8; reasons.append(f"기관 20일 순매수 {inst20:,}주")
    if inst5 > 0:
        score += 4; reasons.append(f"기관 5일 순매수 {inst5:,}주")
    if inst60 > 0:
        score += 2; reasons.append("기관 60일 누적 순매수")

    if foreign20 > 0 and inst20 > 0:
        score += 3; reasons.append("외국인·기관 20일 동시 순매수")
    if foreign20 > 0 and foreign5 > abs(foreign20) * 0.35:
        score += 1; reasons.append("외국인 단기 유입 가속")
    if inst20 > 0 and inst5 > abs(inst20) * 0.35:
        score += 1; reasons.append("기관 단기 유입 가속")

    score = max(0, min(30, int(score)))

    if not reasons:
        reasons.append("네이버 수급 조회 성공, 순매수 우위 제한")

    return {
        "status": "ok",
        "score": score,
        "reason": " / ".join(reasons),
        "indicators": {
            "foreign5": foreign5,
            "foreign20": foreign20,
            "foreign60": foreign60,
            "institution5": inst5,
            "institution20": inst20,
            "institution60": inst60,
            "pension20": 0,
            "trust20": 0,
            "finance20": 0,
            "rows": len(df),
            "columns": [str(c) for c in cols],
            "source": "naver_frgn",
            "unit": "shares"
        },
        "errors": errors[:5],
        "rows": len(df),
    }

def recompute(item):
    chart = safe_int(item.get("chartScore", 0))
    supply = safe_int(item.get("supplyScore", 0))
    news = safe_int(item.get("newsScore", 0))
    fundamental = safe_int(item.get("fundamentalScore", item.get("macroScore", 0)))
    risk = safe_int(item.get("riskScore", 0))
    total = max(0, min(100, chart + supply + news + fundamental + risk))
    item["score"] = total
    item["grade"] = "A" if total >= 85 else "B+" if total >= 75 else "B" if total >= 65 else "C+" if total >= 55 else "C"

def main():
    run_id = datetime.now().isoformat(timespec="seconds")
    raw = load_json(CANDIDATES, [])
    candidates = normalize_candidates(raw)

    details = []
    ok = 0
    positive = 0

    for item in candidates:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or item.get("stockCode") or item.get("ticker") or "").zfill(6)
        name = item.get("name", "")
        if not code or code == "000000":
            continue

        r = calc_supply_from_naver(code)

        item["supplyScore"] = int(r["score"])
        item["supplyReason"] = f"[수급 {r['score']}/30] {r['reason']} (네이버 투자자별 매매동향)"
        ind = r.get("indicators", {})
        item["foreignNet"] = safe_int(ind.get("foreign20", 0))
        item["institutionNet"] = safe_int(ind.get("institution20", 0))
        item["pensionNet"] = 0
        item["trustNet"] = 0
        item["financeNet"] = 0
        item["supplyIndicators"] = ind
        item["supplyEngineVersion"] = "A233"
        item["updatedAt"] = run_id

        recompute(item)

        item["reasonDetail"] = (
            f"{name}({code}) 최종점수 {item.get('score', 0)}점({item.get('grade', '')}). "
            f"산식: 차트 {item.get('chartScore', 0)}/35 + 수급 {item.get('supplyScore', 0)}/30 + "
            f"뉴스 {item.get('newsScore', 0)}/20 + 기본 {item.get('fundamentalScore', item.get('macroScore', 0))}/10 + "
            f"리스크 {item.get('riskScore', 0)}/10. 수급 근거: {r['reason']}."
        )
        item["detailReport"] = item["reasonDetail"]
        item["reason"] = item["reasonDetail"]

        if r["status"] == "ok":
            ok += 1
        if r["score"] > 0:
            positive += 1

        details.append({
            "code": code,
            "name": name,
            "status": r["status"],
            "supplyScore": r["score"],
            "reason": r["reason"],
            "rows": r.get("rows", 0),
            "indicators": r.get("indicators", {}),
            "errors": r.get("errors", []),
            "totalScore": item.get("score", 0),
            "grade": item.get("grade", ""),
        })

    candidates = [x for x in candidates if isinstance(x, dict)]
    candidates.sort(key=lambda x: int(x.get("score", 0)), reverse=True)
    save_json(CANDIDATES, candidates)

    summary = load_json(SUMMARY, {})
    if not isinstance(summary, dict):
        summary = {}
    price_count = sum(1 for x in candidates if safe_int(x.get("currentPrice", x.get("close", 0))) > 0)
    chart_count = sum(1 for x in candidates if safe_int(x.get("chartScore", 0)) > 0)
    news_count = sum(1 for x in candidates if safe_int(x.get("newsScore", 0)) > 0)

    summary.update({
        "version": "A233",
        "generatedAt": run_id,
        "status": "naver_supply_engine",
        "candidateCount": len(candidates),
        "priceCount": price_count,
        "chartScoreCount": chart_count,
        "supplyOkCount": ok,
        "supplyScoreCount": positive,
        "newsScoreCount": news_count,
        "supplySource": "naver_finance_item_frgn",
        "ready": len(candidates) >= 20 and ok >= 20,
        "output": "stock_candidates_ai_scored.json",
    })
    save_json(SUMMARY, summary)
    save_json(DETAIL, details)
    save_json(PIPE, {
        "version": "A233",
        "generatedAt": run_id,
        "summary": summary,
        "detailCount": len(details),
        "sample": details[:5],
    })

    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
