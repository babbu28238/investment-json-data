#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V285 MARKET PIPELINE VALIDATION LOCK

목적:
- V279~V284 통합 파이프라인 실행 후 생성물이 실제 운영 가능한지 점검
- 앱이 읽는 핵심 JSON/CSV의 존재 여부, 후보 수, 필드 품질, 실시간 현재가 병합 준비 상태를 검증
- 실패하더라도 진단 리포트는 생성하여 GitHub Actions에서 원인 확인 가능하게 함

출력:
- market_pipeline_validation.json
- market_pipeline_validation.txt
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()

FILES = {
    "stock_candidates_input": ROOT / "stock_candidates_input.csv",
    "stock_candidates": ROOT / "stock_candidates.json",
    "live_quotes": ROOT / "live_quotes.json",
    "app_status": ROOT / "app_data_status.json",
    "news_signals": ROOT / "news_signals.json",
    "report_signals": ROOT / "report_signals.json",
    "supply_flow": ROOT / "supply_flow_input.csv",
    "recommendation_summary": ROOT / "recommendation_summary.json",
}

OUT_JSON = ROOT / "market_pipeline_validation.json"
OUT_TXT = ROOT / "market_pipeline_validation.txt"

REQUIRED_CANDIDATE_FIELDS = ["rank", "name", "code", "score", "grade"]
OPTIONAL_QUALITY_FIELDS = ["market", "sector", "reason", "strategy", "newsSignal", "reportSignal", "riskMemo"]
MIN_CANDIDATES = 10
TARGET_CANDIDATES = 50


def now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"__error__": str(e)}


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    for enc in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
        except Exception:
            return []
    return []


