#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CV306_EOD_MINIMAL_SCANNER
mode: EOD_CLOSE_BASED

목적:
- GitHub Actions에서 오래 걸리는 종목별 OHLCV/pykrx 전체 순회를 완전히 제거한다.
- 네이버 시가총액 페이지의 종가/거래량/등락률만 사용해 종가 기준 후보를 빠르게 만든다.
- 이 파일은 V306 전용 독립 스캐너다. 기존 scripts/generate_stock_candidates.py를 건드리지 않는다.
"""

from __future__ import annotations

import csv
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()

OUT_INPUT_CSV = ROOT / "stock_candidates_input.csv"
OUT_UNIVERSE_JSON = ROOT / "market_universe.json"
OUT_SCAN_JSON = ROOT / "market_scan_results.json"
OUT_SUMMARY_JSON = ROOT / "market_scanner_summary.json"
OUT_ERRORS_TXT = ROOT / "market_scanner_errors.txt"

VERSION = "CV306_EOD_MINIMAL_SCANNER"
MODE = "EOD_CLOSE_BASED"
SOURCE = "naver_market_sum_v306_eod_minimal"

MAX_PAGES_PER_MARKET = 8
UNIVERSE_TOP_N = 300
FINAL_TOP_N = 80
MIN_PRICE = 3000
MIN_EST_TRADING_VALUE = 1_000_000_000
REQUEST_TIMEOUT = 5
SLEEP_SECONDS = 0.08

EXCLUDE_KEYWORDS = ["스팩", "SPAC", "ETF", "ETN", "리츠", "인프라", "우선주"]

THEME_RULES = [
    ("반도체·AI", ["삼성전자", "SK하이닉스", "한미반도체", "이오테크닉스", "원익IPS", "리노공업", "ISC", "테크윙"]),
    ("방산·우주항공", ["한화시스템", "한화에어로스페이스", "한국항공우주", "LIG넥스원", "현대로템", "풍산"]),
    ("조선·해양", ["HD현대중공업", "HD한국조선해양", "삼성중공업", "한화오션", "현대미포", "한화엔진"]),
    ("원전·전력·에너지", ["두산에너빌리티", "한전기술", "한전KPS", "한국전력", "LS ELECTRIC", "효성중공업", "HD현대일렉트릭", "일진전기", "대한전선"]),
    ("2차전지·소재", ["LG에너지솔루션", "삼성SDI", "SK이노베이션", "엘앤에프", "에코프로비엠", "에코프로", "포스코퓨처엠", "POSCO홀딩스", "엔켐"]),
    ("자동차·모빌리티", ["현대차", "기아", "현대모비스", "HL만도", "한온시스템", "현대위아"]),
    ("금융·밸류업", ["KB금융", "신한지주", "하나금융지주", "우리금융지주", "기업은행", "미래에셋증권", "메리츠금융지주"]),
    ("바이오·제약", ["삼성바이오로직스", "셀트리온", "SK바이오팜", "한미약품", "유한양행", "알테오젠", "리가켐바이오", "HLB"]),
    ("인터넷·게임·콘텐츠", ["NAVER", "카카오", "크래프톤", "엔씨소프트", "넷마블", "하이브", "JYP Ent.", "에스엠"]),
    ("로봇·자동화", ["레인보우로보틱스", "고영", "로보스타", "뉴로메카", "로보티즈"]),
]


def now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def today_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def clean_text(value: Any) -> str:
    return str(value or "").replace("\xa0", " ").strip()


def to_int(value: Any, default: int = 0) -> int:
    s = re.sub(r"[^0-9\-]", "", clean_text(value))
    try:
        return int(s) if s not in ("", "-") else default
    except Exception:
        return default


def to_float_percent(value: Any, default: float = 0.0) -> float:
    s = clean_text(value).replace("%", "").replace(",", "")
    s = re.sub(r"[^0-9\.\-]", "", s)
    try:
        return float(s) if s not in ("", "-", ".") else default
    except Exception:
        return default


def normalize_code(code: str) -> str:
    return str(code).strip().zfill(6)[-6:]


def is_excluded_name(name: str) -> bool:
    up = name.upper()
    if any(k.upper() in up for k in EXCLUDE_KEYWORDS):
        return True
    if name.endswith("우") or name.endswith("우B"):
        return True
    return False


def classify(name: str, market: str) -> str:
    up = name.upper()
    for sector, names in THEME_RULES:
        if any(n.upper() in up for n in names):
            return sector
    return f"{market} 종가선별"


def fetch_market_page(sosok: int, page: int) -> List[Dict[str, Any]]:
    market = "KOSPI" if sosok == 0 else "KOSDAQ"
    url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}"
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/121 Safari/537.36",
        "Referer": "https://finance.naver.com/",
    }
    res = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "lxml")
    rows: List[Dict[str, Any]] = []

    for tr in soup.select("table.type_2 tr"):
        a = tr.select_one("a.tltle")
        if not a:
            continue
        href = a.get("href", "")
        m = re.search(r"code=(\d{6})", href)
        if not m:
            continue
        code = normalize_code(m.group(1))
        name = clean_text(a.get_text())
        tds = [clean_text(td.get_text(" ", strip=True)) for td in tr.select("td")]
        # Naver market_sum columns: no, name, price, diff, rate, par, market cap, shares, foreign, volume, PER, ROE
        price = to_int(tds[2] if len(tds) > 2 else 0)
        change_rate = to_float_percent(tds[4] if len(tds) > 4 else 0)
        market_cap_100m = to_int(tds[6] if len(tds) > 6 else 0)
        volume = to_int(tds[9] if len(tds) > 9 else 0)
        market_cap = market_cap_100m * 100_000_000
        est_trading_value = price * volume
        if not name or is_excluded_name(name):
            continue
        if price < MIN_PRICE or est_trading_value < MIN_EST_TRADING_VALUE:
            continue
        rows.append({
            "code": code,
            "name": name,
            "market": market,
            "price": price,
            "changeRateValue": change_rate,
            "marketCap": market_cap,
            "volume": volume,
            "tradingValue": est_trading_value,
        })
    return rows


def build_universe() -> tuple[List[Dict[str, Any]], List[str]]:
    errors: List[str] = []
    all_rows: List[Dict[str, Any]] = []
    seen = set()
    for sosok in (0, 1):
        market = "KOSPI" if sosok == 0 else "KOSDAQ"
        for page in range(1, MAX_PAGES_PER_MARKET + 1):
            try:
                rows = fetch_market_page(sosok, page)
                print(f"[OK] {market} page={page} rows={len(rows)}")
                for r in rows:
                    if r["code"] not in seen:
                        seen.add(r["code"])
                        all_rows.append(r)
            except Exception as e:
                msg = f"{market} page={page} failed: {e}"
                errors.append(msg)
                print(f"[WARN] {msg}")
            time.sleep(SLEEP_SECONDS)
    all_rows.sort(key=lambda x: (x.get("tradingValue", 0), x.get("marketCap", 0)), reverse=True)
    return all_rows[:UNIVERSE_TOP_N], errors


def score_item(row: Dict[str, Any], rank: int) -> Dict[str, Any]:
    price = int(row.get("price", 0))
    trading_value = int(row.get("tradingValue", 0))
    market_cap = int(row.get("marketCap", 0))
    chg = float(row.get("changeRateValue", 0.0))
    name = str(row.get("name", ""))
    market = str(row.get("market", ""))
    sector = classify(name, market)

    score = 50
    if rank <= 30:
        score += 18
    elif rank <= 80:
        score += 13
    elif rank <= 150:
        score += 8
    else:
        score += 4

    if trading_value >= 100_000_000_000:
        score += 12
    elif trading_value >= 50_000_000_000:
        score += 9
    elif trading_value >= 20_000_000_000:
        score += 6
    elif trading_value >= 5_000_000_000:
        score += 3

    if -1.5 <= chg <= 4.5:
        score += 8
    elif 4.5 < chg <= 8.0:
        score += 3
    elif chg > 8.0:
        score -= 8
    elif chg < -4.0:
        score -= 4

    if any(sector.startswith(s) for s in ["반도체", "방산", "조선", "원전", "금융", "로봇"]):
        score += 4

    score = max(0, min(100, int(score)))
    grade = "S" if score >= 90 else "A" if score >= 80 else "B" if score >= 70 else "C"
    action = "진입 후보" if score >= 82 and chg <= 5 else ("눌림목 대기" if score >= 72 else "관찰 후보")
    risk = "급등 추격 주의" if chg >= 7 else "종가 기준 변동성 확인"
    reason = f"종가 기준 거래대금 상위 {rank} / {sector} / 등락률 {chg:.2f}%"

    return {
        "rank": rank,
        "name": name,
        "code": row.get("code", ""),
        "score": score,
        "grade": grade,
        "reason": reason,
        "market": market,
        "sector": sector,
        "changeRate": f"{chg:.2f}%",
        "entryPrice": "내일 시가 추격 금지, 장중 눌림 또는 전일 종가 지지 확인",
        "stopLoss": "전일 종가/단기 지지선 이탈",
        "targetPrice": "분할 익절",
        "strategy": f"{action}: 오늘 종가 기준 내일 대응 후보",
        "weeklyCloud": "V306 minimal: 종가/거래대금 1차 선별",
        "dailySignal": "종가 기준 시장 강도 선별",
        "rsi": "후속 V307에서 차트지표 연결",
        "macd": "후속 V307에서 차트지표 연결",
        "volumeSignal": "거래대금 우선 선별",
        "foreign5D": "-", "foreign20D": "-", "foreign60D": "-",
        "pension5D": "-", "pension20D": "-", "pension60D": "-",
        "trust5D": "-", "trust20D": "-", "trust60D": "-",
        "finance5D": "-", "finance20D": "-", "finance60D": "-",
        "reportSignal": "기존 리포트 엔진 병합 예정",
        "newsSignal": "기존 뉴스 엔진 병합 예정",
        "riskMemo": risk,
        "currentPrice": price,
        "tradingValue": trading_value,
        "marketCap": market_cap,
        "selectionSource": VERSION,
        "dataStatus": {
            "baseScore": score,
            "supplyBoost": 0,
            "supplySummary": "V306 종가 기준 최소 스캐너",
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
    started_at = now_kst()
    t0 = time.time()
    print(f"[START] {VERSION} mode={MODE}")

    universe, errors = build_universe()
    universe_rows = []
    for i, r in enumerate(universe, 1):
        universe_rows.append({
            "rankByTradingValue": i,
            "code": r["code"],
            "name": r["name"],
            "market": r["market"],
            "price": r["price"],
            "marketCap": r["marketCap"],
            "tradingValue": r["tradingValue"],
        })

    selected = [score_item(r, i) for i, r in enumerate(universe[:FINAL_TOP_N], 1)]
    write_csv(selected)

    elapsed = round(time.time() - t0, 2)
    OUT_UNIVERSE_JSON.write_text(json.dumps({
        "version": "CV306_MARKET_UNIVERSE",
        "mode": MODE,
        "updatedAt": now_kst(),
        "strategyDate": today_kst(),
        "source": SOURCE,
        "count": len(universe_rows),
        "items": universe_rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    OUT_SCAN_JSON.write_text(json.dumps({
        "version": "CV306_MARKET_SCAN_RESULTS",
        "mode": MODE,
        "updatedAt": now_kst(),
        "strategyDate": today_kst(),
        "source": SOURCE,
        "universeCount": len(universe_rows),
        "deepScanCount": 0,
        "selectedInputCount": len(selected),
        "items": selected,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    grade_counts: Dict[str, int] = {}
    sector_counts: Dict[str, int] = {}
    for item in selected:
        grade_counts[item.get("grade", "-")] = grade_counts.get(item.get("grade", "-"), 0) + 1
        sector_counts[item.get("sector", "-")] = sector_counts.get(item.get("sector", "-"), 0) + 1

    OUT_SUMMARY_JSON.write_text(json.dumps({
        "version": VERSION,
        "mode": MODE,
        "status": "warning" if errors else "ok",
        "startedAt": started_at,
        "updatedAt": now_kst(),
        "strategyDate": today_kst(),
        "source": SOURCE,
        "maxPagesPerMarket": MAX_PAGES_PER_MARKET,
        "universeTargetTopN": UNIVERSE_TOP_N,
        "universeCount": len(universe_rows),
        "deepScanCount": 0,
        "selectedInputCount": len(selected),
        "errorCount": len(errors),
        "elapsedSeconds": elapsed,
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

    OUT_ERRORS_TXT.write_text("\n".join(errors) if errors else "No errors.", encoding="utf-8")
    print(f"[DONE] universe={len(universe_rows)} selected={len(selected)} elapsed={elapsed}s errors={len(errors)}")


if __name__ == "__main__":
    main()
