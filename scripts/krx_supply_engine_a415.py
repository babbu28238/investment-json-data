# scripts/krx_supply_engine_a415.py
# A415: KRX 기반 외국인/기관/연기금 수급 수집 엔진
# A414의 네이버 공개 페이지 수급 수집 실패를 보완하기 위해 pykrx 투자자별 거래대금 데이터를 사용한다.

import json
from pathlib import Path
from datetime import datetime, timedelta

DATA = Path("data")
SRC = DATA / "realtime_recommendations_a405.json"
FALLBACK = DATA / "stock_candidates_ai_scored.json"
OUT = DATA / "realtime_recommendations_a405.json"
CAND = DATA / "stock_candidates_ai_scored.json"
SUMMARY = DATA / "market_scanner_summary.json"
SUPPLY_OUT = DATA / "krx_supply_a415.json"
DEBUG_OUT = DATA / "krx_supply_debug_a415.json"

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
        for k in ["candidates", "data", "items", "stocks", "top"]:
            if isinstance(raw.get(k), list):
                return raw[k]
    return []

def si(x):
    try:
        return int(float(str(x).replace(",", "").replace("원", "").strip()))
    except Exception:
        return 0

def clamp(v):
    return max(0, min(100, int(round(v))))

def pick_col(df, keys):
    for key in keys:
        for col in df.columns:
            if key in str(col):
                return col
    return None

def date_range(days=10):
    end = datetime.now()
    start = end - timedelta(days=days)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

def get_krx_supply(code):
    from pykrx import stock

    debug = []
    start, end = date_range(10)

    # 1) detail=True: 연기금 포함 가능성이 가장 높음
    for detail in [True, False]:
        try:
            df = stock.get_market_trading_value_by_date(start, end, code, detail=detail)
            debug.append({"method": f"get_market_trading_value_by_date_detail_{detail}", "ok": True, "rows": len(df), "columns": [str(c) for c in df.columns]})
            if df is None or len(df) == 0:
                continue

            # 최근 5거래일 누적 순매수대금 기준
            tail = df.tail(5)

            foreign_col = pick_col(tail, ["외국인합계", "외국인"])
            inst_col = pick_col(tail, ["기관합계", "기관"])
            pension_col = pick_col(tail, ["연기금", "연기금등"])

            foreign = int(tail[foreign_col].sum()) if foreign_col else 0
            institution = int(tail[inst_col].sum()) if inst_col else 0
            pension = int(tail[pension_col].sum()) if pension_col else 0

            if foreign != 0 or institution != 0 or pension != 0:
                return {
                    "foreignNetBuy": foreign,
                    "institutionNetBuy": institution,
                    "pensionNetBuy": pension,
                    "foreignCol": str(foreign_col) if foreign_col else "",
                    "institutionCol": str(inst_col) if inst_col else "",
                    "pensionCol": str(pension_col) if pension_col else "",
                    "status": "수집성공",
                    "source": f"pykrx:get_market_trading_value_by_date:{start}-{end}:detail={detail}",
                    "debug": debug
                }
        except Exception as e:
            debug.append({"method": f"get_market_trading_value_by_date_detail_{detail}", "ok": False, "error": str(e)[:200]})

    # 2) 거래량 기준 fallback
    try:
        df = stock.get_market_trading_volume_by_date(start, end, code)
        debug.append({"method": "get_market_trading_volume_by_date", "ok": True, "rows": len(df), "columns": [str(c) for c in df.columns]})
        if df is not None and len(df) > 0:
            tail = df.tail(5)
            foreign_col = pick_col(tail, ["외국인합계", "외국인"])
            inst_col = pick_col(tail, ["기관합계", "기관"])
            pension_col = pick_col(tail, ["연기금", "연기금등"])

            foreign = int(tail[foreign_col].sum()) if foreign_col else 0
            institution = int(tail[inst_col].sum()) if inst_col else 0
            pension = int(tail[pension_col].sum()) if pension_col else 0

            if foreign != 0 or institution != 0 or pension != 0:
                return {
                    "foreignNetBuy": foreign,
                    "institutionNetBuy": institution,
                    "pensionNetBuy": pension,
                    "foreignCol": str(foreign_col) if foreign_col else "",
                    "institutionCol": str(inst_col) if inst_col else "",
                    "pensionCol": str(pension_col) if pension_col else "",
                    "status": "수집성공",
                    "source": f"pykrx:get_market_trading_volume_by_date:{start}-{end}",
                    "debug": debug
                }
    except Exception as e:
        debug.append({"method": "get_market_trading_volume_by_date", "ok": False, "error": str(e)[:200]})

    return {
        "foreignNetBuy": 0,
        "institutionNetBuy": 0,
        "pensionNetBuy": 0,
        "foreignCol": "",
        "institutionCol": "",
        "pensionCol": "",
        "status": "수집실패",
        "source": "pykrx",
        "debug": debug
    }

def score_supply(foreign, institution, pension):
    vals = [foreign, institution, pension]
    score = 50

    # 방향성: 순매수 주체 수
    for v, weight in [(foreign, 16), (institution, 16), (pension, 10)]:
        if v > 0:
            score += weight
        elif v < 0:
            score -= weight

    # 규모 보정: 억원 단위 기준. 거래대금/거래량 fallback 모두 과도한 점수 방지
    abs_total = abs(foreign) + abs(institution) + abs(pension)
    if abs_total >= 50_000_000_000:
        score += 6 if (foreign + institution + pension) > 0 else -6
    elif abs_total >= 10_000_000_000:
        score += 3 if (foreign + institution + pension) > 0 else -3

    return clamp(score)

