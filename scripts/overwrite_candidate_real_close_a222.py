# scripts/overwrite_candidate_real_close_a222.py
# HSinvest A222 REAL CLOSE OVERWRITE
# stock_candidates_ai_scored.json의 모든 후보 currentPrice/close를 종목코드별 실제 최신 종가로 덮어쓴다.

import json
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

DATA = Path("data")
CANDIDATES = DATA / "stock_candidates_ai_scored.json"
SUMMARY = DATA / "market_scanner_summary.json"
PRICE_SUMMARY = DATA / "price_update_summary.json"
DETAIL = DATA / "price_update_detail_a222.json"

def ymd(dt):
    return dt.strftime("%Y%m%d")

def safe_int(v, default=0):
    try:
        if pd.isna(v):
            return default
        return int(float(v))
    except Exception:
        try:
            return int(str(v).replace(",", ""))
        except Exception:
            return default

def safe_float(v, default=0.0):
    try:
        if pd.isna(v):
            return default
        return float(v)
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
            value = raw.get(key)
            if isinstance(value, list):
                return value
    return []

def latest_close_for_code(stock, code, max_days=45):
    code = str(code).zfill(6)

    # 1) 가장 정확한 방식: 해당 종목의 일자별 OHLCV 직접 조회
    for d in range(0, max_days):
        day = datetime.now() - timedelta(days=d)
        start = ymd(day)
        end = start
        try:
            df = stock.get_market_ohlcv_by_date(start, end, code)
            if df is not None and not df.empty:
                row = df.iloc[-1]
                close = safe_int(row.get("종가"))
                if close > 0:
                    volume = safe_int(row.get("거래량"))
                    value = safe_int(row.get("거래대금"))
                    change = safe_float(row.get("등락률", 0.0))
                    return {
                        "currentPrice": close,
                        "close": close,
                        "volume": volume,
                        "tradingValue": value if value > 0 else close * volume,
                        "changeRate": change,
                        "priceDate": start,
                        "priceSource": "pykrx_by_date",
                    }
        except Exception:
            continue

    # 2) 보조 방식: 시장별 ticker table에서 찾기
    for market in ["KOSPI", "KOSDAQ"]:
        for d in range(0, max_days):
            day = ymd(datetime.now() - timedelta(days=d))
            try:
                df = stock.get_market_ohlcv_by_ticker(day, market=market)
                if df is None or df.empty:
                    continue
                df = df.copy()
                df.index = [str(x).zfill(6) for x in df.index]
                if code not in df.index:
                    continue
                row = df.loc[code]
                close = safe_int(row.get("종가"))
                if close > 0:
                    volume = safe_int(row.get("거래량"))
                    value = safe_int(row.get("거래대금"))
                    change = safe_float(row.get("등락률", 0.0))
                    return {
                        "currentPrice": close,
                        "close": close,
                        "volume": volume,
                        "tradingValue": value if value > 0 else close * volume,
                        "changeRate": change,
                        "priceDate": day,
                        "priceSource": f"pykrx_ticker_{market}",
                    }
            except Exception:
                continue

    return None

def ensure_detail(item, px):
    code = item.get("code", "")
    name = item.get("name", "")
    sector = item.get("sector", item.get("market", ""))

    item["chartReason"] = f"최신 종가 {px['close']:,}원, 거래대금 {px['tradingValue']:,}원, 등락률 {px['changeRate']:.2f}% 기준으로 반영했습니다."
    if not item.get("supplyReason"):
        item["supplyReason"] = "외국인·기관·연기금 수급 연속성을 확인합니다."
    if not item.get("newsReason"):
        item["newsReason"] = "뉴스·공시 이벤트는 추천 점수와 리스크 판단에 반영됩니다."
    if not item.get("fundamentalReason"):
        item["fundamentalReason"] = f"{sector} 업종 흐름과 실적 안정성을 함께 확인합니다."
    if not item.get("riskReason"):
        item["riskReason"] = "단기 급등, 거래대금 감소, 부정 뉴스 발생 여부를 리스크로 확인합니다."

    report = f"{name}({code}) 최신 종가 {px['close']:,}원 기준 후보입니다. 차트·수급·뉴스·펀더멘털·리스크를 함께 확인합니다."
    if not item.get("detailReport"):
        item["detailReport"] = report
    if not item.get("reasonDetail"):
        item["reasonDetail"] = item.get("detailReport", report)
    if not item.get("reason"):
        item["reason"] = item.get("reasonDetail", report)

