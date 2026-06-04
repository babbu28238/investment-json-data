#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V288 APP OPERATION STATUS BRIDGE

목적:
- GitHub Actions 산출물들을 앱이 읽기 쉬운 단일 상태 파일로 통합
- pipeline_health.json, app_data_status.json, recommendation_summary.json,
  live_quotes.json, market_pipeline_validation.json을 읽어 app_operation_status.json 생성

출력:
- app_operation_status.json
- app_operation_status.txt

설계 원칙:
- 일부 파일이 없어도 실패하지 않고 missing 상태로 기록
- 앱에서는 app_operation_status.json 하나만 읽어도 운영 상태를 판단할 수 있음
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()

OUT_JSON = ROOT / "app_operation_status.json"
OUT_TXT = ROOT / "app_operation_status.txt"

INPUTS = {
    "pipelineHealth": ROOT / "pipeline_health.json",
    "appDataStatus": ROOT / "app_data_status.json",
    "recommendationSummary": ROOT / "recommendation_summary.json",
    "marketValidation": ROOT / "market_pipeline_validation.json",
    "liveQuotes": ROOT / "live_quotes.json",
    "stockCandidates": ROOT / "stock_candidates.json",
    "newsSignals": ROOT / "news_signals.json",
    "supplySummary": ROOT / "supply_flow_summary.json",
    "reportSummary": ROOT / "report_signals_summary.json",
}


def now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"_readError": str(e)}


def file_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"exists": False, "size": 0, "modifiedAt": None}
    stat = path.stat()
    modified = datetime.fromtimestamp(stat.st_mtime, KST).strftime("%Y-%m-%d %H:%M:%S")
    return {"exists": True, "size": stat.st_size, "modifiedAt": modified}


def count_candidates(data: Any) -> int:
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in ["candidates", "items", "data", "results", "stocks"]:
            if isinstance(data.get(key), list):
                return len(data[key])
    return 0


def grade_counts(data: Any) -> Dict[str, int]:
    rows = data if isinstance(data, list) else []
    if isinstance(data, dict):
        for key in ["candidates", "items", "data", "results", "stocks"]:
            if isinstance(data.get(key), list):
                rows = data[key]
                break
    counts: Dict[str, int] = {}
    for item in rows:
        if isinstance(item, dict):
            grade = str(item.get("grade", "-")).strip() or "-"
            counts[grade] = counts.get(grade, 0) + 1
    return counts


def quote_stats(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {"quoteCount": 0, "okCount": 0, "failCount": 0, "partialCount": 0}
    return {
        "quoteCount": int(data.get("quoteCount", 0) or 0),
        "okCount": int(data.get("okCount", 0) or 0),
        "failCount": int(data.get("failCount", 0) or 0),
        "partialCount": int(data.get("partialCount", 0) or 0),
        "source": data.get("source", "-"),
        "updatedAt": data.get("updatedAt", "-"),
    }


def derive_status(files: Dict[str, Dict[str, Any]], data: Dict[str, Any]) -> Dict[str, Any]:
    issues: List[str] = []
    warnings: List[str] = []

    required = ["stockCandidates", "liveQuotes", "appDataStatus"]
    for key in required:
        if not files[key]["exists"]:
            issues.append(f"필수 파일 없음: {key}")

    candidate_count = count_candidates(data.get("stockCandidates"))
    if candidate_count == 0:
        issues.append("추천 후보 수가 0개입니다.")
    elif candidate_count < 10:
        warnings.append("추천 후보 수가 10개 미만입니다.")

    q = quote_stats(data.get("liveQuotes"))
    if q["quoteCount"] == 0:
        warnings.append("실시간 현재가 quoteCount가 0입니다.")
    if q["failCount"] > 0:
        warnings.append(f"현재가 수집 실패 {q['failCount']}건")

    pipeline = data.get("pipelineHealth") or {}
    if isinstance(pipeline, dict):
        health_status = str(pipeline.get("status", "")).lower()
        if health_status in ["fail", "error", "critical"]:
            issues.append("pipeline_health 상태가 실패입니다.")
        elif health_status in ["warning", "partial"]:
            warnings.append("pipeline_health 상태가 경고/부분성공입니다.")

    if issues:
        status = "error"
        message = "운영 전 확인 필요"
    elif warnings:
        status = "warning"
        message = "운영 가능하나 일부 경고 확인 필요"
    else:
        status = "ok"
        message = "앱 운영 가능"

    return {
        "status": status,
        "message": message,
        "issues": issues,
        "warnings": warnings,
        "candidateCount": candidate_count,
        "gradeCounts": grade_counts(data.get("stockCandidates")),
        "quoteStats": q,
    }


def main() -> None:
    files = {key: file_state(path) for key, path in INPUTS.items()}
    data = {key: read_json(path) for key, path in INPUTS.items()}
    derived = derive_status(files, data)

    payload = {
        "version": "V288_APP_OPERATION_STATUS_BRIDGE",
        "updatedAt": now_kst(),
        "status": derived["status"],
        "message": derived["message"],
        "candidateCount": derived["candidateCount"],
        "gradeCounts": derived["gradeCounts"],
        "quoteStats": derived["quoteStats"],
        "issues": derived["issues"],
        "warnings": derived["warnings"],
        "files": files,
        "sourceVersions": {
            "pipelineHealth": (data.get("pipelineHealth") or {}).get("version") if isinstance(data.get("pipelineHealth"), dict) else None,
            "appDataStatus": (data.get("appDataStatus") or {}).get("version") if isinstance(data.get("appDataStatus"), dict) else None,
            "recommendationSummary": (data.get("recommendationSummary") or {}).get("version") if isinstance(data.get("recommendationSummary"), dict) else None,
            "marketValidation": (data.get("marketValidation") or {}).get("version") if isinstance(data.get("marketValidation"), dict) else None,
            "liveQuotes": (data.get("liveQuotes") or {}).get("version") if isinstance(data.get("liveQuotes"), dict) else None,
        },
    }

    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "V288 APP OPERATION STATUS BRIDGE",
        f"updatedAt: {payload['updatedAt']}",
        f"status: {payload['status']}",
        f"message: {payload['message']}",
        f"candidateCount: {payload['candidateCount']}",
        f"gradeCounts: {payload['gradeCounts']}",
        f"quoteStats: {payload['quoteStats']}",
        "",
        "Issues:",
    ]
    lines.extend([f"- {x}" for x in payload["issues"]] or ["- none"])
    lines.append("")
    lines.append("Warnings:")
    lines.extend([f"- {x}" for x in payload["warnings"]] or ["- none"])
    OUT_TXT.write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
