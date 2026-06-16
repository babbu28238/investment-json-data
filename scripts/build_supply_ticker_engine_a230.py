# scripts/build_supply_ticker_engine_a230.py
# HSinvest A230 SUPPLY TICKER ENGINE
# 종목별 get_market_trading_value_by_date가 empty로 실패할 때,
# 일자별/시장별/투자자별 get_market_trading_value_by_ticker 방식으로 수급을 집계한다.

import json
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

DATA = Path("data")
CANDIDATES = DATA / "stock_candidates_ai_scored.json"
SUMMARY = DATA / "market_scanner_summary.json"
DETAIL = DATA / "supply_ticker_detail_a230.json"
PIPE = DATA / "full_pipeline_summary_a230.json"

INVESTORS = [
    ("외국인", "foreign"),
    ("기관합계", "institution"),
    ("연기금", "pension"),
    ("투신", "trust"),
    ("금융투자", "finance"),
]

MARKETS = ["KOSPI", "KOSDAQ"]

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

def candidate_codes(candidates):
    codes = set()
    for item in candidates:
        if isinstance(item, dict):
            code = str(item.get("code") or item.get("stockCode") or item.get("ticker") or "").zfill(6)
            if code and code != "000000":
                codes.add(code)
    return codes

def get_value_from_row(row):
    # pykrx 투자자별 ticker table은 환경에 따라 '순매수', '거래대금', '순매수거래대금' 등 컬럼명이 다를 수 있음
    for col in ["순매수거래대금", "순매수", "거래대금", "매수거래대금"]:
        if col in row.index:
            return safe_int(row[col])
    # 숫자 컬럼 중 마지막 값을 보조 사용
    nums = []
    for v in row.values:
        x = safe_int(v, None)
        if x is not None:
            nums.append(x)
    return nums[-1] if nums else 0

def build_supply_map(stock, codes, days=60):
    supply = {
        code: {
            "foreign5": 0, "foreign20": 0, "foreign60": 0,
            "institution5": 0, "institution20": 0, "institution60": 0,
            "pension20": 0, "trust20": 0, "finance20": 0,
            "hitDays": 0, "sourceHits": []
        } for code in codes
    }

    used_dates = []
    errors = []

    for offset in range(days):
        day = ymd(datetime.now() - timedelta(days=offset))
        any_hit_day = False

        for investor_name, key in INVESTORS:
            for market in MARKETS:
                try:
                    df = stock.get_market_trading_value_by_ticker(day, market=market, investor=investor_name)
                    if df is None or df.empty:
                        continue

                    df = df.copy()
                    df.index = [str(x).zfill(6) for x in df.index]
                    common = codes.intersection(set(df.index))
                    if not common:
                        continue

                    any_hit_day = True

                    for code in common:
                        value = get_value_from_row(df.loc[code])
                        if offset < 5 and key in ["foreign", "institution"]:
                            supply[code][f"{key}5"] += value
                        if offset < 20:
                            if key in ["foreign", "institution"]:
                                supply[code][f"{key}20"] += value
                            elif key == "pension":
                                supply[code]["pension20"] += value
                            elif key == "trust":
                                supply[code]["trust20"] += value
                            elif key == "finance":
                                supply[code]["finance20"] += value
                        if offset < 60 and key in ["foreign", "institution"]:
                            supply[code][f"{key}60"] += value

                        supply[code]["sourceHits"].append({
                            "date": day,
                            "market": market,
                            "investor": investor_name,
                            "value": value
                        })
                except Exception as e:
                    if len(errors) < 30:
                        errors.append({"date": day, "market": market, "investor": investor_name, "error": str(e)})

        if any_hit_day:
            used_dates.append(day)
            for code in codes:
                # code별 hitDays는 sourceHits 날짜 unique로 나중 산출
                pass

    for code in codes:
        supply[code]["hitDays"] = len(set(x["date"] for x in supply[code]["sourceHits"]))

    return supply, used_dates, errors

