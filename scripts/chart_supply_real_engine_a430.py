# scripts/chart_supply_real_engine_a430.py
# A430: KRX/pykrx 기반 실제 차트/OHLCV 및 투자자별 수급 원자료 연결
import json
from pathlib import Path
from datetime import datetime, timedelta

DATA = Path("data")
FILES = [
    DATA / "realtime_recommendations_a405.json",
    DATA / "stock_candidates_ai_scored.json",
]
OUT = DATA / "chart_supply_real_engine_a430.json"

def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def normalize(raw):
    if isinstance(raw, list):
        return raw, "list"
    if isinstance(raw, dict):
        for key in ["candidates", "data", "items", "stocks", "top"]:
            if isinstance(raw.get(key), list):
                return raw[key], key
    return [], "none"

def iv(v, default=0):
    try:
        return int(float(str(v).replace(",", "").replace("+", "").strip() or default))
    except Exception:
        return default

def clamp(x):
    return max(0, min(100, int(round(x))))

def latest_market_date():
    try:
        from pykrx import stock
        today = datetime.now()
        debug = []
        for d in range(0, 45):
            day = (today - timedelta(days=d)).strftime("%Y%m%d")
            try:
                tickers = stock.get_market_ticker_list(day, market="KOSPI")
                debug.append({"date": day, "count": len(tickers)})
                if len(tickers) > 100:
                    return day, debug
            except Exception as e:
                debug.append({"date": day, "error": str(e)[:120]})
        return today.strftime("%Y%m%d"), debug
    except Exception as e:
        return datetime.now().strftime("%Y%m%d"), [{"error": str(e)[:120]}]

def chart_score(last, ma5, ma20, ma60):
    score = 50
    reasons = []
    if last > ma5:
        score += 8
        reasons.append("현재가가 5일 이동평균선 위")
    else:
        score -= 6
        reasons.append("현재가가 5일 이동평균선 아래")
    if last > ma20:
        score += 10
        reasons.append("현재가가 20일 이동평균선 위")
    else:
        score -= 10
        reasons.append("현재가가 20일 이동평균선 아래")
    if ma5 > ma20:
        score += 8
        reasons.append("5일선이 20일선 위")
    if ma20 > ma60:
        score += 8
        reasons.append("20일선이 60일선 위")
    if last > ma5 > ma20:
        score += 8
        reasons.append("단기 상승 배열")
    return clamp(score), reasons

def connect_chart(code, date):
    try:
        from pykrx import stock
        end = datetime.strptime(date, "%Y%m%d")
        start = (end - timedelta(days=180)).strftime("%Y%m%d")
        df = stock.get_market_ohlcv_by_date(start, date, code)
        if df is None or len(df) < 20:
            return None, {"status": "failed", "reason": "OHLCV row 부족", "rows": 0 if df is None else len(df)}
        closes = [iv(x) for x in df["종가"].tolist() if iv(x) > 0]
        volumes = [iv(x) for x in df["거래량"].tolist()] if "거래량" in df.columns else []
        if len(closes) < 20:
            return None, {"status": "failed", "reason": "종가 데이터 부족", "rows": len(closes)}
        last = closes[-1]
        ma5 = sum(closes[-5:]) / 5
        ma20 = sum(closes[-20:]) / 20
        ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else ma20
        vol20 = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 0
        score, reasons = chart_score(last, ma5, ma20, ma60)
        data = {
            "chartDataStatus": "connected",
            "chartScore": score,
            "chartSummary": f"KRX OHLCV 기준 현재가 {last:,}원, MA5 {ma5:,.0f}, MA20 {ma20:,.0f}, MA60 {ma60:,.0f}. " + ", ".join(reasons),
            "chartIndicators": {
                "last": round(last),
                "ma5": round(ma5),
                "ma20": round(ma20),
                "ma60": round(ma60),
                "volume20": round(vol20),
                "source": f"pykrx_ohlcv:{start}-{date}"
            }
        }
        return data, {"status": "connected", "rows": len(closes), "source": f"pykrx_ohlcv:{start}-{date}"}
    except Exception as e:
        return None, {"status": "failed", "reason": str(e)[:300]}

def pick_col(df, keys):
    for key in keys:
        for col in df.columns:
            if key in str(col):
                return col
    return None

def supply_score(foreign, institution, pension):
    score = 50
    if foreign > 0:
        score += 16
    elif foreign < 0:
        score -= 14
    if institution > 0:
        score += 16
    elif institution < 0:
        score -= 14
    if pension > 0:
        score += 10
    elif pension < 0:
        score -= 8
    if foreign > 0 and institution > 0:
        score += 8
    if foreign < 0 and institution < 0:
        score -= 8
    return clamp(score)

