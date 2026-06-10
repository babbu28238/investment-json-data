#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V940 HANSU Evidence Engine
- Reads V930 outputs and builds human-readable evidence reports per stock.
- Inputs expected at repository root:
  hansu_ai_score_fusion.json
  stock_candidates_ai_scored.json
- Outputs:
  hansu_evidence_v940.json
  hansu_evidence_v940_summary.json
  stock_candidates_ai_evidence.json
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

KST = timezone(timedelta(hours=9))
ROOT = Path.cwd()

FUSION_PATH = ROOT / "hansu_ai_score_fusion.json"
SCORED_PATH = ROOT / "stock_candidates_ai_scored.json"

OUT_EVIDENCE = ROOT / "hansu_evidence_v940.json"
OUT_SUMMARY = ROOT / "hansu_evidence_v940_summary.json"
OUT_CANDIDATES = ROOT / "stock_candidates_ai_evidence.json"


def now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def as_num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "-":
            return default
        if isinstance(value, str):
            value = value.replace(",", "").replace("%", "").strip()
        return float(value)
    except Exception:
        return default


def grade_label(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 60:
        return "C"
    return "D"


def close_buy_decision(score: float, has_evidence: bool) -> str:
    if score >= 78 and has_evidence:
        return "종가 기준 분할 관심"
    if score >= 70:
        return "관찰"
    if score >= 60:
        return "보류"
    return "제외 검토"


def realtime_sell_decision(score: float, profit_rate: float | None = None) -> str:
    if profit_rate is not None:
        if profit_rate <= -12:
            return "손절 후보"
        if profit_rate <= -7:
            return "비중축소 검토"
        if profit_rate >= 15:
            return "익절 후보"
        if profit_rate >= 3 and score >= 60:
            return "보유 유지"
    if score < 55:
        return "실시간 리스크 점검"
    if score < 62:
        return "관찰"
    return "보유/관찰"


def normalize_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def make_evidence(item: Dict[str, Any]) -> Dict[str, Any]:
    code = str(item.get("code", "")).zfill(6)
    name = item.get("name", "-")
    score = as_num(item.get("hansuFinalScore"), 0)
    breakdown = item.get("scoreBreakdown", {}) or {}
    raw = breakdown.get("raw", {}) or {}
    flags = item.get("sourceFlags", {}) or {}

    chart = as_num(raw.get("chartScore"), 50)
    supply = as_num(raw.get("supplyScore"), 50)
    news = as_num(raw.get("newsScore"), 50)
    report = as_num(raw.get("reportScore"), 50)
    macro = as_num(raw.get("macroScore"), 60)

    positives: List[str] = []
    negatives: List[str] = []
    watches: List[str] = []

    positives.extend(normalize_list(item.get("positiveFactors")))
    negatives.extend(normalize_list(item.get("negativeFactors")))

    if chart >= 75:
        positives.append(f"차트 점수 {chart:.0f}점: 종가 기준 후보 흐름 양호")
    elif chart < 60:
        negatives.append(f"차트 점수 {chart:.0f}점: 기술 흐름 약화")

    if flags.get("hasSupply"):
        if supply >= 70:
            positives.append(f"수급 점수 {supply:.0f}점: 외국인·기관 누적 수급 우호")
        elif supply < 50:
            negatives.append(f"수급 점수 {supply:.0f}점: 수급 약화 또는 단기성 자금 주의")
    else:
        watches.append("수급 데이터 미확인: 외국인·기관·연기금 흐름 추가 확인 필요")

    if flags.get("hasReport"):
        if report > 60:
            positives.append(f"리포트 점수 {report:.0f}점: 증권사 의견 우호")
        elif report < 45:
            negatives.append(f"리포트 점수 {report:.0f}점: 목표가·실적 전망 하향 가능성")
        else:
            watches.append("리포트 중립: 목표가·실적 추정 변화 확인 필요")
    else:
        watches.append("리포트 데이터 미확인")

    if news >= 70:
        positives.append(f"뉴스/이슈 점수 {news:.0f}점: 테마·업황 모멘텀 우호")
    elif news < 50:
        negatives.append(f"뉴스/이슈 점수 {news:.0f}점: 이슈 모멘텀 부족")

    if macro >= 70:
        positives.append(f"매크로 점수 {macro:.0f}점: 시장환경 우호")
    elif macro < 50:
        negatives.append(f"매크로 점수 {macro:.0f}점: 시장환경 부담")
    else:
        watches.append("매크로 기본값 적용: 금리·환율·유동성 데이터 연결 필요")

    if not flags.get("hasLiveQuote"):
        watches.append("현재가 미연결: 실시간 매도 판단 제한")

    positives = list(dict.fromkeys(positives))[:6]
    negatives = list(dict.fromkeys(negatives))[:6]
    watches = list(dict.fromkeys(watches))[:6]

    has_evidence = bool(positives or negatives)
    close_decision = close_buy_decision(score, has_evidence)
    realtime_decision = item.get("realtimeSellDecision") or realtime_sell_decision(score)

    final_comment = (
        f"{name}은 HANSU AI {score:.0f}점({grade_label(score)})입니다. "
        f"매수 판단은 종가 기준으로 '{close_decision}', 매도 대응은 실시간 기준으로 '{realtime_decision}'입니다."
    )

    report_lines = [
        f"[{name} {code}] HANSU V940 근거 리포트",
        f"최종점수: {score:.0f}점 / 등급: {grade_label(score)}",
        f"차트 {breakdown.get('chart30', '-')} / 수급 {breakdown.get('supply30', '-')} / 뉴스 {breakdown.get('news10', '-')} / 리포트 {breakdown.get('report10', '-')} / 매크로 {breakdown.get('macro20', '-')}",
        f"종가 매수 판단: {close_decision}",
        f"실시간 매도 판단: {realtime_decision}",
        "긍정요인: " + ("; ".join(positives) if positives else "확인된 강한 긍정요인 없음"),
        "부정요인: " + ("; ".join(negatives) if negatives else "확인된 강한 부정요인 없음"),
        "관찰포인트: " + ("; ".join(watches) if watches else "추가 관찰 필요 낮음"),
    ]

    return {
        "code": code,
        "name": name,
        "market": item.get("market", "-"),
        "sector": item.get("sector", "-"),
        "hansuRank": item.get("hansuRank"),
        "hansuFinalScore": int(round(score)),
        "hansuGrade": grade_label(score),
        "scoreBreakdown": breakdown,
        "closeBuyDecision": close_decision,
        "realtimeSellDecision": realtime_decision,
        "positiveFactors": positives,
        "negativeFactors": negatives,
        "watchPoints": watches,
        "riskMemo": item.get("riskMemo", "종가 기준 변동성 확인"),
        "finalComment": final_comment,
        "copyReport": "\n".join(report_lines),
        "sourceFlags": flags,
        "livePrice": item.get("livePrice", "-"),
        "updatedAt": now_kst(),
    }


def main() -> None:
    fusion = load_json(FUSION_PATH, {})
    fusion_items = fusion.get("items") if isinstance(fusion, dict) else None
    if not isinstance(fusion_items, list):
        # Some summaries store top10 only; prefer full fusion file but support summary fallback.
        fusion_items = fusion.get("top10", []) if isinstance(fusion, dict) else []

    scored = load_json(SCORED_PATH, [])
    if not isinstance(scored, list):
        scored = []

    evidence_items = [make_evidence(item) for item in fusion_items]
    evidence_by_code = {e["code"]: e for e in evidence_items}

    enriched_candidates = []
    for cand in scored:
        c = dict(cand)
        code = str(c.get("code", "")).zfill(6)
        ev = evidence_by_code.get(code)
        if ev:
            c["hansuEvidence"] = ev
            c["hansuFinalScore"] = ev["hansuFinalScore"]
            c["hansuGrade"] = ev["hansuGrade"]
            c["hansuAction"] = ev["closeBuyDecision"]
        enriched_candidates.append(c)

    summary = {
        "version": "V940_HANSU_EVIDENCE_ENGINE",
        "updatedAt": now_kst(),
        "inputFusionExists": FUSION_PATH.exists(),
        "inputScoredExists": SCORED_PATH.exists(),
        "evidenceCount": len(evidence_items),
        "candidateCount": len(enriched_candidates),
        "top10": evidence_items[:10],
        "outputs": [
            OUT_EVIDENCE.name,
            OUT_SUMMARY.name,
            OUT_CANDIDATES.name,
        ],
    }

    write_json(OUT_EVIDENCE, {
        "version": "V940_HANSU_EVIDENCE_ENGINE",
        "updatedAt": now_kst(),
        "items": evidence_items,
    })
    write_json(OUT_SUMMARY, summary)
    write_json(OUT_CANDIDATES, enriched_candidates)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
