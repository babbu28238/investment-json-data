# scripts/build_supply_engine_a228.py
# HSinvest A228 SUPPLY ENGINE
# pykrx 투자자별 거래대금으로 외국인/기관/연기금/투신/금융투자 수급 점수 재계산

import json
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd

DATA = Path("data")
CANDIDATES = DATA / "stock_candidates_ai_scored.json"
SUMMARY = DATA / "market_scanner_summary.json"
DETAIL = DATA / "supply_engine_detail_a228.json"

def ymd(dt):
    return dt.strftime("%Y%m%d")

def safe_int(v, default=0):
    try:
        if pd.isna(v):
            return default
        return int(float(str(v).replace(",", "")))
    except Exception:
        return default

def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def normalize_candidates(raw):
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ["candidates", "data", "items", "stocks", "top"]:
            if isinstance(raw.get(key), list):
                return raw[key]
    return []

def find_col(columns, names):
    for n in names:
        for c in columns:
            if n in str(c):
                return c
    return None

def get_trading_value(stock, code, start, end):
    # detail=True가 가능한 환경이면 연기금/투신/금융투자까지 분리됨
    tries = [
        {"detail": True},
        {},
    ]

    last_error = ""
    for kwargs in tries:
        try:
            df = stock.get_market_trading_value_by_date(start, end, code, **kwargs)
            if df is not None and not df.empty:
                return df, ""
        except Exception as e:
            last_error = str(e)

    return pd.DataFrame(), last_error or "empty"

def sum_last(df, col, n):
    if col is None or col not in df.columns:
        return 0
    return safe_int(df[col].tail(n).sum())

def score_supply(stock, code):
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=120)
    start = ymd(start_dt)
    end = ymd(end_dt)

    df, error = get_trading_value(stock, code, start, end)
    if df is None or df.empty:
        return {
            "score": 0,
            "reason": f"수급 데이터 조회 실패: {error}",
            "indicators": {},
            "status": "fail"
        }

    cols = list(df.columns)

    foreign_col = find_col(cols, ["외국인합계", "외국인"])
    institution_col = find_col(cols, ["기관합계", "기관"])
    pension_col = find_col(cols, ["연기금"])
    trust_col = find_col(cols, ["투신"])
    finance_col = find_col(cols, ["금융투자"])

    foreign5 = sum_last(df, foreign_col, 5)
    foreign20 = sum_last(df, foreign_col, 20)
    foreign60 = sum_last(df, foreign_col, 60)

    institution5 = sum_last(df, institution_col, 5)
    institution20 = sum_last(df, institution_col, 20)
    institution60 = sum_last(df, institution_col, 60)

    pension20 = sum_last(df, pension_col, 20)
    trust20 = sum_last(df, trust_col, 20)
    finance20 = sum_last(df, finance_col, 20)

    score = 0
    reasons = []

    # 총 30점
    if foreign20 > 0:
        score += 6; reasons.append(f"외국인 20일 +{foreign20:,}")
    if foreign5 > 0:
        score += 3; reasons.append(f"외국인 5일 +{foreign5:,}")
    if foreign60 > 0:
        score += 2; reasons.append("외국인 60일 누적 순매수")

    if institution20 > 0:
        score += 6; reasons.append(f"기관 20일 +{institution20:,}")
    if institution5 > 0:
        score += 3; reasons.append(f"기관 5일 +{institution5:,}")
    if institution60 > 0:
        score += 2; reasons.append("기관 60일 누적 순매수")

    if pension20 > 0:
        score += 3; reasons.append(f"연기금 20일 +{pension20:,}")
    if trust20 > 0:
        score += 2; reasons.append(f"투신 20일 +{trust20:,}")
    if finance20 > 0:
        score += 1; reasons.append(f"금융투자 20일 +{finance20:,}")

    if foreign20 > 0 and institution20 > 0:
        score += 2; reasons.append("외국인·기관 동시 유입")
    if foreign5 > foreign20 * 0.4 and foreign20 > 0:
        score += 1; reasons.append("외국인 단기 유입 가속")
    if institution5 > institution20 * 0.4 and institution20 > 0:
        score += 1; reasons.append("기관 단기 유입 가속")

    score = max(0, min(30, int(score)))

    if not reasons:
        reasons.append("외국인·기관·주요 기관 수급 우위 제한")

    indicators = {
        "foreign5": foreign5,
        "foreign20": foreign20,
        "foreign60": foreign60,
        "institution5": institution5,
        "institution20": institution20,
        "institution60": institution60,
        "pension20": pension20,
        "trust20": trust20,
        "finance20": finance20,
        "columns": [str(c) for c in cols],
    }

    return {
        "score": score,
        "reason": " / ".join(reasons),
        "indicators": indicators,
        "status": "ok"
    }

