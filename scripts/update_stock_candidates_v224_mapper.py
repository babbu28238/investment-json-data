#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V224 REAL SUPPLY MAPPER

목적:
- 사용자가 실제로 가지고 있는 수급 CSV의 컬럼명이 조금 달라도 자동 매핑
- stock_candidates_input.csv + report_hints.csv + supply_flow_input.csv를 결합
- 앱용 stock_candidates.json 자동 생성

입력 파일:
- stock_candidates_input.csv
- report_hints.csv
- supply_flow_input.csv

출력 파일:
- stock_candidates.json
- app_data_status.json
- v224_generation_summary.json
- v224_collection_errors.txt
"""

import csv
import json
import re
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()

CANDIDATE_FILE = ROOT / "stock_candidates_input.csv"
REPORT_FILE = ROOT / "report_hints.csv"
SUPPLY_FILE = ROOT / "supply_flow_input.csv"

OUT_CANDIDATES = ROOT / "stock_candidates.json"
OUT_STATUS = ROOT / "app_data_status.json"
OUT_SUMMARY = ROOT / "v224_generation_summary.json"
OUT_ERRORS = ROOT / "v224_collection_errors.txt"

ERRORS = []
WARNINGS = []

def now_text():
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

def read_csv_flexible(path):
    if not path.exists():
        WARNINGS.append(f"파일 없음: {path.name}")
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
        if not s or s == "-":
            return default
        return int(round(float(s)))
    except Exception:
        return default

def to_float(v, default=0.0):
    try:
        s = str(v).replace(",", "").replace("%", "").replace("원", "").replace("주", "").strip()
        if not s or s == "-":
            return default
        return float(s)
    except Exception:
        return default

def normalize_key(s):
    s = str(s or "").lower().strip()
    s = re.sub(r"[\s\-_./()\[\]{}]+", "", s)
    replacements = {
        "종목코드": "code",
        "단축코드": "code",
        "코드": "code",
        "ticker": "code",
        "symbol": "code",
        "종목명": "name",
        "이름": "name",
        "name": "name",
        "stockname": "name",
        "외국인": "foreign",
        "foreign": "foreign",
        "foreigner": "foreign",
        "연기금": "pension",
        "연기금등": "pension",
        "pension": "pension",
        "투신": "trust",
        "trust": "trust",
        "금융투자": "finance",
        "금투": "finance",
        "finance": "finance",
        "금융": "finance",
    }

    for k, v in replacements.items():
        s = s.replace(k, v)

    s = s.replace("순매수", "")
    s = s.replace("누적", "")
    s = s.replace("금액", "")
    s = s.replace("수량", "")
    s = s.replace("netbuy", "")
    s = s.replace("buy", "")

    return s

def first(row, keys, default="-"):
    if not row:
        return default

    # direct lookup
    for k in keys:
        if k in row and clean(row[k], "") != "":
            return clean(row[k], default)

    # normalized lookup
    norm_map = {normalize_key(k): k for k in row.keys()}
    for k in keys:
        nk = normalize_key(k)
        if nk in norm_map:
            real_key = norm_map[nk]
            if clean(row.get(real_key), "") != "":
                return clean(row.get(real_key), default)

    return default

def key_of(row):
    code = first(row, ["code", "stockCode", "stock_code", "종목코드", "단축코드", "ticker", "symbol"], "")
    name = first(row, ["name", "stockName", "stock_name", "종목명"], "")
    return code or name

def find_supply_value(row, actor, period):
    """
    actor: foreign/pension/trust/finance
    period: 5D/20D/60D
    실제 컬럼명이 아래처럼 달라도 최대한 인식:
    Foreign_5D, 외국인_5D, 외국인5일, 외국인_5일, foreign5d, 외국인순매수5D 등
    """
    if not row:
        return "-"

    actor_alias = {
        "foreign": ["foreign", "foreigner", "외국인"],
        "pension": ["pension", "연기금", "연기금등"],
        "trust": ["trust", "투신"],
        "finance": ["finance", "금융투자", "금투", "금융"],
    }[actor]

    period_alias = {
        "5D": ["5d", "5일", "5"],
        "20D": ["20d", "20일", "20"],
        "60D": ["60d", "60일", "60"],
    }[period]

    # exact-ish candidates first
    direct_candidates = []
    for a in actor_alias:
        for p in period_alias:
            direct_candidates.extend([
                f"{a}_{period}",
                f"{a}{period}",
                f"{a}_{p}",
                f"{a}{p}",
                f"{a}순매수{p}",
                f"{a}누적{p}",
            ])

    direct = first(row, direct_candidates, "")
    if direct != "":
        return direct

    # fuzzy scan
    for col, val in row.items():
        ncol = normalize_key(col)
        actor_hit = any(normalize_key(a) in ncol for a in actor_alias)
        period_hit = any(normalize_key(p) in ncol for p in period_alias)
        if actor_hit and period_hit and clean(val, "") != "":
            return clean(val)

    return "-"

def supply_score(row):
    if not row:
        return 0, "수급 데이터 없음"

    vals = []
    for actor in ["foreign", "pension", "trust", "finance"]:
        for period in ["5D", "20D", "60D"]:
            v = find_supply_value(row, actor, period)
            if v != "-":
                vals.append(to_float(v))

    if not vals:
        return 0, "수급 데이터 없음"

    pos = sum(1 for v in vals if v > 0)
    neg = sum(1 for v in vals if v < 0)
    total = sum(vals)

    if pos >= 9:
        return 10, "외국인·기관 수급 강한 동반 개선"
    if pos >= 7 and total > 0:
        return 8, "주요 주체 수급 동반 개선"
    if pos >= 5 and total > 0:
        return 6, "수급 우위"
    if pos >= 3 and total > 0:
        return 3, "일부 수급 개선"
    if neg >= 7:
        return -7, "주요 주체 수급 약화"
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
        code = first(row, ["code", "stockCode", "stock_code", "종목코드", "단축코드"], "")
        name = first(row, ["name", "stockName", "stock_name", "종목명"], f"후보 {idx}")
        key = code or name

        report = report_map.get(key, report_map.get(name, {}))
        supply = supply_map.get(key, supply_map.get(name, {}))

        base_score = to_int(first(row, ["score", "aiScore", "totalScore", "점수", "종합점수"], "75"), 75)
        boost, supply_summary = supply_score(supply)
        final_score = max(0, min(100, base_score + boost))

        grade = first(row, ["grade", "등급"], "")
        if grade in ["", "-"]:
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
            "foreign5D": find_supply_value(supply, "foreign", "5D"),
            "foreign20D": find_supply_value(supply, "foreign", "20D"),
            "foreign60D": find_supply_value(supply, "foreign", "60D"),
            "pension5D": find_supply_value(supply, "pension", "5D"),
            "pension20D": find_supply_value(supply, "pension", "20D"),
            "pension60D": find_supply_value(supply, "pension", "60D"),
            "trust5D": find_supply_value(supply, "trust", "5D"),
            "trust20D": find_supply_value(supply, "trust", "20D"),
            "trust60D": find_supply_value(supply, "trust", "60D"),
            "finance5D": find_supply_value(supply, "finance", "5D"),
            "finance20D": find_supply_value(supply, "finance", "20D"),
            "finance60D": find_supply_value(supply, "finance", "60D"),
            "reportSignal": report_signal,
            "newsSignal": news_signal,
            "riskMemo": risk_memo,
            "dataStatus": {
                "baseScore": base_score,
                "supplyBoost": boost,
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
        "version": "V224_REAL_SUPPLY_MAPPER",
        "updatedAt": now_text(),
        "candidateCount": len(output),
        "sGradeCount": sum(1 for x in output if x.get("grade") == "S"),
        "aGradeCount": sum(1 for x in output if x.get("grade") == "A"),
        "hasSupplyFile": SUPPLY_FILE.exists(),
        "hasReportFile": REPORT_FILE.exists(),
        "warnings": WARNINGS,
        "errors": ERRORS,
        "message": "V224 실제 수급 CSV 자동 매핑 생성 완료" if not ERRORS else "V224 생성 실패 또는 일부 오류 확인 필요"
    }

    summary = {
        "version": "V224",
        "generatedAt": now_text(),
        "inputFiles": {
            "stock_candidates_input.csv": CANDIDATE_FILE.exists(),
            "report_hints.csv": REPORT_FILE.exists(),
            "supply_flow_input.csv": SUPPLY_FILE.exists()
        },
        "candidateCount": len(output),
        "topCandidates": output[:5],
        "warnings": WARNINGS,
        "errors": ERRORS
    }

    OUT_CANDIDATES.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_STATUS.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_ERRORS.write_text("\n".join(ERRORS + WARNINGS) if (ERRORS or WARNINGS) else "No errors.", encoding="utf-8")

    print(f"Generated {OUT_CANDIDATES.name}: {len(output)} candidates")
    print(f"Generated {OUT_STATUS.name}")
    print(f"Generated {OUT_SUMMARY.name}")
    if WARNINGS:
        print("Warnings:")
        for w in WARNINGS:
            print("-", w)
    if ERRORS:
        print("Errors:")
        for e in ERRORS:
            print("-", e)

if __name__ == "__main__":
    build()