def score_supply(v):
    score = 0
    reasons = []

    if v["foreign20"] > 0:
        score += 6; reasons.append(f"외국인 20일 +{v['foreign20']:,}")
    if v["foreign5"] > 0:
        score += 3; reasons.append(f"외국인 5일 +{v['foreign5']:,}")
    if v["foreign60"] > 0:
        score += 2; reasons.append("외국인 60일 누적 순매수")

    if v["institution20"] > 0:
        score += 6; reasons.append(f"기관 20일 +{v['institution20']:,}")
    if v["institution5"] > 0:
        score += 3; reasons.append(f"기관 5일 +{v['institution5']:,}")
    if v["institution60"] > 0:
        score += 2; reasons.append("기관 60일 누적 순매수")

    if v["pension20"] > 0:
        score += 3; reasons.append(f"연기금 20일 +{v['pension20']:,}")
    if v["trust20"] > 0:
        score += 2; reasons.append(f"투신 20일 +{v['trust20']:,}")
    if v["finance20"] > 0:
        score += 1; reasons.append(f"금융투자 20일 +{v['finance20']:,}")

    if v["foreign20"] > 0 and v["institution20"] > 0:
        score += 2; reasons.append("외국인·기관 동시 유입")

    if v["foreign20"] > 0 and v["foreign5"] > abs(v["foreign20"]) * 0.35:
        score += 1; reasons.append("외국인 단기 유입 가속")
    if v["institution20"] > 0 and v["institution5"] > abs(v["institution20"]) * 0.35:
        score += 1; reasons.append("기관 단기 유입 가속")

    score = max(0, min(30, int(score)))

    if not reasons:
        if v["hitDays"] > 0:
            reasons.append("수급 데이터는 조회됐으나 순매수 우위 제한")
        else:
            reasons.append("수급 데이터 조회 실패")

    return score, " / ".join(reasons)

def recompute_total(item):
    chart = safe_int(item.get("chartScore", 0))
    supply = safe_int(item.get("supplyScore", 0))
    news = safe_int(item.get("newsScore", 0))
    fundamental = safe_int(item.get("fundamentalScore", item.get("macroScore", 0)))
    risk = safe_int(item.get("riskScore", 0))

    # 과거 riskScore가 -3처럼 감점으로 들어온 구조면 그대로 합산
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

    run_id = datetime.now().isoformat(timespec="seconds")
    raw = load_json(CANDIDATES, [])
    candidates = normalize_candidates(raw)
    codes = candidate_codes(candidates)

    supply_map, used_dates, errors = build_supply_map(stock, codes, days=60)

    details = []
    ok = 0
    positive = 0

    for item in candidates:
        if not isinstance(item, dict):
            continue

        code = str(item.get("code") or item.get("stockCode") or item.get("ticker") or "").zfill(6)
        name = item.get("name", "")
        if code not in supply_map:
            continue

        v = supply_map[code]
        score, reason = score_supply(v)

        item["supplyScore"] = score
        item["supplyReason"] = f"[수급 {score}/30] {reason}"
        item["foreignNet"] = v["foreign20"]
        item["institutionNet"] = v["institution20"]
        item["pensionNet"] = v["pension20"]
        item["trustNet"] = v["trust20"]
        item["financeNet"] = v["finance20"]
        item["supplyIndicators"] = {
            k: v[k] for k in [
                "foreign5", "foreign20", "foreign60",
                "institution5", "institution20", "institution60",
                "pension20", "trust20", "finance20", "hitDays"
            ]
        }
        item["supplyEngineVersion"] = "A230"
        item["updatedAt"] = run_id

        recompute_total(item)

        item["reasonDetail"] = (
            f"{name}({code}) 최종점수 {item.get('score', 0)}점({item.get('grade', '')}). "
            f"산식: 차트 {item.get('chartScore', 0)}/35 + 수급 {item.get('supplyScore', 0)}/30 + "
            f"뉴스 {item.get('newsScore', 0)}/20 + 기본 {item.get('fundamentalScore', item.get('macroScore', 0))}/10 + "
            f"리스크 {item.get('riskScore', 0)}/10. "
            f"수급 근거: {reason}."
        )
        item["detailReport"] = item["reasonDetail"]
        item["reason"] = item["reasonDetail"]

        if v["hitDays"] > 0:
            ok += 1
        if score > 0:
            positive += 1

        details.append({
            "code": code,
            "name": name,
            "supplyScore": score,
            "reason": reason,
            "hitDays": v["hitDays"],
            "indicators": item["supplyIndicators"],
            "sourceSamples": v["sourceHits"][:10],
            "score": item.get("score", 0),
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
        "version": "A230",
        "generatedAt": run_id,
        "status": "supply_ticker_engine",
        "candidateCount": len(candidates),
        "priceCount": price_count,
        "chartScoreCount": chart_count,
        "supplyOkCount": ok,
        "supplyScoreCount": positive,
        "newsScoreCount": news_count,
        "usedSupplyDates": used_dates[:10],
        "supplyErrorSample": errors[:10],
        "ready": len(candidates) >= 20 and price_count >= 20 and chart_count >= 20 and ok >= 20,
        "output": "stock_candidates_ai_scored.json",
    })
    save_json(SUMMARY, summary)
    save_json(DETAIL, details)
    save_json(PIPE, {
        "version": "A230",
        "generatedAt": run_id,
        "summary": summary,
        "detailCount": len(details),
        "usedSupplyDates": used_dates,
        "errors": errors[:50],
    })

    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