def recompute_total(item):
    chart = safe_int(item.get("chartScore", 0))
    supply = safe_int(item.get("supplyScore", 0))
    news = safe_int(item.get("newsScore", 0))
    fundamental = safe_int(item.get("fundamentalScore", 0))
    risk = safe_int(item.get("riskScore", 0))

    total = max(0, min(100, chart + supply + news + fundamental + risk))
    item["score"] = total

    if total >= 85:
        item["grade"] = "A"
    elif total >= 75:
        item["grade"] = "B+"
    elif total >= 65:
        item["grade"] = "B"
    elif total >= 55:
        item["grade"] = "C+"
    else:
        item["grade"] = "C"

def main():
    from pykrx import stock

    raw = load_json(CANDIDATES, [])
    candidates = normalize_candidates(raw)

    run_id = datetime.now().isoformat(timespec="seconds")
    details = []
    ok = 0
    fail = 0

    for item in candidates:
        if not isinstance(item, dict):
            continue

        code = str(item.get("code") or item.get("stockCode") or item.get("ticker") or "").zfill(6)
        name = item.get("name", "")
        if not code or code == "000000":
            fail += 1
            continue

        result = score_supply(stock, code)
        item["supplyScore"] = int(result["score"])
        item["supplyReason"] = f"[수급 {result['score']}/30] {result['reason']}"
        item["supplyIndicators"] = result["indicators"]
        item["supplyEngineVersion"] = "A228"
        item["updatedAt"] = run_id

        recompute_total(item)

        # 전체 상세 근거도 수급 점수 반영
        item["reasonDetail"] = (
            f"{name}({code}) 최종점수 {item.get('score', 0)}점({item.get('grade', '')}). "
            f"산식: 차트 {item.get('chartScore', 0)}/35 + 수급 {item.get('supplyScore', 0)}/30 + "
            f"뉴스 {item.get('newsScore', 0)}/20 + 기본 {item.get('fundamentalScore', 0)}/10 + 리스크 {item.get('riskScore', 0)}/10. "
            f"수급 근거: {result['reason']}."
        )
        item["detailReport"] = item["reasonDetail"]
        item["reason"] = item["reasonDetail"]

        if result["status"] == "ok":
            ok += 1
        else:
            fail += 1

        details.append({
            "code": code,
            "name": name,
            "supplyScore": result["score"],
            "supplyReason": result["reason"],
            "status": result["status"],
            "indicators": result["indicators"],
            "totalScore": item.get("score", 0),
            "grade": item.get("grade", ""),
        })

    candidates = [x for x in candidates if isinstance(x, dict)]
    candidates.sort(key=lambda x: int(x.get("score", 0)), reverse=True)
    CANDIDATES.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = load_json(SUMMARY, {})
    if not isinstance(summary, dict):
        summary = {}
    summary.update({
        "version": "A228",
        "generatedAt": run_id,
        "candidateCount": len(candidates),
        "supplyOkCount": ok,
        "supplyFailCount": fail,
        "supplyScoreCount": sum(1 for x in candidates if safe_int(x.get("supplyScore", 0)) > 0),
        "status": "supply_engine",
        "output": "stock_candidates_ai_scored.json",
    })
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    DETAIL.write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8")

    print(summary)

if __name__ == "__main__":
    main()