def recalc_final(c):
    q = si(c.get("quantScore")) or 50
    s = si(c.get("supplyScore")) or 50
    co = si(c.get("companyScore")) or 50
    ev = si(c.get("eventScore")) or si(c.get("newsScore")) or 50
    report = si(c.get("reportScore")) or 50
    chart = si(c.get("chartScore")) or 50
    ma = si(c.get("macroScore")) or 50
    ri = si(c.get("riskScore")) or 50
    return clamp(q * 0.18 + s * 0.18 + co * 0.18 + ev * 0.14 + report * 0.10 + chart * 0.10 + ma * 0.07 + ri * 0.05)

def main():
    run = datetime.now().isoformat(timespec="seconds")
    data = norm(load(SRC, [])) or norm(load(FALLBACK, []))

    updated = []
    debug_rows = []
    success = 0
    failed = 0

    for idx, c in enumerate(data):
        if not isinstance(c, dict):
            continue

        code = str(c.get("code") or c.get("stockCode") or "").zfill(6)
        name = str(c.get("name") or c.get("stockName") or "")
        if not code:
            continue

        result = get_krx_supply(code)

        f = result["foreignNetBuy"]
        i = result["institutionNetBuy"]
        p = result["pensionNetBuy"]

        if result["status"] == "수집성공":
            score = score_supply(f, i, p)
            c["foreignNetBuy"] = f
            c["institutionNetBuy"] = i
            c["pensionNetBuy"] = p
            c["supplyScore"] = score
            c["supplyStatus"] = "수집성공"
            c["supplySource"] = result["source"]
            c["supplyReason"] = f"최근 5거래일 KRX 수급 기준 외국인 {f:,}, 기관 {i:,}, 연기금 {p:,}을 반영했습니다."
            c["supplyOpinion"] = f"최근 5거래일 KRX 수급 기준 외국인 {f:,}, 기관 {i:,}, 연기금 {p:,}을 반영해 수급 점수 {score}점으로 평가했습니다."
            success += 1
        else:
            c["foreignNetBuy"] = 0
            c["institutionNetBuy"] = 0
            c["pensionNetBuy"] = 0
            c["supplyScore"] = si(c.get("supplyScore")) or 50
            c["supplyStatus"] = "수집실패"
            c["supplySource"] = "pykrx"
            c["supplyReason"] = "KRX 투자자별 수급 원자료 수집에 실패했습니다. pykrx 응답 또는 거래일/종목코드 확인이 필요합니다."
            c["supplyOpinion"] = "KRX 투자자별 수급 원자료 수집 실패로 중립 50점으로 평가했습니다."
            failed += 1

        final = recalc_final(c)
        c["score"] = final
        c["realtimeScore"] = final
        c["expertSummary"] = f"퀀트 {si(c.get('quantScore')) or 50}점, 수급 {si(c.get('supplyScore')) or 50}점, 기업 {si(c.get('companyScore')) or 50}점, 이벤트 {si(c.get('eventScore')) or si(c.get('newsScore')) or 50}점, 매크로 {si(c.get('macroScore')) or 50}점, 리스크 {si(c.get('riskScore')) or 50}점을 종합했습니다."
        c["recommendationReason"] = f"{name}: KRX 수급을 반영한 전문가 패널 종합점수 {final}점으로 산출했습니다."
        c["reason"] = c["recommendationReason"]
        c["finalScoreReason"] = "최종점수는 퀀트 18%, 수급 18%, 기업분석 18%, 뉴스/이벤트 14%, 리포트 10%, 차트 10%, 매크로 7%, 리스크 5%로 계산했습니다. A415부터 수급은 KRX 투자자별 원자료를 반영합니다."
        c["updatedAt"] = run
        c["targetEngineVersion"] = "A415"

        updated.append(c)
        debug_rows.append({
            "code": code,
            "name": name,
            "supplyStatus": c.get("supplyStatus"),
            "supplyScore": c.get("supplyScore"),
            "foreignNetBuy": c.get("foreignNetBuy"),
            "institutionNetBuy": c.get("institutionNetBuy"),
            "pensionNetBuy": c.get("pensionNetBuy"),
            "supplySource": c.get("supplySource"),
            "debug": result.get("debug", [])[:4]
        })

        if idx % 50 == 0:
            print(f"processed {idx}/{len(data)} success={success} failed={failed}")

    updated.sort(key=lambda x: x.get("realtimeScore", x.get("score", 0)), reverse=True)

    save(OUT, updated)
    save(CAND, updated)

    summary = load(SUMMARY, {})
    if not isinstance(summary, dict):
        summary = {}
    summary.update({
        "version": "A415",
        "generatedAt": run,
        "status": "krx_supply_engine",
        "candidateCount": len(updated),
        "krxSupplyCollectedCount": success,
        "krxSupplyFailedCount": failed,
        "output": "realtime_recommendations_a405.json"
    })
    save(SUMMARY, summary)
    save(SUPPLY_OUT, {"summary": summary, "top": updated[:50]})
    save(DEBUG_OUT, {"summary": summary, "items": debug_rows})

    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
