#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V941 HANSU Final Data Merge
- V930 AI score + V940 evidence + live_quotes + supply/report/deep diagnosis coverage를 최종 앱용 구조로 병합
- 없는 데이터는 점수로 과장하지 않고 coverage/reliability로 명확히 표시
Outputs:
  hansu_final_operation_v941.json
  hansu_final_operation_v941_summary.json
  stock_candidates_hansu_final.json
"""
from __future__ import annotations
import json, os, re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Tuple

KST = timezone(timedelta(hours=9))
ROOT = os.getcwd()


def now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")


def read_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def norm_code(v: Any) -> str:
    s = re.sub(r"\D", "", str(v or ""))
    return s.zfill(6)[-6:] if s else ""


def list_from_any(data: Any, *keys: str) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for k in keys:
            v = data.get(k)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
    return []


def index_by_code(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for it in items:
        c = norm_code(it.get("code") or it.get("ticker") or it.get("stockCode"))
        if c:
            out[c] = it
    return out


def to_number(v: Any, default: float = 0.0) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v or "").replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except Exception:
        return default


def get_score_breakdown(evidence: Dict[str, Any], ai: Dict[str, Any]) -> Dict[str, Any]:
    sb = evidence.get("scoreBreakdown") or ai.get("scoreBreakdown") or {}
    raw = sb.get("raw") if isinstance(sb.get("raw"), dict) else {}
    return {
        "chart30": round(to_number(sb.get("chart30")), 1),
        "supply30": round(to_number(sb.get("supply30")), 1),
        "news10": round(to_number(sb.get("news10")), 1),
        "report10": round(to_number(sb.get("report10")), 1),
        "macro20": round(to_number(sb.get("macro20")), 1),
        "raw": {
            "chartScore": round(to_number(raw.get("chartScore")), 1),
            "supplyScore": round(to_number(raw.get("supplyScore")), 1),
            "newsScore": round(to_number(raw.get("newsScore")), 1),
            "reportScore": round(to_number(raw.get("reportScore")), 1),
            "macroScore": round(to_number(raw.get("macroScore")), 1),
        }
    }


def reliability(flags: Dict[str, bool]) -> Tuple[int, str]:
    weights = {
        "hasCandidate": 20,
        "hasLiveQuote": 20,
        "hasSupply": 20,
        "hasReport": 10,
        "hasEvidence": 20,
        "hasDeepDiagnosis": 10,
    }
    score = sum(w for k, w in weights.items() if flags.get(k))
    if score >= 80:
        grade = "높음"
    elif score >= 60:
        grade = "보통"
    elif score >= 40:
        grade = "낮음"
    else:
        grade = "부족"
    return score, grade


def decision(final_score: float, grade: str, close_buy: str, realtime_sell: str, live_ok: bool, reliability_score: int) -> Dict[str, str]:
    # 매수는 종가 기준, 매도는 실시간 기준
    if not live_ok:
        sell = "실시간 판단 제한"
    elif "손절" in realtime_sell or "리스크" in realtime_sell:
        sell = "실시간 리스크 점검"
    elif final_score >= 75 and reliability_score >= 60:
        sell = "보유 가능"
    else:
        sell = realtime_sell or "관찰"

    if final_score >= 80 and reliability_score >= 70:
        buy = "종가 기준 관심"
    elif final_score >= 70 and reliability_score >= 50:
        buy = "관찰"
    else:
        buy = close_buy or "보류"

    final_action = "보류"
    if sell in ["실시간 리스크 점검", "실시간 판단 제한"]:
        final_action = sell
    elif buy in ["종가 기준 관심", "관찰"]:
        final_action = buy

    return {"closeBuyDecision": buy, "realtimeSellDecision": sell, "finalAction": final_action}


def main() -> None:
    stock = read_json("stock_candidates_ai_evidence.json", read_json("stock_candidates_ai_scored.json", read_json("stock_candidates.json", [])))
    evidence_doc = read_json("hansu_evidence_v940.json", {})
    supply_doc = read_json("supply_data.json", {})
    report_doc = read_json("report_signals.json", {})
    live_doc = read_json("live_quotes.json", [])
    deep_doc = read_json("watchlist_deep_diagnosis.json", read_json("deep_diagnosis.json", {}))

    candidates = list_from_any(stock, "items", "candidates", "data")
    evidence_items = list_from_any(evidence_doc, "items", "evidence", "data")
    supply_items = list_from_any(supply_doc, "items", "data")
    report_items = list_from_any(report_doc, "items", "reports", "data", "signals")
    live_items = list_from_any(live_doc, "items", "quotes", "data")
    deep_items = list_from_any(deep_doc, "items", "diagnosis", "data")

    evidence_idx = index_by_code(evidence_items)
    supply_idx = index_by_code(supply_items)
    report_idx = index_by_code(report_items)
    live_idx = index_by_code(live_items)
    deep_idx = index_by_code(deep_items)

    final_items: List[Dict[str, Any]] = []
    for cand in candidates:
        code = norm_code(cand.get("code"))
        if not code:
            continue
        ev = evidence_idx.get(code) or cand.get("hansuEvidence") or {}
        ai = cand.get("hansuAI") or {}
        sup = supply_idx.get(code)
        rep = report_idx.get(code)
        live = live_idx.get(code)
        deep = deep_idx.get(code)

        name = cand.get("name") or ev.get("name") or ai.get("name") or (live or {}).get("name") or code
        market = cand.get("market") or ev.get("market") or ai.get("market") or "-"
        sector = cand.get("sector") or cand.get("industry") or ev.get("sector") or ai.get("sector") or "-"

        flags = {
            "hasCandidate": True,
            "hasLiveQuote": bool(live or cand.get("hasLiveQuote") or ev.get("sourceFlags", {}).get("hasLiveQuote")),
            "hasSupply": bool(sup or ev.get("sourceFlags", {}).get("hasSupply")),
            "hasReport": bool(rep or ev.get("sourceFlags", {}).get("hasReport")),
            "hasEvidence": bool(ev),
            "hasDeepDiagnosis": bool(deep or ev.get("sourceFlags", {}).get("hasDeepDiagnosis")),
        }
        rel_score, rel_grade = reliability(flags)
        final_score = to_number(ev.get("hansuFinalScore", cand.get("hansuFinalScore", ai.get("hansuFinalScore", cand.get("score", 0)))))
        grade = ev.get("hansuGrade") or cand.get("hansuGrade") or ai.get("hansuGrade") or cand.get("grade") or "-"
        live_price = (live or {}).get("currentPrice") or (live or {}).get("price") or (live or {}).get("livePrice") or cand.get("livePrice") or ev.get("livePrice") or "-"

        actions = decision(final_score, grade, ev.get("closeBuyDecision", ai.get("closeBuyDecision", "보류")), ev.get("realtimeSellDecision", ai.get("realtimeSellDecision", "관찰")), flags["hasLiveQuote"], rel_score)

        watch = list(ev.get("watchPoints") or [])
        if not flags["hasSupply"] and "수급 데이터 미확인: 외국인·기관·연기금 흐름 추가 확인 필요" not in watch:
            watch.append("수급 데이터 미확인: 외국인·기관·연기금 흐름 추가 확인 필요")
        if not flags["hasReport"] and "리포트 데이터 미확인" not in watch:
            watch.append("리포트 데이터 미확인")
        if not flags["hasLiveQuote"] and "현재가 미연결: 실시간 매도 판단 제한" not in watch:
            watch.append("현재가 미연결: 실시간 매도 판단 제한")
        if "매크로 기본값 적용: 금리·환율·유동성 데이터 연결 필요" not in watch:
            # macroScore 60/default일 때만 명시
            raw_macro = get_score_breakdown(ev, ai).get("raw", {}).get("macroScore")
            if raw_macro == 60:
                watch.append("매크로 기본값 적용: 금리·환율·유동성 데이터 연결 필요")

        item = {
            "code": code,
            "name": name,
            "market": market,
            "sector": sector,
            "rank": cand.get("rank"),
            "hansuRank": ev.get("hansuRank") or ai.get("hansuRank"),
            "hansuFinalScore": int(round(final_score)),
            "hansuGrade": grade,
            "scoreBreakdown": get_score_breakdown(ev, ai),
            "closeBuyDecision": actions["closeBuyDecision"],
            "realtimeSellDecision": actions["realtimeSellDecision"],
            "hansuFinalAction": actions["finalAction"],
            "positiveFactors": ev.get("positiveFactors", ai.get("positiveFactors", [])),
            "negativeFactors": ev.get("negativeFactors", ai.get("negativeFactors", [])),
            "watchPoints": watch,
            "riskMemo": ev.get("riskMemo") or cand.get("riskMemo") or "종가 기준 변동성 확인",
            "finalComment": f"{name}은 HANSU AI {int(round(final_score))}점({grade})입니다. 매수는 종가 기준 '{actions['closeBuyDecision']}', 매도는 실시간 기준 '{actions['realtimeSellDecision']}'입니다. 데이터 신뢰도는 {rel_score}점({rel_grade})입니다.",
            "copyReport": ev.get("copyReport", ""),
            "sourceFlags": flags,
            "dataReliabilityScore": rel_score,
            "dataReliabilityGrade": rel_grade,
            "livePrice": live_price,
            "liveStatus": "ok" if flags["hasLiveQuote"] else "missing",
            "supplySummary": (sup or {}).get("supplySummary") or ev.get("supplySummary") or ai.get("supplySummary") or "수급 데이터 미확인",
            "reportSignal": ev.get("reportSignal") or ai.get("reportSignal") or "리포트 데이터 미확인",
            "updatedAt": now_kst(),
        }
        merged_cand = dict(cand)
        merged_cand["hansuFinal"] = item
        final_items.append(merged_cand)

    final_items.sort(key=lambda x: (-(x.get("hansuFinal", {}).get("dataReliabilityScore", 0)), -(x.get("hansuFinal", {}).get("hansuFinalScore", 0))))
    compact = [x["hansuFinal"] for x in final_items]
    summary = {
        "version": "V941_HANSU_FINAL_DATA_MERGE",
        "updatedAt": now_kst(),
        "candidateCount": len(candidates),
        "finalCount": len(final_items),
        "coverage": {
            "liveQuote": sum(1 for x in compact if x["sourceFlags"].get("hasLiveQuote")),
            "supply": sum(1 for x in compact if x["sourceFlags"].get("hasSupply")),
            "report": sum(1 for x in compact if x["sourceFlags"].get("hasReport")),
            "evidence": sum(1 for x in compact if x["sourceFlags"].get("hasEvidence")),
            "deepDiagnosis": sum(1 for x in compact if x["sourceFlags"].get("hasDeepDiagnosis")),
        },
        "reliability": {
            "high": sum(1 for x in compact if x["dataReliabilityScore"] >= 80),
            "medium": sum(1 for x in compact if 60 <= x["dataReliabilityScore"] < 80),
            "low": sum(1 for x in compact if 40 <= x["dataReliabilityScore"] < 60),
            "insufficient": sum(1 for x in compact if x["dataReliabilityScore"] < 40),
        },
        "top10": compact[:10],
        "outputs": ["hansu_final_operation_v941.json", "hansu_final_operation_v941_summary.json", "stock_candidates_hansu_final.json"],
    }
    write_json("hansu_final_operation_v941.json", {"version": "V941_HANSU_FINAL_DATA_MERGE", "updatedAt": now_kst(), "items": compact})
    write_json("hansu_final_operation_v941_summary.json", summary)
    write_json("stock_candidates_hansu_final.json", final_items)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
