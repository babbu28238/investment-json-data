# scripts/build_supply_exhaustive_a232.py
# HSinvest A232 SUPPLY EXHAUSTIVE ENGINE
# pykrx 수급 함수/투자자명/시장 조합을 전부 테스트해 실제 응답이 있는 방법으로 수급 점수 계산

import json
from pathlib import Path
from datetime import datetime, timedelta
import inspect
import pandas as pd

DATA = Path("data")
CANDIDATES = DATA / "stock_candidates_ai_scored.json"
SUMMARY = DATA / "market_scanner_summary.json"
DETAIL = DATA / "supply_exhaustive_detail_a232.json"
DIAG = DATA / "supply_api_diagnostics_a232.json"

INVESTOR_NAMES = [
    ("외국인", "foreign"),
    ("외국인합계", "foreign"),
    ("기타외국인", "foreign_etc"),
    ("기관합계", "institution"),
    ("금융투자", "finance"),
    ("보험", "insurance"),
    ("투신", "trust"),
    ("사모", "private"),
    ("은행", "bank"),
    ("기타금융", "other_finance"),
    ("연기금", "pension"),
    ("연기금 등", "pension"),
    ("개인", "personal"),
]

MARKETS = ["KOSPI", "KOSDAQ", "ALL"]

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

def get_codes(candidates):
    codes = set()
    for item in candidates:
        if isinstance(item, dict):
            code = str(item.get("code") or item.get("stockCode") or item.get("ticker") or "").zfill(6)
            if code and code != "000000":
                codes.add(code)
    return codes

def row_value(row):
    for col in ["순매수거래대금", "순매수", "순매수금액", "거래대금", "매수거래대금"]:
        if col in row.index:
            return safe_int(row[col])
    nums = []
    for v in row.values:
        try:
            nums.append(int(float(str(v).replace(",", ""))))
        except Exception:
            pass
    return nums[-1] if nums else 0

def normalize_index(df):
    df = df.copy()
    df.index = [str(x).zfill(6) for x in df.index]
    return df

def try_by_ticker(stock, start, end, investor, market):
    calls = []

    if hasattr(stock, "get_market_net_purchases_of_equities_by_ticker"):
        f = stock.get_market_net_purchases_of_equities_by_ticker
        calls += [
            ("net_pos", lambda: f(start, end, market, investor)),
            ("net_kw", lambda: f(start, end, market=market, investor=investor)),
            ("net_inv_market", lambda: f(start, end, investor, market)),
        ]

    if hasattr(stock, "get_market_trading_value_by_ticker"):
        f = stock.get_market_trading_value_by_ticker
        # date 단일 조회용이라 end 대신 end 날짜만 사용
        calls += [
            ("value_ticker_kw", lambda: f(end, market=market, investor=investor)),
            ("value_ticker_pos", lambda: f(end, market, investor)),
        ]

    errors = []
    for name, call in calls:
        try:
            df = call()
            if df is not None and not df.empty:
                return normalize_index(df), name, ""
            errors.append({"call": name, "error": "empty"})
        except Exception as e:
            errors.append({"call": name, "error": str(e)[:200]})
    return pd.DataFrame(), "", errors

def try_by_date_single(stock, start, end, code):
    calls = []
    if hasattr(stock, "get_market_trading_value_by_date"):
        f = stock.get_market_trading_value_by_date
        calls += [
            ("by_date_detail", lambda: f(start, end, code, detail=True)),
            ("by_date_plain", lambda: f(start, end, code)),
        ]

    errors = []
    for name, call in calls:
        try:
            df = call()
            if df is not None and not df.empty:
                return df, name, ""
            errors.append({"call": name, "error": "empty"})
        except Exception as e:
            errors.append({"call": name, "error": str(e)[:200]})
    return pd.DataFrame(), "", errors

def build_period(stock, codes, days):
    end = ymd(datetime.now())
    start = ymd(datetime.now() - timedelta(days=days * 2 + 10))
    values = {c: {
        "foreign": 0, "institution": 0, "pension": 0, "trust": 0, "finance": 0,
        "hits": []
    } for c in codes}
    diagnostics = []

    # 1) 시장/투자자 ticker 집계
    for investor, key in INVESTOR_NAMES:
        for market in MARKETS:
            df, call_name, err = try_by_ticker(stock, start, end, investor, market)
            diagnostics.append({
                "period": days, "method": "ticker", "investor": investor, "market": market,
                "call": call_name, "rows": 0 if df is None else len(df), "error": err if isinstance(err, str) else err[:3]
            })
            if df is None or df.empty:
                continue

            common = codes.intersection(set(df.index))
            for code in common:
                value = row_value(df.loc[code])
                if key == "foreign" or key == "foreign_etc":
                    values[code]["foreign"] += value
                elif key == "institution":
                    values[code]["institution"] += value
                elif key == "pension":
                    values[code]["pension"] += value
                elif key == "trust":
                    values[code]["trust"] += value
                elif key == "finance":
                    values[code]["finance"] += value

                values[code]["hits"].append({
                    "period": days, "method": "ticker", "investor": investor, "market": market,
                    "call": call_name, "value": value, "columns": [str(x) for x in df.columns]
                })

    # 2) 종목별 날짜 테이블 보조
    for code in codes:
        df, call_name, err = try_by_date_single(stock, start, end, code)
        diagnostics.append({
            "period": days, "method": "by_date", "code": code, "call": call_name,
            "rows": 0 if df is None else len(df), "error": err if isinstance(err, str) else err[:3]
        })
        if df is None or df.empty:
            continue
        cols = [str(c) for c in df.columns]
        for col in df.columns:
            col_s = str(col)
            val = safe_int(df[col].sum())
            if "외국인" in col_s:
                values[code]["foreign"] += val
            elif "기관" in col_s:
                values[code]["institution"] += val
            elif "연기금" in col_s:
                values[code]["pension"] += val
            elif "투신" in col_s:
                values[code]["trust"] += val
            elif "금융투자" in col_s:
                values[code]["finance"] += val
        values[code]["hits"].append({"period": days, "method": "by_date", "call": call_name, "columns": cols})

    return values, diagnostics

