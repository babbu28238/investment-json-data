#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V294 SIGNAL REFLECTION AUDIT
- Checks whether market scanner, news, supply, report, live quote, recommendation, and bundle outputs
  are actually reflected in stock_candidates.json and app_data_bundle.json.
- Produces machine-readable and human-readable audit reports.
"""
from __future__ import annotations

import json
import csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Tuple

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()

FILES = {
    "stock_candidates": ROOT / "stock_candidates.json",
    "stock_candidates_input": ROOT / "stock_candidates_input.csv",
    "live_quotes": ROOT / "live_quotes.json",
    "news_signals": ROOT / "news_signals.json",
    "supply_summary": ROOT / "supply_flow_summary.json",
    "supply_input": ROOT / "supply_flow_input.csv",
    "report_signals": ROOT / "report_signals.json",
    "report_hints": ROOT / "report_hints.csv",
    "recommendation_summary": ROOT / "recommendation_summary.json",
    "app_bundle": ROOT / "app_data_bundle.json",
    "pipeline_validation": ROOT / "market_pipeline_validation.json",
}

OUT_JSON = ROOT / "signal_reflection_audit.json"
OUT_TXT = ROOT / "signal_reflection_audit.txt"


def now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")


def load_json(path: Path, default: Any = None) -> Any:
    if default is None:
        default = {}
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"_loadError": str(e)}


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
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
        for key in ("candidates", "items", "data", "results", "stocks", "recommendations"):
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def normalize_code(value: Any) -> str:
    s = str(value or "").strip()
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits.zfill(6)[-6:] if digits else ""


def text_has_value(value: Any) -> bool:
    s = str(value or "").strip()
    return s not in ("", "-", "None", "null", "nan", "NaN", "확인 필요", "뉴스 확인 필요", "리포트 확인 필요", "수급 데이터 없음")


def numeric_value(value: Any) -> float:
    try:
        s = str(value or "").replace(",", "").replace("%", "").replace("원", "").strip()
        if s in ("", "-"):
            return 0.0
        return float(s)
    except Exception:
        return 0.0


def count_candidate_fields(candidates: List[Dict[str, Any]]) -> Dict[str, int]:
    result = {
        "candidateCount": len(candidates),
        "hasNewsSignal": 0,
        "hasReportSignal": 0,
        "hasRiskMemo": 0,
        "hasSupplyFields": 0,
        "hasLiveFields": 0,
        "hasRecommendationMeta": 0,
        "hasScore": 0,
        "sOrAGrade": 0,
    }
    supply_keys = [
        "foreign5D", "foreign20D", "foreign60D", "pension5D", "pension20D", "pension60D",
        "trust5D", "trust20D", "trust60D", "finance5D", "finance20D", "finance60D",
        "Foreign_5D", "Foreign_20D", "Foreign_60D", "Pension_5D", "Pension_20D", "Pension_60D",
        "Trust_5D", "Trust_20D", "Trust_60D", "Finance_5D", "Finance_20D", "Finance_60D",
    ]
    live_keys = ["livePrice", "liveChangeRate", "liveVolume", "liveUpdatedAt", "currentPrice", "priceChangeRate"]
    reco_keys = ["finalScore", "recommendationScore", "actionPriority", "actionLabel", "recommendationReason", "technicalScore", "flowScore", "issueScore"]

    for item in candidates:
        if text_has_value(item.get("newsSignal") or item.get("news_signal")):
            result["hasNewsSignal"] += 1
        if text_has_value(item.get("reportSignal") or item.get("report_signal")):
            result["hasReportSignal"] += 1
        if text_has_value(item.get("riskMemo") or item.get("risk_memo")):
            result["hasRiskMemo"] += 1
        if any(text_has_value(item.get(k)) and numeric_value(item.get(k)) != 0 for k in supply_keys):
            result["hasSupplyFields"] += 1
        if any(text_has_value(item.get(k)) for k in live_keys):
            result["hasLiveFields"] += 1
        if any(text_has_value(item.get(k)) for k in reco_keys):
            result["hasRecommendationMeta"] += 1
        if numeric_value(item.get("score")) > 0:
            result["hasScore"] += 1
        if str(item.get("grade", "")).strip() in ("S", "A"):
            result["sOrAGrade"] += 1
    return result


def top_codes(candidates: List[Dict[str, Any]], n: int = 10) -> List[str]:
    codes = []
    for item in candidates[:n]:
        code = normalize_code(item.get("code") or item.get("ticker") or item.get("symbol"))
        if code:
            codes.append(code)
    return codes


def build_audit() -> Dict[str, Any]:
    stock_data = load_json(FILES["stock_candidates"], [])
    candidates = unwrap_candidates(stock_data)
    live_data = load_json(FILES["live_quotes"], {})
    news_data = load_json(FILES["news_signals"], {})
    report_data = load_json(FILES["report_signals"], {})
    reco_data = load_json(FILES["recommendation_summary"], {})
    bundle_data = load_json(FILES["app_bundle"], {})

    stock_input_rows = read_csv_rows(FILES["stock_candidates_input"])
    supply_rows = read_csv_rows(FILES["supply_input"])
    report_hint_rows = read_csv_rows(FILES["report_hints"])

    live_quotes = []
    if isinstance(live_data, dict) and isinstance(live_data.get("quotes"), list):
        live_quotes = live_data.get("quotes", [])
    elif isinstance(live_data, list):
        live_quotes = live_data

    file_status = {name: path.exists() for name, path in FILES.items()}
    field_counts = count_candidate_fields(candidates)

    required = [
        "stock_candidates", "stock_candidates_input", "live_quotes", "news_signals",
        "supply_input", "report_hints", "recommendation_summary", "app_bundle"
    ]
    missing_required = [name for name in required if not file_status.get(name)]

    warnings = []
    failures = []

    if missing_required:
        failures.append(f"필수 산출물 누락: {', '.join(missing_required)}")
    if len(candidates) < 20:
        warnings.append("최종 후보 수가 20개 미만입니다. 시장 스캐너/추천 엔진 결과를 확인하세요.")
    if len(stock_input_rows) < 50:
        warnings.append("stock_candidates_input.csv 행 수가 50개 미만입니다. 시장 스캐너가 충분히 작동했는지 확인하세요.")
    if len(live_quotes) == 0:
        warnings.append("live_quotes.json에 현재가 데이터가 없습니다.")
    if len(supply_rows) == 0:
        warnings.append("supply_flow_input.csv에 수급 데이터가 없습니다.")
    if len(report_hint_rows) == 0:
        warnings.append("report_hints.csv에 뉴스/리포트 힌트가 없습니다.")
    if field_counts["hasNewsSignal"] == 0:
        warnings.append("stock_candidates.json에 newsSignal 반영이 확인되지 않습니다.")
    if field_counts["hasReportSignal"] == 0:
        warnings.append("stock_candidates.json에 reportSignal 반영이 확인되지 않습니다.")
    if field_counts["hasSupplyFields"] == 0:
        warnings.append("stock_candidates.json에 수급 필드 반영이 확인되지 않습니다.")
    if field_counts["hasLiveFields"] == 0:
        warnings.append("stock_candidates.json 후보에 현재가/실시간 필드 반영이 약합니다. 앱 fallback 병합이면 정상일 수 있습니다.")

    # pass conditions: data engine can operate even if live fields are only in bundle/live_quotes
    pass_checks = {
        "hasCandidateJson": file_status["stock_candidates"] and len(candidates) > 0,
        "hasMarketScannerInput": file_status["stock_candidates_input"] and len(stock_input_rows) >= 50,
        "hasLiveQuotes": file_status["live_quotes"] and len(live_quotes) > 0,
        "hasNewsSignals": file_status["news_signals"],
        "hasSupplyData": file_status["supply_input"] and len(supply_rows) > 0,
        "hasReportHints": file_status["report_hints"] and len(report_hint_rows) > 0,
        "hasRecommendationSummary": file_status["recommendation_summary"],
        "hasAppBundle": file_status["app_bundle"],
        "stockJsonHasScores": field_counts["hasScore"] > 0,
    }

    passed_count = sum(1 for v in pass_checks.values() if v)
    total_count = len(pass_checks)
    if failures:
        overall = "fail"
    elif passed_count >= total_count - 1 and not any("반영이 확인되지" in w for w in warnings[:3]):
        overall = "ok"
    else:
        overall = "warning"

    top_preview = []
    for item in candidates[:10]:
        top_preview.append({
            "rank": item.get("rank"),
            "code": normalize_code(item.get("code")),
            "name": item.get("name"),
            "score": item.get("score"),
            "grade": item.get("grade"),
            "newsSignal": item.get("newsSignal") or item.get("news_signal"),
            "reportSignal": item.get("reportSignal") or item.get("report_signal"),
            "riskMemo": item.get("riskMemo") or item.get("risk_memo"),
        })

    return {
        "version": "V294_SIGNAL_REFLECTION_AUDIT",
        "updatedAt": now_kst(),
        "overallStatus": overall,
        "passedChecks": passed_count,
        "totalChecks": total_count,
        "fileStatus": file_status,
        "passChecks": pass_checks,
        "counts": {
            "stockCandidates": len(candidates),
            "stockCandidatesInputRows": len(stock_input_rows),
            "liveQuotes": len(live_quotes),
            "supplyRows": len(supply_rows),
            "reportHintRows": len(report_hint_rows),
            "newsSignalItems": len(news_data.get("items", [])) if isinstance(news_data, dict) else (len(news_data) if isinstance(news_data, list) else 0),
            "reportSignalItems": len(report_data.get("items", [])) if isinstance(report_data, dict) else (len(report_data) if isinstance(report_data, list) else 0),
        },
        "candidateFieldReflection": field_counts,
        "topCodes": top_codes(candidates),
        "topPreview": top_preview,
        "warnings": warnings,
        "failures": failures,
        "recommendationSummaryVersion": reco_data.get("version") if isinstance(reco_data, dict) else None,
        "appBundleVersion": bundle_data.get("version") if isinstance(bundle_data, dict) else None,
    }


def write_text_report(audit: Dict[str, Any]) -> str:
    lines = []
    lines.append("V294 SIGNAL REFLECTION AUDIT")
    lines.append(f"updatedAt: {audit['updatedAt']}")
    lines.append(f"overallStatus: {audit['overallStatus']}")
    lines.append(f"checks: {audit['passedChecks']}/{audit['totalChecks']}")
    lines.append("")
    lines.append("[Counts]")
    for k, v in audit["counts"].items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("[Candidate Field Reflection]")
    for k, v in audit["candidateFieldReflection"].items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("[Pass Checks]")
    for k, v in audit["passChecks"].items():
        lines.append(f"- {k}: {'OK' if v else 'CHECK'}")
    lines.append("")
    lines.append("[Top Preview]")
    for item in audit["topPreview"]:
        lines.append(f"- {item.get('rank')}. {item.get('name')}({item.get('code')}) score={item.get('score')} grade={item.get('grade')} news={item.get('newsSignal')} report={item.get('reportSignal')}")
    lines.append("")
    if audit["warnings"]:
        lines.append("[Warnings]")
        lines.extend([f"- {w}" for w in audit["warnings"]])
    if audit["failures"]:
        lines.append("[Failures]")
        lines.extend([f"- {f}" for f in audit["failures"]])
    return "\n".join(lines)


def main() -> None:
    audit = build_audit()
    OUT_JSON.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_TXT.write_text(write_text_report(audit), encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    if audit["overallStatus"] == "fail":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