def unwrap_candidates(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ["candidates", "stocks", "items", "data", "results", "stockCandidates", "recommendations", "rows"]:
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def unwrap_quotes(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ["quotes", "items", "data", "results", "rows"]:
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def norm_code(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits.zfill(6)[-6:] if digits else ""


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    s = str(value).strip()
    return s in ["", "-", "None", "null", "nan", "NaN"]


def score_candidate_quality(candidates: List[Dict[str, Any]]) -> Tuple[int, List[str]]:
    warnings: List[str] = []
    if len(candidates) < MIN_CANDIDATES:
        warnings.append(f"후보 수가 너무 적습니다: {len(candidates)}개")
    elif len(candidates) < TARGET_CANDIDATES:
        warnings.append(f"최종 후보 수가 목표({TARGET_CANDIDATES})보다 적습니다: {len(candidates)}개")

    missing_required = []
    missing_optional_counts = {field: 0 for field in OPTIONAL_QUALITY_FIELDS}
    invalid_scores = 0
    duplicate_codes = 0
    seen = set()

    for idx, item in enumerate(candidates, start=1):
        for field in REQUIRED_CANDIDATE_FIELDS:
            if field not in item or is_blank(item.get(field)):
                missing_required.append(f"#{idx}:{field}")
        for field in OPTIONAL_QUALITY_FIELDS:
            if field not in item or is_blank(item.get(field)):
                missing_optional_counts[field] += 1
        try:
            score = float(str(item.get("score", 0)).replace(",", ""))
            if score < 0 or score > 100:
                invalid_scores += 1
        except Exception:
            invalid_scores += 1
        code = norm_code(item.get("code"))
        if code:
            if code in seen:
                duplicate_codes += 1
            seen.add(code)

    if missing_required:
        warnings.append(f"필수 필드 누락: {len(missing_required)}건 / 예: {missing_required[:10]}")
    if invalid_scores:
        warnings.append(f"score 값 이상: {invalid_scores}건")
    if duplicate_codes:
        warnings.append(f"중복 종목코드: {duplicate_codes}건")

    for field, count in missing_optional_counts.items():
        if candidates and count >= max(5, int(len(candidates) * 0.5)):
            warnings.append(f"선택 품질 필드 '{field}' 공백 비율 높음: {count}/{len(candidates)}")

    # 100점 기준 품질 점수
    quality = 100
    quality -= min(40, len(missing_required) * 2)
    quality -= min(20, invalid_scores * 3)
    quality -= min(10, duplicate_codes * 2)
    if len(candidates) < TARGET_CANDIDATES:
        quality -= 10
    if len(candidates) < MIN_CANDIDATES:
        quality -= 30
    return max(0, quality), warnings


def main() -> None:
    checks: Dict[str, Any] = {}
    warnings: List[str] = []
    errors: List[str] = []

    file_status = {key: path.exists() for key, path in FILES.items()}
    checks["files"] = file_status

    # 핵심 파일은 반드시 있어야 함
    for key in ["stock_candidates", "app_status"]:
        if not file_status.get(key):
            errors.append(f"핵심 파일 없음: {FILES[key].name}")

    candidates_raw = read_json(FILES["stock_candidates"], [])
    candidates = unwrap_candidates(candidates_raw)
    quote_raw = read_json(FILES["live_quotes"], {})
    quotes = unwrap_quotes(quote_raw)

    input_rows = read_csv_rows(FILES["stock_candidates_input"])
    supply_rows = read_csv_rows(FILES["supply_flow"])

    quality_score, candidate_warnings = score_candidate_quality(candidates)
    warnings.extend(candidate_warnings)

    candidate_codes = {norm_code(x.get("code")) for x in candidates if norm_code(x.get("code"))}
    quote_codes = {norm_code(x.get("code")) for x in quotes if norm_code(x.get("code"))}
    quote_matched = len(candidate_codes & quote_codes)

    if candidates and quotes and quote_matched == 0:
        warnings.append("live_quotes.json과 stock_candidates.json 종목코드 매칭이 0건입니다.")
    if candidates and not quotes:
        warnings.append("live_quotes.json에 quotes 데이터가 없거나 파일이 없습니다.")

    app_status = read_json(FILES["app_status"], {})
    rec_summary = read_json(FILES["recommendation_summary"], {})
    news_signals = read_json(FILES["news_signals"], {})
    report_signals = read_json(FILES["report_signals"], {})

    checks.update({
        "candidateInputCount": len(input_rows),
        "candidateCount": len(candidates),
        "liveQuoteCount": len(quotes),
        "liveQuoteMatchedCount": quote_matched,
        "supplyRowCount": len(supply_rows),
        "hasNewsSignals": bool(news_signals) and not (isinstance(news_signals, dict) and news_signals.get("__error__")),
        "hasReportSignals": bool(report_signals) and not (isinstance(report_signals, dict) and report_signals.get("__error__")),
        "hasRecommendationSummary": bool(rec_summary) and not (isinstance(rec_summary, dict) and rec_summary.get("__error__")),
        "appStatusVersion": app_status.get("version") if isinstance(app_status, dict) else None,
        "recommendationVersion": rec_summary.get("version") if isinstance(rec_summary, dict) else None,
        "candidateQualityScore": quality_score,
        "topCandidates": [
            {
                "rank": x.get("rank"),
                "name": x.get("name"),
                "code": x.get("code"),
                "grade": x.get("grade"),
                "score": x.get("score"),
            }
            for x in candidates[:10]
        ],
    })

    if quality_score < 70:
        errors.append(f"후보 데이터 품질 점수 낮음: {quality_score}")

    status = "fail" if errors else ("warning" if warnings else "ok")
    payload = {
        "version": "V285_MARKET_PIPELINE_VALIDATION_LOCK",
        "updatedAt": now_kst(),
        "status": status,
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
        "message": "시장 스캐너 통합 파이프라인 검증 완료" if status != "fail" else "시장 스캐너 통합 파이프라인 검증 실패",
    }

    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "V285 MARKET PIPELINE VALIDATION LOCK",
        f"updatedAt: {payload['updatedAt']}",
        f"status: {status}",
        "",
        "Counts:",
        f"- stock_candidates_input.csv rows: {checks['candidateInputCount']}",
        f"- stock_candidates.json candidates: {checks['candidateCount']}",
        f"- live_quotes.json quotes: {checks['liveQuoteCount']}",
        f"- live quote matched: {checks['liveQuoteMatchedCount']}",
        f"- supply_flow_input.csv rows: {checks['supplyRowCount']}",
        f"- candidate quality score: {quality_score}",
        "",
        "Top candidates:",
    ]
    for item in checks["topCandidates"]:
        lines.append(f"- {item.get('rank')} {item.get('name')}({item.get('code')}) {item.get('grade')} {item.get('score')}")
    if warnings:
        lines += ["", "Warnings:"] + [f"- {w}" for w in warnings]
    if errors:
        lines += ["", "Errors:"] + [f"- {e}" for e in errors]

    OUT_TXT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    # fail은 실제로 액션 실패 처리. warning은 커밋되도록 정상 종료.
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
