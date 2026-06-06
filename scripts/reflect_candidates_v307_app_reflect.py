# V307_APP_REFLECT_GUARD
# Purpose:
# - Force app-facing files to reflect V306 EOD scanner output.
# - Prevent regression to old 24-candidate app bundle.
# - Always write v307_app_reflect_report.json.

from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


VERSION = "V307_APP_REFLECT_GUARD"
MIN_FINAL_COUNT = 50

INPUT_CSV = Path("stock_candidates_input.csv")
STOCK_JSON = Path("stock_candidates.json")
APP_BUNDLE = Path("app_data_bundle.json")
REPORT_JSON = Path("v307_app_reflect_report.json")


def now_kst_like() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write_report(status: str, **kwargs: Any) -> None:
    report = {
        "version": VERSION,
        "status": status,
        "updatedAt": now_kst_like(),
        **kwargs,
    }
    REPORT_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_json_any(path: Path) -> Any:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def normalize_key_map(row: Dict[str, Any]) -> Dict[str, Any]:
    return {str(k).strip().lower(): v for k, v in row.items()}


def first_value(row: Dict[str, Any], *names: str, default: str = "") -> str:
    lower = normalize_key_map(row)
    for name in names:
        key = name.lower()
        if key in lower and lower[key] not in (None, ""):
            return str(lower[key]).strip()
    return default


def to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        s = str(value).replace(",", "").replace("%", "").strip()
        if s == "":
            return default
        return int(float(s))
    except Exception:
        return default


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        s = str(value).replace(",", "").replace("%", "").strip()
        if s == "":
            return default
        return float(s)
    except Exception:
        return default


def load_input_candidates() -> List[Dict[str, Any]]:
    if not INPUT_CSV.exists():
        raise FileNotFoundError(f"{INPUT_CSV} not found")

    rows: List[Dict[str, Any]] = []
    with INPUT_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            code = first_value(raw, "code", "종목코드", "ticker", "symbol")
            name = first_value(raw, "name", "종목명", "stockName")
            if not code or not name:
                continue

            code = code.zfill(6)
            market = first_value(raw, "market", "시장", default="KOSPI")
            sector = first_value(raw, "sector", "industry", "업종", "theme", default="종가선별")
            grade = first_value(raw, "grade", "등급", default="C")
            score = to_int(first_value(raw, "score", "totalScore", "점수", default="50"), 50)
            change_rate = first_value(raw, "changeRate", "change_rate", "등락률", default="-")

            rows.append(
                {
                    "rank": len(rows) + 1,
                    "name": name,
                    "code": code,
                    "market": market,
                    "sector": sector,
                    "industry": sector,
                    "score": score,
                    "grade": grade,
                    "changeRate": change_rate,
                    "reason": f"V306 종가 기준 선별 / 최종 {score}점({grade})",
                    "strategy": "종가 기준 후보: 다음 거래일 시가·눌림·수급 확인 후 분할 접근",
                    "entryPrice": "시가 과열 시 추격 금지, 눌림 확인",
                    "stopLoss": "전일 저점 또는 20일선 이탈",
                    "targetPrice": "분할 익절",
                    "recommendationAction": "관찰" if score >= 60 else "보류",
                    "recommendationGrade": grade,
                    "recommendationScore": score,
                    "recommendationReason": f"V306 EOD 스캐너 선별 후보 / 종가 기준 점수 {score}",
                    "hasRecommendationMeta": False,
                    "dataStatus": {
                        "finalRecommendationScore": score,
                        "recommendationAction": "관찰" if score >= 60 else "보류",
                        "technicalScore": to_int(first_value(raw, "technicalScore", "technical_score", default=str(score)), score),
                        "hasSupplyData": False,
                        "hasReportHint": False,
                        "recommendationUpdatedAt": now_kst_like(),
                    },
                }
            )

    return rows


