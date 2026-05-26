# -*- coding: utf-8 -*-
"""
V100 KRX Universe Top50 + Industry/Theme Mapping

V99 개선점:
- KOSPI/KOSDAQ 전체 자동 TOP 50 선별 유지
- 종목명 기반 업종·테마 분류 강화
- recentIssue에 자동선별 근거 + 업종/테마 설명 추가
- selectionTags 필드 추가
- industryConfidence 필드 추가

주의:
- 수급 조회는 안정성 문제로 계속 비활성화
- 업종 분류는 종목명/대표 키워드 기반 1차 매핑입니다.
- V101에서 KRX 업종 코드 또는 외부 업종 DB 연동으로 고도화 예정
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from pykrx import stock

OUTPUT_JSON = "stock_candidates.json"
SUMMARY_JSON = "v100_generation_summary.json"
ERROR_LOG = "v100_collection_errors.txt"

LOOKBACK_DAYS = 180
SLEEP_SECONDS = 0.10

UNIVERSE_TOP_N_BY_TRADING_VALUE = 350
FINAL_TOP_N = 50

MIN_PRICE = 3000
MIN_TRADING_VALUE = 3_000_000_000
MIN_MARKET_CAP = 100_000_000_000

EXCLUDE_KEYWORDS = [
    "스팩", "SPAC", "ETN", "리츠", "인프라", "우선주", "ETF"
]


# MARK: - 업종·테마 매핑

THEME_RULES = [
    {
        "industry": "반도체·AI",
        "keywords": [
            "삼성전자", "SK하이닉스", "한미반도체", "이오테크닉스", "원익IPS", "원익QnC",
            "심텍", "리노공업", "ISC", "하나마이크론", "테스", "주성엔지니어링", "에스앤에스텍",
            "동진쎄미켐", "솔브레인", "DB하이텍", "LX세미콘", "파크시스템스", "유진테크",
            "티씨케이", "피에스케이", "넥스틴", "제우스", "고영", "HPSP", "가온칩스",
            "네패스", "덕산하이메탈", "코미코", "하나머티리얼즈", "케이씨텍"
        ],
        "tags": ["반도체", "AI", "HBM", "장비", "후공정"]
    },
    {
        "industry": "방산·우주항공",
        "keywords": [
            "한화시스템", "한화에어로스페이스", "한국항공우주", "LIG넥스원", "현대로템",
            "풍산", "쎄트렉아이", "인텔리안테크", "AP위성", "켄코아에어로스페이스",
            "제노코", "퍼스텍", "빅텍", "휴니드", "아이쓰리시스템"
        ],
        "tags": ["방산", "우주항공", "수주", "수출", "국방"]
    },
    {
        "industry": "조선·해양",
        "keywords": [
            "HD현대중공업", "HD한국조선해양", "삼성중공업", "한화오션", "HD현대미포",
            "현대미포조선", "세진중공업", "태광", "성광벤드", "동성화인텍", "한국카본",
            "STX엔진", "STX중공업", "HSD엔진", "한화엔진"
        ],
        "tags": ["조선", "LNG", "수주", "선박", "해양"]
    },
    {
        "industry": "원전·전력·에너지",
        "keywords": [
            "두산에너빌리티", "한전기술", "한전KPS", "한국전력", "LS ELECTRIC", "LS전선아시아",
            "효성중공업", "제룡전기", "HD현대일렉트릭", "일진전기", "대한전선", "지투파워",
            "우진", "비에이치아이", "우리기술", "서전기전", "보성파워텍"
        ],
        "tags": ["원전", "전력기기", "전력망", "에너지", "인프라"]
    },
    {
        "industry": "2차전지·소재",
        "keywords": [
            "LG에너지솔루션", "삼성SDI", "SK이노베이션", "엘앤에프", "에코프로비엠", "에코프로",
            "포스코퓨처엠", "POSCO홀딩스", "롯데에너지머티리얼즈", "솔루스첨단소재", "천보",
            "더블유씨피", "SK아이이테크놀로지", "대주전자재료", "나노신소재", "윤성에프앤씨",
            "피엔티", "씨아이에스", "엔켐", "코스모신소재", "후성", "일진머티리얼즈"
        ],
        "tags": ["2차전지", "양극재", "전지박", "ESS", "소재"]
    },
    {
        "industry": "자동차·모빌리티",
        "keywords": [
            "현대차", "기아", "현대모비스", "현대글로비스", "HL만도", "한온시스템",
            "성우하이텍", "화신", "에스엘", "서연이화", "현대위아", "모트렉스",
            "SNT모티브", "명신산업", "평화정공", "코리아에프티"
        ],
        "tags": ["자동차", "모빌리티", "전장", "주주환원", "밸류업"]
    },
    {
        "industry": "금융·밸류업",
        "keywords": [
            "KB금융", "신한지주", "하나금융지주", "우리금융지주", "기업은행", "BNK금융지주",
            "DGB금융지주", "JB금융지주", "삼성생명", "삼성화재", "현대해상", "DB손해보험",
            "미래에셋증권", "한국금융지주", "키움증권", "NH투자증권", "메리츠금융지주"
        ],
        "tags": ["금융", "밸류업", "배당", "자사주", "금리"]
    },
    {
        "industry": "바이오·제약",
        "keywords": [
            "삼성바이오로직스", "셀트리온", "SK바이오팜", "한미약품", "유한양행", "종근당",
            "대웅제약", "녹십자", "알테오젠", "리가켐바이오", "HLB", "에이비엘바이오",
            "오스코텍", "보로노이", "파마리서치", "휴젤", "메디톡스", "바이넥스",
            "에스티팜", "동아에스티"
        ],
        "tags": ["바이오", "제약", "신약", "CDMO", "바이오시밀러"]
    },
    {
        "industry": "화장품·소비재",
        "keywords": [
            "LG생활건강", "아모레퍼시픽", "코스맥스", "한국콜마", "클리오", "브이티",
            "실리콘투", "아이패밀리에스씨", "마녀공장", "토니모리", "애경산업", "콜마비앤에이치",
            "CJ제일제당", "오리온", "농심", "삼양식품", "롯데웰푸드", "하이트진로"
        ],
        "tags": ["화장품", "소비재", "K뷰티", "음식료", "중국소비"]
    },
    {
        "industry": "인터넷·게임·콘텐츠",
        "keywords": [
            "NAVER", "카카오", "크래프톤", "엔씨소프트", "넷마블", "펄어비스", "카카오게임즈",
            "위메이드", "컴투스", "디어유", "하이브", "JYP Ent.", "에스엠", "와이지엔터테인먼트",
            "스튜디오드래곤", "CJ ENM", "콘텐트리중앙"
        ],
        "tags": ["인터넷", "AI", "게임", "콘텐츠", "플랫폼"]
    },
    {
        "industry": "건설·기계·인프라",
        "keywords": [
            "현대건설", "대우건설", "삼성엔지니어링", "GS건설", "DL이앤씨", "HDC현대산업개발",
            "두산밥캣", "HD현대건설기계", "HD현대인프라코어", "진성티이씨", "대창단조"
        ],
        "tags": ["건설", "기계", "인프라", "해외수주", "재건"]
    },
    {
        "industry": "철강·화학·소재",
        "keywords": [
            "POSCO홀딩스", "현대제철", "세아베스틸지주", "동국제강", "고려아연", "풍산",
            "LG화학", "롯데케미칼", "금호석유", "한화솔루션", "효성첨단소재", "코오롱인더",
            "SKC", "롯데정밀화학", "대한유화", "애경케미칼", "PI첨단소재"
        ],
        "tags": ["철강", "화학", "소재", "스프레드", "업황회복"]
    },
    {
        "industry": "유통·운송·관광",
        "keywords": [
            "신세계", "롯데쇼핑", "이마트", "현대백화점", "호텔신라", "하나투어", "모두투어",
            "대한항공", "아시아나항공", "제주항공", "진에어", "HMM", "CJ대한통운", "팬오션"
        ],
        "tags": ["유통", "면세", "항공", "해운", "관광"]
    }
]


def classify_industry_and_tags(name: str, code: str, market: str) -> tuple[str, list[str], str]:
    n = str(name)

    for rule in THEME_RULES:
        for keyword in rule["keywords"]:
            if keyword.upper() in n.upper():
                return rule["industry"], rule["tags"], "high"

    # 부분 키워드 fallback
    fallback_rules = [
        ("반도체·AI", ["반도체", "AI"], ["반도체", "테크"], "medium"),
        ("바이오·제약", ["바이오", "제약", "약품", "팜"], ["바이오", "제약"], "medium"),
        ("금융·밸류업", ["금융", "은행", "증권", "보험"], ["금융", "밸류업"], "medium"),
        ("조선·해양", ["조선", "중공업", "오션"], ["조선", "수주"], "medium"),
        ("화장품·소비재", ["화장품", "푸드", "식품", "제당"], ["소비재", "음식료"], "medium"),
        ("자동차·모빌리티", ["모비스", "모터", "오토", "차"], ["자동차", "모빌리티"], "medium"),
        ("철강·화학·소재", ["화학", "소재", "철강", "제철"], ["소재", "업황"], "medium"),
        ("원전·전력·에너지", ["전력", "전기", "에너지"], ["전력", "에너지"], "medium"),
    ]

    for industry, keys, tags, confidence in fallback_rules:
        if any(k.upper() in n.upper() for k in keys):
            return industry, tags, confidence

    return f"{market} 자동선별", ["자동선별", "거래대금"], "low"


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

    for col in ["종가", "시가총액", "거래대금"]:
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


def make_recent_issue(
    industry: str,
    tags: list[str],
    weekly_breakout: bool,
    daily_breakout: bool,
    rsi_value: float,
    price_change_rate: float,
    trading_value: int,
    rank: int,
) -> str:
    parts = [f"KRX 전체 자동선별 TOP {rank}", industry]
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
        "selectionSource": "KRX_UNIVERSE_AUTO_TOP50_V100",
        "selectionTags": tags,
        "industryConfidence": confidence,
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
                    f"{item['industry']} {item['grade']} {item['score']}"
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

    industry_counts = {}
    for item in final_candidates:
        industry_counts[item["industry"]] = industry_counts.get(item["industry"], 0) + 1

    summary = {
        "version": "V100_KRX_UNIVERSE_AUTO_TOP50_INDUSTRY_THEME",
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "baseDate": base_date,
        "universeTopNByTradingValue": UNIVERSE_TOP_N_BY_TRADING_VALUE,
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
    print("V100 전체 시장 자동선별 + 업종·테마 분류 완료")
    print("분석 기준 거래일:", base_date)
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