def connect_supply(code, date):
    try:
        from pykrx import stock
        end = datetime.strptime(date, "%Y%m%d")
        start = (end - timedelta(days=30)).strftime("%Y%m%d")
        debug = []
        for detail in [True, False]:
            try:
                df = stock.get_market_trading_value_by_date(start, date, code, detail=detail)
                debug.append({"detail": detail, "rows": 0 if df is None else len(df), "columns": [] if df is None else [str(c) for c in df.columns]})
                if df is None or len(df) == 0:
                    continue
                tail = df.tail(5)
                fc = pick_col(tail, ["외국인합계", "외국인"])
                ic = pick_col(tail, ["기관합계", "기관"])
                pc = pick_col(tail, ["연기금", "연기금등"])
                foreign = int(tail[fc].sum()) if fc else 0
                institution = int(tail[ic].sum()) if ic else 0
                pension = int(tail[pc].sum()) if pc else 0
                if foreign != 0 or institution != 0 or pension != 0 or fc or ic:
                    score = supply_score(foreign, institution, pension)
                    data = {
                        "foreignNetBuy": foreign,
                        "institutionNetBuy": institution,
                        "pensionNetBuy": pension,
                        "supplyDataStatus": "connected",
                        "supplyStatus": "connected",
                        "supplySource": f"pykrx_trading_value:{start}-{date}",
                        "supplyScore": score,
                        "supplyReason": f"최근 5거래일 KRX 투자자별 거래대금 기준 외국인 {foreign:,}, 기관 {institution:,}, 연기금 {pension:,} 순매수를 반영했습니다.",
                        "supplyOpinion": f"최근 5거래일 KRX 투자자별 거래대금 기준 외국인 {foreign:,}, 기관 {institution:,}, 연기금 {pension:,} 순매수를 반영해 수급 점수 {score}점으로 산정했습니다."
                    }
                    return data, {"status": "connected", "source": f"pykrx_trading_value:{start}-{date}", "debug": debug}
            except Exception as e:
                debug.append({"detail": detail, "error": str(e)[:160]})
        return None, {"status": "failed", "reason": "수급 컬럼 또는 rows 부족", "debug": debug}
    except Exception as e:
        return None, {"status": "failed", "reason": str(e)[:300]}

def data_score(x):
    total = 0
    for key in ["priceDataStatus", "newsDataStatus", "reportDataStatus", "chartDataStatus", "supplyDataStatus", "macroDataStatus"]:
        status = str(x.get(key, ""))
        if status == "connected":
            total += 17
        elif status == "partial":
            total += 8
        elif status == "derived":
            total += 4
        elif status == "missing":
            total += 2
    return max(0, min(100, total))

def final_score(x):
    q = iv(x.get("quantScore") or x.get("priceScore") or 50, 50)
    s = iv(x.get("supplyScore") or 50, 50)
    c = iv(x.get("companyScore") or x.get("reportScore") or 50, 50)
    e = iv(x.get("eventScore") or x.get("newsScore") or 50, 50)
    r = iv(x.get("reportScore") or 50, 50)
    ch = iv(x.get("chartScore") or 50, 50)
    m = iv(x.get("macroScore") or 50, 50)
    risk = iv(x.get("riskScore") or 50, 50)
    adj = iv(x.get("macroAdjustmentScore") or 0, 0)
    return max(0, min(100, round(q*.18+s*.18+c*.18+e*.14+r*.10+ch*.10+m*.07+risk*.05+adj)))

def main():
    date, date_debug = latest_market_date()
    now = datetime.now().isoformat(timespec="seconds")
    summary = {
        "version": "A430",
        "updatedAt": now,
        "marketDate": date,
        "dateDebug": date_debug[:10],
        "files": [],
        "total": 0,
        "chartConnected": 0,
        "chartFailed": 0,
        "supplyConnected": 0,
        "supplyFailed": 0,
        "debug": []
    }

    for path in FILES:
        raw = load(path)
        items, key = normalize(raw)
        if not items:
            continue

        for x in items:
            code = str(x.get("code") or "").zfill(6)
            name = str(x.get("name") or "")
            if not code or code == "000000":
                continue
            summary["total"] += 1

            chart_data, chart_debug = connect_chart(code, date)
            if chart_data:
                x.update(chart_data)
                summary["chartConnected"] += 1
            else:
                x["chartDataStatus"] = "failed"
                x["chartSummary"] = f"KRX OHLCV 차트 원자료 연결 실패: {chart_debug.get('reason','확인필요')}"
                summary["chartFailed"] += 1

            supply_data, supply_debug = connect_supply(code, date)
            if supply_data:
                x.update(supply_data)
                summary["supplyConnected"] += 1
            else:
                x["supplyDataStatus"] = "failed"
                x["supplyStatus"] = "failed"
                x["supplyReason"] = f"KRX 투자자별 수급 원자료 연결 실패: {supply_debug.get('reason','확인필요')}"
                x["supplyOpinion"] = x["supplyReason"]
                summary["supplyFailed"] += 1

            x["dataConnectionScore"] = data_score(x)
            x["dataConnectionReason"] = (
                f"A430 실제 원자료 연결 결과: 차트={x.get('chartDataStatus')}, "
                f"수급={x.get('supplyDataStatus')}, 연결점수={x.get('dataConnectionScore')}점입니다."
            )
            x["score"] = final_score(x)
            x["realtimeScore"] = x["score"]
            x["source"] = "a430_real_chart_supply_engine"
            x["targetEngineVersion"] = "A430"
            x["updatedAt"] = now

            if len(summary["debug"]) < 200:
                summary["debug"].append({
                    "code": code,
                    "name": name,
                    "chart": chart_debug,
                    "supply": supply_debug
                })

        if isinstance(raw, list):
            save(path, items)
        elif isinstance(raw, dict):
            raw[key if key != "none" else "candidates"] = items
            save(path, raw)

        summary["files"].append(str(path))

    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
