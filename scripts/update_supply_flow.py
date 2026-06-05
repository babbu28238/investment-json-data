#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V296 SUPPLY FLOW ENGINE REBUILD

목적:
- V282의 종목별 투자자 수급 조회가 GitHub Actions에서 empty를 반환하는 문제를 우회
- 종목별 조회 대신, pykrx의 '시장 전체 투자자별 순매수 테이블'을 기간/시장/투자자별로 수집한 뒤 후보 종목에 매핑
- 기존 V224 mapper가 그대로 읽을 수 있는 supply_flow_input.csv 생성

출력:
- supply_flow_input.csv
- supply_flow_summary.json
- supply_flow_log.txt
- supply_flow_debug.json

핵심 변경:
- 기존: get_market_trading_value_by_date(start, end, code, detail=True)  # 종목별, empty 발생
- 변경: get_market_trading_value_by_ticker(start, end, market=..., investor=...)  # 시장 전체, 코드 매핑
"""

from __future__ import annotations

import csv
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
from pykrx import stock

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()

CANDIDATE_CSV = ROOT / "stock_candidates_input.csv"
CANDIDATES_JSON = ROOT / "stock_candidates.json"
OUT_CSV = ROOT / "supply_flow_input.csv"
OUT_SUMMARY = ROOT / "supply_flow_summary.json"
OUT_LOG = ROOT / "supply_flow_log.txt"
OUT_DEBUG = ROOT / "supply_flow_debug.json"

PERIODS = [5, 20, 60]
INVESTORS = {
    "foreign": ["외국인", "외국인합계"],
    "pension": ["연기금", "연기금등"],
    "trust": ["투신", "투자신탁"],
    "finance": ["금융투자"],
}
MARKETS = ["KOSPI", "KOSDAQ"]
SLEEP_SECONDS = 0.05
MAX_CANDIDATES = 120


def now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def ymd(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def normalize_code(value: Any) -> str:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    return digits.zfill(6)[-6:] if digits else ""


def clean_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    s = str(value).strip()
    return s if s else default


def read_csv_rows(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    for enc in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
        except Exception:
            continue
    return []


def read_json_candidates(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ["candidates", "items", "data", "results", "stocks", "rows", "stockCandidates"]:
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def first(row: Dict[str, Any], keys: Iterable[str], default: str = "") -> str:
    for key in keys:
        if key in row and clean_text(row.get(key), ""):
            return clean_text(row.get(key), default)
    return default


def load_candidates() -> List[Dict[str, str]]:
    rows = read_csv_rows(CANDIDATE_CSV)
    source = "stock_candidates_input.csv"
    if not rows:
        rows = read_json_candidates(CANDIDATES_JSON)
        source = "stock_candidates.json"

    out: List[Dict[str, str]] = []
    seen = set()
    for row in rows:
        code = normalize_code(first(row, ["code", "stockCode", "stock_code", "종목코드", "단축코드", "ticker", "symbol"]))
        name = first(row, ["name", "stockName", "stock_name", "종목명", "displayName"], code)
        market = first(row, ["market", "시장"], "")
        if code and code not in seen:
            seen.add(code)
            out.append({"code": code, "name": name or code, "market": market, "source": source})
    return out[:MAX_CANDIDATES]


def recent_market_date(code: str = "005930", max_back_days: int = 20) -> str:
    today = datetime.now(KST).replace(tzinfo=None)
    for i in range(max_back_days + 1):
        date = ymd(today - timedelta(days=i))
        try:
            df = stock.get_market_ohlcv_by_date(date, date, code)
            if df is not None and not df.empty:
                return date
        except Exception:
            pass
    return ymd(today)


def trading_window(base_date: str, trading_days: int) -> Tuple[str, str]:
    end = datetime.strptime(base_date, "%Y%m%d")
    # 휴장일/주말 포함 여유분
    start = end - timedelta(days=max(10, int(trading_days * 2.3) + 7))
    return ymd(start), base_date


def detect_market_map(base_date: str) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for market in MARKETS:
        try:
            tickers = stock.get_market_ticker_list(base_date, market=market)
            for code in tickers:
                mapping[normalize_code(code)] = market
        except Exception:
            continue
    return mapping


def safe_number(value: Any) -> float:
    try:
        if value is None or pd.isna(value):
            return 0.0
        return float(str(value).replace(",", "").replace("+", ""))
    except Exception:
        return 0.0


def pick_net_column(df: pd.DataFrame) -> Optional[str]:
    if df is None or df.empty:
        return None
    columns = [str(c) for c in df.columns]
    priority = ["순매수", "순매수거래대금", "순매수금액", "순매수대금", "순매수거래량"]
    for p in priority:
        for c in columns:
            if p == c or p in c:
                return c
    # pykrx가 컬럼 하나만 주는 경우도 있어 백업
    numeric_cols = []
    for c in columns:
        try:
            pd.to_numeric(df[c].astype(str).str.replace(",", ""), errors="coerce")
            numeric_cols.append(c)
        except Exception:
            pass
    return numeric_cols[-1] if numeric_cols else None


def fetch_market_investor_table(start: str, end: str, market: str, investor_aliases: List[str]) -> Tuple[Optional[pd.DataFrame], str, str]:
    last_error = ""
    for investor in investor_aliases:
        attempts = [
            lambda investor=investor: stock.get_market_trading_value_by_ticker(start, end, market=market, investor=investor),
            lambda investor=investor: stock.get_market_trading_value_by_ticker(start, end, market, investor),
        ]
        for fn in attempts:
            try:
                df = fn()
                if df is not None and not df.empty:
                    df = df.copy()
                    df.index = [normalize_code(x) for x in df.index]
                    return df, "ok", investor
            except Exception as e:
                last_error = str(e)[:160]
    return None, last_error or "empty", ""


def build_supply_maps(base_date: str, logs: List[str]) -> Tuple[Dict[Tuple[str, str, int], Dict[str, float]], List[Dict[str, Any]]]:
    maps: Dict[Tuple[str, str, int], Dict[str, float]] = {}
    debug: List[Dict[str, Any]] = []

    for period in PERIODS:
        start, end = trading_window(base_date, period)
        for market in MARKETS:
            for actor, aliases in INVESTORS.items():
                df, status, used_investor = fetch_market_investor_table(start, end, market, aliases)
                net_col = pick_net_column(df) if df is not None else None
                values: Dict[str, float] = {}
                if df is not None and not df.empty and net_col:
                    for code, row in df.iterrows():
                        values[normalize_code(code)] = safe_number(row.get(net_col))
                    status_text = f"ok rows={len(values)} col={net_col} investor={used_investor}"
                else:
                    status_text = f"fail status={status} investor={used_investor or aliases[0]}"

                maps[(market, actor, period)] = values
                logs.append(f"[{market} {actor} {period}D] {status_text}")
                debug.append({
                    "market": market,
                    "actor": actor,
                    "period": period,
                    "start": start,
                    "end": end,
                    "status": status,
                    "usedInvestor": used_investor,
                    "netColumn": net_col,
                    "rowCount": len(values),
                    "columns": [str(c) for c in df.columns] if df is not None else [],
                })
                time.sleep(SLEEP_SECONDS)
    return maps, debug


def format_amount(value: float) -> str:
    # 원 단위 순매수 금액을 백만원 단위로 축약. 기존 mapper는 문자열 숫자를 처리함.
    million = int(round(value / 1_000_000))
    return str(million)


def build_row(candidate: Dict[str, str], market_map: Dict[str, str], supply_maps: Dict[Tuple[str, str, int], Dict[str, float]]) -> Tuple[Dict[str, str], Dict[str, Any]]:
    code = candidate["code"]
    name = candidate["name"]
    market = candidate.get("market") or market_map.get(code, "")
    if market not in MARKETS:
        market = market_map.get(code, "KOSPI")

    row: Dict[str, str] = {"code": code, "name": name}
    non_zero = 0
    actor20: Dict[str, float] = {}

    for actor in INVESTORS.keys():
        for period in PERIODS:
            value = supply_maps.get((market, actor, period), {}).get(code, 0.0)
            row[f"{actor}{period}D"] = format_amount(value)
            if abs(value) > 0:
                non_zero += 1
            if period == 20:
                actor20[actor] = value

    positive20 = sum(1 for v in actor20.values() if v > 0)
    total20 = sum(actor20.values())

    if non_zero == 0:
        memo = "수급 데이터 없음 또는 조회값 0"
        status = "zero"
    elif positive20 >= 3:
        memo = "외국인·기관 주요 주체 20일 수급 동반 개선"
        status = "ok"
    elif actor20.get("foreign", 0) > 0 and total20 > 0:
        memo = "외국인 및 기관 수급 우위"
        status = "ok"
    elif actor20.get("foreign", 0) < 0 and total20 < 0:
        memo = "외국인·기관 수급 동반 약화"
        status = "ok"
    else:
        memo = "수급 중립 또는 혼조"
        status = "ok"

    row["supplyMemo"] = memo
    detail = {"code": code, "name": name, "market": market, "status": status, "nonZeroFields": non_zero, "memo": memo}
    return row, detail


def main() -> None:
    started = now_kst()
    base_date = recent_market_date()
    candidates = load_candidates()
    logs: List[str] = []
    logs.append(f"V296 SUPPLY FLOW ENGINE REBUILD startedAt={started} baseDate={base_date}")
    logs.append(f"candidateCount={len(candidates)} maxCandidates={MAX_CANDIDATES}")

    market_map = detect_market_map(base_date)
    logs.append(f"marketMapCount={len(market_map)}")

    supply_maps, debug = build_supply_maps(base_date, logs)

    rows: List[Dict[str, str]] = []
    details: List[Dict[str, Any]] = []
    for candidate in candidates:
        row, detail = build_row(candidate, market_map, supply_maps)
        rows.append(row)
        details.append(detail)
        logs.append(f"{detail['code']} {detail['name']} {detail['market']} {detail['status']} nonZero={detail['nonZeroFields']} {detail['memo']}")

    fieldnames = [
        "code", "name",
        "foreign5D", "foreign20D", "foreign60D",
        "pension5D", "pension20D", "pension60D",
        "trust5D", "trust20D", "trust60D",
        "finance5D", "finance20D", "finance60D",
        "supplyMemo",
    ]
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    ok_count = sum(1 for d in details if d.get("status") == "ok")
    zero_count = sum(1 for d in details if d.get("status") == "zero")
    non_zero_rows = sum(1 for d in details if d.get("nonZeroFields", 0) > 0)

    summary = {
        "version": "V296_SUPPLY_FLOW_ENGINE_REBUILD",
        "updatedAt": now_kst(),
        "startedAt": started,
        "baseDate": base_date,
        "candidateCount": len(candidates),
        "outputRows": len(rows),
        "okCount": ok_count,
        "zeroCount": zero_count,
        "nonZeroRows": non_zero_rows,
        "output": OUT_CSV.name,
        "detailsTop20": details[:20],
        "debugTop20": debug[:20],
    }

    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_DEBUG.write_text(json.dumps({"debug": debug, "details": details}, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_LOG.write_text("\n".join(logs), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
