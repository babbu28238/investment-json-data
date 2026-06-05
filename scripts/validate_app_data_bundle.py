#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V290 APP DATA BUNDLE VALIDATION LOCK

목적:
- app_data_bundle.json이 앱에서 읽을 수 있는 최소 조건을 만족하는지 검증
- 후보/현재가/추천요약/파이프라인 상태가 번들에 포함됐는지 확인
- 앱 적용 전 GitHub Actions 단계에서 실패 원인을 빠르게 확인할 수 있도록 리포트 생성

출력:
- app_data_bundle_validation.json
- app_data_bundle_validation.txt
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()

BUNDLE = ROOT / "app_data_bundle.json"
OUT_JSON = ROOT / "app_data_bundle_validation.json"
OUT_TXT = ROOT / "app_data_bundle_validation.txt"


def now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def as_list(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    if isinstance(value, dict):
        for key in ["candidates", "items", "stocks", "data", "results", "recommendations"]:
            if isinstance(value.get(key), list):
                return [x for x in value[key] if isinstance(x, dict)]
    return []


def get_payload(bundle: Dict[str, Any], key: str) -> Any:
    payload = bundle.get("payload")
    if isinstance(payload, dict):
        return payload.get(key)
    return None


def count_quotes(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        quotes = value.get("quotes")
        if isinstance(quotes, list):
            return len(quotes)
    return 0


def main() -> None:
    checks = []
    warnings = []
    errors = []

    if not BUNDLE.exists():
        result = {
            "version": "V290_APP_DATA_BUNDLE_VALIDATION_LOCK",
            "updatedAt": now_kst(),
            "status": "fail",
            "errors": ["app_data_bundle.json 파일이 없습니다."],
            "warnings": [],
            "checks": [],
        }
        OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        OUT_TXT.write_text("V290 APP DATA BUNDLE VALIDATION\nstatus: fail\nerror: app_data_bundle.json missing", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    try:
        bundle = read_json(BUNDLE)
    except Exception as e:
        result = {
            "version": "V290_APP_DATA_BUNDLE_VALIDATION_LOCK",
            "updatedAt": now_kst(),
            "status": "fail",
            "errors": [f"app_data_bundle.json 파싱 실패: {e}"],
            "warnings": [],
            "checks": [],
        }
        OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        OUT_TXT.write_text(f"V290 APP DATA BUNDLE VALIDATION\nstatus: fail\nerror: {e}", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    bundle_status = str(bundle.get("status", "-")).lower()
    candidate_count = int(bundle.get("candidateCount") or 0)
    quote_count = int(bundle.get("liveQuoteCount") or 0)
    top_candidates = bundle.get("topCandidates") if isinstance(bundle.get("topCandidates"), list) else []

    candidates_payload = get_payload(bundle, "candidates")
    live_quotes_payload = get_payload(bundle, "liveQuotes")
    app_status_payload = get_payload(bundle, "appDataStatus")
    pipeline_payload = get_payload(bundle, "pipelineHealth")
    recommendation_payload = get_payload(bundle, "recommendationSummary")

    candidate_rows = as_list(candidates_payload)
    quote_rows = count_quotes(live_quotes_payload)

    def add_check(name: str, passed: bool, detail: str):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})
        if not passed:
            errors.append(detail)

    add_check("bundle_status", bundle_status in ["ok", "warning"], f"bundle status={bundle_status}")
    add_check("candidate_count", candidate_count > 0, f"candidateCount={candidate_count}")
    add_check("candidate_payload", len(candidate_rows) > 0, f"payload.candidates rows={len(candidate_rows)}")
    add_check("live_quote_count", quote_count > 0 or quote_rows > 0, f"liveQuoteCount={quote_count}, payload quotes={quote_rows}")
    add_check("top_candidates", len(top_candidates) > 0, f"topCandidates={len(top_candidates)}")
    add_check("app_status_payload", isinstance(app_status_payload, dict), "payload.appDataStatus 확인")
    add_check("pipeline_health_payload", isinstance(pipeline_payload, dict), "payload.pipelineHealth 확인")
    add_check("recommendation_summary_payload", isinstance(recommendation_payload, dict), "payload.recommendationSummary 확인")

    if candidate_count < 10:
        warnings.append("후보 수가 10개 미만입니다. 시장 스캐너 또는 매퍼 실행 결과를 확인하세요.")
    if quote_count < min(candidate_count, 10):
        warnings.append("현재가 수가 후보 수보다 현저히 적습니다. update_live_quotes.py 실행 결과를 확인하세요.")
    if bundle.get("missingFiles"):
        warnings.append("누락 파일: " + ", ".join(map(str, bundle.get("missingFiles", []))))

    status = "ok" if not errors else "fail"
    if status == "ok" and warnings:
        status = "warning"

    result = {
        "version": "V290_APP_DATA_BUNDLE_VALIDATION_LOCK",
        "updatedAt": now_kst(),
        "status": status,
        "candidateCount": candidate_count,
        "liveQuoteCount": quote_count,
        "topCandidateCount": len(top_candidates),
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
    }

    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "V290 APP DATA BUNDLE VALIDATION LOCK",
        f"updatedAt: {result['updatedAt']}",
        f"status: {status}",
        f"candidateCount: {candidate_count}",
        f"liveQuoteCount: {quote_count}",
        "",
        "Checks:",
    ]
    for check in checks:
        mark = "OK" if check["passed"] else "FAIL"
        lines.append(f"- {mark} {check['name']}: {check['detail']}")
    if warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"- {w}" for w in warnings])
    if errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"- {e}" for e in errors])

    OUT_TXT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
