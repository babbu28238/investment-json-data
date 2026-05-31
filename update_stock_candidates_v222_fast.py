#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V222 PYTHON COLLECTOR FAST

목적
- 기존 GitHub 저장소(investment-json-data)를 그대로 활용합니다.
- stock_candidates_input.csv를 읽어 앱용 stock_candidates.json을 생성합니다.
- 선택 입력 파일 report_hints.csv가 있으면 종목코드 기준으로 리포트/뉴스 힌트를 병합합니다.
- app_data_status.json, v222_generation_summary.json, v222_collection_errors.txt도 함께 생성합니다.

실행
python3 scripts/update_stock_candidates_v222_fast.py

선택 실행
python3 scripts/update_stock_candidates_v222_fast.py --input stock_candidates_input.csv --output stock_candidates.json
"""

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

FIELDNAMES = [
    "rank", "name", "code", "score", "grade", "reason", "market", "sector", "changeRate",
    "entryPrice", "stopLoss", "targetPrice", "strategy", "weeklyCloud", "dailySignal",
    "rsi", "macd", "volumeSignal", "foreign5D", "foreign20D", "foreign60D",
    "pension5D", "pension20D", "pension60D", "trust5D", "trust20D", "trust60D",
    "finance5D", "finance20D", "finance60D", "reportSignal", "newsSignal", "riskMemo",
]

# 점수 자동 보정에 사용하는 입력 컬럼. CSV에 없어도 됩니다.
OPTIONAL_SCORE_COLUMNS = [
    "supplyScore", "chartScore", "reportScore", "riskScore",
]


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def clean(value, default: str = "-") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def parse_int(value, default: int = 0) -> int:
    try:
        text = str(value).replace(",", "").replace("%", "").strip()
        if text == "":
            return default
        return int(round(float(text)))
    except Exception:
        return default


def infer_grade(score: int) -> str:
    if score >= 90:
        return "S"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B"
    return "C"


def infer_action(score: int) -> str:
    if score >= 90:
        return "우선 검토"
    if score >= 80:
        return "조건 확인"
    if score >= 70:
        return "관찰"
    return "제외 검토"


def merge_report_hints(rows: List[Dict], hints_path: Path) -> Tuple[List[Dict], List[str]]:
    warnings = []
    if not hints_path.exists():
        warnings.append(f"report_hints.csv 없음: {hints_path} - 힌트 병합 생략")
        return rows, warnings

    with hints_path.open("r", encoding="utf-8-sig", newline="") as f:
        hints = list(csv.DictReader(f))

    hint_by_code = {}
    for hint in hints:
        code = clean(hint.get("code", ""), "")
        if code:
            hint_by_code[code] = hint

    for row in rows:
        code = clean(row.get("code", ""), "")
        hint = hint_by_code.get(code)
        if not hint:
            continue
        # 빈 값일 때만 힌트로 채웁니다. CSV 본문 값이 우선입니다.
        for key in ["reportSignal", "newsSignal", "riskMemo", "reason"]:
            if clean(row.get(key, "")) == "-" and clean(hint.get(key, "")) != "-":
                row[key] = clean(hint.get(key))
    return rows, warnings


def auto_score(row: Dict) -> int:
    """score가 비어 있을 때만 간단 점수 합산으로 자동 산출합니다."""
    explicit = parse_int(row.get("score", ""), default=-1)
    if explicit >= 0:
        return max(0, min(100, explicit))

    supply = parse_int(row.get("supplyScore", 0))
    chart = parse_int(row.get("chartScore", 0))
    report = parse_int(row.get("reportScore", 0))
    risk = parse_int(row.get("riskScore", 0))
    total = supply + chart + report - risk
    return max(0, min(100, total))


def normalize_row(row: Dict, index: int) -> Dict:
    score = auto_score(row)
    rank = parse_int(row.get("rank", index + 1), index + 1)
    grade = clean(row.get("grade", ""))
    if grade == "-":
        grade = infer_grade(score)

    item = {}
    for field in FIELDNAMES:
        if field == "rank":
            item[field] = rank
        elif field == "score":
            item[field] = score
        elif field == "grade":
            item[field] = grade
        else:
            item[field] = clean(row.get(field, "-"))

    # reason이 비어 있으면 빠르게 자동 문구 생성
    if item["reason"] == "-":
        item["reason"] = f"{item['sector']} 섹터 후보로 {infer_action(score)} 대상입니다. 수급·차트·뉴스 확인 후 진입 여부를 판단하세요."

    return item


def validate_items(items: List[Dict]) -> Tuple[List[Dict], List[str]]:
    errors = []
    valid = []
    seen_codes = set()
    for idx, item in enumerate(items, start=1):
        name = clean(item.get("name", ""), "")
        code = clean(item.get("code", ""), "")
        if not name:
            errors.append(f"{idx}행 제외: name이 비어 있습니다.")
            continue
        if not code:
            errors.append(f"{idx}행 제외: code가 비어 있습니다. name={name}")
            continue
        if code in seen_codes:
            errors.append(f"{idx}행 경고: code 중복 감지 {code}. 앱에는 둘 다 표시될 수 있습니다.")
        seen_codes.add(code)
        valid.append(item)
    return valid, errors


def build(input_path: Path, output_path: Path, hints_path: Path, status_path: Path, summary_path: Path, error_path: Path) -> None:
    warnings = []
    if not input_path.exists():
        raise FileNotFoundError(f"입력 CSV 없음: {input_path}")

    with input_path.open("r", encoding="utf-8-sig", newline="") as f:
        raw_rows = list(csv.DictReader(f))

    normalized = [normalize_row(row, idx) for idx, row in enumerate(raw_rows)]
    normalized, hint_warnings = merge_report_hints(normalized, hints_path)
    warnings.extend(hint_warnings)
    valid, validation_errors = validate_items(normalized)

    # score 높은 순으로 자동 순위 재정렬. rank를 직접 유지하고 싶으면 아래 줄을 주석 처리하세요.
    valid.sort(key=lambda x: (-parse_int(x.get("score", 0)), parse_int(x.get("rank", 9999))))
    for i, item in enumerate(valid, start=1):
        item["rank"] = i
        item["grade"] = infer_grade(parse_int(item.get("score", 0)))

    payload = {
        "generatedAt": now_text(),
        "source": "V222 PYTHON COLLECTOR FAST",
        "notice": "CSV 기반 자동 생성 파일입니다. 투자 판단 전 원자료와 현재가를 반드시 확인하세요.",
        "candidates": valid,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    status = {
        "version": "V222 PYTHON COLLECTOR FAST",
        "generatedAt": payload["generatedAt"],
        "candidateCount": len(valid),
        "sGradeCount": sum(1 for x in valid if x.get("grade") == "S"),
        "aGradeCount": sum(1 for x in valid if x.get("grade") == "A"),
        "sourceInput": str(input_path),
        "output": str(output_path),
        "status": "success" if valid else "empty",
        "warnings": warnings,
        "errors": validation_errors,
    }
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "generatedAt": payload["generatedAt"],
        "rowsRead": len(raw_rows),
        "rowsWritten": len(valid),
        "topCandidates": [
            {"rank": x["rank"], "name": x["name"], "code": x["code"], "score": x["score"], "grade": x["grade"]}
            for x in valid[:10]
        ],
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    error_lines = []
    error_lines.append(f"generatedAt: {payload['generatedAt']}")
    error_lines.append("[warnings]")
    error_lines.extend(warnings or ["없음"])
    error_lines.append("")
    error_lines.append("[errors]")
    error_lines.extend(validation_errors or ["없음"])
    error_path.write_text("\n".join(error_lines), encoding="utf-8")

    print(f"완료: {output_path}")
    print(f"후보 수: {len(valid)}개 / S등급 {status['sGradeCount']}개 / A등급 {status['aGradeCount']}개")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="stock_candidates_input.csv")
    p.add_argument("--output", default="stock_candidates.json")
    p.add_argument("--hints", default="report_hints.csv")
    p.add_argument("--status", default="app_data_status.json")
    p.add_argument("--summary", default="v222_generation_summary.json")
    p.add_argument("--errors", default="v222_collection_errors.txt")
    args = p.parse_args()

    build(
        input_path=Path(args.input),
        output_path=Path(args.output),
        hints_path=Path(args.hints),
        status_path=Path(args.status),
        summary_path=Path(args.summary),
        error_path=Path(args.errors),
    )


if __name__ == "__main__":
    main()
