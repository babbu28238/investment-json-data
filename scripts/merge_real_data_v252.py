#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V252 REAL DATA MERGER+

목적:
- stock_candidates.json에 실제 차트/수급/리포트 CSV 데이터를 병합
- V250의 보정값(수급 미연결, 차트 확인 필요 등)을 실제 값으로 교체
- 병합 후 V250을 한 번 더 실행하면 누락 필드는 안전하게 보정됨

실행 권장 순서:
1. Update Stock Candidates V224 Mapper
2. Merge Real Data V252
3. Force Repair Extended Fields V250
4. Validate Real Data Quality V251
5. 앱 새로고침
"""

import csv
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()

CANDIDATES_JSON = ROOT / "stock_candidates.json"
STATUS_JSON = ROOT / "app_data_status.json"
SUMMARY_JSON = ROOT / "v252_real_data_merge_summary.json"
SUMMARY_TXT = ROOT / "v252_real_data_merge_summary.txt"

SUPPLY_FILES = [
    ROOT / "supply_flow_input.csv",
    ROOT / "supply_flow_input_v251_template.csv",
    ROOT / "data_templates" / "supply_flow_input_v251_template.csv",
]

REPORT_FILES = [
    ROOT / "report_hints.csv",
    ROOT / "report_hints_input.csv",
    ROOT / "report_hints_v251_template.csv",
    ROOT / "data_templates" / "report_hints_v251_template.csv",
]

CHART_FILES = [
    ROOT / "chart_signals_input.csv",
    ROOT / "chart_signal_input.csv",
    ROOT / "chart_signals.csv",
    ROOT / "data_templates" / "chart_signals_input_v252_template.csv",
]

PLACEHOLDERS = [
    "-",
    "",
    "수급 미연결",
    "차트 확인 필요",
    "일봉 확인 필요",
    "RSI 확인 필요",
    "MACD 확인 필요",
    "거래량 확인 필요",
    "리포트 확인 필요",
    "뉴스 확인 필요",
    "후보 사유 기반 검토 필요",
    "손절 기준 확인 필요",
    "진입 기준 확인 필요",
    "목표 기준 확인 필요",
]


def now_text():
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def read_csv_dict(path):
    if not path.exists():
        return []

    encodings = ["utf-8-sig", "utf-8", "cp949", "euc-kr"]

    for enc in encodings:
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue

    raise RuntimeError(f"CSV 인코딩을 읽지 못했습니다: {path}")


def find_existing(paths):
    return [p for p in paths if p.exists()]


def unwrap_candidates(data):
    if isinstance(data, list):
        return data, None

    if isinstance(data, dict):
        for key in ["candidates", "items", "data", "results", "stocks"]:
            if isinstance(data.get(key), list):
                return data[key], key

    raise ValueError("stock_candidates.json에서 후보 배열을 찾지 못했습니다.")


def norm(value):
    if value is None:
        return ""

    return str(value).strip()


def get(row, keys, default=""):
    for key in keys:
        if key in row and norm(row.get(key)) not in ["", "-", "nan", "NaN", "None", "null"]:
            return norm(row.get(key))

    return default


def candidate_key(row):
    code = get(row, ["code", "종목코드", "Code"], "")
    name = get(row, ["name", "종목명", "Name"], "")

    if code:
        return f"code:{code.zfill(6) if code.isdigit() else code}"

    return f"name:{name}"


def build_lookup(rows):
    lookup = {}

    for row in rows:
        code = get(row, ["code", "종목코드", "Code"], "")
        name = get(row, ["name", "종목명", "Name"], "")

        if code:
            lookup[f"code:{code.zfill(6) if code.isdigit() else code}"] = row

        if name:
            lookup[f"name:{name}"] = row

    return lookup


def should_replace(current, new_value):
    current = norm(current)
    new_value = norm(new_value)

    if not new_value or new_value == "-":
        return False

    if current in PLACEHOLDERS:
        return True

    # 기존 값이 있어도 CSV 실제 값이 들어오면 교체 허용
    return True


def set_if_available(candidate, source, target, source_keys):
    new_value = get(source, source_keys, "")

    if should_replace(candidate.get(target, "-"), new_value):
        candidate[target] = new_value
        return True

    return False


def merge_supply(candidate, row):
    changed = 0

    mapping = {
        "foreign5D": ["foreign5D", "foreign_5d", "Foreign_5D", "외국인5D", "외국인_5일"],
        "foreign20D": ["foreign20D", "foreign_20d", "Foreign_20D", "외국인20D", "외국인_20일"],
        "foreign60D": ["foreign60D", "foreign_60d", "Foreign_60D", "외국인60D", "외국인_60일"],
        "pension5D": ["pension5D", "pension_5d", "Pension_5D", "연기금5D", "연기금_5일"],
        "pension20D": ["pension20D", "pension_20d", "Pension_20D", "연기금20D", "연기금_20일"],
        "pension60D": ["pension60D", "pension_60d", "Pension_60D", "연기금60D", "연기금_60일"],
        "trust5D": ["trust5D", "trust_5d", "Trust_5D", "투신5D", "투신_5일"],
        "trust20D": ["trust20D", "trust_20d", "Trust_20D", "투신20D", "투신_20일"],
        "trust60D": ["trust60D", "trust_60d", "Trust_60D", "투신60D", "투신_60일"],
        "finance5D": ["finance5D", "finance_5d", "Finance_5D", "금융투자5D", "금투_5일"],
        "finance20D": ["finance20D", "finance_20d", "Finance_20D", "금융투자20D", "금투_20일"],
        "finance60D": ["finance60D", "finance_60d", "Finance_60D", "금융투자60D", "금투_60일"],
    }

    for target, keys in mapping.items():
        changed += 1 if set_if_available(candidate, row, target, keys) else 0

    supply_memo = get(row, ["supplyMemo", "supply_memo", "수급메모", "수급_메모"], "")

    if supply_memo and should_replace(candidate.get("riskMemo", "-"), supply_memo):
        candidate["riskMemo"] = supply_memo
        changed += 1

    return changed


def merge_report(candidate, row):
    changed = 0

    mapping = {
        "reportSignal": ["reportSignal", "report_signal", "리포트신호", "리포트_신호", "reportTitle", "리포트제목"],
        "newsSignal": ["newsSignal", "news_signal", "뉴스신호", "뉴스_신호"],
        "riskMemo": ["riskMemo", "risk_memo", "리스크메모", "리스크", "memo", "메모"],
    }

    for target, keys in mapping.items():
        changed += 1 if set_if_available(candidate, row, target, keys) else 0

    return changed


def merge_chart(candidate, row):
    changed = 0

    mapping = {
        "weeklyCloud": ["weeklyCloud", "weekly_cloud", "주봉구름대", "주봉_구름대"],
        "dailySignal": ["dailySignal", "daily_signal", "일봉신호", "일봉_신호"],
        "rsi": ["rsi", "RSI", "rsiSignal", "rsi_signal", "RSI신호"],
        "macd": ["macd", "MACD", "macdSignal", "macd_signal", "MACD신호"],
        "volumeSignal": ["volumeSignal", "volume_signal", "거래량신호", "거래량_신호"],
    }

    for target, keys in mapping.items():
        changed += 1 if set_if_available(candidate, row, target, keys) else 0

    return changed


def main():
    if not CANDIDATES_JSON.exists():
        raise SystemExit("stock_candidates.json 파일이 없습니다. V224 Mapper를 먼저 실행하세요.")

    raw = json.loads(CANDIDATES_JSON.read_text(encoding="utf-8"))
    candidates, container_key = unwrap_candidates(raw)

    supply_paths = find_existing(SUPPLY_FILES)
    report_paths = find_existing(REPORT_FILES)
    chart_paths = find_existing(CHART_FILES)

    supply_rows = []
    report_rows = []
    chart_rows = []

    for path in supply_paths:
        supply_rows.extend(read_csv_dict(path))

    for path in report_paths:
        report_rows.extend(read_csv_dict(path))

    for path in chart_paths:
        chart_rows.extend(read_csv_dict(path))

    supply_lookup = build_lookup(supply_rows)
    report_lookup = build_lookup(report_rows)
    chart_lookup = build_lookup(chart_rows)

    stats = {
        "candidateCount": len(candidates),
        "supplyRows": len(supply_rows),
        "reportRows": len(report_rows),
        "chartRows": len(chart_rows),
        "supplyMatched": 0,
        "reportMatched": 0,
        "chartMatched": 0,
        "fieldsUpdated": 0,
    }

    unmatched = []

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue

        key = candidate_key(candidate)
        name_key = f"name:{get(candidate, ['name', '종목명'], '')}"

        matched_any = False

        supply_row = supply_lookup.get(key) or supply_lookup.get(name_key)
        if supply_row:
            changed = merge_supply(candidate, supply_row)
            stats["fieldsUpdated"] += changed
            stats["supplyMatched"] += 1
            matched_any = True

        report_row = report_lookup.get(key) or report_lookup.get(name_key)
        if report_row:
            changed = merge_report(candidate, report_row)
            stats["fieldsUpdated"] += changed
            stats["reportMatched"] += 1
            matched_any = True

        chart_row = chart_lookup.get(key) or chart_lookup.get(name_key)
        if chart_row:
            changed = merge_chart(candidate, chart_row)
            stats["fieldsUpdated"] += changed
            stats["chartMatched"] += 1
            matched_any = True

        if not matched_any:
            unmatched.append({
                "name": get(candidate, ["name", "종목명"], "-"),
                "code": get(candidate, ["code", "종목코드"], "-"),
            })

    if isinstance(raw, list):
        output = candidates
    else:
        output = raw
        output[container_key] = candidates
        output["version"] = "V252_REAL_DATA_MERGER"
        output["updatedAt"] = now_text()
        output["v252Merge"] = True

    CANDIDATES_JSON.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    status = {
        "version": "V252_REAL_DATA_MERGER",
        "updatedAt": now_text(),
        "candidateCount": len(candidates),
        "message": "V252 실제 데이터 병합 완료",
        "supplyMatched": stats["supplyMatched"],
        "reportMatched": stats["reportMatched"],
        "chartMatched": stats["chartMatched"],
        "fieldsUpdated": stats["fieldsUpdated"],
    }

    STATUS_JSON.write_text(
        json.dumps(status, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    summary = {
        "version": "V252_REAL_DATA_MERGER",
        "updatedAt": now_text(),
        **stats,
        "supplyFiles": [str(p.relative_to(ROOT)) for p in supply_paths],
        "reportFiles": [str(p.relative_to(ROOT)) for p in report_paths],
        "chartFiles": [str(p.relative_to(ROOT)) for p in chart_paths],
        "unmatchedTop20": unmatched[:20],
    }

    SUMMARY_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    lines = [
        "V252 REAL DATA MERGER",
        f"updatedAt: {summary['updatedAt']}",
        f"candidateCount: {stats['candidateCount']}",
        f"supplyRows: {stats['supplyRows']}, supplyMatched: {stats['supplyMatched']}",
        f"reportRows: {stats['reportRows']}, reportMatched: {stats['reportMatched']}",
        f"chartRows: {stats['chartRows']}, chartMatched: {stats['chartMatched']}",
        f"fieldsUpdated: {stats['fieldsUpdated']}",
        "",
        "Files:",
        f"- supply: {summary['supplyFiles']}",
        f"- report: {summary['reportFiles']}",
        f"- chart: {summary['chartFiles']}",
        "",
        "Unmatched Top 20:",
    ]

    for item in unmatched[:20]:
        lines.append(f"- {item['name']} ({item['code']})")

    SUMMARY_TXT.write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
