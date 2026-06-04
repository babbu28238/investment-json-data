#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V289 APP DATA BUNDLE BUILDER

목적:
- 앱이 여러 JSON을 따로 확인하지 않아도 되도록 핵심 운영 데이터를 하나의 번들로 통합
- stock_candidates.json, live_quotes.json, app_data_status.json, pipeline_health.json,
  app_operation_status.json, recommendation_summary.json 등을 읽어 app_data_bundle.json 생성
- 파일이 없어도 실패하지 않고 missing 상태로 기록

출력:
- app_data_bundle.json
- app_data_bundle.txt
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()

OUT_JSON = ROOT / "app_data_bundle.json"
OUT_TXT = ROOT / "app_data_bundle.txt"

FILES = {
    "candidates": ROOT / "stock_candidates.json",
    "liveQuotes": ROOT / "live_quotes.json",
    "appDataStatus": ROOT / "app_data_status.json",
    "pipelineHealth": ROOT / "pipeline_health.json",
    "appOperationStatus": ROOT / "app_operation_status.json",
    "recommendationSummary": ROOT / "recommendation_summary.json",
    "newsSignalsSummary": ROOT / "news_signals_summary.json",
    "supplyFlowSummary": ROOT / "supply_flow_summary.json",
    "reportSignalsSummary": ROOT / "report_signals_summary.json",
    "marketValidation": ROOT / "market_pipeline_validation.json",
}


def now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def read_json_safe(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"exists": False, "path": path.name, "data": None, "error": "missing"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {"exists": True, "path": path.name, "data": data, "error": ""}
    except Exception as e:
        return {"exists": True, "path": path.name, "data": None, "error": str(e)[:200]}


def count_candidates(data: Any) -> int:
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in ["candidates", "items", "stocks", "data", "results"]:
            value = data.get(key)
            if isinstance(value, list):
                return len(value)
    return 0


def count_quotes(data: Any) -> int:
    if isinstance(data, dict):
        value = data.get("quotes")
        if isinstance(value, list):
            return len(value)
    if isinstance(data, list):
        return len(data)
    return 0


def top_candidates(data: Any, limit: int = 10):
    rows = data if isinstance(data, list) else []
    if isinstance(data, dict):
        for key in ["candidates", "items", "stocks", "data", "results"]:
            if isinstance(data.get(key), list):
                rows = data[key]
                break
    output = []
    for row in rows[:limit]:
        if isinstance(row, dict):
            output.append({
                "rank": row.get("rank", len(output) + 1),
                "name": row.get("name", row.get("종목명", "-")),
                "code": row.get("code", row.get("종목코드", "-")),
                "score": row.get("score", "-"),
                "grade": row.get("grade", "-"),
                "reason": row.get("reason", row.get("recentIssue", "-")),
            })
    return output


def main() -> None:
    loaded = {key: read_json_safe(path) for key, path in FILES.items()}

    candidate_data = loaded["candidates"].get("data")
    quote_data = loaded["liveQuotes"].get("data")

    missing = [key for key, value in loaded.items() if not value.get("exists")]
    errors = [f"{key}: {value.get('error')}" for key, value in loaded.items() if value.get("error") and value.get("exists")]

    candidate_count = count_candidates(candidate_data)
    quote_count = count_quotes(quote_data)

    status = "ok"
    warnings = []
    if candidate_count == 0:
        status = "warning"
        warnings.append("stock_candidates.json 후보 수가 0개입니다.")
    if quote_count == 0:
        status = "warning"
        warnings.append("live_quotes.json 현재가 수가 0개입니다.")
    if errors:
        status = "warning"
        warnings.extend(errors)

    bundle = {
        "version": "V289_APP_DATA_BUNDLE",
        "updatedAt": now_kst(),
        "status": status,
        "candidateCount": candidate_count,
        "liveQuoteCount": quote_count,
        "missingFiles": missing,
        "warnings": warnings,
        "topCandidates": top_candidates(candidate_data, 10),
        "sources": {
            key: {
                "exists": value.get("exists"),
                "path": value.get("path"),
                "error": value.get("error"),
            }
            for key, value in loaded.items()
        },
        "payload": {
            key: value.get("data") for key, value in loaded.items() if value.get("exists") and not value.get("error")
        },
    }

    OUT_JSON.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "V289 APP DATA BUNDLE",
        f"updatedAt: {bundle['updatedAt']}",
        f"status: {status}",
        f"candidateCount: {candidate_count}",
        f"liveQuoteCount: {quote_count}",
        f"missingFiles: {', '.join(missing) if missing else '-'}",
        "",
        "Top Candidates:",
    ]
    for item in bundle["topCandidates"]:
        lines.append(f"- #{item['rank']} {item['name']}({item['code']}) {item['grade']} {item['score']}")
    if warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"- {w}" for w in warnings])

    OUT_TXT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({
        "version": bundle["version"],
        "status": status,
        "candidateCount": candidate_count,
        "liveQuoteCount": quote_count,
        "missingFiles": missing,
        "warnings": warnings,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
