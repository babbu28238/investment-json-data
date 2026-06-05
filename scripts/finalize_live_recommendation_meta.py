#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V299 LIVE + RECOMMENDATION META FIX

Purpose
- Preserve the successful V298 supply fields.
- Merge live_quotes.json back into stock_candidates.json.
- Add stable recommendation metadata fields for the iOS app and audits.
- Rebuild app_data_bundle.json if the bundle builder is not present.

Inputs
- stock_candidates.json
- live_quotes.json
- recommendation_summary.json optional
- supply_flow_input.csv optional

Outputs
- stock_candidates.json
- v299_live_recommendation_meta_fix.json
- v299_live_recommendation_meta_fix.txt
"""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()

CANDIDATES_JSON = ROOT / "stock_candidates.json"
LIVE_QUOTES_JSON = ROOT / "live_quotes.json"
SUPPLY_CSV = ROOT / "supply_flow_input.csv"
RECOMMENDATION_SUMMARY_JSON = ROOT / "recommendation_summary.json"
APP_DATA_BUNDLE_JSON = ROOT / "app_data_bundle.json"
OUT_JSON = ROOT / "v299_live_recommendation_meta_fix.json"
OUT_TXT = ROOT / "v299_live_recommendation_meta_fix.txt"


def now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")


def normalize_code(value: Any) -> str:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    return digits.zfill(6)[-6:] if digits else ""


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def unwrap_candidates(data: Any) -> Tuple[List[Dict[str, Any]], str | None, Any]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)], None, data
    if isinstance(data, dict):
        for key in ["candidates", "items", "data", "results", "stocks", "rows", "recommendations"]:
            if isinstance(data.get(key), list):
                return [x for x in data[key] if isinstance(x, dict)], key, data
    return [], None, data


def get_first(item: Dict[str, Any], keys: Iterable[str], default: str = "") -> str:
    for key in keys:
        value = item.get(key)
        if value not in (None, "", "-", "null", "None"):
            return str(value).strip()
    return default


def load_live_lookup() -> Dict[str, Dict[str, Any]]:
    raw = read_json(LIVE_QUOTES_JSON, {})
    if isinstance(raw, dict):
        rows = raw.get("quotes") or raw.get("items") or raw.get("data") or raw.get("results") or []
    elif isinstance(raw, list):
        rows = raw
    else:
        rows = []
    lookup: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = normalize_code(get_first(row, ["code", "stockCode", "stock_code", "ticker", "symbol", "종목코드"]))
        if code:
            lookup[code] = row
    return lookup


def read_csv_lookup(path: Path) -> Dict[str, Dict[str, str]]:
    if not path.exists():
        return {}
    rows: List[Dict[str, str]] = []
    for enc in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
        try:
            with path.open("r", encoding=enc, newline="") as f:
                rows = list(csv.DictReader(f))
            break
        except UnicodeDecodeError:
            continue
        except Exception:
            return {}
    lookup: Dict[str, Dict[str, str]] = {}
    for row in rows:
        code = normalize_code(get_first(row, ["code", "종목코드", "Code", "stockCode", "ticker", "symbol"]))
        if code:
            lookup[code] = row
    return lookup


def merge_live(candidate: Dict[str, Any], quote: Dict[str, Any]) -> bool:
    if not quote:
        return False
    price = get_first(quote, ["price", "currentPrice", "현재가"], "-")
    change_rate = get_first(quote, ["changeRate", "change_rate", "등락률"], "-")
    volume = get_first(quote, ["volume", "거래량"], "-")
    updated_at = get_first(quote, ["updatedAt", "updated_at", "갱신시각"], "-")
    source = get_first(quote, ["source"], "live_quotes")
    status = get_first(quote, ["status"], "ok")

    candidate["livePrice"] = price
    candidate["liveChangeRate"] = change_rate
    candidate["liveVolume"] = volume
    candidate["liveUpdatedAt"] = updated_at
    candidate["liveSource"] = source
    candidate["liveStatus"] = status

    # Keep legacy/common aliases for older Swift models and audits.
    candidate["currentPriceLive"] = price
    candidate["realTimePrice"] = price
    candidate["realTimeChangeRate"] = change_rate
    candidate["realTimeVolume"] = volume
    candidate["hasLiveQuote"] = bool(price and price != "-")
    return bool(price and price != "-")


def merge_supply_aliases(candidate: Dict[str, Any], supply: Dict[str, str]) -> bool:
    if not supply:
        return False
    changed = False
    for key in [
        "foreign5D", "foreign20D", "foreign60D",
        "pension5D", "pension20D", "pension60D",
        "trust5D", "trust20D", "trust60D",
        "finance5D", "finance20D", "finance60D",
        "supplyMemo",
    ]:
        value = supply.get(key)
        if value not in (None, "", "-"):
            candidate[key] = value
            changed = True
    if changed:
        candidate["supplyReflectionStatus"] = "reflected"
    return changed


def numeric(value: Any, default: float = 0.0) -> float:
    try:
        s = str(value or "").replace(",", "").replace("%", "").strip()
        if s in ("", "-", "None", "null"):
            return default
        return float(s)
    except Exception:
        return default


def grade_from_score(score: float) -> str:
    if score >= 88:
        return "S"
    if score >= 78:
        return "A"
    if score >= 66:
        return "B"
    if score >= 55:
        return "C"
    return "D"


def action_label(score: float, grade: str, candidate: Dict[str, Any]) -> str:
    foreign20 = numeric(candidate.get("foreign20D"))
    finance20 = numeric(candidate.get("finance20D"))
    has_positive_supply = foreign20 > 0 or finance20 > 0
    if score >= 82 and has_positive_supply:
        return "우선검토"
    if score >= 70:
        return "조건확인"
    if score >= 60:
        return "관찰"
    return "보류"


def add_recommendation_meta(candidate: Dict[str, Any], rank: int) -> None:
    score = numeric(candidate.get("score"), 0)
    grade = str(candidate.get("grade") or grade_from_score(score))
    if grade in ("", "-", "None"):
        grade = grade_from_score(score)
    candidate["grade"] = grade
    candidate["rank"] = rank
    candidate["recommendationMeta"] = {
        "version": "V299_LIVE_RECOMMENDATION_META_FIX",
        "rank": rank,
        "score": int(round(score)),
        "grade": grade,
        "action": action_label(score, grade, candidate),
        "basis": [
            "technical_score",
            "news_signal",
            "report_signal",
            "supply_flow",
            "live_quote",
        ],
        "updatedAt": now_kst(),
    }
    candidate["recommendationAction"] = candidate["recommendationMeta"]["action"]
    candidate["recommendationGrade"] = grade
    candidate["recommendationScore"] = int(round(score))
    candidate["recommendationReason"] = build_reason(candidate)
    candidate["hasRecommendationMeta"] = True


def build_reason(candidate: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key in ["newsSignal", "reportSignal", "supplyMemo"]:
        value = str(candidate.get(key) or "").strip()
        if value and value != "-":
            parts.append(value)
    live = str(candidate.get("livePrice") or "").strip()
    if live and live != "-":
        parts.append(f"현재가 {live} 반영")
    if not parts:
        parts.append("기술·거래대금 기반 자동선별")
    return " / ".join(parts[:4])


def rebuild_app_bundle(candidates: List[Dict[str, Any]], summary: Dict[str, Any]) -> None:
    existing = read_json(APP_DATA_BUNDLE_JSON, {})
    if not isinstance(existing, dict):
        existing = {}
    existing["version"] = "V299_APP_DATA_BUNDLE_REFRESH"
    existing["updatedAt"] = now_kst()
    existing["stockCandidates"] = candidates
    existing["candidates"] = candidates
    existing["v299Fix"] = summary
    write_json(APP_DATA_BUNDLE_JSON, existing)


def main() -> None:
    raw = read_json(CANDIDATES_JSON, [])
    candidates, container_key, container = unwrap_candidates(raw)
    live_lookup = load_live_lookup()
    supply_lookup = read_csv_lookup(SUPPLY_CSV)

    live_merged = 0
    supply_merged = 0
    meta_added = 0

    # Stable ranking by current score descending before adding rank.
    candidates.sort(key=lambda x: numeric(x.get("score"), 0), reverse=True)

    for idx, candidate in enumerate(candidates, start=1):
        code = normalize_code(get_first(candidate, ["code", "stockCode", "stock_code", "ticker", "symbol", "종목코드"]))
        if code:
            if merge_live(candidate, live_lookup.get(code, {})):
                live_merged += 1
            if merge_supply_aliases(candidate, supply_lookup.get(code, {})):
                supply_merged += 1
        add_recommendation_meta(candidate, idx)
        meta_added += 1

    if isinstance(raw, list):
        output: Any = candidates
    elif isinstance(container, dict) and container_key:
        container[container_key] = candidates
        container["version"] = "V299_LIVE_RECOMMENDATION_META_FIX"
        container["updatedAt"] = now_kst()
        output = container
    else:
        output = candidates

    write_json(CANDIDATES_JSON, output)

    summary = {
        "version": "V299_LIVE_RECOMMENDATION_META_FIX",
        "updatedAt": now_kst(),
        "candidateCount": len(candidates),
        "liveQuotesAvailable": len(live_lookup),
        "supplyRowsAvailable": len(supply_lookup),
        "liveMerged": live_merged,
        "supplyMerged": supply_merged,
        "recommendationMetaAdded": meta_added,
        "topPreview": [
            {
                "rank": c.get("rank"),
                "code": c.get("code"),
                "name": c.get("name"),
                "score": c.get("score"),
                "grade": c.get("grade"),
                "livePrice": c.get("livePrice"),
                "foreign20D": c.get("foreign20D"),
                "finance20D": c.get("finance20D"),
                "action": c.get("recommendationAction"),
            }
            for c in candidates[:10]
        ],
    }
    write_json(OUT_JSON, summary)
    rebuild_app_bundle(candidates, summary)

    lines = [
        "V299 LIVE + RECOMMENDATION META FIX",
        f"updatedAt: {summary['updatedAt']}",
        f"candidateCount: {summary['candidateCount']}",
        f"liveQuotesAvailable: {summary['liveQuotesAvailable']}",
        f"supplyRowsAvailable: {summary['supplyRowsAvailable']}",
        f"liveMerged: {summary['liveMerged']}",
        f"supplyMerged: {summary['supplyMerged']}",
        f"recommendationMetaAdded: {summary['recommendationMetaAdded']}",
        "",
        "Top Preview:",
    ]
    for item in summary["topPreview"]:
        lines.append(f"- {item['rank']}. {item['name']}({item['code']}) score={item['score']} grade={item['grade']} live={item['livePrice']} action={item['action']}")
    OUT_TXT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
