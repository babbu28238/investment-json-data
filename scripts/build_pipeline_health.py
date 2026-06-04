#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V287 PIPELINE HEALTH MONITOR
- Purpose: summarize the market scanner pipeline health after scheduled/manual runs.
- Inputs: generated JSON/TXT files from scanner/news/supply/report/recommendation/live quote/validation steps.
- Outputs:
  - pipeline_health.json
  - pipeline_health.txt

This script is intentionally defensive. Missing optional files become warnings, not hard failures.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()

OUT_JSON = ROOT / "pipeline_health.json"
OUT_TXT = ROOT / "pipeline_health.txt"

REQUIRED_FILES = [
    "stock_candidates.json",
    "app_data_status.json",
    "live_quotes.json",
]

OPTIONAL_FILES = [
    "stock_candidates_input.csv",
    "v101_generation_summary.json",
    "news_signals.json",
    "news_signals_summary.json",
    "supply_flow_input.csv",
    "supply_flow_summary.json",
    "report_signals.json",
    "report_signals_summary.json",
    "recommendation_summary.json",
    "market_pipeline_validation.json",
    "intraday_pipeline_status.json",
    "live_quotes_validation_report.json",
    "app_pipeline_status.json",
]


def now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")


def read_json_safe(path: Path) -> Tuple[Any, str]:
    if not path.exists():
        return None, "missing"
    try:
        return json.loads(path.read_text(encoding="utf-8")), "ok"
    except Exception as exc:
        return None, f"json_error: {exc}"


def unwrap_candidates(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ["candidates", "items", "data", "results", "stocks", "recommendations", "rows"]:
            if isinstance(data.get(key), list):
                return [x for x in data[key] if isinstance(x, dict)]
    return []


def count_live_quotes(data: Any) -> Tuple[int, int, int]:
    if isinstance(data, dict):
        quotes = data.get("quotes")
        if isinstance(quotes, list):
            total = len(quotes)
            ok = sum(1 for q in quotes if isinstance(q, dict) and str(q.get("status", "")).lower() == "ok")
            fail = sum(1 for q in quotes if isinstance(q, dict) and str(q.get("status", "")).lower() == "fail")
            return total, ok, fail
    if isinstance(data, list):
        total = len(data)
        ok = sum(1 for q in data if isinstance(q, dict) and str(q.get("status", "ok")).lower() == "ok")
        fail = sum(1 for q in data if isinstance(q, dict) and str(q.get("status", "")).lower() == "fail")
        return total, ok, fail
    return 0, 0, 0


def file_info(name: str) -> Dict[str, Any]:
    path = ROOT / name
    if not path.exists():
        return {"name": name, "exists": False}
    stat = path.stat()
    modified = datetime.fromtimestamp(stat.st_mtime, KST).strftime("%Y-%m-%d %H:%M:%S KST")
    return {"name": name, "exists": True, "sizeBytes": stat.st_size, "modifiedAt": modified}


def main() -> None:
    warnings: List[str] = []
    errors: List[str] = []

    files = {name: file_info(name) for name in REQUIRED_FILES + OPTIONAL_FILES}

    for name in REQUIRED_FILES:
        if not files[name]["exists"]:
            errors.append(f"필수 파일 없음: {name}")

    candidates_raw, candidates_status = read_json_safe(ROOT / "stock_candidates.json")
    candidates = unwrap_candidates(candidates_raw)
    candidate_count = len(candidates)
    if candidates_status != "ok":
        errors.append(f"stock_candidates.json 읽기 실패: {candidates_status}")
    elif candidate_count == 0:
        errors.append("stock_candidates.json 후보 수 0")
    elif candidate_count < 10:
        warnings.append(f"후보 수가 적습니다: {candidate_count}")

    live_raw, live_status = read_json_safe(ROOT / "live_quotes.json")
    quote_count, quote_ok, quote_fail = count_live_quotes(live_raw)
    if live_status != "ok":
        errors.append(f"live_quotes.json 읽기 실패: {live_status}")
    elif quote_count == 0:
        warnings.append("live_quotes.json 현재가 데이터 0건")
    elif quote_ok < max(1, int(quote_count * 0.7)):
        warnings.append(f"현재가 수집 성공률 낮음: {quote_ok}/{quote_count}")

    app_raw, app_status = read_json_safe(ROOT / "app_data_status.json")
    app_status_value = "unknown"
    if isinstance(app_raw, dict):
        app_status_value = str(app_raw.get("status", "unknown"))
        qws = app_raw.get("qualityWarnings")
        if isinstance(qws, list) and qws:
            warnings.extend([f"app_data_status 경고: {w}" for w in qws[:5]])
    elif app_status != "missing":
        warnings.append(f"app_data_status.json 읽기 상태: {app_status}")

    validation_raw, validation_status = read_json_safe(ROOT / "market_pipeline_validation.json")
    validation_status_value = "missing"
    if isinstance(validation_raw, dict):
        validation_status_value = str(validation_raw.get("status", validation_raw.get("result", "unknown")))
        if validation_status_value.lower() not in ["ok", "success", "passed", "warning"]:
            warnings.append(f"market_pipeline_validation 상태 확인 필요: {validation_status_value}")

    # Grade summary
    grade_counts: Dict[str, int] = {}
    top_names: List[Dict[str, Any]] = []
    for item in candidates:
        grade = str(item.get("grade", "-")).strip() or "-"
        grade_counts[grade] = grade_counts.get(grade, 0) + 1
    for item in candidates[:10]:
        top_names.append({
            "rank": item.get("rank"),
            "name": item.get("name"),
            "code": item.get("code"),
            "score": item.get("score"),
            "grade": item.get("grade"),
            "reason": item.get("reason", item.get("recentIssue", "-")),
        })

    if errors:
        status = "error"
    elif warnings:
        status = "warning"
    else:
        status = "ok"

    payload = {
        "version": "V287_PIPELINE_HEALTH_MONITOR",
        "updatedAt": now_kst(),
        "status": status,
        "candidateCount": candidate_count,
        "gradeCounts": grade_counts,
        "liveQuote": {
            "quoteCount": quote_count,
            "okCount": quote_ok,
            "failCount": quote_fail,
        },
        "appDataStatus": app_status_value,
        "marketPipelineValidationStatus": validation_status_value,
        "warnings": warnings,
        "errors": errors,
        "topCandidates": top_names,
        "files": files,
        "nextAction": "앱 데이터 탭에서 저장 URL 새로고침 후 후보/현재가/뉴스·수급·리포트 반영 여부 확인" if status != "error" else "GitHub Actions 로그와 pipeline_health.txt의 errors를 먼저 확인",
    }

    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "V287 PIPELINE HEALTH MONITOR",
        f"updatedAt: {payload['updatedAt']}",
        f"status: {status}",
        f"candidateCount: {candidate_count}",
        f"gradeCounts: {grade_counts}",
        f"liveQuote: {quote_ok}/{quote_count} ok, {quote_fail} fail",
        f"appDataStatus: {app_status_value}",
        f"marketPipelineValidationStatus: {validation_status_value}",
        "",
        "Warnings:",
    ]
    lines.extend([f"- {w}" for w in warnings] or ["- none"])
    lines.append("")
    lines.append("Errors:")
    lines.extend([f"- {e}" for e in errors] or ["- none"])
    lines.append("")
    lines.append("Top Candidates:")
    for item in top_names:
        lines.append(f"- {item.get('rank')}. {item.get('name')}({item.get('code')}) {item.get('grade')} {item.get('score')}")

    OUT_TXT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
