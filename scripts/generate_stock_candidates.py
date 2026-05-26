# -*- coding: utf-8 -*-
"""
V100.1 Stable Fallback Version

핵심 보완:
- GitHub Actions 환경에서 pykrx get_market_cap_by_ticker가 실패해도 중단하지 않음
- 1차: KRX 전체 시가총액/거래대금 유니버스 시도
- 실패 시: 내장 대형·고거래대금 유니버스로 fallback
- 각 종목 가격/OHLCV 기반 기술지표 계산
- 업종·테마 분류 유지
- 최종 stock_candidates.json 50개 생성

주의:
- fallback 유니버스는 전체 시장 완전 자동 선별은 아니지만,
  GitHub Actions 안정성을 확보하기 위한 실전 운영용 안전장치입니다.
- V101에서 FinanceDataReader 또는 별도 KRX 티커 CSV를 붙이면 전체시장 안정성이 더 좋아집니다.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from pykrx import stock

OUTPUT_JSON = "stock_candidates.json"
SUMMARY_JSON = "v100_1_generation_summary.json"
ERROR_LOG = "v100_1_collection_errors.txt"

LOOKBACK_DAYS = 180
SLEEP_SECONDS = 0.10

UNIVERSE_TOP_N_BY_TRADING_VALUE = 350
FINAL_TOP_N = 50

MIN_PRICE = 3000
MIN_TRADING_VALUE = 3_000_000_000
MIN_MARKET_CAP = 100_000_000_000

EXCLUDE_KEYWORDS = ["스팩", "SPAC", "ETN", "리츠", "인프라", "우선주", "ETF"]


FALLBACK_UNIVERSE = [
    ("005930", "삼성전자", "KOSPI"),
    ("000660", "SK하이닉스", "KOSPI"),
    ("373220", "LG에너지솔루션", "KOSPI"),
    ("207940", "삼성바이오로직스", "KOSPI"),
    ("005380", "현대차", "KOSPI"),
    ("000270", "기아", "KOSPI"),
    ("068270", "셀트리온", "KOSPI"),
    ("005490", "POSCO홀딩스", "KOSPI"),
    ("035420", "NAVER", "KOSPI"),
    ("105560", "KB금융", "KOSPI"),
    ("055550", "신한지주", "KOSPI"),
    ("012330", "현대모비스", "KOSPI"),
    ("028260", "삼성물산", "KOSPI"),
    ("051910", "LG화학", "KOSPI"),
    ("006400", "삼성SDI", "KOSPI"),
    ("035720", "카카오", "KOSPI"),
    ("032830", "삼성생명", "KOSPI"),
    ("086790", "하나금융지주", "KOSPI"),
    ("015760", "한국전력", "KOSPI"),
    ("009540", "HD한국조선해양", "KOSPI"),
    ("329180", "HD현대중공업", "KOSPI"),
    ("042660", "한화오션", "KOSPI"),
    ("010140", "삼성중공업", "KOSPI"),
    ("012450", "한화에어로스페이스", "KOSPI"),
    ("272210", "한화시스템", "KOSPI"),
    ("047810", "한국항공우주", "KOSPI"),
    ("079550", "LIG넥스원", "KOSPI"),
    ("064350", "현대로템", "KOSPI"),
    ("034020", "두산에너빌리티", "KOSPI"),
    ("267260", "HD현대일렉트릭", "KOSPI"),
    ("010120", "LS ELECTRIC", "KOSPI"),
    ("010130", "고려아연", "KOSPI"),
    ("003670", "포스코퓨처엠", "KOSPI"),
    ("066970", "엘앤에프", "KOSPI"),
    ("361610", "SK아이이테크놀로지", "KOSPI"),
    ("006260", "LS", "KOSPI"),
    ("096770", "SK이노베이션", "KOSPI"),
    ("352820", "하이브", "KOSPI"),
    ("259960", "크래프톤", "KOSPI"),
    ("251270", "넷마블", "KOSPI"),
    ("030200", "KT", "KOSPI"),
    ("017670", "SK텔레콤", "KOSPI"),
    ("036570", "엔씨소프트", "KOSPI"),
    ("090430", "아모레퍼시픽", "KOSPI"),
    ("051900", "LG생활건강", "KOSPI"),
    ("192820", "코스맥스", "KOSPI"),
    ("097950", "CJ제일제당", "KOSPI"),
    ("004170", "신세계", "KOSPI"),
    ("023530", "롯데쇼핑", "KOSPI"),
    ("011200", "HMM", "KOSPI"),
    ("003490", "대한항공", "KOSPI"),
    ("047050", "포스코인터내셔널", "KOSPI"),
    ("042700", "한미반도체", "KOSPI"),
    ("009150", "삼성전기", "KOSPI"),
    ("011070", "LG이노텍", "KOSPI"),
    ("011790", "SKC", "KOSPI"),
    ("010620", "현대미포조선", "KOSPI"),
    ("010060", "OCI홀딩스", "KOSPI"),
    ("241560", "두산밥캣", "KOSPI"),
    ("042670", "HD현대인프라코어", "KOSPI"),
    ("000720", "현대건설", "KOSPI"),
    ("047040", "대우건설", "KOSPI"),
    ("028050", "삼성엔지니어링", "KOSPI"),
    ("128940", "한미약품", "KOSPI"),
    ("326030", "SK바이오팜", "KOSPI"),
    ("128660", "피제이메탈", "KOSDAQ"),
    ("247540", "에코프로비엠", "KOSDAQ"),
    ("086520", "에코프로", "KOSDAQ"),
    ("196170", "알테오젠", "KOSDAQ"),
    ("277810", "레인보우로보틱스", "KOSDAQ"),
    ("039030", "이오테크닉스", "KOSDAQ"),
    ("140860", "파크시스템스", "KOSDAQ"),
    ("240810", "원익IPS", "KOSDAQ"),
    ("058470", "리노공업", "KOSDAQ"),
    ("095340", "ISC", "KOSDAQ"),
    ("222800", "심텍", "KOSDAQ"),
    ("067310", "하나마이크론", "KOSDAQ"),
    ("036930", "주성엔지니어링", "KOSDAQ"),
    ("348370", "엔켐", "KOSDAQ"),
    ("112040", "위메이드", "KOSDAQ"),
    ("263750", "펄어비스", "KOSDAQ"),
    ("293490", "카카오게임즈", "KOSDAQ"),
    ("145020", "휴젤", "KOSDAQ"),
    ("086900", "메디톡스", "KOSDAQ"),
    ("141080", "리가켐바이오", "KOSDAQ"),
    ("028300", "HLB", "KOSDAQ"),
    ("035900", "JYP Ent.", "KOSDAQ"),
    ("041510", "에스엠", "KOSDAQ"),
    ("122870", "와이지엔터테인먼트", "KOSDAQ"),
    ("214450", "파마리서치", "KOSDAQ"),
    ("237690", "에스티팜", "KOSDAQ"),
    ("145720", "덴티움", "KOSPI"),
    ("253450", "스튜디오드래곤", "KOSDAQ"),
    ("035760", "CJ ENM", "KOSDAQ"),
    ("257720", "실리콘투", "KOSDAQ"),
    ("018290", "브이티", "KOSDAQ"),
    ("161890", "한국콜마", "KOSPI"),
    ("000250", "삼천당제약", "KOSDAQ"),
    ("214150", "클래시스", "KOSDAQ"),
    ("214370", "케어젠", "KOSDAQ"),
    ("108320", "LX세미콘", "KOSPI"),
    ("089030", "테크윙", "KOSDAQ"),
    ("215200", "메가스터디교육", "KOSDAQ"),
    ("204320", "HL만도", "KOSPI"),
    ("018880", "한온시스템", "KOSPI"),
    ("005850", "에스엘", "KOSPI"),
    ("011210", "현대위아", "KOSPI"),
    ("000150", "두산", "KOSPI"),
    ("000880", "한화", "KOSPI"),
    ("003550", "LG", "KOSPI"),
    ("034730", "SK", "KOSPI"),
    ("316140", "우리금융지주", "KOSPI"),
]


THEME_RULES = [
    {"industry": "반도체·AI", "keywords": ["삼성전자", "SK하이닉스", "한미반도체", "이오테크닉스", "원익IPS", "심텍", "리노공업", "ISC", "하나마이크론", "주성엔지니어링", "파크시스템스", "LX세미콘", "테크윙"], "tags": ["반도체", "AI", "HBM", "장비", "후공정"]},
    {"industry": "방산·우주항공", "keywords": ["한화시스템", "한화에어로스페이스", "한국항공우주", "LIG넥스원", "현대로템", "풍산", "쎄트렉아이", "인텔리안테크", "AP위성", "퍼스텍"], "tags": ["방산", "우주항공", "수주", "수출", "국방"]},
    {"industry": "조선·해양", "keywords": ["HD현대중공업", "HD한국조선해양", "삼성중공업", "한화오션", "HD현대미포", "현대미포", "한화엔진"], "tags": ["조선", "LNG", "수주", "선박", "해양"]},
    {"industry": "원전·전력·에너지", "keywords": ["두산에너빌리티", "한전기술", "한전KPS", "한국전력", "LS ELECTRIC", "효성중공업", "HD현대일렉트릭", "일진전기", "대한전선", "지투파워"], "tags": ["원전", "전력기기", "전력망", "에너지", "인프라"]},
    {"industry": "2차전지·소재", "keywords": ["LG에너지솔루션", "삼성SDI", "SK이노베이션", "엘앤에프", "에코프로비엠", "에코프로", "포스코퓨처엠", "POSCO홀딩스", "롯데에너지머티리얼즈", "솔루스첨단소재", "천보", "SK아이이테크놀로지", "엔켐"], "tags": ["2차전지", "양극재", "전지박", "ESS", "소재"]},
    {"industry": "자동차·모빌리티", "keywords": ["현대차", "기아", "현대모비스", "현대글로비스", "HL만도", "한온시스템", "에스엘", "현대위아"], "tags": ["자동차", "모빌리티", "전장", "주주환원", "밸류업"]},
    {"industry": "금융·밸류업", "keywords": ["KB금융", "신한지주", "하나금융지주", "우리금융지주", "기업은행", "삼성생명", "삼성화재", "현대해상", "미래에셋증권", "한국금융지주", "키움증권", "메리츠금융지주"], "tags": ["금융", "밸류업", "배당", "자사주", "금리"]},
    {"industry": "바이오·제약", "keywords": ["삼성바이오로직스", "셀트리온", "SK바이오팜", "한미약품", "유한양행", "종근당", "대웅제약", "녹십자", "알테오젠", "리가켐바이오", "HLB", "파마리서치", "휴젤", "메디톡스", "삼천당제약", "클래시스", "케어젠", "에스티팜"], "tags": ["바이오", "제약", "신약", "CDMO", "바이오시밀러"]},
    {"industry": "화장품·소비재", "keywords": ["LG생활건강", "아모레퍼시픽", "코스맥스", "한국콜마", "클리오", "브이티", "실리콘투", "CJ제일제당", "오리온", "농심", "삼양식품", "롯데웰푸드"], "tags": ["화장품", "소비재", "K뷰티", "음식료", "중국소비"]},
    {"industry": "인터넷·게임·콘텐츠", "keywords": ["NAVER", "카카오", "크래프톤", "엔씨소프트", "넷마블", "펄어비스", "카카오게임즈", "위메이드", "하이브", "JYP Ent.", "에스엠", "와이지엔터테인먼트", "스튜디오드래곤", "CJ ENM"], "tags": ["인터넷", "AI", "게임", "콘텐츠", "플랫폼"]},
    {"industry": "건설·기계·인프라", "keywords": ["현대건설", "대우건설", "삼성엔지니어링", "GS건설", "DL이앤씨", "두산밥캣", "HD현대건설기계", "HD현대인프라코어"], "tags": ["건설", "기계", "인프라", "해외수주", "재건"]},
    {"industry": "철강·화학·소재", "keywords": ["POSCO홀딩스", "현대제철", "고려아연", "풍산", "LG화학", "롯데케미칼", "금호석유", "한화솔루션", "효성첨단소재", "SKC", "OCI홀딩스"], "tags": ["철강", "화학", "소재", "스프레드", "업황회복"]},
    {"industry": "유통·운송·관광", "keywords": ["신세계", "롯데쇼핑", "이마트", "현대백화점", "호텔신라", "하나투어", "대한항공", "제주항공", "HMM", "CJ대한통운", "팬오션"], "tags": ["유통", "면세", "항공", "해운", "관광"]},
    {"industry": "로봇·자동화", "keywords": ["레인보우로보틱스", "고영", "로보스타", "유일로보틱스", "뉴로메카"], "tags": ["로봇", "자동화", "피지컬AI", "스마트팩토리"]},
]


def classify_industry_and_tags(name: str, code: str, market: str):
    n = str(name)
    for rule in THEME_RULES:
        for keyword in rule["keywords"]:
            if keyword.upper() in n.upper():
                return rule["industry"], rule["tags"], "high"
    return f"{market} 자동선별", ["자동선별", "거래대금"], "low"


def ymd(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def safe_float(value, default=0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def safe_int(value, default=0) -> int:
    try:
        if value is None or pd.isna(value):
            return default
        return int(float(value))
    except Exception:
        return default


def normalize_code(code: str) -> str:
    return str(code).strip().zfill(6)


def recent_market_date(code="005930", max_back_days=20) -> str:
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
    # 날짜 조회가 완전히 실패하면 오늘을 기준으로 두되 개별 종목에서 다시 실패 처리
    return ymd(today)


def is_excluded_name(name: str) -> bool:
    upper_name = str(name).upper()
    for keyword in EXCLUDE_KEYWORDS:
        if keyword.upper() in upper_name:
            return True
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


def build_fallback_universe() -> pd.DataFrame:
    rows = []
    for idx, (code, name, market) in enumerate(FALLBACK_UNIVERSE, start=1):
        rows.append({
            "code": normalize_code(code),
            "name": name,
            "market": market,
            "종가": 0,
            "시가총액": 0,
            "거래대금": max(1, (len(FALLBACK_UNIVERSE) - idx + 1)) * 1_000_000_000,
            "fallbackRank": idx,
        })
    df = pd.DataFrame(rows)
    print(f"fallback 유니버스 사용: {len(df)}개")
    return df


def build_liquid_universe(base_date: str) -> tuple[pd.DataFrame, str]:
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
        return build_fallback_universe(), "fallback_static_universe"

    try:
        universe = pd.concat(frames, ignore_index=True)
        name_map = get_market_name_map(base_date)
        universe["name"] = universe["code"].map(name_map).fillna(universe["code"])

        for col in ["종가", "시가총액", "거래대금"]:
            if col not in universe.columns:
                print(f"[경고] 필수 컬럼 누락: {col}. fallback으로 전환합니다.")
                return build_fallback_universe(), "fallback_missing_columns"

        universe = universe[
            (universe["종가"] >= MIN_PRICE) &
            (universe["거래대금"] >= MIN_TRADING_VALUE) &
            (universe["시가총액"] >= MIN_MARKET_CAP)
        ].copy()

        universe = universe[~universe["name"].apply(is_excluded_name)].copy()
        universe = universe.sort_values("거래대금", ascending=False).head(UNIVERSE_TOP_N_BY_TRADING_VALUE)

        if universe.empty:
            print("[경고] 필터 후 유니버스 0개. fallback으로 전환합니다.")
            return build_fallback_universe(), "fallback_empty_after_filter"

        print(f"KRX 전체 유동성 후보군: {len(universe)}개")
        return universe.reset_index(drop=True), "krx_market_cap_universe"

    except Exception as e:
        print(f"[경고] 유니버스 처리 실패: {e}. fallback으로 전환합니다.")
        return build_fallback_universe(), "fallback_processing_error"


def calc_rsi(close: pd.Series, period=14) -> float:
    close = pd.Series(close).astype(float)
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return safe_float(rsi.iloc[-1], 50.0)


def calc_macd(close: pd.Series):
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


def make_recent_issue(industry, tags, weekly_breakout, daily_breakout, rsi_value, price_change_rate, trading_value, rank, universe_source):
    parts = [f"자동선별 TOP {rank}", industry]
    if universe_source.startswith("fallback"):
        parts.append("fallback 유니버스")
    else:
        parts.append("KRX 전체 유니버스")
    if tags:
        parts.append("·".join(tags[:3]))
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


def get_ohlcv_with_retry(code: str, end_date: str):
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


def calculate_candidate(row: pd.Series, base_date: str, rank_by_value: int, universe_source: str):
    code = normalize_code(row["code"])
    name = str(row["name"])
    market = str(row["market"])

    ohlcv = get_ohlcv_with_retry(code, base_date)
    if ohlcv is None or ohlcv.empty or len(ohlcv) < 80:
        raise RuntimeError("OHLCV 데이터 부족 또는 조회 실패")

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

    # fallback에서는 당일 거래대금/시총이 없으므로 최근 종가 데이터의 거래량으로 보정
    if trading_value <= 1_000_000_000:
        last_volume = safe_int(ohlcv["거래량"].iloc[-1]) if "거래량" in ohlcv.columns else 0
        trading_value = last_volume * current_price

    industry, tags, confidence = classify_industry_and_tags(name, code, market)

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
    if confidence == "high":
        issue += 2
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

    issue = int(max(0, min(10, issue)))
    score = int(max(0, min(100, technical + liquidity + issue)))

    recent_issue = make_recent_issue(
        industry=industry,
        tags=tags,
        weekly_breakout=weekly_breakout,
        daily_breakout=daily_breakout,
        rsi_value=rsi_value,
        price_change_rate=price_change_rate,
        trading_value=trading_value,
        rank=rank_by_value,
        universe_source=universe_source,
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
        "selectionSource": f"KRX_UNIVERSE_AUTO_TOP50_V100_1_{universe_source}",
        "selectionTags": tags,
        "industryConfidence": confidence,
    }


def generate_stock_candidates():
    base_date = recent_market_date()
    print("분석 기준 거래일:", base_date)

    universe, universe_source = build_liquid_universe(base_date)
    print("유니버스 소스:", universe_source)

    candidates = []
    errors = []

    for idx, (_, row) in enumerate(universe.iterrows(), start=1):
        try:
            item = calculate_candidate(row, base_date, idx, universe_source)
            if item:
                candidates.append(item)
                print(f"[성공] {idx}/{len(universe)} {item['code']} {item['name']} {item['industry']} {item['grade']} {item['score']}")
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
            x.get("tradingValue", 0),
        ),
        reverse=True,
    )

    final_candidates = candidates[:FINAL_TOP_N]

    if len(final_candidates) == 0:
        raise RuntimeError("최종 후보 0개: OHLCV 조회가 전부 실패했습니다.")

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(final_candidates, f, ensure_ascii=False, indent=2)

    with open(ERROR_LOG, "w", encoding="utf-8") as f:
        f.write("\n".join(errors))

    industry_counts = {}
    for item in final_candidates:
        industry_counts[item["industry"]] = industry_counts.get(item["industry"], 0) + 1

    summary = {
        "version": "V100_1_STABLE_FALLBACK",
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "baseDate": base_date,
        "universeSource": universe_source,
        "universeInputCount": len(universe),
        "candidateCalculatedCount": len(candidates),
        "finalCandidateCount": len(final_candidates),
        "errorCount": len(errors),
        "industryCounts": industry_counts,
        "filters": {
            "minPrice": MIN_PRICE,
            "minTradingValue": MIN_TRADING_VALUE,
            "minMarketCap": MIN_MARKET_CAP
        }
    }

    with open(SUMMARY_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("=" * 70)
    print("V100.1 안정화 fallback 자동선별 완료")
    print("분석 기준 거래일:", base_date)
    print("유니버스 소스:", universe_source)
    print("계산 후보 수:", len(candidates))
    print("최종 저장 후보 수:", len(final_candidates))
    print("오류 수:", len(errors))
    print("업종 분포:", industry_counts)
    print("상위 10개:")
    for item in final_candidates[:10]:
        print(item["code"], item["name"], item["industry"], item["grade"], item["score"])

    return final_candidates


if __name__ == "__main__":
    generate_stock_candidates()
