# scripts/build_supply_net_purchase_a231.py
# HSinvest A231 SUPPLY NET PURCHASE
# A230의 ticker table 방식이 전부 실패했기 때문에 pykrx 순매수 집계 전용 API로 재시도한다.

import json
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

DATA = Path("data")
CANDIDATES = DATA / "stock_candidates_ai_scored.json"
SUMMARY = DATA / "market_scanner_summary.json"
DETAIL = DATA / "supply_net_purchase_detail_a231.json"
PIPE = DATA / "full_pipeline_summary_a231.json"

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
    out = set()
    for item in candidates:
        if isinstance(item, dict):
            code = str(item.get("code") or item.get("stockCode") or item.get("ticker") or "").zfill(6)
            if code and code != "000000":
                out.add(code)
    return out

def value_from_row(row):
    for col in ["순매수거래대금", "순매수", "순매수금액", "거래대금"]:
        if col in row.index:
            return safe_int(row[col])
    nums = []
    for v in row.values:
        x = safe_int(v, None)
        if x is not None:
            nums.append(x)
    return nums[-1] if nums else 0

def call_net_purchase(stock, start, end, market, investor):
    # pykrx 버전별 signature 차이 방어
    attempts = [
        lambda: stock.get_market_net_purchases_of_equities_by_ticker(start, end, market, investor),
        lambda: stock.get_market_net_purchases_of_equities_by_ticker(start, end, market=market, investor=investor),
        lambda: stock.get_market_net_purchases_of_equities_by_ticker(start, end, investor, market),
    ]

    last_error = ""
    for fn in attempts:
        try:
            df = fn()
            if df is not None and not df.empty:
                df = df.copy()
                df.index = [str(x).zfill(6) for x in df.index]
                return df, ""
        except Exception as e:
            last_error = str(e)

    return pd.DataFrame(), last_error or "empty"

def build_period_supply(stock, codes, days):
    end = ymd(datetime.now())
    start = ymd(datetime.now() - timedelta(days=days * 2 + 10))

    values = {
        code: {
            "foreign": 0,
            "institution": 0,
            "pension": 0,
            "trust": 0,
            "finance": 0,
            "hits": [],
        } for code in codes
    }
    errors = []

    for investor, key in INVESTORS:
        for market in MARKETS:
            df, err = call_net_purchase(stock, start, end, market, investor)
            if df is None or df.empty:
                if len(errors) < 30:
                    errors.append({"period": days, "market": market, "investor": investor, "error": err})
                continue

            common = codes.intersection(set(df.index))
            for code in common:
                value = value_from_row(df.loc[code])
                values[code][key] += value
                values[code]["hits"].append({
                    "period": days,
                    "market": market,
                    "investor": investor,
                    "value": value,
                    "columns": [str(c) for c in df.columns],
                })

    return values, errors

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

    score = max(0, min(30, int(score)))
    if not reasons:
        hit_count = len(v.get("hits", []))
        if hit_count > 0:
            reasons.append(f"수급 조회 {hit_count}건, 순매수 우위 제한")
        else:
            reasons.append("수급 데이터 조회 실패")

    return score, " / ".join(reasons)

def recompute_total(item):
    chart = safe_int(item.get("chartScore", 0))
    supply = safe_int(item.get("supplyScore", 0))
    news = safe_int(item.get("newsScore", 0))
    fundamental = safe_int(item.get("fundamentalScore", item.get("macroScore", 0)))
    risk = safe_int(item.get("riskScore", 0))
    total = max(0, min(100, chart + supply + news + fundamental + risk))
    item["score"] = total
    item["grade"] = "A" if total >= 85 else "B+" if total >= 75 else "B" if total >= 65 else "C+" if total >= 55 else "C"

def main():
    from pykrx import stock

    run_id = datetime.now().isoformat(timespec="seconds")
    raw = load_json(CANDIDATES, [])
    candidates = normalize_candidates(raw)
    codes = candidate_codes(candidates)

    p5, e5 = build_period_supply(stock, codes, 5)
    p20, e20 = build_period_supply(stock, codes, 20)
    p60, e60 = build_period_supply(stock, codes, 60)

    details = []
    hit_count = 0
    score_count = 0

    for item in candidates:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or item.get("stockCode") or item.get("ticker") or "").zfill(6)
        name = item.get("name", "")
        if code not in codes:
            continue

        v = {
            "foreign5": p5[code]["foreign"],
            "foreign20": p20[code]["foreign"],
            "foreign60": p60[code]["foreign"],
            "institution5": p5[code]["institution"],
            "institution20": p20[code]["institution"],
            "institution60": p60[code]["institution"],
            "pension20": p20[code]["pension"],
            "trust20": p20[code]["trust"],
            "finance20": p20[code]["finance"],
            "hits": p5[code]["hits"] + p20[code]["hits"] + p60[code]["hits"],
        }

        score, reason = score_supply(v)
        if len(v["hits"]) > 0:
            hit_count += 1
        if score > 0:
            score_count += 1

        item["supplyScore"] = score
        item["supplyReason"] = f"[수급 {score}/30] {reason}"
        item["foreignNet"] = v["foreign20"]
        item["institutionNet"] = v["institution20"]
        item["pensionNet"] = v["pension20"]
        item["trustNet"] = v["trust20"]
        item["financeNet"] = v["finance20"]
        item["supplyIndicators"] = {k: v[k] for k in [
            "foreign5", "foreign20", "foreign60",
            "institution5", "institution20", "institution60",
            "pension20", "trust20", "finance20"
        ]}
        item["supplyEngineVersion"] = "A231"
        item["updatedAt"] = run_id

        recompute_total(item)
        item["reasonDetail"] = (
            f"{name}({code}) 최종점수 {item.get('score', 0)}점({item.get('grade', '')}). "
            f"산식: 차트 {item.get('chartScore', 0)}/35 + 수급 {item.get('supplyScore', 0)}/30 + "
            f"뉴스 {item.get('newsScore', 0)}/20 + 기본 {item.get('fundamentalScore', item.get('macroScore', 0))}/10 + "
            f"리스크 {item.get('riskScore', 0)}/10. 수급 근거: {reason}."
        )
        item["detailReport"] = item["reasonDetail"]
        item["reason"] = item["reasonDetail"]

        details.append({
            "code": code,
            "name": name,
            "supplyScore": score,
            "reason": reason,
            "indicators": item["supplyIndicators"],
            "hitCount": len(v["hits"]),
            "hitSamples": v["hits"][:10],
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

    errors = e5 + e20 + e60
    summary.update({
        "version": "A231",
        "generatedAt": run_id,
        "status": "supply_net_purchase",
        "candidateCount": len(candidates),
        "priceCount": price_count,
        "chartScoreCount": chart_count,
        "supplyHitCount": hit_count,
        "supplyScoreCount": score_count,
        "newsScoreCount": news_count,
        "supplyErrorSample": errors[:20],
        "ready": len(candidates) >= 20 and price_count >= 20 and chart_count >= 20 and hit_count >= 20,
        "output": "stock_candidates_ai_scored.json",
    })
    save_json(SUMMARY, summary)
    save_json(DETAIL, details)
    save_json(PIPE, {
        "version": "A231",
        "generatedAt": run_id,
        "summary": summary,
        "detailCount": len(details),
        "errors": errors[:50],
    })

    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
