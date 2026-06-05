#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CV302 NO-LOGIN MARKET UNIVERSE GENERATOR

역할:
- KOSPI/KOSDAQ 전체 종목을 pykrx로 수집
- 가격/시총/거래대금 기본 필터 적용
- 거래대금 상위 1200개를 대상으로 기술적 점수 계산
- 기존 V224 Mapper가 읽는 stock_candidates_input.csv 생성
- market_universe.json, market_scan_results.json, market_scanner_summary.json 생성

다음 단계:
- scripts/update_stock_candidates_v224_mapper.py 실행
- scripts/update_live_quotes.py 실행
- scripts/merge_real_data_v252.py 실행(선택)

주의:
- GitHub Actions에서 pykrx 또는 KRX 조회가 실패하면 fallback 유니버스로 최소 파일을 생성합니다.
"""

from __future__ import annotations

import csv
import json
import math
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
from pykrx import stock

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()

OUT_INPUT_CSV = ROOT / "stock_candidates_input.csv"
OUT_UNIVERSE_JSON = ROOT / "market_universe.json"
OUT_SCAN_JSON = ROOT / "market_scan_results.json"
OUT_SUMMARY_JSON = ROOT / "market_scanner_summary.json"
OUT_ERRORS_TXT = ROOT / "market_scanner_errors.txt"

LOOKBACK_DAYS = 180
UNIVERSE_TOP_N_BY_TRADING_VALUE = 1200
FINAL_INPUT_TOP_N = 120
SLEEP_SECONDS = 0.05

MIN_PRICE = 3000
MIN_TRADING_VALUE = 1_000_000_000
MIN_MARKET_CAP = 50_000_000_000

EXCLUDE_KEYWORDS = ["스팩", "SPAC", "ETN", "ETF", "리츠", "인프라", "우선주"]

FALLBACK_UNIVERSE = [
    ("005930", "삼성전자", "KOSPI"), ("000660", "SK하이닉스", "KOSPI"),
    ("373220", "LG에너지솔루션", "KOSPI"), ("207940", "삼성바이오로직스", "KOSPI"),
    ("005380", "현대차", "KOSPI"), ("000270", "기아", "KOSPI"),
    ("068270", "셀트리온", "KOSPI"), ("005490", "POSCO홀딩스", "KOSPI"),
    ("035420", "NAVER", "KOSPI"), ("105560", "KB금융", "KOSPI"),
    ("042660", "한화오션", "KOSPI"), ("012450", "한화에어로스페이스", "KOSPI"),
    ("272210", "한화시스템", "KOSPI"), ("047810", "한국항공우주", "KOSPI"),
    ("079550", "LIG넥스원", "KOSPI"), ("034020", "두산에너빌리티", "KOSPI"),
    ("267260", "HD현대일렉트릭", "KOSPI"), ("010120", "LS ELECTRIC", "KOSPI"),
    ("247540", "에코프로비엠", "KOSDAQ"), ("086520", "에코프로", "KOSDAQ"),
    ("196170", "알테오젠", "KOSDAQ"), ("277810", "레인보우로보틱스", "KOSDAQ"),
    ("039030", "이오테크닉스", "KOSDAQ"), ("058470", "리노공업", "KOSDAQ"),
]

THEME_RULES = [
    ("반도체·AI", ["삼성전자", "SK하이닉스", "한미반도체", "이오테크닉스", "원익IPS", "리노공업", "ISC", "하나마이크론", "주성엔지니어링", "테크윙"], ["반도체", "AI", "HBM"]),
    ("방산·우주항공", ["한화시스템", "한화에어로스페이스", "한국항공우주", "LIG넥스원", "현대로템", "풍산", "쎄트렉아이", "인텔리안테크", "AP위성"], ["방산", "우주항공", "수주"]),
    ("조선·해양", ["HD현대중공업", "HD한국조선해양", "삼성중공업", "한화오션", "현대미포", "한화엔진"], ["조선", "LNG", "수주"]),
    ("원전·전력·에너지", ["두산에너빌리티", "한전기술", "한전KPS", "한국전력", "LS ELECTRIC", "효성중공업", "HD현대일렉트릭", "일진전기", "대한전선", "지투파워"], ["원전", "전력기기", "에너지"]),
    ("2차전지·소재", ["LG에너지솔루션", "삼성SDI", "SK이노베이션", "엘앤에프", "에코프로비엠", "에코프로", "포스코퓨처엠", "POSCO홀딩스", "엔켐"], ["2차전지", "소재", "ESS"]),
    ("자동차·모빌리티", ["현대차", "기아", "현대모비스", "HL만도", "한온시스템", "에스엘", "현대위아"], ["자동차", "모빌리티", "전장"]),
    ("금융·밸류업", ["KB금융", "신한지주", "하나금융지주", "우리금융지주", "기업은행", "삼성생명", "삼성화재", "미래에셋증권", "한국금융지주", "키움증권", "메리츠금융지주"], ["금융", "밸류업", "배당"]),
    ("바이오·제약", ["삼성바이오로직스", "셀트리온", "SK바이오팜", "한미약품", "유한양행", "알테오젠", "리가켐바이오", "HLB", "휴젤", "메디톡스", "삼천당제약"], ["바이오", "제약", "신약"]),
    ("인터넷·게임·콘텐츠", ["NAVER", "카카오", "크래프톤", "엔씨소프트", "넷마블", "펄어비스", "카카오게임즈", "위메이드", "하이브", "JYP Ent.", "에스엠", "CJ ENM"], ["인터넷", "게임", "콘텐츠"]),
    ("로봇·자동화", ["레인보우로보틱스", "고영", "로보스타", "유일로보틱스", "뉴로메카", "로보티즈"], ["로봇", "자동화", "피지컬AI"]),
]


def now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def ymd(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def normalize_code(code: Any) -> str:
    return str(code).strip().zfill(6)[-6:]


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(str(value).replace(",", ""))
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(round(safe_float(value, float(default))))
    except Exception:
        return default


def recent_market_date(max_back_days: int = 20) -> str:
    today = datetime.now(KST).replace(tzinfo=None)
    for i in range(max_back_days + 1):
        d = today - timedelta(days=i)
        date = ymd(d)
        try:
            df = stock.get_market_ohlcv_by_date(date, date, "005930")
            if df is not None and not df.empty:
                return date
        except Exception:
            pass
    return ymd(today)


def classify(name: str, market: str) -> Tuple[str, str, str]:
    n = str(name).upper()
    for industry, keywords, tags in THEME_RULES:
        if any(k.upper() in n for k in keywords):
            return industry, "·".join(tags), "high"
    return f"{market} 자동선별", "자동선별·거래대금", "low"


def is_excluded_name(name: str) -> bool:
    n = str(name).upper().strip()
    if any(k.upper() in n for k in EXCLUDE_KEYWORDS):
        return True
    if str(name).endswith("우"):
        return True
    return False


def market_name_map(base_date: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for market in ["KOSPI", "KOSDAQ"]:
        try:
            for code in stock.get_market_ticker_list(base_date, market=market):
                result[normalize_code(code)] = stock.get_market_ticker_name(code)
        except Exception as e:
            print(f"[WARN] ticker list failed {market}: {e}")
    return result


def pick_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    """pykrx 버전별 컬럼명 차이를 흡수하기 위한 컬럼 탐색."""
    if df is None or df.empty:
        return None
    normalized = {str(c).replace(" ", "").replace("_", "").lower(): c for c in df.columns}
    for cand in candidates:
        key = str(cand).replace(" ", "").replace("_", "").lower()
        if key in normalized:
            return normalized[key]
    for c in df.columns:
        ctext = str(c).replace(" ", "").replace("_", "").lower()
        for cand in candidates:
            key = str(cand).replace(" ", "").replace("_", "").lower()
            if key and key in ctext:
                return c
    return None


def latest_ohlcv_snapshot(code: str, base_date: str) -> Optional[Dict[str, Any]]:
    """
    V302 핵심: KRX_ID/KRX_PW 없이 종목별 OHLCV로 유니버스 생성.
    get_market_ohlcv_by_ticker가 GitHub Actions에서 실패하므로,
    종목별 get_market_ohlcv_by_date만 사용한다.
    """
    end = datetime.strptime(base_date, "%Y%m%d")
    for back in [10, 20, 40]:
        start = end - timedelta(days=back)
        try:
            df = stock.get_market_ohlcv_by_date(ymd(start), base_date, code)
            if df is None or df.empty:
                continue
            last = df.dropna().iloc[-1]
            close = safe_float(last.get("종가", 0))
            volume = safe_float(last.get("거래량", 0))
            value = safe_float(last.get("거래대금", 0))
            if value <= 0 and close > 0 and volume > 0:
                value = close * volume
            if close > 0:
                return {"종가": close, "거래량": volume, "거래대금": value}
        except Exception:
            continue
    return None


def build_universe(base_date: str) -> Tuple[pd.DataFrame, str, List[str]]:
    """
    V302 NO-LOGIN UNIVERSE.
    - KRX_ID/KRX_PW를 요구하지 않는다.
    - 시장 전체 ticker list를 가져온 뒤 종목별 OHLCV로 가격/거래대금 유니버스를 만든다.
    - 시가총액은 0으로 두고 시총 필터는 비활성화한다.
    """
    errors: List[str] = []
    rows: List[Dict[str, Any]] = []
    names = market_name_map(base_date)

    for market in ["KOSPI", "KOSDAQ"]:
        try:
            tickers = [normalize_code(c) for c in stock.get_market_ticker_list(base_date, market=market)]
        except Exception as e:
            errors.append(f"{market} ticker list failed: {e}")
            tickers = []

        print(f"[INFO] {market} tickerCount={len(tickers)}")
        for idx, code in enumerate(tickers, start=1):
            name = names.get(code) or stock.get_market_ticker_name(code) or code
            if not name or is_excluded_name(name):
                continue
            snap = latest_ohlcv_snapshot(code, base_date)
            if not snap:
                continue
            rows.append({
                "code": code,
                "name": name,
                "market": market,
                "종가": safe_float(snap.get("종가", 0)),
                "거래량": safe_float(snap.get("거래량", 0)),
                "거래대금": safe_float(snap.get("거래대금", 0)),
                "시가총액": 0,
            })
            if idx % 200 == 0:
                print(f"[INFO] {market} snapshot {idx}/{len(tickers)} collectedRows={len(rows)}")
            time.sleep(0.003)

    if not rows:
        errors.append("V302 no-login universe empty: fallback_static_universe 사용")
        fallback_rows = []
        for idx, (code, name, market) in enumerate(FALLBACK_UNIVERSE, start=1):
            fallback_rows.append({
                "code": code, "name": name, "market": market,
                "종가": 0, "시가총액": 0, "거래량": 0,
                "거래대금": max(1, len(FALLBACK_UNIVERSE) - idx + 1) * 1_000_000_000,
            })
        return pd.DataFrame(fallback_rows), "fallback_static_universe", errors

    universe = pd.DataFrame(rows)
    before = len(universe)
    universe = universe[
        (universe["종가"].astype(float) >= MIN_PRICE) &
        (universe["거래대금"].astype(float) >= MIN_TRADING_VALUE)
    ].copy()
    universe = universe.sort_values("거래대금", ascending=False).head(UNIVERSE_TOP_N_BY_TRADING_VALUE)

    if universe.empty:
        errors.append(f"V302 universe empty after filter before={before}")
        fallback_rows = []
        for idx, (code, name, market) in enumerate(FALLBACK_UNIVERSE, start=1):
            fallback_rows.append({
                "code": code, "name": name, "market": market,
                "종가": 0, "시가총액": 0, "거래량": 0,
                "거래대금": max(1, len(FALLBACK_UNIVERSE) - idx + 1) * 1_000_000_000,
            })
        return pd.DataFrame(fallback_rows), "fallback_empty_after_filter", errors

    errors.append("V302: 시가총액 필터 비활성화, 종목별 OHLCV 기반 거래대금 유니버스 사용")
    print(f"[OK] V302 no-login universe filter {before} -> {len(universe)}")
    return universe.reset_index(drop=True), "krx_no_login_ohlcv_universe_v302", errors


def get_ohlcv(code: str, end_date: str) -> Optional[pd.DataFrame]:
    end = datetime.strptime(end_date, "%Y%m%d")
    for back in [LOOKBACK_DAYS, 240, 300]:
        start = end - timedelta(days=back)
        try:
            df = stock.get_market_ohlcv_by_date(ymd(start), end_date, code)
            if df is not None and not df.empty and len(df) >= 80:
                return df
        except Exception:
            pass
    return None


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


def calc_macd(close: pd.Series) -> Tuple[float, float]:
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
    return safe_float(close.iloc[-1]) > top > 0


def weekly_cloud_breakout(daily_df: pd.DataFrame) -> bool:
    try:
        df = daily_df.copy()
        df.index = pd.to_datetime(df.index)
        weekly = pd.DataFrame()
        weekly["시가"] = df["시가"].resample("W-FRI").first()
        weekly["고가"] = df["고가"].resample("W-FRI").max()
        weekly["저가"] = df["저가"].resample("W-FRI").min()
        weekly["종가"] = df["종가"].resample("W-FRI").last()
        return cloud_breakout(weekly.dropna())
    except Exception:
        return False


def grade_from_score(score: int) -> str:
    if score >= 90:
        return "S"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B"
    return "C"


def analyze_stock(row: pd.Series, base_date: str, rank_by_value: int, source: str) -> Optional[Dict[str, Any]]:
    code = normalize_code(row["code"])
    name = str(row["name"])
    market = str(row["market"])
    df = get_ohlcv(code, base_date)
    if df is None or df.empty or len(df) < 80:
        return None

    close = df["종가"].astype(float)
    current = safe_float(close.iloc[-1])
    prev = safe_float(close.iloc[-2], current)
    change_rate = ((current - prev) / prev * 100) if prev else 0.0
    ma5 = safe_float(close.rolling(5).mean().iloc[-1])
    ma20 = safe_float(close.rolling(20).mean().iloc[-1])
    ma60 = safe_float(close.rolling(60).mean().iloc[-1])
    ma120 = safe_float(close.rolling(120).mean().iloc[-1]) if len(close) >= 120 else 0.0
    high_52w = safe_float(close.tail(252).max(), current)
    low_52w = safe_float(close.tail(252).min(), current)
    high_52w_position = current / high_52w * 100 if high_52w else 0.0

    rsi = calc_rsi(close)
    macd, macd_signal = calc_macd(close)
    daily_cloud = cloud_breakout(df)
    weekly_cloud = weekly_cloud_breakout(df)
    trading_value = safe_int(row.get("거래대금", 0))
    market_cap = safe_int(row.get("시가총액", 0))
    volume_today = safe_int(df["거래량"].iloc[-1]) if "거래량" in df.columns else 0
    volume_avg20 = safe_float(df["거래량"].tail(20).mean(), 0)
    volume_ratio = volume_today / volume_avg20 if volume_avg20 else 0.0

    industry, tags, confidence = classify(name, market)

    technical = 40
    if current > ma5 > 0: technical += 3
    if current > ma20 > 0: technical += 7
    if current > ma60 > 0: technical += 8
    if ma20 > ma60 > 0: technical += 5
    if ma60 > ma120 > 0: technical += 4
    if daily_cloud: technical += 5
    if weekly_cloud: technical += 8
    if macd > macd_signal: technical += 5
    if 45 <= rsi <= 70: technical += 5
    elif 70 < rsi <= 78: technical += 1
    elif rsi > 78: technical -= 7
    if 85 <= high_52w_position <= 100: technical += 4
    if volume_ratio >= 1.5: technical += 3
    if change_rate > 7: technical -= 5
    technical = int(max(0, min(80, technical)))

    liquidity = 0
    if trading_value >= 100_000_000_000: liquidity += 10
    elif trading_value >= 50_000_000_000: liquidity += 8
    elif trading_value >= 20_000_000_000: liquidity += 5
    elif trading_value >= 10_000_000_000: liquidity += 3
    elif trading_value >= 3_000_000_000: liquidity += 1
    if market_cap >= 10_000_000_000_000: liquidity += 4
    elif market_cap >= 1_000_000_000_000: liquidity += 2
    liquidity = int(max(0, min(14, liquidity)))

    issue = 0
    if confidence == "high": issue += 2
    if weekly_cloud and daily_cloud: issue += 3
    if rank_by_value <= 100: issue += 3
    elif rank_by_value <= 300: issue += 2
    elif rank_by_value <= 600: issue += 1
    issue = int(max(0, min(6, issue)))

    score = int(max(0, min(100, technical + liquidity + issue)))
    grade = grade_from_score(score)
    entry = "20일선 지지 확인" if current > ma20 else "20일선 회복 확인"
    stop = "20일선 이탈" if current > ma20 else "전저점 이탈"
    target = "분할 익절"
    weekly_text = "주봉 구름대 돌파/상단" if weekly_cloud else "주봉 추세 확인"
    daily_text = "일봉 구름대 돌파" if daily_cloud else "일봉 이평선 확인"
    rsi_text = "RSI 안정권" if 45 <= rsi <= 70 else ("RSI 과열 주의" if rsi > 70 else "RSI 회복 확인")
    macd_text = "MACD 상승 우위" if macd > macd_signal else "MACD 확인 필요"
    volume_text = "거래량 증가" if volume_ratio >= 1.3 else "거래량 확인"

    reason_parts = [f"KRX 전체시장 자동선별 TOP {rank_by_value}", industry]
    if current > ma20: reason_parts.append("20일선 상회")
    if weekly_cloud: reason_parts.append("주봉 구름대 우위")
    if volume_ratio >= 1.3: reason_parts.append("거래량 증가")
    if 85 <= high_52w_position <= 100: reason_parts.append("52주 고점 근접")

    return {
        "rank": rank_by_value,
        "name": name,
        "code": code,
        "score": score,
        "grade": grade,
        "reason": " / ".join(reason_parts),
        "market": market,
        "sector": industry,
        "changeRate": f"{change_rate:.2f}%",
        "entryPrice": entry,
        "stopLoss": stop,
        "targetPrice": target,
        "strategy": "시장 전체 자동선별 후보 / 분할 접근",
        "weeklyCloud": weekly_text,
        "dailySignal": daily_text,
        "rsi": rsi_text,
        "macd": macd_text,
        "volumeSignal": volume_text,
        "reportSignal": "리포트 엔진 연결 예정",
        "newsSignal": "뉴스 엔진 연결 예정",
        "riskMemo": "시장 전체 자동선별: 이격도·거래량·뉴스 확인 필요",
        "foreign5D": "-", "foreign20D": "-", "foreign60D": "-",
        "pension5D": "-", "pension20D": "-", "pension60D": "-",
        "trust5D": "-", "trust20D": "-", "trust60D": "-",
        "finance5D": "-", "finance20D": "-", "finance60D": "-",
        "currentPrice": int(current),
        "tradingValue": trading_value,
        "marketCap": market_cap,
        "rsiValue": round(rsi, 2),
        "volumeRatio20D": round(volume_ratio, 2),
        "high52wPosition": round(high_52w_position, 2),
        "selectionSource": f"CV302_MARKET_SCANNER_{source}",
        "dataStatus": {
            "baseScore": score,
            "supplyBoost": 0,
            "supplySummary": "시장 전체 스캐너 기반 자동선별",
            "hasSupplyData": False,
            "hasReportHint": False,
        },
    }


def write_csv(rows: List[Dict[str, Any]]) -> None:
    fieldnames = [
        "rank", "name", "code", "score", "grade", "reason", "market", "sector", "changeRate",
        "entryPrice", "stopLoss", "targetPrice", "strategy", "weeklyCloud", "dailySignal", "rsi",
        "macd", "volumeSignal", "foreign5D", "foreign20D", "foreign60D", "pension5D", "pension20D",
        "pension60D", "trust5D", "trust20D", "trust60D", "finance5D", "finance20D", "finance60D",
        "reportSignal", "newsSignal", "riskMemo",
    ]
    with OUT_INPUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "-") for k in fieldnames})


def main() -> None:
    started = now_kst()
    base_date = recent_market_date()
    print(f"[START] CV302 market scanner base_date={base_date}")

    universe, source, errors = build_universe(base_date)
    universe_rows = []
    for idx, (_, r) in enumerate(universe.iterrows(), start=1):
        universe_rows.append({
            "rankByTradingValue": idx,
            "code": normalize_code(r.get("code", "")),
            "name": str(r.get("name", "")),
            "market": str(r.get("market", "")),
            "price": safe_int(r.get("종가", 0)),
            "marketCap": safe_int(r.get("시가총액", 0)),
            "tradingValue": safe_int(r.get("거래대금", 0)),
        })
    OUT_UNIVERSE_JSON.write_text(json.dumps({
        "version": "CV302_MARKET_UNIVERSE",
        "updatedAt": now_kst(),
        "baseDate": base_date,
        "source": source,
        "count": len(universe_rows),
        "items": universe_rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    scanned: List[Dict[str, Any]] = []
    scan_errors: List[str] = list(errors)
    for idx, (_, row) in enumerate(universe.iterrows(), start=1):
        try:
            item = analyze_stock(row, base_date, idx, source)
            if item:
                scanned.append(item)
                print(f"[OK] {idx}/{len(universe)} {item['code']} {item['name']} {item['grade']} {item['score']}")
            else:
                scan_errors.append(f"{normalize_code(row.get('code', ''))} {row.get('name', '')}: OHLCV 부족")
        except Exception as e:
            scan_errors.append(f"{normalize_code(row.get('code', ''))} {row.get('name', '')}: {e}")
            print(f"[ERR] {idx}/{len(universe)} {row.get('code','')} {row.get('name','')}: {e}")
        time.sleep(SLEEP_SECONDS)

    scanned.sort(key=lambda x: (x.get("score", 0), x.get("tradingValue", 0), x.get("high52wPosition", 0)), reverse=True)
    final_rows = scanned[:FINAL_INPUT_TOP_N]
    for i, item in enumerate(final_rows, start=1):
        item["rank"] = i

    write_csv(final_rows)

    OUT_SCAN_JSON.write_text(json.dumps({
        "version": "CV302_MARKET_SCAN_RESULTS",
        "updatedAt": now_kst(),
        "baseDate": base_date,
        "source": source,
        "universeCount": len(universe_rows),
        "scannedCount": len(scanned),
        "selectedInputCount": len(final_rows),
        "items": final_rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    grade_counts: Dict[str, int] = {}
    sector_counts: Dict[str, int] = {}
    for item in final_rows:
        grade_counts[item.get("grade", "-")] = grade_counts.get(item.get("grade", "-"), 0) + 1
        sector_counts[item.get("sector", "-")] = sector_counts.get(item.get("sector", "-"), 0) + 1

    OUT_SUMMARY_JSON.write_text(json.dumps({
        "version": "CV302_MARKET_SCANNER",
        "status": "warning" if scan_errors else "ok",
        "startedAt": started,
        "updatedAt": now_kst(),
        "baseDate": base_date,
        "source": source,
        "universeTargetTopNByTradingValue": UNIVERSE_TOP_N_BY_TRADING_VALUE,
        "universeCount": len(universe_rows),
        "scannedCount": len(scanned),
        "selectedInputCount": len(final_rows),
        "errorCount": len(scan_errors),
        "gradeCounts": grade_counts,
        "sectorCounts": sector_counts,
        "outputs": [
            "stock_candidates_input.csv",
            "market_universe.json",
            "market_scan_results.json",
            "market_scanner_summary.json",
            "market_scanner_errors.txt",
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    OUT_ERRORS_TXT.write_text("\n".join(scan_errors) if scan_errors else "No errors.", encoding="utf-8")
    print(f"[DONE] universe={len(universe_rows)} scanned={len(scanned)} selected_input={len(final_rows)} errors={len(scan_errors)}")


if __name__ == "__main__":
    main()
