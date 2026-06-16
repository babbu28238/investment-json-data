# scripts/update_stock_candidate_prices_a220.py
# HSinvest A220 REAL PRICE PIPELINE
# 기존 stock_candidates_ai_scored.json의 currentPrice/close를 pykrx 최신 종가로 자동 갱신한다.

import json
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd

DATA = Path("data")
CANDIDATES = DATA / "stock_candidates_ai_scored.json"
SUMMARY = DATA / "market_scanner_summary.json"
PRICE_SUMMARY = DATA / "price_update_summary.json"

def ymd(dt):
    return dt.strftime("%Y%m%d")

def safe_int(v, default=0):
    try:
        if pd.isna(v):
            return default
        return int(float(v))
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
    from pykrx import stock

    price_map = {}
    used_days = {}

    for market in ["KOSPI", "KOSDAQ"]:
        day, df = latest_market_table(stock, market)
        used_days[market] = day
        if df is None or df.empty:
            continue

        for code, row in df.iterrows():
            code = str(code).zfill(6)
            close = safe_int(row.get("종가"))
            volume = safe_int(row.get("거래량"))
            value = safe_int(row.get("거래대금"))
            change = safe_float(row.get("등락률", 0.0))

            if close <= 0:
                continue

            price_map[code] = {
                "currentPrice": close,
                "close": close,
                "volume": volume,
                "tradingValue": value if value > 0 else close * volume,
                "changeRate": change,
                "priceDate": day,
                "priceSource": "pykrx",
            }

    return price_map, used_days

def main():
    DATA.mkdir(exist_ok=True)

    candidates = load_json(CANDIDATES, [])
    if not isinstance(candidates, list):
        if isinstance(candidates, dict):
            candidates = candidates.get("candidates") or candidates.get("data") or candidates.get("items") or []
        else:
            candidates = []

    price_map, used_days = build_price_map()

    updated = 0
    missing = []
    zero_before = 0

    for item in candidates:
        if not isinstance(item, dict):
            continue

        code = str(item.get("code") or item.get("stockCode") or item.get("ticker") or "").zfill(6)
        if not code or code == "000000":
            continue

        before_price = safe_int(item.get("currentPrice", item.get("close", 0)))
        if before_price <= 0:
            zero_before += 1

        px = price_map.get(code)
        if not px:
            missing.append(code)
            continue

        item["code"] = code
        item["currentPrice"] = px["currentPrice"]
        item["close"] = px["close"]
        item["volume"] = px["volume"]
        item["tradingValue"] = px["tradingValue"]
        item["changeRate"] = px["changeRate"]
        item["priceDate"] = px["priceDate"]
        item["priceSource"] = px["priceSource"]
        item["updatedAt"] = datetime.now().isoformat(timespec="seconds")
        updated += 1

        # 화면 상세 보강
        name = item.get("name", "")
        sector = item.get("sector", item.get("market", ""))
        item.setdefault("chartReason", "")
        item.setdefault("supplyReason", "")
        item.setdefault("newsReason", "")
        item.setdefault("fundamentalReason", "")
        item.setdefault("riskReason", "")
        item.setdefault("detailReport", "")
        item.setdefault("reasonDetail", "")

        if not item["chartReason"]:
            item["chartReason"] = f"최신 종가 {px['close']:,}원, 거래대금 {px['tradingValue']:,}원, 등락률 {px['changeRate']:.2f}% 기준으로 반영했습니다."
        if not item["fundamentalReason"]:
            item["fundamentalReason"] = f"{sector} 업종 흐름과 실적 안정성을 함께 확인합니다."
        if not item["detailReport"]:
            item["detailReport"] = f"{name}({code}) 최신 종가 {px['close']:,}원 기준 후보입니다. 차트·수급·뉴스·펀더멘털·리스크를 함께 확인합니다."
        if not item["reasonDetail"]:
            item["reasonDetail"] = item["detailReport"]

    candidates = [x for x in candidates if isinstance(x, dict)]
    candidates.sort(key=lambda x: int(x.get("score", 0)), reverse=True)

    CANDIDATES.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")

    old_summary = load_json(SUMMARY, {})
    if not isinstance(old_summary, dict):
        old_summary = {}

    old_summary.update({
        "version": "A220",
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "candidateCount": len(candidates),
        "priceUpdatedCount": updated,
        "priceMissingCount": len(missing),
        "zeroBeforeCount": zero_before,
        "usedPriceDate": used_days,
        "priceSource": "pykrx",
        "status": "ok" if updated >= min(20, len(candidates)) else "partial",
        "output": "stock_candidates_ai_scored.json",
    })
    SUMMARY.write_text(json.dumps(old_summary, ensure_ascii=False, indent=2), encoding="utf-8")

    PRICE_SUMMARY.write_text(json.dumps({
        "version": "A220",
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "candidateCount": len(candidates),
        "updated": updated,
        "missing": missing[:100],
        "missingCount": len(missing),
        "usedPriceDate": used_days,
        "source": "pykrx",
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(old_summary)

if __name__ == "__main__":
    main()