def main():
    from pykrx import stock

    DATA.mkdir(exist_ok=True)
    raw = load_json(CANDIDATES, [])
    candidates = normalize_candidates(raw)

    run_id = datetime.now().isoformat(timespec="seconds")
    details = []
    updated = 0
    failed = 0
    zero_after = 0

    for item in candidates:
        if not isinstance(item, dict):
            continue

        code = str(item.get("code") or item.get("stockCode") or item.get("ticker") or "").zfill(6)
        name = item.get("name", "")
        if not code or code == "000000":
            failed += 1
            details.append({"code": code, "name": name, "status": "fail", "reason": "missing_code"})
            continue

        before = safe_int(item.get("currentPrice", item.get("close", 0)))
        px = latest_close_for_code(stock, code)

        if px is None:
            failed += 1
            after = before
            if after <= 0:
                zero_after += 1
            details.append({
                "code": code,
                "name": name,
                "beforePrice": before,
                "afterPrice": after,
                "status": "fail",
                "reason": "pykrx_price_not_found",
            })
            continue

        item["code"] = code
        item["currentPrice"] = int(px["currentPrice"])
        item["close"] = int(px["close"])
        item["volume"] = int(px.get("volume", 0))
        item["tradingValue"] = int(px.get("tradingValue", 0))
        item["changeRate"] = float(px.get("changeRate", 0.0))
        item["priceDate"] = px.get("priceDate", "")
        item["priceSource"] = px.get("priceSource", "")
        item["updatedAt"] = run_id
        item["pricePipelineVersion"] = "A222"
        item["pricePipelineRunId"] = run_id

        ensure_detail(item, px)

        after = int(px["currentPrice"])
        updated += 1
        if after <= 0:
            zero_after += 1

        details.append({
            "code": code,
            "name": name,
            "beforePrice": before,
            "afterPrice": after,
            "priceDate": px.get("priceDate", ""),
            "priceSource": px.get("priceSource", ""),
            "status": "updated",
            "changed": before != after,
        })

    candidates = [x for x in candidates if isinstance(x, dict)]
    candidates.sort(key=lambda x: int(x.get("score", 0)), reverse=True)

    # 변경 강제: 메타 필드
    for item in candidates:
        if isinstance(item, dict):
            item["priceOverwriteVersion"] = "A222"
            item["priceOverwriteRunId"] = run_id

    CANDIDATES.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = load_json(SUMMARY, {})
    if not isinstance(summary, dict):
        summary = {}
    summary.update({
        "version": "A222",
        "generatedAt": run_id,
        "candidateCount": len(candidates),
        "priceUpdatedCount": updated,
        "priceFailedCount": failed,
        "zeroAfterCount": zero_after,
        "status": "ok" if updated >= min(20, len(candidates)) and zero_after == 0 else "partial",
        "priceSource": "pykrx_by_date",
        "output": "stock_candidates_ai_scored.json",
    })
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    PRICE_SUMMARY.write_text(json.dumps({
        "version": "A222",
        "generatedAt": run_id,
        "candidateCount": len(candidates),
        "updated": updated,
        "failed": failed,
        "zeroAfterCount": zero_after,
        "hanwhaOcean": next((x for x in details if x.get("code") == "042660"), None),
        "source": "pykrx_by_date",
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    DETAIL.write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8")

    print(summary)
    print("HanwhaOcean:", next((x for x in details if x.get("code") == "042660"), None))

if __name__ == "__main__":
    main()
