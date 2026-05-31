#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V223 SUPPLY DATA CONNECTOR

입력:
- stock_candidates_input.csv
- report_hints.csv
- supply_flow_input.csv

출력:
- stock_candidates.json
- app_data_status.json
- v223_generation_summary.json
- v223_collection_errors.txt
"""

import csv
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()

CANDIDATE_FILE = ROOT / "stock_candidates_input.csv"
REPORT_FILE = ROOT / "report_hints.csv"
SUPPLY_FILE = ROOT / "supply_flow_input.csv"

OUT_CANDIDATES = ROOT / "stock_candidates.json"
OUT_STATUS = ROOT / "app_data_status.json"
OUT_SUMMARY = ROOT / "v223_generation_summary.json"
OUT_ERRORS = ROOT / "v223_collection_errors.txt"

ERRORS = []

def now_text():
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

def read_csv_flexible(path):
    if not path.exists():
        ERRORS.append(f"파일 없음: {path.name}")
        return []

    for enc in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except Exception:
            pass

    ERRORS.append(f"CSV 읽기 실패: {path.name}")
    return []

def clean(v, default="-"):
    if v is None:
        return default
    s = str(v).strip()
    return s if s else default

def to_int(v, default=0):
    try:
        s = str(v).replace(",", "").replace("%", "").strip()
        if not s:
            return default
        return int(round(float(s)))
    except Exception:
        return default

def to_float(v, default=0.0):
    try:
        s = str(v).replace(",", "").replace("%", "").strip()
        if not s:
            return default
        return float(s)
    except Exception:
        return default

def first(row, keys, default="-"):
    if not row:
        return default
    for k in keys:
        if k in row and str(row[k]).strip() != "":
            return clean(row[k], default)
    return default

def key_of(row):
    code = first(row, ["code", "stockCode", "stock_code", "종목코드", "ticker", "symbol"], "")
    name = first(row, ["name", "stockName", "stock_name", "종목명"], "")
    return code or name

def supply_score_from_values(row):
    cols = [
        "Foreign_5D", "Foreign_20D", "Foreign_60D",
        "Pension_5D", "Pension_20D", "Pension_60D",
        "Trust_5D", "Trust_20D", "Trust_60D",
        "Finance_5D", "Finance_20D", "Finance_60D",
        "외국인_5D", "외국인_20D", "외국인_60D",
        "연기금_5D", "연기금_20D", "연기금_60D",
        "투신_5D", "투신_20D", "투신_60D",
        "금융투자_5D", "금융투자_20D", "금융투자_60D",
    ]
    total = 0.0
    positive_count = 0
    negative_count = 0
    used = 0

    for col in cols:
        if col in row and str(row[col]).strip() != "":
            val = to_float(row[col])
            total += val
            used += 1
            if val > 0:
                positive_count += 1
            elif val < 0:
                negative_count += 1

    if used == 0:
        return 0, "수급 데이터 없음"
    if positive_count >= 8:
        return 8, "주요 주체 수급 동반 개선"
    if positive_count >= 5 and total > 0:
        return 6, "수급 우위"
    if positive_count >= 3 and total > 0:
        return 3, "일부 수급 개선"
    if negative_count >= 6:
        return -6, "수급 약화"
    if total < 0:
        return -3, "수급 점검 필요"
    return 0, "수급 중립"

def grade_from_score(score):
    if score >= 90:
        return "S"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B"
    return "C"

def status_from_grade(grade):
    return {"S": "우선 검토", "A": "조건 확인", "B": "관찰", "C": "제외 검토"}.get(grade, "관찰")

def build():
    candidates = read_csv_flexible(CANDIDATE_FILE)
    reports = read_csv_flexible(REPORT_FILE)
    supplies = read_csv_flexible(SUPPLY_FILE)

    report_map = {key_of(r): r for r in reports if key_of(r)}
    supply_map = {key_of(r): r for r in supplies if key_of(r)}

    if not candidates:
        ERRORS.append("stock_candidates_input.csv에 후보 데이터가 없습니다.")

    output = []
    for idx, row in enumerate(candidates, start=1):
        code = first(row, ["code", "stockCode", "stock_code", "종목코드"], "")
        name = first(row, ["name", "stockName", "stock_name", "종목명"], f"후보 {idx}")
        key = code or name

        report = report_map.get(key, report_map.get(name, {}))
        supply = supply_map.get(key, supply_map.get(name, {}))

        base_score = to_int(first(row, ["score", "aiScore", "totalScore", "점수", "종합점수"], "75"), 75)
        supply_boost, supply_summary = supply_score_from_values(supply) if supply else (0, "수급 데이터 없음")
        final_score = max(0, min(100, base_score + supply_boost))

        grade = first(row, ["grade", "등급"], "")
        if not grade or grade == "-":
            grade = grade_from_score(final_score)

        report_signal = first(report, ["reportSignal", "리포트신호", "리포트", "report_hint"], first(row, ["reportSignal", "리포트신호"], "-"))
        news_signal = first(report, ["newsSignal", "뉴스신호", "뉴스", "news_hint"], first(row, ["newsSignal", "뉴스신호"], "-"))
        risk_memo = first(report, ["riskMemo", "리스크", "risk_hint"], first(row, ["riskMemo", "리스크"], "-"))

        item = {
            "rank": to_int(first(row, ["rank", "ranking", "순위"], str(idx)), idx),
            "name": name,
            "code": code or "-",
            "score": final_score,
            "grade": grade,
            "reason": first(row, ["reason", "summary", "사유", "분석"], f"{supply_summary} / {report_signal if report_signal != '-' else '리포트 확인 필요'}"),
            "market": first(row, ["market", "시장"], "-"),
            "sector": first(row, ["sector", "industry", "업종", "섹터"], "-"),
            "changeRate": first(row, ["changeRate", "등락률", "상승률"], "-"),
            "entryPrice": first(row, ["entryPrice", "진입가", "매수가"], "조건 확인"),
            "stopLoss": first(row, ["stopLoss", "손절가", "손절"], "기준 확인"),
            "targetPrice": first(row, ["targetPrice", "목표가", "목표"], "분할 익절"),
            "strategy": first(row, ["strategy", "전략", "매매전략"], f"{status_from_grade(grade)} 후 분할 접근"),
            "weeklyCloud": first(row, ["weeklyCloud", "주봉구름대"], "-"),
            "dailySignal": first(row, ["dailySignal", "일봉신호"], "-"),
            "rsi": first(row, ["rsi", "RSI"], "-"),
            "macd": first(row, ["macd", "MACD"], "-"),
            "volumeSignal": first(row, ["volumeSignal", "거래량신호"], "-"),
            "foreign5D": first(supply, ["Foreign_5D", "외국인_5D"], first(row, ["foreign5D", "외국인5D"], "-")),
            "foreign20D": first(supply, ["Foreign_20D", "외국인_20D"], first(row, ["foreign20D", "외국인20D"], "-")),
            "foreign60D": first(supply, ["Foreign_60D", "외국인_60D"], first(row, ["foreign60D", "외국인60D"], "-")),
            "pension5D": first(supply, ["Pension_5D", "연기금_5D"], first(row, ["pension5D", "연기금5D"], "-")),
            "pension20D": first(supply, ["Pension_20D", "연기금_20D"], first(row, ["pension20D", "연기금20D"], "-")),
            "pension60D": first(supply, ["Pension_60D", "연기금_60D"], first(row, ["pension60D", "연기금60D"], "-")),
            "trust5D": first(supply, ["Trust_5D", "투신_5D"], first(row, ["trust5D", "투신5D"], "-")),
            "trust20D": first(supply, ["Trust_20D", "투신_20D"], first(row, ["trust20D", "투신20D"], "-")),
            "trust60D": first(supply, ["Trust_60D", "투신_60D"], first(row, ["trust60D", "투신60D"], "-")),
            "finance5D": first(supply, ["Finance_5D", "금융투자_5D"], first(row, ["finance5D", "금융투자5D"], "-")),
            "finance20D": first(supply, ["Finance_20D", "금융투자_20D"], first(row, ["finance20D", "금융투자20D"], "-")),
            "finance60D": first(supply, ["Finance_60D", "금융투자_60D"], first(row, ["finance60D", "금융투자60D"], "-")),
            "reportSignal": report_signal,
            "newsSignal": news_signal,
            "riskMemo": risk_memo,
            "dataStatus": {
                "baseScore": base_score,
                "supplyBoost": supply_boost,
                "supplySummary": supply_summary,
                "hasSupplyData": bool(supply),
                "hasReportHint": bool(report)
            }
        }
        output.append(item)

    output.sort(key=lambda x: (-int(x.get("score", 0)), int(x.get("rank", 9999))))
    for i, item in enumerate(output, start=1):
        item["rank"] = i

    status = {
        "version": "V223_SUPPLY_DATA_CONNECTOR",
        "updatedAt": now_text(),
        "candidateCount": len(output),
        "sGradeCount": sum(1 for x in output if x.get("grade") == "S"),
        "aGradeCount": sum(1 for x in output if x.get("grade") == "A"),
        "hasSupplyFile": SUPPLY_FILE.exists(),
        "hasReportFile": REPORT_FILE.exists(),
        "errors": ERRORS,
        "message": "V223 수급 CSV 연결 생성 완료" if not ERRORS else "V223 생성 완료, 일부 경고 확인 필요"
    }

    summary = {
        "version": "V223",
        "generatedAt": now_text(),
        "inputFiles": {
            "stock_candidates_input.csv": CANDIDATE_FILE.exists(),
            "report_hints.csv": REPORT_FILE.exists(),
            "supply_flow_input.csv": SUPPLY_FILE.exists()
        },
        "candidateCount": len(output),
        "topCandidates": output[:5],
        "errors": ERRORS
    }

    OUT_CANDIDATES.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_STATUS.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_ERRORS.write_text("\\n".join(ERRORS) if ERRORS else "No errors.", encoding="utf-8")

    print(f"Generated {OUT_CANDIDATES.name}: {len(output)} candidates")
    print(f"Generated {OUT_STATUS.name}")
    print(f"Generated {OUT_SUMMARY.name}")
    if ERRORS:
        print("Warnings/Errors:")
        for e in ERRORS:
            print("-", e)

if __name__ == "__main__":
    build()