def load_existing_candidates_by_code() -> Dict[str, Dict[str, Any]]:
    data = read_json_any(STOCK_JSON)
    if data is None:
        return {}

    if isinstance(data, dict):
        items = data.get("candidates", [])
    elif isinstance(data, list):
        items = data
    else:
        items = []

    result: Dict[str, Dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code", "")).zfill(6)
        if code:
            result[code] = item
    return result


def merge_candidates(input_rows: List[Dict[str, Any]], existing_by_code: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []

    for idx, base in enumerate(input_rows, start=1):
        code = str(base.get("code", "")).zfill(6)
        old = existing_by_code.get(code, {})

        item = dict(old)
        item.update(base)

        item["rank"] = idx
        item["code"] = code

        # Preserve enriched fields when they exist.
        for key in [
            "livePrice",
            "liveChangeRate",
            "liveVolume",
            "liveUpdatedAt",
            "liveSource",
            "liveStatus",
            "currentPriceLive",
            "realTimePrice",
            "realTimeChangeRate",
            "realTimeVolume",
            "hasLiveQuote",
            "foreign5D",
            "foreign20D",
            "foreign60D",
            "pension5D",
            "pension20D",
            "pension60D",
            "trust5D",
            "trust20D",
            "trust60D",
            "finance5D",
            "finance20D",
            "finance60D",
            "newsSignal",
            "reportSignal",
            "riskMemo",
            "supplyMemo",
            "supplyReflectionStatus",
            "recommendationMeta",
            "recommendationBreakdown",
            "recommendationVersion",
        ]:
            if key in old and old.get(key) not in (None, ""):
                item[key] = old[key]

        if old.get("recommendationReason"):
            item["recommendationReason"] = old["recommendationReason"]
        if old.get("recommendationAction"):
            item["recommendationAction"] = old["recommendationAction"]
        if old.get("recommendationScore") is not None:
            item["recommendationScore"] = old["recommendationScore"]
        if old.get("recommendationGrade"):
            item["recommendationGrade"] = old["recommendationGrade"]
        if old.get("dataStatus"):
            item["dataStatus"] = old["dataStatus"]

        merged.append(item)

    return merged


def write_stock_candidates(candidates: List[Dict[str, Any]]) -> None:
    STOCK_JSON.write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def make_text_bundle(candidates: List[Dict[str, Any]]) -> str:
    lines = [
        "V307 APP DATA BUNDLE",
        f"updatedAt: {now_kst_like()}",
        "status: ok",
        f"candidateCount: {len(candidates)}",
        f"liveQuoteCount: {sum(1 for c in candidates if c.get('hasLiveQuote'))}",
        "missingFiles: -",
        "",
        "Top Candidates:",
    ]

    for item in candidates[:20]:
        rank = item.get("rank", "-")
        name = item.get("name", "-")
        code = item.get("code", "-")
        grade = item.get("recommendationGrade") or item.get("grade", "-")
        score = item.get("recommendationScore") or item.get("score", "-")
        lines.append(f"- #{rank} {name}({code}) {grade} {score}")

    return "\n".join(lines) + "\n"


def write_app_bundle(candidates: List[Dict[str, Any]]) -> str:
    existing_text = APP_BUNDLE.read_text(encoding="utf-8", errors="ignore") if APP_BUNDLE.exists() else ""
    existing_json = read_json_any(APP_BUNDLE)

    if isinstance(existing_json, dict):
        bundle = dict(existing_json)
        bundle["version"] = "V307_APP_DATA_BUNDLE"
        bundle["updatedAt"] = now_kst_like()
        bundle["status"] = "ok"
        bundle["candidateCount"] = len(candidates)
        bundle["candidates"] = candidates

        payload = bundle.get("payload")
        if isinstance(payload, dict):
            payload["candidateCount"] = len(candidates)
            payload["candidates"] = candidates

        APP_BUNDLE.write_text(
            json.dumps(bundle, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return "json"

    # Existing bundle is text or missing. Write text bundle compatible with the current V289-style file.
    APP_BUNDLE.write_text(make_text_bundle(candidates), encoding="utf-8")
    return "text"


def main() -> None:
    try:
        input_rows = load_input_candidates()
        existing_by_code = load_existing_candidates_by_code()
        candidates = merge_candidates(input_rows, existing_by_code)

        final_count = len(candidates)
        if final_count < MIN_FINAL_COUNT:
            write_report(
                "fail",
                reason=f"finalCandidateCount too small: {final_count}",
                inputCandidateCount=len(input_rows),
                existingCandidateCount=len(existing_by_code),
                finalCandidateCount=final_count,
            )
            raise SystemExit(f"[FAIL] finalCandidateCount too small: {final_count}")

        write_stock_candidates(candidates)
        bundleFormat = write_app_bundle(candidates)

        write_report(
            "ok",
            inputCandidateCount=len(input_rows),
            existingCandidateCount=len(existing_by_code),
            finalCandidateCount=final_count,
            stockCandidatesUpdated=True,
            appBundleUpdated=True,
            appBundleFormat=bundleFormat,
            stockCandidatesPath=str(STOCK_JSON),
            appBundlePath=str(APP_BUNDLE),
        )

        print(f"[OK] {VERSION}")
        print(f"[OK] finalCandidateCount={final_count}")
        print(f"[OK] appBundleFormat={bundleFormat}")
        print(f"[OK] report={REPORT_JSON}")

    except Exception as e:
        write_report(
            "fail",
            reason=str(e),
            finalCandidateCount=0,
            stockCandidatesUpdated=False,
            appBundleUpdated=False,
        )
        raise


if __name__ == "__main__":
    main()
