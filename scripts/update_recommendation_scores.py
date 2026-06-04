#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V284 RECOMMENDATION SCORE ENGINE

목적:
- V279 시장 스캐너, V280 뉴스, V282 수급, V283 리포트 신호를 하나의 최종 추천 점수로 통합
- stock_candidates.json의 score/grade/rank/reason/strategy/dataStatus를 최종 추천 기준으로 재정렬
- 앱 기존 구조를 깨지 않고 기존 필드는 최대한 유지

입력:
- stock_candidates.json
- news_signals.json (있으면 반영)
- report_signals.json (있으면 반영)
- supply_flow_input.csv (있으면 보조 반영)

출력:
- stock_candidates.json
- recommendation_summary.json
- recommendation_log.txt
- app_data_status.json 보강
"""

from __future__ import annotations

import csv
import json
import math
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()

CANDIDATES_JSON = ROOT / "stock_candidates.json"
NEWS_JSON = ROOT / "news_signals.json"
REPORT_JSON = ROOT / "report_signals.json"
SUPPLY_CSV = ROOT / "supply_flow_input.csv"
APP_STATUS_JSON = ROOT / "app_data_status.json"
SUMMARY_JSON = ROOT / "recommendation_summary.json"
LOG_TXT = ROOT / "recommendation_log.txt"

FINAL_TOP_N = 50

# 점수 가중치. 총합 100.
WEIGHTS = {
    "technical": 35,
    "supply": 25,
    "news": 15,
    "report": 15,
    "liquidity": 10,
}


def now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def normalize_code(value: Any) -> str:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    return digits.zfill(6)[-6:] if digits else ""


def clean_text(value: Any, default: str = "-") -> str:
    if value is None:
        return default
    s = str(value).strip()
    return s if s else default


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        s = str(value).replace(",", "").replace("%", "").replace("원", "").replace("주", "").strip()
        if s in ["", "-", "None", "nan", "NaN", "null"]:
            return default
        return float(s)
    except Exception:
        return default


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def first(row: Dict[str, Any], keys: Iterable[str], default: str = "") -> str:
    lowered = {str(k).lower(): k for k in row.keys()}
    for key in keys:
        if key in row and clean_text(row.get(key), ""):
            return clean_text(row.get(key), default)
        lk = key.lower()
        if lk in lowered and clean_text(row.get(lowered[lk]), ""):
            return clean_text(row.get(lowered[lk]), default)
    return default


def read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def unwrap_candidates(data: Any) -> Tuple[List[Dict[str, Any]], str | None, Any]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)], None, data
    if isinstance(data, dict):
        for key in ["candidates", "items", "data", "results", "stocks", "rows", "recommendations"]:
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)], key, data
    return [], None, data


def read_csv_rows(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    for enc in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
        except Exception:
            continue
    return []


def build_signal_lookup(path: Path, score_key: str) -> Dict[str, Dict[str, Any]]:
    data = read_json(path)
    if not isinstance(data, dict):
        return {}
    signals = data.get("signals")
    if not isinstance(signals, list):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for item in signals:
        if not isinstance(item, dict):
            continue
        code = normalize_code(item.get("code"))
        name = clean_text(item.get("name"), "")
        if code:
            out[code] = item
        if name:
            out[f"name:{name}"] = item
    return out


def build_supply_lookup() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in read_csv_rows(SUPPLY_CSV):
        code = normalize_code(row.get("code") or row.get("종목코드"))
        name = clean_text(row.get("name") or row.get("종목명"), "")
        if code:
            out[code] = row
        if name:
            out[f"name:{name}"] = row
    return out


def supply_score_from_values(candidate: Dict[str, Any], supply_row: Dict[str, Any] | None) -> Tuple[int, str]:
    values: List[float] = []
    fields = [
        "foreign5D", "foreign20D", "foreign60D",
        "pension5D", "pension20D", "pension60D",
        "trust5D", "trust20D", "trust60D",
        "finance5D", "finance20D", "finance60D",
    ]

    for field in fields:
        raw = None
        if supply_row and field in supply_row:
            raw = supply_row.get(field)
        elif field in candidate:
            raw = candidate.get(field)
        if raw not in [None, "", "-"]:
            values.append(to_float(raw, 0.0))

    data_status = candidate.get("dataStatus") if isinstance(candidate.get("dataStatus"), dict) else {}
    supply_boost = to_float(data_status.get("supplyBoost"), 0.0)
    supply_summary = clean_text(data_status.get("supplySummary"), "")

    if not values and supply_boost:
        score = int(clamp(50 + supply_boost * 4))
        return score, supply_summary or "수급 보정점수 반영"

    if not values:
        return 50, "수급 데이터 부족"

    pos = sum(1 for v in values if v > 0)
    neg = sum(1 for v in values if v < 0)
    total = sum(values)

    score = 50
    score += min(28, pos * 3)
    score -= min(24, neg * 3)

    if total > 0:
        score += min(12, math.log10(abs(total) + 1) * 2)
    elif total < 0:
        score -= min(12, math.log10(abs(total) + 1) * 2)

    score = int(clamp(score))
    if score >= 75:
        memo = "외국인·기관 수급 우위"
    elif score <= 38:
        memo = "외국인·기관 수급 약화"
    else:
        memo = "수급 중립/혼조"
    return score, memo


def technical_score(candidate: Dict[str, Any]) -> int:
    # generate_stock_candidates.py가 technicalScore를 제공하면 우선 사용한다.
    if "technicalScore" in candidate:
        return int(clamp(to_float(candidate.get("technicalScore"), 50.0)))

    base = to_float(candidate.get("score"), 70.0)
    score = 45 + (base - 70) * 0.6

    weekly = str(candidate.get("weeklyCloud") or candidate.get("weekly_cloud") or candidate.get("weeklyCloudBreakout") or "")
    daily = str(candidate.get("dailySignal") or candidate.get("daily_signal") or candidate.get("dailyCloudBreakout") or "")
    rsi_text = str(candidate.get("rsi") or "")
    macd = str(candidate.get("macd") or "")
    volume = str(candidate.get("volumeSignal") or candidate.get("volume_signal") or "")

    positive_words = ["돌파", "상단", "지지", "회복", "상승", "개선", "우수", "True", "true"]
    negative_words = ["이탈", "하락", "약화", "과열", "주의", "둔화"]

    joined = " ".join([weekly, daily, rsi_text, macd, volume])
    score += sum(5 for w in positive_words if w in joined)
    score -= sum(5 for w in negative_words if w in joined)

    rsi_value = to_float(rsi_text, -1)
    if 45 <= rsi_value <= 70:
        score += 6
    elif rsi_value >= 78:
        score -= 8

    return int(clamp(score))


def liquidity_score(candidate: Dict[str, Any]) -> int:
    trading_value = to_float(candidate.get("tradingValue") or candidate.get("거래대금"), 0.0)
    market_cap = to_float(candidate.get("marketCap") or candidate.get("시가총액"), 0.0)
    score = 45
    if trading_value >= 100_000_000_000:
        score += 30
    elif trading_value >= 50_000_000_000:
        score += 24
    elif trading_value >= 20_000_000_000:
        score += 16
    elif trading_value >= 10_000_000_000:
        score += 8
    elif trading_value > 0:
        score += 2

    if market_cap >= 10_000_000_000_000:
        score += 8
    elif market_cap >= 1_000_000_000_000:
        score += 5
    elif market_cap >= 100_000_000_000:
        score += 2
    return int(clamp(score))


def grade_from_score(score: int) -> str:
    if score >= 90:
        return "S"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B"
    if score >= 60:
        return "C"
    return "D"


def action_label(score: int, news_score: int, supply_score: int, report_score: int) -> str:
    if score >= 88 and supply_score >= 65 and news_score >= 50 and report_score >= 45:
        return "즉시확인"
    if score >= 80:
        return "진입대기"
    if score >= 70:
        return "관찰상위"
    if score >= 60:
        return "관찰"
    return "제외검토"


def price_guides(candidate: Dict[str, Any]) -> Tuple[str, str, str]:
    price = to_float(candidate.get("currentPrice") or candidate.get("livePrice"), 0.0)
    if price <= 0:
        return (
            clean_text(candidate.get("entryPrice"), "조건 확인"),
            clean_text(candidate.get("stopLoss"), "기준 확인"),
            clean_text(candidate.get("targetPrice"), "분할 익절"),
        )
    entry_low = int(round(price * 0.985))
    entry_high = int(round(price * 1.005))
    stop = int(round(price * 0.94))
    target = int(round(price * 1.10))
    return f"{entry_low:,}~{entry_high:,}", f"{stop:,}", f"{target:,}"


def enrich_candidate(candidate: Dict[str, Any], idx: int, news_lookup: Dict[str, Dict[str, Any]], report_lookup: Dict[str, Dict[str, Any]], supply_lookup: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    code = normalize_code(candidate.get("code") or candidate.get("ticker") or candidate.get("symbol"))
    name = clean_text(candidate.get("name") or candidate.get("stockName") or candidate.get("종목명"), code or f"후보{idx}")
    key_name = f"name:{name}"

    news = news_lookup.get(code) or news_lookup.get(key_name) or {}
    report = report_lookup.get(code) or report_lookup.get(key_name) or {}
    supply = supply_lookup.get(code) or supply_lookup.get(key_name)

    t_score = technical_score(candidate)
    s_score, s_memo = supply_score_from_values(candidate, supply)
    n_score = int(clamp(to_float(news.get("newsScore"), 50.0)))
    r_score = int(clamp(to_float(report.get("reportScore"), 50.0)))
    l_score = liquidity_score(candidate)

    final = int(round(
        t_score * WEIGHTS["technical"] / 100 +
        s_score * WEIGHTS["supply"] / 100 +
        n_score * WEIGHTS["news"] / 100 +
        r_score * WEIGHTS["report"] / 100 +
        l_score * WEIGHTS["liquidity"] / 100
    ))
    final = int(clamp(final))
    grade = grade_from_score(final)
    label = action_label(final, n_score, s_score, r_score)

    news_signal = clean_text(news.get("newsSignal"), clean_text(candidate.get("newsSignal"), "뉴스 확인 필요"))
    report_signal = clean_text(report.get("reportSignal"), clean_text(candidate.get("reportSignal"), "리포트 확인 필요"))
    risk_parts = []
    for item in [candidate.get("riskMemo"), news.get("riskMemo"), report.get("reportRiskMemo")]:
        text = clean_text(item, "")
        if text and text != "-" and text not in risk_parts:
            risk_parts.append(text)
    risk_memo = " / ".join(risk_parts) if risk_parts else "뉴스·수급·리포트 리스크 동시 확인"

    reason = (
        f"{label} / 최종 {final}점({grade}) / "
        f"기술 {t_score}·수급 {s_score}·뉴스 {n_score}·리포트 {r_score}·유동성 {l_score}"
    )

    entry, stop, target = price_guides(candidate)

    out = dict(candidate)
    out.update({
        "name": name,
        "code": code or clean_text(candidate.get("code"), "-"),
        "score": final,
        "grade": grade,
        "reason": reason,
        "strategy": f"{label}: 수급·뉴스·리포트 확인 후 분할 접근",
        "entryPrice": entry,
        "stopLoss": stop,
        "targetPrice": target,
        "newsSignal": news_signal,
        "reportSignal": report_signal,
        "riskMemo": risk_memo,
        "recommendationAction": label,
        "recommendationVersion": "V284_RECOMMENDATION_SCORE_ENGINE",
        "recommendationBreakdown": {
            "technicalScore": t_score,
            "supplyScore": s_score,
            "newsScore": n_score,
            "reportScore": r_score,
            "liquidityScore": l_score,
            "weights": WEIGHTS,
            "supplyMemo": s_memo,
        },
        "dataStatus": {
            **(candidate.get("dataStatus") if isinstance(candidate.get("dataStatus"), dict) else {}),
            "finalRecommendationScore": final,
            "recommendationAction": label,
            "technicalScore": t_score,
            "supplyScore": s_score,
            "newsScore": n_score,
            "reportScore": r_score,
            "liquidityScore": l_score,
            "recommendationUpdatedAt": now_kst(),
        }
    })
    return out


def main() -> None:
    started = now_kst()
    raw = read_json(CANDIDATES_JSON)
    candidates, container_key, container = unwrap_candidates(raw)
    if not candidates:
        raise SystemExit("stock_candidates.json 후보 배열을 찾지 못했습니다. V224 mapper를 먼저 실행하세요.")

    news_lookup = build_signal_lookup(NEWS_JSON, "newsScore")
    report_lookup = build_signal_lookup(REPORT_JSON, "reportScore")
    supply_lookup = build_supply_lookup()

    enriched = [enrich_candidate(c, i, news_lookup, report_lookup, supply_lookup) for i, c in enumerate(candidates, start=1)]
    enriched.sort(key=lambda x: (int(x.get("score", 0)), x.get("recommendationAction") == "즉시확인"), reverse=True)
    enriched = enriched[:FINAL_TOP_N]
    for rank, item in enumerate(enriched, start=1):
        item["rank"] = rank

    if isinstance(raw, list):
        output: Any = enriched
    elif isinstance(container, dict) and container_key:
        output = dict(container)
        output[container_key] = enriched
        output["version"] = "V284_RECOMMENDATION_SCORE_ENGINE"
        output["updatedAt"] = now_kst()
    else:
        output = enriched

    CANDIDATES_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    grade_counts: Dict[str, int] = {}
    action_counts: Dict[str, int] = {}
    sector_counts: Dict[str, int] = {}
    for item in enriched:
        grade_counts[item.get("grade", "-")] = grade_counts.get(item.get("grade", "-"), 0) + 1
        action_counts[item.get("recommendationAction", "-")] = action_counts.get(item.get("recommendationAction", "-"), 0) + 1
        sector = clean_text(item.get("sector") or item.get("industry"), "-")
        sector_counts[sector] = sector_counts.get(sector, 0) + 1

    summary = {
        "version": "V284_RECOMMENDATION_SCORE_ENGINE",
        "updatedAt": now_kst(),
        "startedAt": started,
        "inputCandidateCount": len(candidates),
        "finalCandidateCount": len(enriched),
        "newsSignalCount": len([k for k in news_lookup if not k.startswith("name:")]),
        "reportSignalCount": len([k for k in report_lookup if not k.startswith("name:")]),
        "supplyRowCount": len([k for k in supply_lookup if not k.startswith("name:")]),
        "gradeCounts": grade_counts,
        "actionCounts": action_counts,
        "sectorCounts": sector_counts,
        "topCandidates": [
            {
                "rank": x.get("rank"),
                "name": x.get("name"),
                "code": x.get("code"),
                "score": x.get("score"),
                "grade": x.get("grade"),
                "action": x.get("recommendationAction"),
                "breakdown": x.get("recommendationBreakdown"),
            }
            for x in enriched[:10]
        ],
    }
    SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "V284 RECOMMENDATION SCORE ENGINE",
        f"startedAt: {started}",
        f"updatedAt: {summary['updatedAt']}",
        f"inputCandidateCount: {summary['inputCandidateCount']}",
        f"finalCandidateCount: {summary['finalCandidateCount']}",
        f"newsSignalCount: {summary['newsSignalCount']}",
        f"reportSignalCount: {summary['reportSignalCount']}",
        f"supplyRowCount: {summary['supplyRowCount']}",
        f"gradeCounts: {grade_counts}",
        f"actionCounts: {action_counts}",
        "",
        "TOP 10:",
    ]
    for x in enriched[:10]:
        lines.append(f"{x.get('rank')}. {x.get('name')}({x.get('code')}) {x.get('grade')} {x.get('score')} {x.get('recommendationAction')}")
    LOG_TXT.write_text("\n".join(lines), encoding="utf-8")

    app_status: Dict[str, Any] = {}
    if APP_STATUS_JSON.exists():
        try:
            existing = json.loads(APP_STATUS_JSON.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                app_status.update(existing)
        except Exception:
            pass
    app_status.update({
        "version": "V284_RECOMMENDATION_SCORE_ENGINE",
        "status": "ok",
        "updatedAt": summary["updatedAt"],
        "candidateCount": len(enriched),
        "sGradeCount": grade_counts.get("S", 0),
        "aGradeCount": grade_counts.get("A", 0),
        "message": "V284 최종 추천 점수 엔진 반영 완료",
        "recommendationSummary": {
            "actionCounts": action_counts,
            "gradeCounts": grade_counts,
            "topCandidates": summary["topCandidates"][:5],
        },
    })
    APP_STATUS_JSON.write_text(json.dumps(app_status, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
