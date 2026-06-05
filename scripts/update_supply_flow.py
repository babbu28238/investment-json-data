#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V297 SUPPLY FLOW COMPAT FIX

목적:
- V296에서 실패한 get_market_trading_value_by_ticker 의존성 제거
- 현재 GitHub Actions pykrx 버전에서 더 보편적으로 사용 가능한
  get_market_trading_value_by_date(start, end, code, detail=True/False) 기반으로 복구
- 실패 시에도 CSV/요약/디버그 파일 생성

출력:
- supply_flow_input.csv
- supply_flow_summary.json
- supply_flow_log.txt
- supply_flow_debug.json
"""

from __future__ import annotations

import csv
import inspect
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

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
SLEEP_SECONDS = 0.05
MAX_CANDIDATES = 80

ACTOR_ALIASES = {
    "foreign": ["외국인", "외국인합계", "외국인 합계", "foreign", "foreigner"],
    "pension": ["연기금", "연기금등", "연기금 등", "pension"],
    "trust": ["투신", "투자신탁", "trust"],
    "finance": ["금융투자", "금투", "finance"],
}


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


def trading_days_until(base_date: str, count: int) -> Tuple[str, str]:
    end = datetime.strptime(base_date, "%Y%m%d")
    start = end - timedelta(days=max(20, int(count * 2.3) + 14))
    return ymd(start), base_date


def normalize_col(name: Any) -> str:
    s = str(name or "").lower()
    s = re.sub(r"[\s_\-./()\[\]{}]+", "", s)
    replacements = {
        "외국인합계": "foreign", "외국인": "foreign", "foreign": "foreign", "foreigner": "foreign",
        "연기금등": "pension", "연기금": "pension", "pension": "pension",
        "투자신탁": "trust", "투신": "trust", "trust": "trust",
        "금융투자": "finance", "금투": "finance", "finance": "finance",
        "순매수": "net", "순매수거래대금": "net", "거래대금": "value",
    }
    for k, v in replacements.items():
        s = s.replace(k, v)
    return s


def safe_number(value: Any) -> float:
    try:
        if value is None or pd.isna(value):
            return 0.0
        return float(str(value).replace(",", "").replace("원", "").strip())
    except Exception:
        return 0.0


def find_actor_column(df: pd.DataFrame, actor: str) -> Any:
    if df is None or df.empty:
        return None
    norm_map = {normalize_col(c): c for c in df.columns}
    if actor in norm_map:
        return norm_map[actor]
    for norm, raw in norm_map.items():
        if actor in norm:
            return raw
    aliases = ACTOR_ALIASES.get(actor, [])
    for raw in df.columns:
        raw_s = str(raw)
        if any(alias in raw_s for alias in aliases):
            return raw
    return None


def fetch_by_date(code: str, start: str, end: str) -> Tuple[pd.DataFrame | None, Dict[str, Any]]:
    debug: Dict[str, Any] = {"method": "get_market_trading_value_by_date", "start": start, "end": end, "code": code}
    attempts = []
    # pykrx 버전별 지원 시그니처를 모두 시도한다.
    attempts.append(("detail_true", lambda: stock.get_market_trading_value_by_date(start, end, code, detail=True)))
    attempts.append(("detail_false", lambda: stock.get_market_trading_value_by_date(start, end, code, detail=False)))
    attempts.append(("plain", lambda: stock.get_market_trading_value_by_date(start, end, code)))

    last_error = ""
    for label, fn in attempts:
        try:
            df = fn()
            debug["attempt"] = label
            if df is not None and not df.empty:
                debug["status"] = "ok"
                debug["rowCount"] = int(len(df))
                debug["columns"] = [str(c) for c in df.columns]
                return df, debug
            last_error = "empty"
        except Exception as e:
            last_error = str(e)[:200]
            debug[f"error_{label}"] = last_error
    debug["status"] = last_error or "empty"
    debug["rowCount"] = 0
    debug["columns"] = []
    return None, debug


def sum_actor(df: pd.DataFrame, actor: str, last_n: int) -> float:
    col = find_actor_column(df, actor)
    if col is None:
        return 0.0
    series = df[col].tail(last_n).apply(safe_number)
    return float(series.sum())


def format_amount(value: float) -> str:
    # 백만원 단위. 0이어도 V224가 값으로 인식하도록 "0" 출력.
    return str(int(round(value / 1_000_000)))


def build_supply_row(candidate: Dict[str, str], base_date: str) -> Tuple[Dict[str, str], Dict[str, Any]]:
    code = candidate["code"]
    name = candidate["name"]
    row: Dict[str, str] = {"code": code, "name": name}
    detail: Dict[str, Any] = {"code": code, "name": name, "periodDebug": []}

    non_zero = 0
    any_ok = False
    last_columns: List[str] = []
    last_status = ""

    for period in PERIODS:
        start, end = trading_days_until(base_date, period)
        df, dbg = fetch_by_date(code, start, end)
        dbg["period"] = period
        detail["periodDebug"].append(dbg)
        last_status = str(dbg.get("status", ""))
        last_columns = list(dbg.get("columns", []))

        if df is not None and not df.empty:
            any_ok = True

        for actor in ["foreign", "pension", "trust", "finance"]:
            value = sum_actor(df, actor, period) if df is not None else 0.0
            if abs(value) > 0:
                non_zero += 1
            row[f"{actor}{period}D"] = format_amount(value)
        time.sleep(0.01)

    def n(key: str) -> float:
        try:
            return float(str(row.get(key, "0")).replace(",", ""))
        except Exception:
            return 0.0

    foreign20 = n("foreign20D")
    pension20 = n("pension20D")
    trust20 = n("trust20D")
    finance20 = n("finance20D")
    institutional20 = pension20 + trust20 + finance20
    positive_count = sum(1 for x in [foreign20, pension20, trust20, finance20] if x > 0)

    if not any_ok:
        memo = f"수급 조회 실패: {last_status or 'empty'}"
        status = "fail"
    elif non_zero == 0:
        memo = "수급 데이터 조회 성공, 순매수값 0 또는 컬럼 미매칭"
        status = "zero"
    elif positive_count >= 3:
        memo = "외국인·기관 주요 주체 20일 수급 동반 개선"
        status = "ok"
    elif foreign20 > 0 and institutional20 > 0:
        memo = "외국인 및 기관 수급 우위"
        status = "ok"
    elif foreign20 < 0 and institutional20 < 0:
        memo = "외국인·기관 수급 동반 약화"
        status = "ok"
    else:
        memo = "수급 중립 또는 혼조"
        status = "ok"

    row["supplyMemo"] = memo
    detail.update({
        "status": status,
        "nonZeroFields": non_zero,
        "columns": last_columns,
        "memo": memo,
        "foreign20D": row.get("foreign20D"),
        "pension20D": row.get("pension20D"),
        "trust20D": row.get("trust20D"),
        "finance20D": row.get("finance20D"),
    })
    return row, detail


def main() -> None:
    started = now_kst()
    base_date = recent_market_date()
    candidates = load_candidates()

    logs: List[str] = []
    details: List[Dict[str, Any]] = []
    rows: List[Dict[str, str]] = []

    logs.append(f"V297 SUPPLY FLOW COMPAT FIX startedAt={started} baseDate={base_date}")
    logs.append(f"candidateCount={len(candidates)} maxCandidates={MAX_CANDIDATES}")
    try:
        logs.append(f"pykrx get_market_trading_value_by_date signature={inspect.signature(stock.get_market_trading_value_by_date)}")
    except Exception as e:
        logs.append(f"signature_check_failed={e}")

    for idx, candidate in enumerate(candidates, start=1):
        row, detail = build_supply_row(candidate, base_date)
        rows.append(row)
        details.append(detail)
        logs.append(f"[{idx}/{len(candidates)}] {candidate['code']} {candidate['name']} {detail.get('status')} nz={detail.get('nonZeroFields')} {row.get('supplyMemo')}")
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
    fail_count = sum(1 for d in details if d.get("status") == "fail")
    zero_count = sum(1 for d in details if d.get("status") == "zero")
    non_zero_rows = sum(1 for d in details if int(d.get("nonZeroFields", 0) or 0) > 0)

    summary = {
        "version": "V297_SUPPLY_FLOW_COMPAT_FIX",
        "updatedAt": now_kst(),
        "startedAt": started,
        "baseDate": base_date,
        "candidateCount": len(candidates),
        "outputRows": len(rows),
        "okCount": ok_count,
        "zeroCount": zero_count,
        "failCount": fail_count,
        "nonZeroRows": non_zero_rows,
        "output": OUT_CSV.name,
        "detailsTop20": details[:20],
    }

    debug = {
        "version": "V297_SUPPLY_FLOW_COMPAT_FIX",
        "updatedAt": summary["updatedAt"],
        "details": details,
        "logs": logs[-100:],
    }

    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_DEBUG.write_text(json.dumps(debug, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_LOG.write_text("\n".join(logs), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
