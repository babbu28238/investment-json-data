#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V282 SUPPLY FLOW ENGINE

목적:
- stock_candidates_input.csv 또는 stock_candidates.json의 후보 종목을 기준으로
  외국인/연기금/투신/금융투자 5D/20D/60D 수급 데이터를 자동 생성
- 기존 V224 mapper가 그대로 읽을 수 있는 supply_flow_input.csv 생성
- 일부 종목/일자 수집 실패 시에도 전체 액션 실패를 막고 진단 파일 생성

출력:
- supply_flow_input.csv
- supply_flow_summary.json
- supply_flow_log.txt

주의:
- pykrx의 투자자별 수급 컬럼명은 시점/시장/버전에 따라 달라질 수 있어
  컬럼명을 유연하게 탐색한다.
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

PERIODS = [5, 20, 60]
SLEEP_SECONDS = 0.08
MAX_CANDIDATES = 80  # 최종 후보/후보풀 전체가 너무 커도 수급 조회는 상위 80개까지만 우선 반영


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
        for key in ["candidates", "items", "data", "results", "stocks", "rows"]:
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
        if code and code not in seen:
            seen.add(code)
            out.append({"code": code, "name": name or code, "source": source})
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


def trading_days_until(base_date: str, count: int) -> Tuple[str, str]:
    end = datetime.strptime(base_date, "%Y%m%d")
    # 달력일 여유를 넉넉히 둔다. 휴장/주말 포함.
    start = end - timedelta(days=max(20, int(count * 2.2) + 10))
    return ymd(start), base_date


def normalize_col(name: Any) -> str:
    s = str(name or "").lower()
    s = re.sub(r"[\s_\-./()\[\]{}]+", "", s)
    aliases = {
        "외국인합계": "foreign",
        "외국인": "foreign",
        "foreign": "foreign",
        "foreigner": "foreign",
        "연기금등": "pension",
        "연기금": "pension",
        "pension": "pension",
        "투신": "trust",
        "투자신탁": "trust",
        "trust": "trust",
        "금융투자": "finance",
        "금투": "finance",
        "finance": "finance",
    }
    for k, v in aliases.items():
        if k in s:
            return v
    return s


def safe_number(value: Any) -> float:
    try:
        if value is None or pd.isna(value):
            return 0.0
        return float(str(value).replace(",", ""))
    except Exception:
        return 0.0


def sum_actor(df: pd.DataFrame, actor: str, last_n: int) -> float:
    if df is None or df.empty:
        return 0.0

    col_map = {normalize_col(c): c for c in df.columns}
    col = col_map.get(actor)
    if col is None:
        # 부분 매칭 백업
        for norm, raw in col_map.items():
            if actor in norm:
                col = raw
                break
    if col is None:
        return 0.0

    series = df[col].tail(last_n).apply(safe_number)
    return float(series.sum())


def fetch_trading_value_by_investor(code: str, base_date: str) -> Tuple[Optional[pd.DataFrame], str]:
    start, end = trading_days_until(base_date, 60)

    attempts = []
    # pykrx 버전별 시그니처 차이를 고려한다.
    attempts.append(lambda: stock.get_market_trading_value_by_date(start, end, code, detail=True))
    attempts.append(lambda: stock.get_market_trading_value_by_date(start, end, code))

    last_error = ""
    for fn in attempts:
        try:
            df = fn()
            if df is not None and not df.empty:
                return df, "ok"
        except Exception as e:
            last_error = str(e)[:160]
    return None, last_error or "empty"


def format_amount(value: float) -> str:
    # 기존 mapper는 문자열/숫자 모두 처리 가능. 백만원 단위로 축약하면 가독성이 좋다.
    million = int(round(value / 1_000_000))
    return str(million)


def build_supply_row(candidate: Dict[str, str], base_date: str) -> Tuple[Dict[str, str], Dict[str, Any]]:
    code = candidate["code"]
    name = candidate["name"]
    df, status = fetch_trading_value_by_investor(code, base_date)

    row: Dict[str, str] = {"code": code, "name": name}
    detail: Dict[str, Any] = {"code": code, "name": name, "status": status}

    actors = {
        "foreign": "foreign",
        "pension": "pension",
        "trust": "trust",
        "finance": "finance",
    }

    if df is None or df.empty:
        for actor in actors:
            for p in PERIODS:
                row[f"{actor}{p}D"] = "-"
        row["supplyMemo"] = f"수급 조회 실패: {status}"
        detail["message"] = status
        return row, detail

    for actor in actors:
        for p in PERIODS:
            value = sum_actor(df, actor, p)
            row[f"{actor}{p}D"] = format_amount(value)

    foreign20 = float(row.get("foreign20D", "0").replace(",", "")) if row.get("foreign20D", "-") != "-" else 0
    pension20 = float(row.get("pension20D", "0").replace(",", "")) if row.get("pension20D", "-") != "-" else 0
    trust20 = float(row.get("trust20D", "0").replace(",", "")) if row.get("trust20D", "-") != "-" else 0
    finance20 = float(row.get("finance20D", "0").replace(",", "")) if row.get("finance20D", "-") != "-" else 0
    positive_count = sum(1 for x in [foreign20, pension20, trust20, finance20] if x > 0)

    if positive_count >= 3:
        memo = "외국인·기관 주요 주체 20일 수급 동반 개선"
    elif foreign20 > 0 and (pension20 + trust20 + finance20) > 0:
        memo = "외국인 및 기관 수급 우위"
    elif foreign20 < 0 and (pension20 + trust20 + finance20) < 0:
        memo = "외국인·기관 수급 동반 약화"
    else:
        memo = "수급 중립 또는 혼조"

    row["supplyMemo"] = memo
    detail["rows"] = len(df)
    detail["columns"] = [str(c) for c in df.columns]
    detail["memo"] = memo
    return row, detail


def main() -> None:
    started = now_kst()
    base_date = recent_market_date()
    candidates = load_candidates()

    logs: List[str] = []
    details: List[Dict[str, Any]] = []
    rows: List[Dict[str, str]] = []

    logs.append(f"V282 SUPPLY FLOW ENGINE startedAt={started} baseDate={base_date}")
    logs.append(f"candidateCount={len(candidates)} maxCandidates={MAX_CANDIDATES}")

    for idx, candidate in enumerate(candidates, start=1):
        row, detail = build_supply_row(candidate, base_date)
        rows.append(row)
        details.append(detail)
        logs.append(f"[{idx}/{len(candidates)}] {candidate['code']} {candidate['name']} {detail.get('status')} {row.get('supplyMemo')}")
        time.sleep(SLEEP_SECONDS)

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
        for row in rows:
            writer.writerow(row)

    ok_count = sum(1 for d in details if d.get("status") == "ok")
    summary = {
        "version": "V282_SUPPLY_FLOW_ENGINE",
        "updatedAt": now_kst(),
        "startedAt": started,
        "baseDate": base_date,
        "candidateCount": len(candidates),
        "outputRows": len(rows),
        "okCount": ok_count,
        "failCount": len(rows) - ok_count,
        "output": OUT_CSV.name,
        "detailsTop20": details[:20],
    }

    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_LOG.write_text("\n".join(logs), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
