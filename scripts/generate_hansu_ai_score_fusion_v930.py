#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V930 HANSU AI SCORE FUSION ENGINE
- stock_candidates.json + supply_data.json + report_signals.json + evidence_data.json + live_quotes.json + watchlist_deep_diagnosis.json 병합
- 산식: 차트 30 + 수급 30 + 뉴스 10 + 리포트 10 + 매크로 20
- 매수는 종가 기준, 매도는 실시간 기준 문구를 함께 생성
- 출력:
  1) hansu_ai_score_fusion.json
  2) stock_candidates_ai_scored.json
  3) hansu_ai_score_fusion_summary.json
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()

CANDIDATES = ROOT / "stock_candidates.json"
SUPPLY = ROOT / "supply_data.json"
REPORTS = ROOT / "report_signals.json"
EVIDENCE = ROOT / "evidence_data.json"
LIVE = ROOT / "live_quotes.json"
DEEP = ROOT / "watchlist_deep_diagnosis.json"

OUT_FUSION = ROOT / "hansu_ai_score_fusion.json"
OUT_CANDIDATES = ROOT / "stock_candidates_ai_scored.json"
OUT_SUMMARY = ROOT / "hansu_ai_score_fusion_summary.json"

DEFAULT_MACRO_SCORE = 60


def now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")


def load_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[WARN] failed to load {path.name}: {e}")
    return default


def norm(code: Any) -> str:
    return str(code or "").strip().zfill(6)[-6:]


def num(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).replace(",", "").replace("%", "").replace("+", "").strip()
        if s in ["", "-", "nan", "None"]:
            return default
        return float(s)
    except Exception:
        return default


def index_items(data: Any, key: str = "items") -> Dict[str, Dict[str, Any]]:
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get(key) or data.get("signals") or data.get("quotes") or []
    else:
        items = []
    out: Dict[str, Dict[str, Any]] = {}
    for item in items:
        if isinstance(item, dict):
            c = norm(item.get("code"))
            if c:
                out[c] = item
    return out


def report_index(data: Any) -> Dict[str, Dict[str, Any]]:
    if isinstance(data, dict):
        items = data.get("signals", [])
    else:
        items = []
    return {norm(x.get("code")): x for x in items if isinstance(x, dict) and x.get("code")}


def quote_index(data: Any) -> Dict[str, Dict[str, Any]]:
    if isinstance(data, dict):
        items = data.get("quotes", [])
    elif isinstance(data, list):
        items = data
    else:
        items = []
    return {norm(x.get("code")): x for x in items if isinstance(x, dict) and x.get("code")}


def clamp(v: float, lo: float = 0, hi: float = 100) -> int:
    return int(round(max(lo, min(hi, v))))


def grade(score: int) -> str:
    if score >= 90:
        return "S"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B"
    if score >= 60:
        return "C"
    return "D"


def action_from_score(score: int, live_change: float, candidate_action: str) -> str:
    # 매수는 종가 기준: 신규 매수성 문구는 종가 확인 또는 눌림 확인으로 제한
    if score >= 85 and live_change > -3:
        return "종가 확인 후 분할매수 후보"
    if score >= 75:
        return "우선관찰"
    if score >= 65:
        return "관찰"
    if score >= 55:
        return "보류"
    return "제외/리스크"


def sell_action(score: int, pnl_rate: Optional[float], live_change: float) -> str:
    # 매도는 실시간 기준
    if pnl_rate is not None:
        if pnl_rate <= -12 or (score < 60 and pnl_rate < -5):
            return "실시간 손절 점검"
        if pnl_rate <= -6:
            return "비중축소 검토"
        if pnl_rate >= 12:
            return "익절 검토"
        if score >= 70:
            return "보유 유지"
        return "관찰 유지"
    if live_change <= -8 or score < 55:
        return "실시간 리스크 점검"
    return "관찰"


def build_reason(chart: int, supply: int, news: int, report: int, macro: int, cand: Dict[str, Any], sup: Dict[str, Any], rep: Dict[str, Any], ev: Dict[str, Any]) -> Dict[str, Any]:
    positives: List[str] = []
    negatives: List[str] = []

    if chart >= 75:
        positives.append(f"차트/기술 점수 양호({chart}점)")
    elif chart < 60:
        negatives.append(f"차트 약세 또는 변동성 확대({chart}점)")

    if supply >= 70:
        positives.append(sup.get("supplySummary") or f"수급 점수 양호({supply}점)")
    elif supply < 50:
        negatives.append(sup.get("supplySummary") or f"수급 약화({supply}점)")

    if news >= 70:
        positives.append(ev.get("news", {}).get("summary") if isinstance(ev.get("news"), dict) else f"뉴스 점수 긍정({news}점)")
    elif news < 50:
        negatives.append(f"뉴스/이슈 모멘텀 부족({news}점)")

    if report > 55:
        positives.append(rep.get("reportSignal") or f"리포트 점수 우호({report}점)")
    elif report < 45:
        negatives.append(rep.get("reportRiskMemo") or f"리포트 점수 부정({report}점)")
    else:
        negatives.append(rep.get("reportRiskMemo") or "리포트는 중립 또는 확인 필요")

    if macro >= 65:
        positives.append(f"시장환경 점수 보통 이상({macro}점)")
    elif macro < 50:
        negatives.append(f"시장환경 부담({macro}점)")

    risk = cand.get("riskMemo") or ev.get("realtimeSellGuide") or "전일 저점·20일선 이탈·거래량 붕괴 시 실시간 대응"
    return {
        "positiveFactors": [x for x in positives if x][:5],
        "negativeFactors": [x for x in negatives if x][:5],
        "riskMemo": risk,
    }


