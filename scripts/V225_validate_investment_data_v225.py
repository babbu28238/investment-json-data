#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V225 DATA QUALITY CHECKER

목적:
- GitHub Actions 실행 전/후 데이터 품질 점검
- stock_candidates_input.csv, report_hints.csv, supply_flow_input.csv, stock_candidates.json 검증
- 앱에서 깨질 가능성이 있는 문제를 사전에 발견

출력:
- v225_data_quality_report.json
- v225_data_quality_report.txt
"""

import csv
import json
import re
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()

FILES = {
    "candidate_csv": ROOT / "stock_candidates_input.csv",
    "report_csv": ROOT / "report_hints.csv",
    "supply_csv": ROOT / "supply_flow_input.csv",
    "app_json": ROOT / "stock_candidates.json",
}

OUT_JSON = ROOT / "v225_data_quality_report.json"
OUT_TXT = ROOT / "v225_data_quality_report.txt"

def now_text():
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

def read_csv_flexible(path):
    if not path.exists():
        return [], f"파일 없음: {path.name}"

    last_error = None
    for enc in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return list(csv.DictReader(f)), None
        except Exception as e:
            last_error = e
    return [], f"CSV 읽기 실패: {path.name} / {last_error}"

def read_json(path):
    if not path.exists():
        return None, f"파일 없음: {path.name}"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as e:
        return None, f"JSON 읽기 실패: {path.name} / {e}"

def clean(v):
    return "" if v is None else str(v).strip()

def normalize(s):
    s = str(s or "").lower().strip()
    s = re.sub(r"[\s\-_./()\[\]{}]+", "", s)
    replacements = {
        "종목코드": "code",
        "단축코드": "code",
        "코드": "code",
        "종목명": "name",
        "외국인": "foreign",
        "연기금": "pension",
        "연기금등": "pension",
        "투신": "trust",
        "금융투자": "finance",
        "금투": "finance",
        "5일": "5d",
        "20일": "20d",
        "60일": "60d",
    }
    for k, v in replacements.items():
        s = s.replace(k, v)
    return s

def get_col(row, aliases):
    if not row:
        return ""
    for a in aliases:
        if a in row and clean(row[a]):
            return clean(row[a])
    norm_map = {normalize(k): k for k in row.keys()}
    for a in aliases:
        na = normalize(a)
        if na in norm_map and clean(row.get(norm_map[na])):
            return clean(row.get(norm_map[na]))
    return ""

def code_of(row):
    return get_col(row, ["code", "stockCode", "stock_code", "종목코드", "단축코드", "ticker", "symbol"])

def name_of(row):
    return get_col(row, ["name", "stockName", "stock_name", "종목명"])

def score_of(row):
    s = get_col(row, ["score", "aiScore", "totalScore", "점수", "종합점수"])
    try:
        return int(round(float(s.replace(",", "").replace("%", ""))))
    except Exception:
        return None

def has_supply_columns(headers):
    if not headers:
        return False, []
    needed = {
        "foreign": False,
        "pension": False,
        "trust": False,
        "finance": False,
    }
    matched = []
    for h in headers:
        nh = normalize(h)
        for actor in needed:
            if actor in nh and ("5d" in nh or "20d" in nh or "60d" in nh):
                needed[actor] = True
                matched.append(h)
    return any(needed.values()), matched

def validate():
    issues = []
    warnings = []
    ok_items = []

    candidate_rows, candidate_error = read_csv_flexible(FILES["candidate_csv"])
    report_rows, report_error = read_csv_flexible(FILES["report_csv"])
    supply_rows, supply_error = read_csv_flexible(FILES["supply_csv"])
    app_json, json_error = read_json(FILES["app_json"])

    if candidate_error:
        issues.append(candidate_error)
    if report_error:
        warnings.append(report_error)
    if supply_error:
        warnings.append(supply_error)
    if json_error:
        warnings.append(json_error)

    # Candidate CSV validation
    candidate_codes = []
    candidate_names = []
    bad_rows = []
    duplicate_codes = []

    if candidate_rows:
        for i, row in enumerate(candidate_rows, start=2):
            code = code_of(row)
            name = name_of(row)
            score = score_of(row)

            if not code and not name:
                bad_rows.append(f"{i}행: 종목코드/종목명 모두 없음")
            if score is None:
                bad_rows.append(f"{i}행: 점수 누락 또는 숫자 아님")

            if code:
                # Excel may remove leading zero; warn for short numeric KRX codes
                if code.isdigit() and len(code) < 6:
                    warnings.append(f"{i}행: 종목코드 {code}는 6자리 미만입니다. 앞자리 0 누락 가능성 확인")
                candidate_codes.append(code)
            if name:
                candidate_names.append(name)

        seen = set()
        for c in candidate_codes:
            if c in seen and c not in duplicate_codes:
                duplicate_codes.append(c)
            seen.add(c)

        if bad_rows:
            issues.extend(bad_rows)
        if duplicate_codes:
            warnings.append(f"중복 종목코드: {', '.join(duplicate_codes)}")

    # Report coverage
    report_keys = set()
    for r in report_rows:
        k = code_of(r) or name_of(r)
        if k:
            report_keys.add(k)

    if candidate_rows and report_rows:
        missing_report = []
        for row in candidate_rows:
            c = code_of(row)
            n = name_of(row)
            if c not in report_keys and n not in report_keys:
                missing_report.append(n or c or "이름없음")
        if missing_report:
            warnings.append(f"report_hints.csv 매칭 누락: {', '.join(missing_report[:10])}")

    # Supply coverage
    supply_headers = supply_rows[0].keys() if supply_rows else []
    has_supply, matched_supply_cols = has_supply_columns(supply_headers)

    if supply_rows and not has_supply:
        issues.append("supply_flow_input.csv에서 외국인/연기금/투신/금융투자 5D/20D/60D 컬럼을 인식하지 못했습니다.")

    supply_keys = set()
    for r in supply_rows:
        k = code_of(r) or name_of(r)
        if k:
            supply_keys.add(k)

    if candidate_rows and supply_rows:
        missing_supply = []
        for row in candidate_rows:
            c = code_of(row)
            n = name_of(row)
            if c not in supply_keys and n not in supply_keys:
                missing_supply.append(n or c or "이름없음")
        if missing_supply:
            warnings.append(f"supply_flow_input.csv 매칭 누락: {', '.join(missing_supply[:10])}")

    # JSON app compatibility
    json_count = 0
    json_required_missing = []
    if isinstance(app_json, list):
        json_count = len(app_json)
        required = ["rank", "name", "code", "score", "reason"]
        for idx, item in enumerate(app_json, start=1):
            if not isinstance(item, dict):
                json_required_missing.append(f"{idx}번째 항목이 객체가 아님")
                continue
            for key in required:
                if key not in item or clean(item.get(key)) == "":
                    json_required_missing.append(f"{idx}번째 항목: {key} 누락")
    elif app_json is not None:
        warnings.append("stock_candidates.json이 배열 구조가 아닙니다. 앱은 wrapper 구조도 일부 지원하지만 배열 구조가 가장 안전합니다.")

    if json_required_missing:
        issues.extend(json_required_missing[:20])

    status = "PASS" if not issues else "FAIL"
    report = {
        "version": "V225_DATA_QUALITY_CHECKER",
        "generatedAt": now_text(),
        "status": status,
        "files": {k: str(v.name) for k, v in FILES.items()},
        "counts": {
            "candidateRows": len(candidate_rows),
            "reportRows": len(report_rows),
            "supplyRows": len(supply_rows),
            "appJsonItems": json_count,
        },
        "supplyColumnMatched": matched_supply_cols,
        "issues": issues,
        "warnings": warnings,
        "nextAction": "GitHub Actions 생성 workflow를 실행해도 됩니다." if status == "PASS" else "issues 항목을 먼저 수정하세요."
    }

    lines = []
    lines.append("V225 DATA QUALITY REPORT")
    lines.append("=" * 32)
    lines.append(f"상태: {status}")
    lines.append(f"생성일시: {report['generatedAt']}")
    lines.append("")
    lines.append("[파일 행 수]")
    for k, v in report["counts"].items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("[수급 인식 컬럼]")
    if matched_supply_cols:
        for c in matched_supply_cols:
            lines.append(f"- {c}")
    else:
        lines.append("- 없음")
    lines.append("")
    lines.append("[문제]")
    if issues:
        for e in issues:
            lines.append(f"- {e}")
    else:
        lines.append("- 없음")
    lines.append("")
    lines.append("[경고]")
    if warnings:
        for w in warnings:
            lines.append(f"- {w}")
    else:
        lines.append("- 없음")
    lines.append("")
    lines.append(f"다음 조치: {report['nextAction']}")

    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_TXT.write_text("\n".join(lines), encoding="utf-8")

    print("\n".join(lines))

    # Do not fail the GitHub Action for warnings, only hard issues.
    if issues:
        raise SystemExit(1)

if __name__ == "__main__":
    validate()
