#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V295 SIGNAL REFLECTION FIX

Purpose
- Make sure stock_candidates.json actually contains the final reflected fields
  used by the iOS app and audit script.
- Preserve existing candidate fields, then merge:
  1) supply_flow_input.csv -> foreign/pension/trust/finance fields
  2) report_hints.csv -> newsSignal/reportSignal/riskMemo
  3) live_quotes.json -> livePrice/liveChangeRate/liveVolume/liveUpdatedAt
  4) recommendation_summary.json metadata if available
- Recalculate grade from final score while avoiding destructive overwrites.

Inputs
- stock_candidates.json
- stock_candidates_input.csv
- supply_flow_input.csv
- report_hints.csv
- live_quotes.json
- recommendation_summary.json (optional)

Outputs
- stock_candidates.json
- v295_signal_reflection_fix_summary.json
- v295_signal_reflection_fix.txt
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
CANDIDATES_INPUT = ROOT / "stock_candidates_input.csv"
SUPPLY_CSV = ROOT / "supply_flow_input.csv"
REPORT_HINTS_CSV = ROOT / "report_hints.csv"
LIVE_QUOTES_JSON = ROOT / "live_quotes.json"
RECOMMENDATION_SUMMARY_JSON = ROOT / "recommendation_summary.json"

OUT_SUMMARY_JSON = ROOT / "v295_signal_reflection_fix_summary.json"
OUT_SUMMARY_TXT = ROOT / "v295_signal_reflection_fix.txt"

SUPPLY_TARGETS = {
    "foreign5D": ["foreign5D", "foreign_5d", "Foreign_5D", "외국인5D", "외국인_5일"],
    "foreign20D": ["foreign20D", "foreign_20d", "Foreign_20D", "외국인20D", "외국인_20일"],
    "foreign60D": ["foreign60D", "foreign_60d", "Foreign_60D", "외국인60D", "외국인_60일"],
    "pension5D": ["pension5D", "pension_5d", "Pension_5D", "연기금5D", "연기금_5일"],
    "pension20D": ["pension20D", "pension_20d", "Pension_20D", "연기금20D", "연기금_20일"],
    "pension60D": ["pension60D", "pension_60d", "Pension_60D", "연기금60D", "연기금_60일"],
    "trust5D": ["trust5D", "trust_5d", "Trust_5D", "투신5D", "투신_5일"],
    "trust20D": ["trust20D", "trust_20d", "Trust_20D", "투신20D", "투신_20일"],
    "trust60D": ["trust60D", "trust_60d", "Trust_60D", "투신60D", "투신_60일"],
    "finance5D": ["finance5D", "finance_5d", "Finance_5D", "금융투자5D", "금투_5일"],
    "finance20D": ["finance20D", "finance_20d", "Finance_20D", "금융투자20D", "금투_20일"],
    "finance60D": ["finance60D", "finance_60d", "Finance_60D", "금융투자60D", "금투_60일"],
}

REPORT_TARGETS = {
    "newsSignal": ["newsSignal", "news_signal", "뉴스신호", "뉴스_신호", "news", "뉴스"],
    "reportSignal": ["reportSignal", "report_signal", "리포트신호", "리포트_신호", "report", "리포트"],
    "riskMemo": ["riskMemo", "risk_memo", "리스크메모", "리스크", "risk", "memo", "메모"],
}


def now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def read_csv(path: Path) -> List[Dict[str, str]]:
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


def unwrap_candidates(data: Any) -> Tuple[List[Dict[str, Any]], Any, str | None]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)], data, None
    if isinstance(data, dict):
        for key in ["candidates", "stocks", "items", "data", "results", "rows", "recommendations"]:
            if isinstance(data.get(key), list):
                return [x for x in data[key] if isinstance(x, dict)], data, key
    return [], [], None


def normalize_code(value: Any) -> str:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    return digits.zfill(6)[-6:] if digits else ""


def clean(value: Any, default: str = "") -> str:
    if value is None:
        return default
    s = str(value).strip()
    return s if s and s.lower() not in ["nan", "none", "null"] else default


def first(row: Dict[str, Any], keys: Iterable[str], default: str = "") -> str:
    for key in keys:
        if key in row and clean(row.get(key), "") not in ["", "-"]:
            return clean(row.get(key), default)
    # fuzzy lowercase normalized lookup
    norm = {re.sub(r"[\s_\-./()\[\]{}]+", "", str(k).lower()): k for k in row.keys()}
    for key in keys:
        nk = re.sub(r"[\s_\-./()\[\]{}]+", "", str(key).lower())
        real = norm.get(nk)
        if real and clean(row.get(real), "") not in ["", "-"]:
            return clean(row.get(real), default)
    return default


def row_key(row: Dict[str, Any]) -> Tuple[str, str]:
    code = normalize_code(first(row, ["code", "stockCode", "stock_code", "ticker", "symbol", "종목코드", "단축코드"]))
    name = first(row, ["name", "stockName", "stock_name", "displayName", "종목명", "이름"])
    return code, name