def main() -> None:
    candidates = load_json(CANDIDATES, [])
    if not isinstance(candidates, list):
        candidates = candidates.get("items", []) if isinstance(candidates, dict) else []

    supply_by = index_items(load_json(SUPPLY, {}))
    report_by = report_index(load_json(REPORTS, {}))
    evidence_by = index_items(load_json(EVIDENCE, {}))
    quote_by = quote_index(load_json(LIVE, {}))
    deep_by = index_items(load_json(DEEP, {}))

    fused: List[Dict[str, Any]] = []
    enriched_candidates: List[Dict[str, Any]] = []

    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        code = norm(cand.get("code"))
        sup = supply_by.get(code, {})
        rep = report_by.get(code, {})
        ev = evidence_by.get(code, {})
        qt = quote_by.get(code, {})
        dp = deep_by.get(code, {})

        chart_score = clamp(cand.get("technicalScore", cand.get("dataStatus", {}).get("technicalScore", cand.get("score", 50))))
        supply_score = clamp(sup.get("supplyScore", ev.get("supply", {}).get("supplyScore", 50)))
        news_score = clamp(ev.get("news", {}).get("newsTotalScore", 50) if isinstance(ev.get("news"), dict) else 50)
        report_score = clamp(rep.get("reportScore", 50))
        macro_score = DEFAULT_MACRO_SCORE

        final_score = clamp(
            chart_score * 0.30 +
            supply_score * 0.30 +
            news_score * 0.10 +
            report_score * 0.10 +
            macro_score * 0.20
        )

        live_change = num(cand.get("changeRate", qt.get("changeRate", 0)), 0)
        pnl_rate = None
        # 앱에서 포트폴리오 평단과 수량은 별도 저장되므로 여기서는 후보/현재가 기반 점수만 생성

        reasons = build_reason(chart_score, supply_score, news_score, report_score, macro_score, cand, sup, rep, ev)
        buy_action = action_from_score(final_score, live_change, cand.get("recommendationAction", cand.get("strategy", "관찰")))
        sell = sell_action(final_score, pnl_rate, live_change)

        item = {
            "code": code,
            "name": cand.get("name", qt.get("name", code)),
            "market": cand.get("market", "-"),
            "sector": cand.get("sector", cand.get("industry", "-")),
            "rank": cand.get("rank", 0),
            "hansuFinalScore": final_score,
            "hansuGrade": grade(final_score),
            "scoreBreakdown": {
                "chart30": round(chart_score * 0.30, 1),
                "supply30": round(supply_score * 0.30, 1),
                "news10": round(news_score * 0.10, 1),
                "report10": round(report_score * 0.10, 1),
                "macro20": round(macro_score * 0.20, 1),
                "raw": {
                    "chartScore": chart_score,
                    "supplyScore": supply_score,
                    "newsScore": news_score,
                    "reportScore": report_score,
                    "macroScore": macro_score,
                },
            },
            "closeBuyDecision": buy_action,
            "realtimeSellDecision": sell,
            "positiveFactors": reasons["positiveFactors"],
            "negativeFactors": reasons["negativeFactors"],
            "riskMemo": reasons["riskMemo"],
            "reportSignal": rep.get("reportSignal", "리포트 데이터 미확인"),
            "supplySummary": sup.get("supplySummary", "수급 데이터 미확인"),
            "livePrice": qt.get("price", cand.get("livePrice", "-")),
            "liveStatus": qt.get("status", cand.get("liveStatus", "-")),
            "sourceFlags": {
                "hasCandidate": True,
                "hasSupply": bool(sup),
                "hasReport": bool(rep),
                "hasEvidence": bool(ev),
                "hasLiveQuote": bool(qt),
                "hasDeepDiagnosis": bool(dp),
            },
        }
        fused.append(item)
        enriched = dict(cand)
        enriched["hansuAI"] = item
        enriched["hansuFinalScore"] = final_score
        enriched["hansuGrade"] = item["hansuGrade"]
        enriched["hansuAction"] = buy_action
        enriched_candidates.append(enriched)

    fused.sort(key=lambda x: x.get("hansuFinalScore", 0), reverse=True)
    for i, it in enumerate(fused, 1):
        it["hansuRank"] = i

    summary = {
        "version": "V930_HANSU_AI_SCORE_FUSION",
        "updatedAt": now_kst(),
        "candidateCount": len(candidates),
        "fusionCount": len(fused),
        "sources": {
            "stock_candidates": CANDIDATES.exists(),
            "supply_data": SUPPLY.exists(),
            "report_signals": REPORTS.exists(),
            "evidence_data": EVIDENCE.exists(),
            "live_quotes": LIVE.exists(),
            "watchlist_deep_diagnosis": DEEP.exists(),
        },
        "weights": {
            "chart": 30,
            "supply": 30,
            "news": 10,
            "report": 10,
            "macro": 20,
        },
        "top10": fused[:10],
        "outputs": [OUT_FUSION.name, OUT_CANDIDATES.name, OUT_SUMMARY.name],
    }

    OUT_FUSION.write_text(json.dumps({
        "version": "V930_HANSU_AI_SCORE_FUSION",
        "updatedAt": summary["updatedAt"],
        "weights": summary["weights"],
        "items": fused,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_CANDIDATES.write_text(json.dumps(enriched_candidates, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
