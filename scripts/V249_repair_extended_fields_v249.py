#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V249 EXTENDED FIELD REPAIR

목적:
- 기존 V224가 만든 stock_candidates.json에 앱이 기대하는 확장 필드가 없을 때 자동 보정
- 앱 필드명 기준으로 아래 필드들을 추가/정리
  grade, weeklyCloud, dailySignal, rsi, macd, volumeSignal
  foreign5D/20D/60D, pension5D/20D/60D, trust5D/20D/60D, finance5D/20D/60D
  reportSignal, newsSignal, riskMemo

주의:
- 실제 수급/차트/리포트 데이터가 없으면 '데이터 미연결' 또는 '확인 필요'로 표시합니다.
- 이 값은 매수 신호가 아니라 데이터 연결 상태를 앱에서 명확히 보기 위한 보정값입니다.
"""

import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()

CANDIDATES_JSON = ROOT / "stock_candidates.json"
STATUS_JSON = ROOT / "app_data_status.json"
SUMMARY_JSON = ROOT / "v249_extended_field_repair_summary.json"
SUMMARY_TXT = ROOT / "v249_extended_field_repair_summary.txt"

def now_text():
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

def pick(row, keys, default="-"):
    for key in keys:
        if key in row and row[key] not in [None, "", "-", "nan", "NaN"]:
            return str(row[key]).strip()
    return default

def pick_number(row, keys, default=0):
    for key in keys:
        if key in row and row[key] not in [None, "", "-", "nan", "NaN"]:
            try:
                return int(float(str(row[key]).replace(",", "").strip()))
            except Exception:
                continue
    return default

def grade_from_score(score):
    try:
        score = int(float(score))
    except Exception:
        return "-"
    if score >= 90:
        return "S"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B"
    return "C"

def safe_set(row, target, source_keys, fallback="-"):
    value = pick(row, [target] + source_keys, default=None)
    if value is None:
        value = fallback
    row[target] = value

def normalize_candidate(row):
    score = pick_number(row, ["score", "점수", "aiScore", "ai_score"], default=0)

    # 등급
    if pick(row, ["grade", "등급"], default="-") == "-":
        row["grade"] = grade_from_score(score)
    else:
        row["grade"] = pick(row, ["grade", "등급"], default="-")

    # 차트 신호
    safe_set(row, "weeklyCloud", ["weekly_cloud", "주봉구름대", "주봉_구름대", "weekly_cloud_signal"], "차트 확인 필요")
    safe_set(row, "dailySignal", ["daily_signal", "일봉신호", "일봉_신호", "daily_signal_text"], "일봉 확인 필요")
    safe_set(row, "rsi", ["RSI", "rsiSignal", "rsi_signal", "RSI신호"], "RSI 확인 필요")
    safe_set(row, "macd", ["MACD", "macdSignal", "macd_signal", "MACD신호"], "MACD 확인 필요")
    safe_set(row, "volumeSignal", ["volume_signal", "거래량신호", "거래량_신호"], "거래량 확인 필요")

    # 수급
    safe_set(row, "foreign5D", ["Foreign_5D", "foreign_5d", "외국인5D", "외국인_5일"], "수급 미연결")
    safe_set(row, "foreign20D", ["Foreign_20D", "foreign_20d", "외국인20D", "외국인_20일"], "수급 미연결")
    safe_set(row, "foreign60D", ["Foreign_60D", "foreign_60d", "외국인60D", "외국인_60일"], "수급 미연결")

    safe_set(row, "pension5D", ["Pension_5D", "pension_5d", "연기금5D", "연기금_5일"], "수급 미연결")
    safe_set(row, "pension20D", ["Pension_20D", "pension_20d", "연기금20D", "연기금_20일"], "수급 미연결")
    safe_set(row, "pension60D", ["Pension_60D", "pension_60d", "연기금60D", "연기금_60일"], "수급 미연결")

    safe_set(row, "trust5D", ["Trust_5D", "trust_5d", "투신5D", "투신_5일"], "수급 미연결")
    safe_set(row, "trust20D", ["Trust_20D", "trust_20d", "투신20D", "투신_20일"], "수급 미연결")
    safe_set(row, "trust60D", ["Trust_60D", "trust_60d", "투신60D", "투신_60일"], "수급 미연결")

    safe_set(row, "finance5D", ["Finance_5D", "finance_5d", "금융투자5D", "금융투자_5일", "금투_5일"], "수급 미연결")
    safe_set(row, "finance20D", ["Finance_20D", "finance_20d", "금융투자20D", "금융투자_20일", "금투_20일"], "수급 미연결")
    safe_set(row, "finance60D", ["Finance_60D", "finance_60d", "금융투자60D", "금융투자_60일", "금투_60일"], "수급 미연결")

    # 리포트/뉴스/리스크
    reason = pick(row, ["reason", "사유", "핵심사유"], default="-")
    safe_set(row, "reportSignal", ["report_signal", "리포트신호", "리포트_신호"], "리포트 확인 필요")
    safe_set(row, "newsSignal", ["news_signal", "뉴스신호", "뉴스_신호"], "뉴스 확인 필요")
    safe_set(row, "riskMemo", ["risk_memo", "리스크메모", "리스크", "risk"], "손절 기준 확인 필요")

    # strategy가 있으면 riskMemo 보완
    if row.get("riskMemo") in ["-", "", "손절 기준 확인 필요"]:
        stop_loss = pick(row, ["stopLoss", "stop_loss", "손절가", "손절"], default="-")
        if stop_loss != "-":
            row["riskMemo"] = f"손절 기준 {stop_loss} 확인"

    # report/news가 완전히 없으면 reason을 기반으로 보완
    if row.get("reportSignal") in ["-", "", "리포트 확인 필요"] and reason != "-":
        row["reportSignal"] = "후보 사유 기반 검토 필요"

    return row

def unwrap_candidates(data):
    if isinstance(data, list):
        return data, "list"
    if isinstance(data, dict):
        for key in ["candidates", "items", "data", "results"]:
            if isinstance(data.get(key), list):
                return data[key], key
    raise ValueError("stock_candidates.json에서 후보 배열을 찾지 못했습니다.")

def main():
    if not CANDIDATES_JSON.exists():
        raise SystemExit("stock_candidates.json 파일이 없습니다. V224 Mapper를 먼저 실행하세요.")

    raw = json.loads(CANDIDATES_JSON.read_text(encoding="utf-8"))
    candidates, key = unwrap_candidates(raw)

    repaired = []
    for row in candidates:
        if isinstance(row, dict):
            repaired.append(normalize_candidate(row))
        else:
            repaired.append(row)

    if isinstance(raw, list):
        output = repaired
    else:
        output = raw
        output[key] = repaired
        output["version"] = "V249_EXTENDED_FIELD_REPAIR"
        output["updatedAt"] = now_text()

    CANDIDATES_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    s_count = sum(1 for x in repaired if isinstance(x, dict) and str(x.get("grade", "")).upper() == "S")
    a_count = sum(1 for x in repaired if isinstance(x, dict) and str(x.get("grade", "")).upper() == "A")

    status = {
        "version": "V249_EXTENDED_FIELD_REPAIR",
        "updatedAt": now_text(),
        "candidateCount": len(repaired),
        "sGradeCount": s_count,
        "aGradeCount": a_count,
        "hasSupplyFile": True,
        "hasReportFile": True,
        "message": "V249 확장 필드 보정 완료"
    }
    STATUS_JSON.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "version": "V249_EXTENDED_FIELD_REPAIR",
        "updatedAt": now_text(),
        "candidateCount": len(repaired),
        "sGradeCount": s_count,
        "aGradeCount": a_count,
        "fieldsAdded": [
            "grade", "weeklyCloud", "dailySignal", "rsi", "macd", "volumeSignal",
            "foreign5D", "foreign20D", "foreign60D",
            "pension5D", "pension20D", "pension60D",
            "trust5D", "trust20D", "trust60D",
            "finance5D", "finance20D", "finance60D",
            "reportSignal", "newsSignal", "riskMemo"
        ]
    }
    SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    SUMMARY_TXT.write_text(
        f"V249 EXTENDED FIELD REPAIR\n"
        f"updatedAt: {summary['updatedAt']}\n"
        f"candidateCount: {len(repaired)}\n"
        f"S: {s_count}, A: {a_count}\n"
        f"status: 확장 필드 보정 완료\n",
        encoding="utf-8"
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