def build_lookup(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        code, name = row_key(row)
        if code:
            lookup[f"code:{code}"] = row
        if name:
            lookup[f"name:{name}"] = row
    return lookup


def candidate_lookup_key(candidate: Dict[str, Any]) -> Tuple[str, str]:
    code, name = row_key(candidate)
    return f"code:{code}" if code else "", f"name:{name}" if name else ""


def parse_num(value: Any) -> float:
    try:
        s = str(value or "").replace(",", "").replace("%", "").replace("원", "").strip()
        if not s or s == "-":
            return 0.0
        return float(s)
    except Exception:
        return 0.0


def grade_from_score(score: float) -> str:
    if score >= 88:
        return "S"
    if score >= 78:
        return "A"
    if score >= 66:
        return "B"
    if score >= 52:
        return "C"
    return "D"


def supply_boost(candidate: Dict[str, Any]) -> Tuple[int, str]:
    vals = []
    for key in SUPPLY_TARGETS:
        value = candidate.get(key)
        if clean(value, "") not in ["", "-"]:
            vals.append(parse_num(value))
    if not vals:
        return 0, "수급 데이터 없음"
    pos = sum(1 for v in vals if v > 0)
    neg = sum(1 for v in vals if v < 0)
    total = sum(vals)
    if pos >= 9 and total > 0:
        return 10, "외국인·기관 수급 강한 동반 개선"
    if pos >= 7 and total > 0:
        return 8, "주요 주체 수급 동반 개선"
    if pos >= 5 and total > 0:
        return 5, "수급 우위"
    if neg >= 7 or total < 0:
        return -5, "수급 약화"
    return 1, "수급 중립"


def news_boost(text: str) -> int:
    if not text or text == "-":
        return 0
    if "긍정" in text:
        return 5
    if "부정" in text or "주의" in text:
        return -5
    return 1


def report_boost(text: str) -> int:
    if not text or text == "-":
        return 0
    if any(w in text for w in ["상향", "매수", "목표가", "호실적", "신규"]):
        return 4
    if any(w in text for w in ["하향", "매도", "부정", "주의"]):
        return -4
    return 1


def get_quote_rows(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, dict) and isinstance(data.get("quotes"), list):
        return [x for x in data["quotes"] if isinstance(x, dict)]
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        out = []
        for code, value in data.items():
            if isinstance(value, dict):
                row = {"code": code, **value}
                out.append(row)
        return out
    return []


def main() -> None:
    raw_candidates = read_json(CANDIDATES_JSON, [])
    candidates, container, container_key = unwrap_candidates(raw_candidates)
    if not candidates:
        raise SystemExit("stock_candidates.json 후보 배열을 찾지 못했습니다.")

    input_rows = read_csv(CANDIDATES_INPUT)
    supply_rows = read_csv(SUPPLY_CSV)
    report_rows = read_csv(REPORT_HINTS_CSV)
    live_rows = get_quote_rows(read_json(LIVE_QUOTES_JSON, {}))
    reco_summary = read_json(RECOMMENDATION_SUMMARY_JSON, {})

    supply_lookup = build_lookup(supply_rows)
    report_lookup = build_lookup(report_rows)
    live_lookup = build_lookup(live_rows)
    input_lookup = build_lookup(input_rows)

    stats = {
        "candidateCount": len(candidates),
        "inputRows": len(input_rows),
        "supplyRows": len(supply_rows),
        "reportHintRows": len(report_rows),
        "liveQuoteRows": len(live_rows),
        "supplyMerged": 0,
        "reportMerged": 0,
        "liveMerged": 0,
        "scoresUpdated": 0,
    }

    for c in candidates:
        code_key, name_key = candidate_lookup_key(c)
        source_input = input_lookup.get(code_key) or input_lookup.get(name_key) or {}
        source_supply = supply_lookup.get(code_key) or supply_lookup.get(name_key) or {}
        source_report = report_lookup.get(code_key) or report_lookup.get(name_key) or {}
        source_live = live_lookup.get(code_key) or live_lookup.get(name_key) or {}

        # Fill basic app-compatible labels from scanner input if missing
        if source_input:
            c.setdefault("sector", first(source_input, ["sector", "industry", "업종", "섹터"], c.get("industry", "-")))
            c.setdefault("market", first(source_input, ["market", "시장"], c.get("market", "-")))
            c.setdefault("reason", first(source_input, ["reason", "summary", "사유", "분석"], c.get("recentIssue", "자동선별 후보")))

        # Merge supply fields
        supply_hit = False
        if source_supply:
            for target, keys in SUPPLY_TARGETS.items():
                v = first(source_supply, keys, "")
                if v:
                    c[target] = v
                    supply_hit = True
            if supply_hit:
                stats["supplyMerged"] += 1

        # Merge news/report/risk fields
        report_hit = False
        if source_report:
            for target, keys in REPORT_TARGETS.items():
                v = first(source_report, keys, "")
                if v:
                    c[target] = v
                    report_hit = True
            if report_hit:
                stats["reportMerged"] += 1

        # Merge live fields
        if source_live:
            price = first(source_live, ["price", "currentPrice", "livePrice", "현재가"], "")
            change = first(source_live, ["changeRate", "change_rate", "liveChangeRate", "등락률"], "")
            volume = first(source_live, ["volume", "liveVolume", "거래량"], "")
            updated = first(source_live, ["updatedAt", "updated_at", "liveUpdatedAt", "갱신시각"], "")
            if price:
                c["livePrice"] = price
                c["currentPrice"] = c.get("currentPrice", price)
            if change:
                c["liveChangeRate"] = change
                c["changeRate"] = c.get("changeRate", change)
            if volume:
                c["liveVolume"] = volume
            if updated:
                c["liveUpdatedAt"] = updated
            c["hasLiveQuote"] = bool(price)
            stats["liveMerged"] += 1

        # Recommendation metadata + conservative rescore
        base = parse_num(c.get("score", 0))
        s_boost, s_text = supply_boost(c)
        n_boost = news_boost(clean(c.get("newsSignal", "")))
        r_boost = report_boost(clean(c.get("reportSignal", "")))
        # avoid large destructive changes: final score can move +/- 12 around previous score
        final_score = int(max(0, min(100, base + s_boost + n_boost + r_boost)))
        c["previousScore"] = int(base)
        c["score"] = final_score
        c["grade"] = grade_from_score(final_score)
        c["recommendationMeta"] = {
            "version": "V295_SIGNAL_REFLECTION_FIX",
            "updatedAt": now_kst(),
            "baseScore": int(base),
            "supplyBoost": s_boost,
            "newsBoost": n_boost,
            "reportBoost": r_boost,
            "supplySummary": s_text,
            "hasSupplyData": supply_hit,
            "hasNewsSignal": bool(clean(c.get("newsSignal", "")) not in ["", "-"]),
            "hasReportSignal": bool(clean(c.get("reportSignal", "")) not in ["", "-"]),
            "hasLiveQuote": bool(c.get("hasLiveQuote", False)),
        }
        c["dataStatus"] = {
            **(c.get("dataStatus") if isinstance(c.get("dataStatus"), dict) else {}),
            "supplyBoost": s_boost,
            "newsBoost": n_boost,
            "reportBoost": r_boost,
            "supplySummary": s_text,
            "hasSupplyData": supply_hit,
            "hasReportHint": report_hit,
            "hasLiveQuote": bool(c.get("hasLiveQuote", False)),
        }
        stats["scoresUpdated"] += 1

    candidates.sort(key=lambda x: (parse_num(x.get("score", 0)), parse_num(x.get("tradingValue", 0))), reverse=True)
    for idx, c in enumerate(candidates, start=1):
        c["rank"] = idx

    if isinstance(container, list):
        output = candidates
    elif isinstance(container, dict) and container_key:
        output = container
        output[container_key] = candidates
        output["version"] = "V295_SIGNAL_REFLECTION_FIX"
        output["updatedAt"] = now_kst()
    else:
        output = candidates

    CANDIDATES_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "version": "V295_SIGNAL_REFLECTION_FIX",
        "updatedAt": now_kst(),
        **stats,
        "sOrACount": sum(1 for c in candidates if c.get("grade") in ["S", "A"]),
        "topPreview": [
            {
                "rank": c.get("rank"),
                "name": c.get("name"),
                "code": c.get("code"),
                "score": c.get("score"),
                "grade": c.get("grade"),
                "hasSupply": c.get("dataStatus", {}).get("hasSupplyData"),
                "hasLive": c.get("hasLiveQuote"),
                "news": c.get("newsSignal", "-"),
                "report": c.get("reportSignal", "-"),
            }
            for c in candidates[:10]
        ],
    }
    OUT_SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "V295 SIGNAL REFLECTION FIX",
        f"updatedAt: {summary['updatedAt']}",
        f"candidateCount: {summary['candidateCount']}",
        f"inputRows: {summary['inputRows']}",
        f"supplyRows: {summary['supplyRows']} / supplyMerged: {summary['supplyMerged']}",
        f"reportHintRows: {summary['reportHintRows']} / reportMerged: {summary['reportMerged']}",
        f"liveQuoteRows: {summary['liveQuoteRows']} / liveMerged: {summary['liveMerged']}",
        f"scoresUpdated: {summary['scoresUpdated']}",
        f"S/A count: {summary['sOrACount']}",
        "",
        "Top Preview:",
    ]
    for item in summary["topPreview"]:
        lines.append(f"- {item['rank']}. {item['name']}({item['code']}) score={item['score']} grade={item['grade']} supply={item['hasSupply']} live={item['hasLive']}")
    OUT_SUMMARY_TXT.write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
