#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V298 NAVER SUPPLY FLOW ENGINE

Purpose
- Replace pykrx investor-flow collection that returned empty in GitHub Actions.
- Read Naver Finance investor table pages for each candidate.
- Create supply_flow_input.csv compatible with update_stock_candidates_v224_mapper.py.

Input priority
1) stock_candidates_input.csv
2) stock_candidates.json

Output
- supply_flow_input.csv
- supply_flow_summary.json
- supply_flow_log.txt
- supply_flow_debug.json

Notes
- Naver Finance investor pages can change. This script is defensive and writes diagnostics.
- Naver table provides foreign/institution daily net volume; detailed actor split
  (pension/trust/finance) is not publicly available on that page, so this version maps:
  foreign = foreign net flow
  finance = institution net flow proxy
  pension/trust = 0 with explicit memo
"""

from __future__ import annotations

import csv
import json
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()

CANDIDATE_CSV = ROOT / "stock_candidates_input.csv"
CANDIDATES_JSON = ROOT / "stock_candidates.json"
OUT_CSV = ROOT / "supply_flow_input.csv"
OUT_SUMMARY = ROOT / "supply_flow_summary.json"
OUT_LOG = ROOT / "supply_flow_log.txt"
OUT_DEBUG = ROOT / "supply_flow_debug.json"

MAX_CANDIDATES = 80
PAGES_TO_FETCH = 8       # about 80 rows, enough for 60 trading days
SLEEP_SECONDS = 0.15

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)


def now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def normalize_code(value: Any) -> str:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    return digits.zfill(6)[-6:] if digits else ""


def clean_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    s = str(value).strip()
    return s if s else default


def first(row: Dict[str, Any], keys: Iterable[str], default: str = "") -> str:
    for key in keys:
        if key in row and clean_text(row.get(key), ""):
            return clean_text(row.get(key), default)
    return default


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


def fetch_html(url: str, timeout: int = 12) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as res:
        raw = res.read()
    for enc in ["euc-kr", "cp949", "utf-8"]:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def strip_tags(fragment: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", fragment, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def parse_int(value: Any) -> int:
    s = str(value or "").replace(",", "").replace("+", "").strip()
    s = re.sub(r"[^0-9\-]", "", s)
    if s in ["", "-"]:
        return 0
    try:
        return int(s)
    except Exception:
        return 0


@dataclass
class InvestorRow:
    date: str
    close: int
    foreign: int
    institution: int


def parse_naver_frgn_rows(html: str) -> List[InvestorRow]:
    # frgn.naver table rows usually include: date, close, change, change%, volume, institution, foreign, foreign_ratio
    rows: List[InvestorRow] = []
    tr_list = re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S | re.I)
    for tr in tr_list:
        if not re.search(r"\d{2}\.\d{2}\.\d{2}", tr):
            continue
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S | re.I)
        values = [strip_tags(c) for c in cells]
        values = [v for v in values if v != ""]
        if len(values) < 7:
            continue

        date_match = re.search(r"\d{2}\.\d{2}\.\d{2}", values[0])
        if not date_match:
            continue

        date = date_match.group(0)
        close = parse_int(values[1])

        # Robust heuristic: in Naver foreign/institution page, the final numeric columns are institution and foreign.
        numeric_values = [parse_int(v) for v in values]
        # Prefer expected positions when available: [date, close, change, change%, volume, institution, foreign, ratio]
        institution = parse_int(values[5]) if len(values) > 5 else 0
        foreign = parse_int(values[6]) if len(values) > 6 else 0

        # If parsing went wrong, fallback to last meaningful signed integer columns.
        if institution == 0 and foreign == 0:
            signed = []
            for v in values:
                if re.search(r"[+\-]?[0-9,]+", v):
                    signed.append(parse_int(v))
            if len(signed) >= 3:
                institution = signed[-3]
                foreign = signed[-2]

        rows.append(InvestorRow(date=date, close=close, foreign=foreign, institution=institution))
    return rows


def fetch_naver_investor_rows(code: str) -> Tuple[List[InvestorRow], List[Dict[str, Any]]]:
    all_rows: List[InvestorRow] = []
    debug: List[Dict[str, Any]] = []
    seen_dates = set()

    for page in range(1, PAGES_TO_FETCH + 1):
        url = f"https://finance.naver.com/item/frgn.naver?code={code}&page={page}"
        status = "ok"
        rows: List[InvestorRow] = []
        try:
            html = fetch_html(url)
            rows = parse_naver_frgn_rows(html)
            if not rows:
                status = "empty"
        except (HTTPError, URLError, TimeoutError, Exception) as e:
            status = str(e)[:180]

        for r in rows:
            if r.date not in seen_dates:
                all_rows.append(r)
                seen_dates.add(r.date)

        debug.append({"page": page, "status": status, "rowCount": len(rows)})
        if page >= 2 and not rows:
            break
        time.sleep(0.05)

    return all_rows, debug


def sum_last(rows: List[InvestorRow], attr: str, n: int) -> int:
    if not rows:
        return 0
    values = [getattr(r, attr, 0) for r in rows[:n]]
    return int(sum(values))


def fmt(value: int) -> str:
    return str(int(value))


def build_supply_row(candidate: Dict[str, str]) -> Tuple[Dict[str, str], Dict[str, Any]]:
    code = candidate["code"]
    name = candidate["name"]
    rows, debug = fetch_naver_investor_rows(code)

    foreign5 = sum_last(rows, "foreign", 5)
    foreign20 = sum_last(rows, "foreign", 20)
    foreign60 = sum_last(rows, "foreign", 60)
    inst5 = sum_last(rows, "institution", 5)
    inst20 = sum_last(rows, "institution", 20)
    inst60 = sum_last(rows, "institution", 60)

    # Naver public table has institution aggregate, not pension/trust/finance split.
    # Put aggregate institution into finance*D proxy so existing V224 scoring can use institutional flow.
    row = {
        "code": code,
        "name": name,
        "foreign5D": fmt(foreign5),
        "foreign20D": fmt(foreign20),
        "foreign60D": fmt(foreign60),
        "pension5D": "0",
        "pension20D": "0",
        "pension60D": "0",
        "trust5D": "0",
        "trust20D": "0",
        "trust60D": "0",
        "finance5D": fmt(inst5),
        "finance20D": fmt(inst20),
        "finance60D": fmt(inst60),
        "supplyMemo": "",
    }

    non_zero = sum(1 for k in ["foreign5D", "foreign20D", "foreign60D", "finance5D", "finance20D", "finance60D"] if parse_int(row[k]) != 0)
    status = "ok" if rows and non_zero > 0 else ("zero" if rows else "fail")

    if status == "ok":
        if foreign20 > 0 and inst20 > 0:
            memo = "외국인·기관 20일 동반 순매수"
        elif foreign20 > 0 and inst20 <= 0:
            memo = "외국인 순매수 우위 / 기관 혼조"
        elif foreign20 <= 0 and inst20 > 0:
            memo = "기관 순매수 우위 / 외국인 혼조"
        elif foreign20 < 0 and inst20 < 0:
            memo = "외국인·기관 20일 동반 순매도"
        else:
            memo = "수급 중립 또는 혼조"
        memo += " (네이버 외국인·기관 집계 기반)"
    elif rows:
        memo = "수급 데이터는 조회됐으나 순매수 합계가 0"
    else:
        memo = "네이버 수급 조회 실패 또는 표 구조 변경"

    row["supplyMemo"] = memo

    detail = {
        "code": code,
        "name": name,
        "status": status,
        "rowCount": len(rows),
        "nonZeroFields": non_zero,
        "foreign20D": row["foreign20D"],
        "finance20D": row["finance20D"],
        "memo": memo,
        "debug": debug[:5],
        "sampleRows": [asdict(r) for r in rows[:3]],
    }
    return row, detail


def main() -> None:
    started = now_kst()
    candidates = load_candidates()
    rows: List[Dict[str, str]] = []
    details: List[Dict[str, Any]] = []
    logs = [f"V298 NAVER SUPPLY FLOW ENGINE startedAt={started}", f"candidateCount={len(candidates)}"]

    for idx, candidate in enumerate(candidates, start=1):
        row, detail = build_supply_row(candidate)
        rows.append(row)
        details.append(detail)
        logs.append(f"[{idx}/{len(candidates)}] {candidate['code']} {candidate['name']} {detail['status']} rows={detail['rowCount']} nonZero={detail['nonZeroFields']} {detail['memo']}")
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
    zero_count = sum(1 for d in details if d.get("status") == "zero")
    fail_count = sum(1 for d in details if d.get("status") == "fail")
    non_zero_rows = sum(1 for d in details if int(d.get("nonZeroFields", 0)) > 0)

    summary = {
        "version": "V298_NAVER_SUPPLY_FLOW_ENGINE",
        "updatedAt": now_kst(),
        "startedAt": started,
        "candidateCount": len(candidates),
        "outputRows": len(rows),
        "okCount": ok_count,
        "zeroCount": zero_count,
        "failCount": fail_count,
        "nonZeroRows": non_zero_rows,
        "source": "naver_finance_frgn_page",
        "output": OUT_CSV.name,
        "detailsTop20": details[:20],
    }

    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_DEBUG.write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_LOG.write_text("\n".join(logs), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