def score_supply(v):
    score = 0
    reasons = []
    if v["foreign20"] > 0:
        score += 7; reasons.append(f"외국인 20일 +{v['foreign20']:,}")
    if v["foreign5"] > 0:
        score += 3; reasons.append(f"외국인 5일 +{v['foreign5']:,}")
    if v["foreign60"] > 0:
        score += 2; reasons.append("외국인 60일 누적 순매수")
    if v["institution20"] > 0:
        score += 7; reasons.append(f"기관 20일 +{v['institution20']:,}")
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
        reasons.append("수급 데이터 조회 실패" if v["hitCount"] == 0 else "수급 조회 성공, 순매수 우위 제한")
    return score, " / ".join(reasons)

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
    from pykrx import stock
    run_id = datetime.now().isoformat(timespec="seconds")
    raw = load_json(CANDIDATES, [])
    candidates = normalize_candidates(raw)
    codes = get_codes(candidates)

    p5, d5 = build_period(stock, codes, 5)
    p20, d20 = build_period(stock, codes, 20)
    p60, d60 = build_period(stock, codes, 60)

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
            "hitCount": len(p5[code]["hits"] + p20[code]["hits"] + p60[code]["hits"]),
        }
        score, reason = score_supply(v)

        item["supplyScore"] = score
        item["supplyReason"] = f"[수급 {score}/30] {reason}"
        item["foreignNet"] = v["foreign20"]
        item["institutionNet"] = v["institution20"]
        item["pensionNet"] = v["pension20"]
        item["trustNet"] = v["trust20"]
        item["financeNet"] = v["finance20"]
        item["supplyIndicators"] = v
        item["supplyEngineVersion"] = "A232"
        item["updatedAt"] = run_id
        recompute(item)

        item["reasonDetail"] = (
            f"{name}({code}) 최종점수 {item.get('score', 0)}점({item.get('grade', '')}). "
            f"산식: 차트 {item.get('chartScore', 0)}/35 + 수급 {item.get('supplyScore', 0)}/30 + "
            f"뉴스 {item.get('newsScore', 0)}/20 + 기본 {item.get('fundamentalScore', item.get('macroScore', 0))}/10 + "
            f"리스크 {item.get('riskScore', 0)}/10. 수급 근거: {reason}."
        )
        item["detailReport"] = item["reasonDetail"]
        item["reason"] = item["reasonDetail"]

        if v["hitCount"] > 0:
            hit_count += 1
        if score > 0:
            score_count += 1

        details.append({
            "code": code, "name": name, "supplyScore": score, "reason": reason,
            "indicators": v, "totalScore": item.get("score", 0),
            "grade": item.get("grade", ""),
            "hitSamples": (p5[code]["hits"] + p20[code]["hits"] + p60[code]["hits"])[:10]
        })

    candidates = [x for x in candidates if isinstance(x, dict)]
    candidates.sort(key=lambda x: int(x.get("score", 0)), reverse=True)
    save_json(CANDIDATES, candidates)

    diag = {
        "version": "A232",
        "generatedAt": run_id,
        "functionNames": [x for x in dir(stock) if "trading" in x.lower() or "purchase" in x.lower() or "investor" in x.lower()],
        "diagnostics": (d5 + d20 + d60)[:300],
    }
    save_json(DIAG, diag)

    summary = load_json(SUMMARY, {})
    if not isinstance(summary, dict):
        summary = {}
    summary.update({
        "version": "A232",
        "generatedAt": run_id,
        "status": "supply_exhaustive",
        "candidateCount": len(candidates),
        "supplyHitCount": hit_count,
        "supplyScoreCount": score_count,
        "supplyDiagRows": len(d5 + d20 + d60),
        "ready": hit_count >= 20,
        "output": "stock_candidates_ai_scored.json",
    })
    save_json(SUMMARY, summary)
    save_json(DETAIL, details)

    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
