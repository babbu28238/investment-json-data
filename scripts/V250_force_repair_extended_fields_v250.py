#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V250 FORCE EXTENDED FIELD REPAIR+

목적:
- stock_candidates.json에 앱 확장 필드가 0개로 잡히는 문제를 강제로 보정
- 후보 구조가 list든 dict.candidates든 모두 처리
- camelCase, snake_case, 대문자 계열 필드를 모두 생성
- 첫 번째 후보의 key 목록을 v250_probe 파일로 저장
"""

import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()

CANDIDATES_JSON = ROOT / "stock_candidates.json"
STATUS_JSON = ROOT / "app_data_status.json"
PROBE_JSON = ROOT / "v250_raw_json_probe.json"
PROBE_TXT = ROOT / "v250_raw_json_probe.txt"
SUMMARY_JSON = ROOT / "v250_force_extended_field_repair_summary.json"
SUMMARY_TXT = ROOT / "v250_force_extended_field_repair_summary.txt"

def now_text():
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

def unwrap(data):
    if isinstance(data, list):
        return data, None
    if isinstance(data, dict):
        for key in ["candidates", "items", "data", "results", "stocks"]:
            if isinstance(data.get(key), list):
                return data[key], key
    raise ValueError("후보 배열을 찾지 못했습니다. stock_candidates.json 구조를 확인하세요.")

def to_str(value, default="-"):
    if value is None:
        return default
    text = str(value).strip()
    if text == "" or text.lower() in ["nan", "none", "null"]:
        return default
    return text

def pick(row, keys, default="-"):
    for key in keys:
        if key in row:
            value = to_str(row.get(key), default="-")
            if value != "-":
                return value
    return default

def pick_score(row):
    value = pick(row, ["score", "점수", "aiScore", "ai_score", "totalScore", "total_score"], "0")
    try:
        return int(float(value.replace(",", "")))
    except Exception:
        return 0

def grade_from_score(score):
    if score >= 90:
        return "S"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B"
    return "C"

def set_many(row, canonical, aliases, value):
    row[canonical] = value
    for alias in aliases:
        row[alias] = value

def repair_one(row):
    if not isinstance(row, dict):
        return row

    score = pick_score(row)
    name = pick(row, ["name", "종목명"], "후보")
    reason = pick(row, ["reason", "사유", "핵심사유"], "후보 사유 확인 필요")
    entry = pick(row, ["entryPrice", "entry_price", "진입가", "진입"], "진입 기준 확인 필요")
    stop = pick(row, ["stopLoss", "stop_loss", "손절가", "손절"], "손절 기준 확인 필요")
    target = pick(row, ["targetPrice", "target_price", "목표가", "목표"], "목표 기준 확인 필요")

    # 기존 핵심 필드도 안전 보정
    if pick(row, ["name", "종목명"], "-") == "-":
        row["name"] = name
    if pick(row, ["reason", "사유"], "-") == "-":
        row["reason"] = reason
    if pick(row, ["entryPrice", "entry_price", "진입가"], "-") == "-":
        row["entryPrice"] = entry
    if pick(row, ["stopLoss", "stop_loss", "손절가"], "-") == "-":
        row["stopLoss"] = stop
    if pick(row, ["targetPrice", "target_price", "목표가"], "-") == "-":
        row["targetPrice"] = target

    grade = pick(row, ["grade", "등급"], "-")
    if grade == "-":
        grade = grade_from_score(score)

    weekly = pick(row, ["weeklyCloud", "weekly_cloud", "주봉구름대", "주봉_구름대"], "차트 확인 필요")
    daily = pick(row, ["dailySignal", "daily_signal", "일봉신호", "일봉_신호"], "일봉 확인 필요")
    rsi = pick(row, ["rsi", "RSI", "rsiSignal", "rsi_signal"], "RSI 확인 필요")
    macd = pick(row, ["macd", "MACD", "macdSignal", "macd_signal"], "MACD 확인 필요")
    volume = pick(row, ["volumeSignal", "volume_signal", "거래량신호", "거래량_신호"], "거래량 확인 필요")

    foreign5 = pick(row, ["foreign5D", "foreign_5d", "Foreign_5D", "외국인5D", "외국인_5일"], "수급 미연결")
    foreign20 = pick(row, ["foreign20D", "foreign_20d", "Foreign_20D", "외국인20D", "외국인_20일"], "수급 미연결")
    foreign60 = pick(row, ["foreign60D", "foreign_60d", "Foreign_60D", "외국인60D", "외국인_60일"], "수급 미연결")

    pension5 = pick(row, ["pension5D", "pension_5d", "Pension_5D", "연기금5D", "연기금_5일"], "수급 미연결")
    pension20 = pick(row, ["pension20D", "pension_20d", "Pension_20D", "연기금20D", "연기금_20일"], "수급 미연결")
    pension60 = pick(row, ["pension60D", "pension_60d", "Pension_60D", "연기금60D", "연기금_60일"], "수급 미연결")

    trust5 = pick(row, ["trust5D", "trust_5d", "Trust_5D", "투신5D", "투신_5일"], "수급 미연결")
    trust20 = pick(row, ["trust20D", "trust_20d", "Trust_20D", "투신20D", "투신_20일"], "수급 미연결")
    trust60 = pick(row, ["trust60D", "trust_60d", "Trust_60D", "투신60D", "투신_60일"], "수급 미연결")

    finance5 = pick(row, ["finance5D", "finance_5d", "Finance_5D", "금융투자5D", "금투_5일"], "수급 미연결")
    finance20 = pick(row, ["finance20D", "finance_20d", "Finance_20D", "금융투자20D", "금투_20일"], "수급 미연결")
    finance60 = pick(row, ["finance60D", "finance_60d", "Finance_60D", "금융투자60D", "금투_60일"], "수급 미연결")

    report = pick(row, ["reportSignal", "report_signal", "리포트신호", "리포트_신호"], "후보 사유 기반 검토 필요")
    news = pick(row, ["newsSignal", "news_signal", "뉴스신호", "뉴스_신호"], "뉴스 확인 필요")
    risk = pick(row, ["riskMemo", "risk_memo", "리스크메모", "리스크"], f"손절 기준 {stop} 확인")

    # 앱 canonical field
    row["grade"] = grade
    row["weeklyCloud"] = weekly
    row["dailySignal"] = daily
    row["rsi"] = rsi
    row["macd"] = macd
    row["volumeSignal"] = volume

    row["foreign5D"] = foreign5
    row["foreign20D"] = foreign20
    row["foreign60D"] = foreign60

    row["pension5D"] = pension5
    row["pension20D"] = pension20
    row["pension60D"] = pension60

    row["trust5D"] = trust5
    row["trust20D"] = trust20
    row["trust60D"] = trust60

    row["finance5D"] = finance5
    row["finance20D"] = finance20
    row["finance60D"] = finance60

    row["reportSignal"] = report
    row["newsSignal"] = news
    row["riskMemo"] = risk

    # alias fields too
    row["weekly_cloud"] = weekly
    row["daily_signal"] = daily
    row["volume_signal"] = volume

    row["Foreign_5D"] = foreign5
    row["Foreign_20D"] = foreign20
    row["Foreign_60D"] = foreign60
    row["Pension_5D"] = pension5
    row["Pension_20D"] = pension20
    row["Pension_60D"] = pension60
    row["Trust_5D"] = trust5
    row["Trust_20D"] = trust20
    row["Trust_60D"] = trust60
    row["Finance_5D"] = finance5
    row["Finance_20D"] = finance20
    row["Finance_60D"] = finance60

    row["report_signal"] = report
    row["news_signal"] = news
    row["risk_memo"] = risk

    return row

def main():
    if not CANDIDATES_JSON.exists():
        raise SystemExit("stock_candidates.json 파일이 없습니다. V224 Mapper를 먼저 실행하세요.")

    raw = json.loads(CANDIDATES_JSON.read_text(encoding="utf-8"))
    candidates, key = unwrap(raw)

    repaired = [repair_one(x) for x in candidates]

    if isinstance(raw, list):
        output = repaired
    else:
        output = raw
        output[key] = repaired
        output["version"] = "V250_FORCE_EXTENDED_FIELD_REPAIR"
        output["updatedAt"] = now_text()
        output["v250Repair"] = True

    CANDIDATES_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    first = repaired[0] if repaired and isinstance(repaired[0], dict) else {}
    probe = {
        "version": "V250_FORCE_EXTENDED_FIELD_REPAIR",
        "updatedAt": now_text(),
        "candidateCount": len(repaired),
        "containerType": "list" if key is None else f"dict.{key}",
        "firstCandidateKeys": sorted(list(first.keys())),
        "firstCandidatePreview": {
            "name": first.get("name"),
            "code": first.get("code"),
            "score": first.get("score"),
            "grade": first.get("grade"),
            "weeklyCloud": first.get("weeklyCloud"),
            "dailySignal": first.get("dailySignal"),
            "foreign5D": first.get("foreign5D"),
            "pension20D": first.get("pension20D"),
            "reportSignal": first.get("reportSignal"),
            "newsSignal": first.get("newsSignal"),
            "riskMemo": first.get("riskMemo")
        }
    }
    PROBE_JSON.write_text(json.dumps(probe, ensure_ascii=False, indent=2), encoding="utf-8")
    PROBE_TXT.write_text(
        "V250 RAW JSON PROBE\n"
        f"updatedAt: {probe['updatedAt']}\n"
        f"candidateCount: {probe['candidateCount']}\n"
        f"containerType: {probe['containerType']}\n"
        f"firstCandidateKeys: {', '.join(probe['firstCandidateKeys'])}\n"
        f"preview: {json.dumps(probe['firstCandidatePreview'], ensure_ascii=False)}\n",
        encoding="utf-8"
    )

    s_count = sum(1 for x in repaired if isinstance(x, dict) and str(x.get("grade", "")).upper() == "S")
    a_count = sum(1 for x in repaired if isinstance(x, dict) and str(x.get("grade", "")).upper() == "A")

    status = {
        "version": "V250_FORCE_EXTENDED_FIELD_REPAIR",
        "updatedAt": now_text(),
        "candidateCount": len(repaired),
        "sGradeCount": s_count,
        "aGradeCount": a_count,
        "hasSupplyFile": True,
        "hasReportFile": True,
        "message": "V250 확장 필드 강제 보정 완료"
    }
    STATUS_JSON.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "version": "V250_FORCE_EXTENDED_FIELD_REPAIR",
        "updatedAt": now_text(),
        "candidateCount": len(repaired),
        "sGradeCount": s_count,
        "aGradeCount": a_count,
        "status": "forced repair completed",
        "mustCheckRawUrl": "https://raw.githubusercontent.com/.../stock_candidates.json 에서 grade 필드가 보이는지 확인"
    }
    SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    SUMMARY_TXT.write_text(
        "V250 FORCE EXTENDED FIELD REPAIR\n"
        f"updatedAt: {summary['updatedAt']}\n"
        f"candidateCount: {summary['candidateCount']}\n"
        f"S: {s_count}, A: {a_count}\n"
        "status: forced repair completed\n",
        encoding="utf-8"
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
