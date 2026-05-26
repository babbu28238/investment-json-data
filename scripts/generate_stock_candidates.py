# -*- coding: utf-8 -*-
"""
V99 KRX Universe Top50 Auto Selector

목표:
- 임의 관심종목 50개가 아니라 KOSPI/KOSDAQ 전체 종목에서 자동 후보 선별
- 거래대금 상위 유동성 종목을 1차 후보군으로 압축
- 가격·기술지표 기반으로 상위 50개 stock_candidates.json 생성
- 기존 앱 JSON 스키마와 호환 유지

주의:
- 수급 조회는 안정성 문제로 비활성화
- GitHub Actions 환경에서 pykrx 조회가 막히면 V99.1에서 fallback 구조로 보완
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from pykrx import stock

OUTPUT_JSON = "stock_candidates.json"
SUMMARY_JSON = "v99_generation_summary.json"
ERROR_LOG = "v99_collection_errors.txt"

LOOKBACK_DAYS = 180
SLEEP_SECONDS = 0.10

# 전체 시장에서 바로 모든 종목 OHLCV를 계산하면 오래 걸리므로,
# 거래대금 상위 종목만 1차 후보군으로 압축합니다.
UNIVERSE_TOP_N_BY_TRADING_VALUE = 350
FINAL_TOP_N = 50

MIN_PRICE = 3000
MIN_TRADING_VALUE = 3_000_000_000  # 30억
MIN_MARKET_CAP = 100_000_000_000   # 1,000억

EXCLUDE_KEYWORDS = [
    "스팩", "SPAC", "ETN", "리츠", "인프라", "우선주", "우", "ETF"
]


def ymd(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def safe_int(value, default: int = 0) -> int:
    try:
        if value is None or pd.isna(value):
            return default
        return int(float(value))
    except Exception:
        return default


def normalize_code(code: str) -> str:
    return str(code).strip().zfill(6)


def recent_market_date(code: str = "005930", max_back_days: int = 20) -> str:
    today = datetime.today()
    for i in range(max_back_days + 1):
        d = today - timedelta(days=i)
        date = ymd(d)
        try:
            df = stock.get_market_ohlcv_by_date(date, date, code)
            if df is not None and not df.empty:
                return date
        except Exception:
            pass
    raise RuntimeError("최근 거래일을 찾지 못했습니다.")


def is_excluded_name(name: str) -> bool:
    upper_name = str(name).upper()
    for keyword in EXCLUDE_KEYWORDS:
        if keyword.upper() in upper_name:
            return True

    # 한국 우선주 간단 제외. 예: 삼성전자우
    if str(name).endswith("우"):
        return True

    return False


def get_market_name_map(base_date: str) -> dict[str, str]:
    name_map = {}
    for market in ["KOSPI", "KOSDAQ"]:
        try:
            tickers = stock.get_market_ticker_list(base_date, market=market)
            for code in tickers:
                try:
                    name_map[normalize_code(code)] = stock.get_market_ticker_name(code)
                except Exception:
                    name_map[normalize_code(code)] = normalize_code(code)
        except Exception as e:
            print(f"[경고] {market} ticker list 실패: {e}")
    return name_map


def build_liquid_universe(base_date: str) -> pd.DataFrame:
    frames = []
    for market in ["KOSPI", "KOSDAQ"]:
        try:
            df = stock.get_market_cap_by_ticker(base_date, market=market)
            if df is None or df.empty:
                print(f"[경고] {market} 시가총액 데이터 없음")
                continue
            df = df.copy()
            df["code"] = [normalize_code(c) for c in df.index]
            df["market"] = market
            frames.append(df)
            print(f"{market} 시가총액/거래대금 수집: {len(df)}개")
        except Exception as e:
            print(f"[실패] {market} 시가총액 수집 실패: {e}")

    if not frames:
        raise RuntimeError("KOSPI/KOSDAQ 유니버스 수집 실패")

    universe = pd.concat(frames, ignore_index=True)
    name_map = get_market_name_map(base_date)
    universe["name"] = universe["code"].map(name_map).fillna(universe["code"])

    # pykrx 컬럼: 종가, 시가총액, 거래량, 거래대금, 상장주식수
    required_cols = ["종가", "시가총액", "거래대금"]
    for col in required_cols:
        if col not in universe.columns:
            raise RuntimeError(f"필수 컬럼 누락: {col}")

    universe = universe[
        (universe["종가"] >= MIN_PRICE) &
        (universe["거래대금"] >= MIN_TRADING_VALUE) &
        (universe["시가총액"] >= MIN_MARKET_CAP)
    ].copy()

    universe = universe[~universe["name"].apply(is_excluded_name)].copy()
    universe = universe.sort_values("거래대금", ascending=False).head(UNIVERSE_TOP_N_BY_TRADING_VALUE)

    print(f"1차 유동성 후보군: {len(universe)}개")
    return universe.reset_index(drop=True)


def calc_rsi(close: pd.Series, period: int = 14) -> float:
    close = pd.Series(close).astype(float)
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return safe_float(rsi.iloc[-1], 50.0)


def calc_macd(close: pd.Series) -> tuple[float, float]:
    close = pd.Series(close).astype(float)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return safe_float(macd.iloc[-1]), safe_float(signal.iloc[-1])


def cloud_breakout(df: pd.DataFrame) -> bool:
    if df is None or len(df) < 60:
        return False
    high = df["고가"].astype(float)
    low = df["저가"].astype(float)
    close = df["종가"].astype(float)

    conversion = (high.rolling(9).max() + low.rolling(9).min()) / 2
    base = (high.rolling(26).max() + low.rolling(26).min()) / 2
    span_a = (conversion + base) / 2
    span_b = (high.rolling(52).max() + low.rolling(52).min()) / 2

    top = max(safe_float(span_a.iloc[-1]), safe_float(span_b.iloc[-1]))
    return safe_float(close.iloc[-1]) > top and top > 0


def weekly_cloud_breakout(daily_df: pd.DataFrame) -> bool:
    try:
        df = daily_df.copy()
        df.index = pd.to_datetime(df.index)
        weekly = pd.DataFrame()
        weekly["시가"] = df["시가"].resample("W-FRI").first()
        weekly["고가"] = df["고가"].resample("W-FRI").max()
        weekly["저가"] = df["저가"].resample("W-FRI").min()
        weekly["종가"] = df["종가"].resample("W-FRI").last()
        weekly = weekly.dropna()
        return cloud_breakout(weekly)
    except Exception:
        return False


def score_to_grade(score_value: int) -> str:
    if score_value >= 88:
        return "S"
    if score_value >= 78:
        return "A"
    if score_value >= 66:
        return "B"
    if score_value >= 52:
        return "C"
    return "D"


def infer_industry(name: str, code: str, market: str) -> str:
    # V99는 외부 업종 DB 없이 자동 선별하므로 우선 간단 분류만 제공합니다.
    # V100에서 KRX 업종/테마 매핑을 붙일 예정입니다.
    n = str(name)
    if any(k in n for k in ["삼성전자", "SK하이닉스", "한미반도체", "이오테크닉스", "원익", "심텍"]):
        return "반도체·AI"
    if any(k in n for k in ["현대차", "기아", "모비스", "글로비스"]):
        return "자동차"
    if any(k in n for k in ["한화", "LIG", "한국항공", "현대로템"]):
        return "방산·우주항공"
    if any(k in n for k in ["조선", "오션", "중공업"]):
        return "조선"
    if any(k in n for k in ["금융", "은행", "지주", "KB", "신한", "하나", "우리"]):
        return "금융·밸류업"
    if any(k in n for k in ["바이오", "셀트리온", "한미약품", "삼성바이오"]):
        return "바이오·제약"
    if any(k in n for k in ["에너지", "전력", "두산"]):
        return "에너지·원전"
    return f"{market} 자동선별"


def make_recent_issue(
    weekly_breakout: bool,
    daily_breakout: bool,
    rsi_value: float,
    price_change_rate: float,
    trading_value: int,
    rank: int,
) -> str:
    parts = [f"KRX 전체 자동선별 TOP {rank}"]
    if weekly_breakout:
        parts.append("주봉 구름대 돌파")
    if daily_breakout:
        parts.append("일봉 구름대 돌파")
    if 45 <= rsi_value <= 70:
        parts.append("RSI 안정권")
    elif rsi_value > 75:
        parts.append("RSI 과열 주의")
    if price_change_rate > 0:
        parts.append("단기 상승 흐름")
    if trading_value >= 30_000_000_000:
        parts.append("거래대금 우수")
    parts.append("수급 조회 비활성화")
    return " / ".join(parts)


def calculate_candidate(row: pd.Series, base_date: str, rank_by_value: int) -> dict | None:
    code = normalize_code(row["code"])
    name = str(row["name"])
    market = str(row["market"])
    end = datetime.strptime(base_date, "%Y%m%d")
    start = end - timedelta(days=LOOKBACK_DAYS)

    ohlcv = stock.get_market_ohlcv_by_date(ymd(start), base_date, code)
    if ohlcv is None or ohlcv.empty or len(ohlcv) < 80:
        raise RuntimeError("OHLCV 데이터 부족")

    close = ohlcv["종가"].astype(float)
    current_price = safe_int(close.iloc[-1])
    prev_close = safe_float(close.iloc[-2], current_price)
    price_change_rate = ((current_price - prev_close) / prev_close * 100) if prev_close > 0 else 0.0

    ma5 = safe_float(close.rolling(5).mean().iloc[-1])
    ma20 = safe_float(close.rolling(20).mean().iloc[-1])
    ma60 = safe_float(close.rolling(60).mean().iloc[-1])
    ma120 = safe_float(close.rolling(120).mean().iloc[-1]) if len(close) >= 120 else 0.0

    rsi_value = calc_rsi(close)
    macd_value, macd_signal = calc_macd(close)
    daily_breakout = cloud_breakout(ohlcv)
    weekly_breakout = weekly_cloud_breakout(ohlcv)

    trading_value = safe_int(row.get("거래대금", 0))
    market_cap = safe_int(row.get("시가총액", 0))

    technical = 38

    if current_price > ma5 > 0:
        technical += 4
    if current_price > ma20 > 0:
        technical += 8
    if current_price > ma60 > 0:
        technical += 8
    if ma20 > ma60 > 0:
        technical += 6
    if ma60 > ma120 > 0:
        technical += 4
    if weekly_breakout:
        technical += 10
    if daily_breakout:
        technical += 6
    if macd_value > macd_signal:
        technical += 6
    if 45 <= rsi_value <= 70:
        technical += 6
    elif 70 < rsi_value <= 78:
        technical += 1
    elif rsi_value > 78:
        technical -= 6

    if price_change_rate > 0:
        technical += 3
    if price_change_rate > 7:
        technical -= 5

    technical = int(max(0, min(82, technical)))

    liquidity = 0
    if trading_value >= 100_000_000_000:
        liquidity += 8
    elif trading_value >= 50_000_000_000:
        liquidity += 6
    elif trading_value >= 20_000_000_000:
        liquidity += 4
    elif trading_value >= 10_000_000_000:
        liquidity += 2

    if market_cap >= 10_000_000_000_000:
        liquidity += 4
    elif market_cap >= 1_000_000_000_000:
        liquidity += 2

    liquidity = int(max(0, min(12, liquidity)))

    issue = 0
    if weekly_breakout and daily_breakout:
        issue += 4
    if macd_value > macd_signal and 45 <= rsi_value <= 70:
        issue += 3
    if rank_by_value <= 50:
        issue += 3
    elif rank_by_value <= 100:
        issue += 2
    elif rank_by_value <= 200:
        issue += 1

    issue = int(max(0, min(8, issue)))

    score = int(max(0, min(100, technical + liquidity + issue)))

    industry = infer_industry(name, code, market)
    recent_issue = make_recent_issue(
        weekly_breakout=weekly_breakout,
        daily_breakout=daily_breakout,
        rsi_value=rsi_value,
        price_change_rate=price_change_rate,
        trading_value=trading_value,
        rank=rank_by_value,
    )

    return {
        "name": name,
        "code": code,
        "market": market,
        "industry": industry,
        "grade": score_to_grade(score),
        "previousGrade": None,
        "score": score,
        "technicalScore": technical,
        "flowScore": 0,
        "issueScore": issue,
        "flowDataStatus": "disabled",
        "currentPrice": current_price,
        "priceChangeRate": round(price_change_rate, 2),
        "weeklyCloudBreakout": bool(weekly_breakout),
        "dailyCloudBreakout": bool(daily_breakout),
        "reportCount": 0,
        "targetPriceUp": False,
        "foreignNetBuy": False,
        "pensionNetBuy": False,
        "institutionNetBuy": False,
        "recentIssue": recent_issue,
        "tradingValue": trading_value,
        "marketCap": market_cap,
        "rsi": round(rsi_value, 2),
        "universeRankByTradingValue": rank_by_value,
        "selectionSource": "KRX_UNIVERSE_AUTO_TOP50_V99",
    }


def generate_stock_candidates():
    base_date = recent_market_date()
    print("분석 기준 거래일:", base_date)

    universe = build_liquid_universe(base_date)
    candidates = []
    errors = []

    for idx, (_, row) in enumerate(universe.iterrows(), start=1):
        try:
            item = calculate_candidate(row, base_date, idx)
            if item:
                candidates.append(item)
                print(
                    f"[성공] {idx}/{len(universe)} {item['code']} {item['name']} "
                    f"{item['grade']} {item['score']} "
                    f"(기술 {item['technicalScore']}, 유동성 {item.get('tradingValue', 0):,})"
                )
        except Exception as e:
            msg = f"{row.get('code', '')} {row.get('name', '')}: {e}"
            errors.append(msg)
            print("[실패]", msg)

        time.sleep(SLEEP_SECONDS)

    candidates = sorted(
        candidates,
        key=lambda x: (
            x["score"],
            x["weeklyCloudBreakout"],
            x["dailyCloudBreakout"],
            x.get("tradingValue", 0)
        ),
        reverse=True
    )

    final_candidates = candidates[:FINAL_TOP_N]

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(final_candidates, f, ensure_ascii=False, indent=2)

    with open(ERROR_LOG, "w", encoding="utf-8") as f:
        f.write("\n".join(errors))

    summary = {
        "version": "V99_KRX_UNIVERSE_AUTO_TOP50",
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "baseDate": base_date,
        "universeTopNByTradingValue": UNIVERSE_TOP_N_BY_TRADING_VALUE,
        "candidateCalculatedCount": len(candidates),
        "finalCandidateCount": len(final_candidates),
        "errorCount": len(errors),
        "filters": {
            "minPrice": MIN_PRICE,
            "minTradingValue": MIN_TRADING_VALUE,
            "minMarketCap": MIN_MARKET_CAP
        }
    }

    with open(SUMMARY_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("=" * 70)
    print("V99 전체 시장 자동선별 완료")
    print("분석 기준 거래일:", base_date)
    print("계산 후보 수:", len(candidates))
    print("최종 저장 후보 수:", len(final_candidates))
    print("오류 수:", len(errors))
    print("상위 10개:")
    for item in final_candidates[:10]:
        print(item["code"], item["name"], item["grade"], item["score"], item["recentIssue"])

    return final_candidates


if __name__ == "__main__":
    generate_stock_candidates()
