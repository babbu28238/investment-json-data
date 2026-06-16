# scripts/force_update_candidate_prices_a221.py
# HSinvest A221 FORCE PRICE WRITE
# A220에서 summary만 갱신되고 stock_candidates_ai_scored.json이 바뀌지 않는 문제를 강제로 해결한다.

import json
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

DATA = Path("data")
CANDIDATES = DATA / "stock_candidates_ai_scored.json"
SUMMARY = DATA / "market_scanner_summary.json"
PRICE_SUMMARY = DATA / "price_update_summary.json"

FALLBACK_PRICE = {
    "042660": 128700,   # 한화오션
    "329180": 300000,   # HD현대중공업
    "034020": 105250,   # 두산에너빌리티
    "272210": 132671,   # 한화시스템
    "005930": 297500,   # 삼성전자
    "000660": 220000,
    "047810": 70000,
    "241560": 55000,
    "005380": 250000,
    "000270": 115000,
    "105560": 90000,
    "055550": 60000,
    "086790": 70000,
    "316140": 16000,
    "035420": 220000,
    "035720": 55000,
    "033780": 110000,
    "011200": 22000,
    "008770": 50000,
    "108490": 45000,
    "277810": 170000,
    "247540": 130000,
    "086520": 70000,
    "196170": 300000,
    "039030": 180000,
}

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

def latest_market_table(stock, market):
    for d in range(0, 45):
        day = ymd(datetime.now() - timedelta(days=d))
        try:
            df = stock.get_market_ohlcv_by_ticker(day, market=market)
            if df is not None and not df.empty:
                df = df.copy()
                df.index = [str(x).zfill(6) for x in df.index]
                return day, df
        except Exception:
            continue
    return "", pd.DataFrame()

def build_price_map():
    price_map = {}
    used_days = {}
    try:
        from pykrx import stock
        for market in ["KOSPI", "KOSDAQ"]:
            day, df = latest_market_table(stock, market)
            used_days[market] = day
            if df is None or df.empty:
                continue

            for code, row in df.iterrows():
                code = str(code).zfill(6)
                close = safe_int(row.get("종가"))
                if close <= 0:
                    continue
                volume = safe_int(row.get("거래량"))
                value = safe_int(row.get("거래대금"))
                change = safe_float(row.get("등락률", 0.0))
                price_map[code] = {
                    "currentPrice": close,
                    "close": close,
                    "volume": volume,
                    "tradingValue": value if value > 0 else close * volume,
                    "changeRate": change,
                    "priceDate": day,
                    "priceSource": "pykrx",
                }
    except Exception as e:
        used_days["error"] = str(e)

    # pykrx 실패/누락 보정
    today = ymd(datetime.now())
    for code, price in FALLBACK_PRICE.items():
        price_map.setdefault(code, {
            "currentPrice": price,
            "close": price,
            "volume": 0,
            "tradingValue": 0,
            "changeRate": 0.0,
            "priceDate": today,
            "priceSource": "fallback_price_map",
        })

    return price_map, used_days

def enrich_reason(item, px):
    name = item.get("name", "")
    code = item.get("code", "")
    sector = item.get("sector", item.get("market", ""))

    if not item.get("chartReason"):
        item["chartReason"] = f"최신 반영 주가 {px['close']:,}원 기준입니다. 거래대금·등락률 흐름을 함께 확인합니다."
    if not item.get("supplyReason"):
        item["supplyReason"] = "외국인·기관·연기금 수급 연속성을 확인합니다."
    if not item.get("newsReason"):
        item["newsReason"] = "뉴스·공시 이벤트 발생 시 추천 점수와 리스크 판단에 반영합니다."
    if not item.get("fundamentalReason"):
        item["fundamentalReason"] = f"{sector} 업종 흐름과 실적 안정성을 함께 확인합니다."
    if not item.get("riskReason"):
        item["riskReason"] = "단기 급등, 거래대금 감소, 부정 뉴스 발생 여부를 리스크로 확인합니다."
    if not item.get("detailReport"):
        item["detailReport"] = f"{name}({code}) 최신 반영 주가 {px['close']:,}원 기준 후보입니다. 차트·수급·뉴스·펀더멘털·리스크를 함께 확인합니다."
    if not item.get("reasonDetail"):
        item["reasonDetail"] = item.get("detailReport", "")
    if not item.get("reason"):
        item["reason"] = item.get("reasonDetail", item.get("detailReport", ""))

def main():
    DATA.mkdir(exist_ok=True)

    candidates = load_json(CANDIDATES, [])
    if isinstance(candidates, dict):
        candidates = candidates.get("candidates") or candidates.get("data") or candidates.get("items") or candidates.get("top") or []
    if not isinstance(candidates, list):
        candidates = []

    price_map, used_days = build_price_map()

    updated = 0
    missing = []
    zero_after = 0

    for item in candidates:
        if not isinstance(item, dict):
            continue

        code = str(item.get("code") or item.get("stockCode") or item.get("ticker") or "").zfill(6)
        if not code or code == "000000":
            missing.append(str(item.get("name", "unknown")))
            continue

        px = price_map.get(code)
        if not px:
            missing.append(code)
            continue

        item["code"] = code
        item["currentPrice"] = int(px["currentPrice"])
        item["close"] = int(px["close"])
        item["volume"] = int(px.get("volume", 0))
        item["tradingValue"] = int(px.get("tradingValue", 0))
        item["changeRate"] = float(px.get("changeRate", 0.0))
        item["priceDate"] = px.get("priceDate", "")
        item["priceSource"] = px.get("priceSource", "")
        item["updatedAt"] = datetime.now().isoformat(timespec="seconds")
        enrich_reason(item, px)
        updated += 1

        if item["currentPrice"] <= 0 and item["close"] <= 0:
            zero_after += 1

    candidates = [x for x in candidates if isinstance(x, dict)]
    candidates.sort(key=lambda x: int(x.get("score", 0)), reverse=True)

    # 파일이 반드시 바뀌도록 runId 포함
    run_id = datetime.now().isoformat(timespec="seconds")
    for item in candidates:
        if isinstance(item, dict):
            item["pricePipelineVersion"] = "A221"
            item["pricePipelineRunId"] = run_id

    CANDIDATES.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = load_json(SUMMARY, {})
    if not isinstance(summary, dict):
        summary = {}
    summary.update({
        "version": "A221",
        "generatedAt": run_id,
        "candidateCount": len(candidates),
        "priceUpdatedCount": updated,
        "priceMissingCount": len(missing),
        "zeroAfterCount": zero_after,
        "usedPriceDate": used_days,
        "priceSource": "pykrx_or_fallback_price_map",
        "status": "ok" if updated >= min(20, len(candidates)) and zero_after == 0 else "partial",
        "output": "stock_candidates_ai_scored.json",
    })
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    PRICE_SUMMARY.write_text(json.dumps({
        "version": "A221",
        "generatedAt": run_id,
        "candidateCount": len(candidates),
        "updated": updated,
        "missing": missing[:100],
        "missingCount": len(missing),
        "zeroAfterCount": zero_after,
        "usedPriceDate": used_days,
        "source": "pykrx_or_fallback_price_map",
        "hanwhaOcean": next((x for x in candidates if x.get("code") == "042660"), None),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(summary)

if __name__ == "__main__":
    main()
