#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V281 DART SIGNAL ENGINE

목적:
- stock_candidates_input.csv 또는 stock_candidates.json의 후보 종목을 기준으로 최근 DART 공시를 조회
- 수주/계약/실적/자사주/증자/CB/BW/소송 등 이벤트를 긍정/주의/부정으로 분류
- dart_signals.json, dart_signals_summary.json, dart_signals_log.txt 생성
- 기존 V224 Mapper가 읽는 report_hints.csv에 공시 신호를 병합

필수/선택:
- DART Open API 키가 있으면 GitHub Repository Secrets에 DART_API_KEY로 등록
- 키가 없으면 실패하지 않고 neutral 상태의 결과 파일을 생성

GitHub Secrets:
- DART_API_KEY: https://opendart.fss.or.kr 에서 발급한 인증키
"""

from __future__ import annotations

import csv
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()

CANDIDATE_INPUT = ROOT / "stock_candidates_input.csv"
CANDIDATES_JSON = ROOT / "stock_candidates.json"
REPORT_HINTS = ROOT / "report_hints.csv"

OUT_JSON = ROOT / "dart_signals.json"
OUT_SUMMARY = ROOT / "dart_signals_summary.json"
OUT_LOG = ROOT / "dart_signals_log.txt"

DART_API_KEY = os.environ.get("DART_API_KEY", "").strip()
LOOKBACK_DAYS = int(os.environ.get("DART_LOOKBACK_DAYS", "14"))
MAX_CANDIDATES = int(os.environ.get("DART_MAX_CANDIDATES", "50"))
SLEEP_SECONDS = float(os.environ.get("DART_SLEEP_SECONDS", "0.15"))

DISCLOSURE_URL = "https://opendart.fss.or.kr/api/list.json"
CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"

POSITIVE_KEYWORDS = [
    "단일판매", "공급계약", "수주", "계약체결", "신규시설투자", "투자판단", "자기주식취득",
    "자사주", "현금배당", "실적개선", "매출액또는손익구조", "최대주주등소유주식변동",
    "임상", "품목허가", "기술이전", "라이선스", "특허권", "주주환원",
]

CAUTION_KEYWORDS = [
    "유상증자", "전환사채", "CB", "신주인수권부사채", "BW", "교환사채", "EB", "주식관련사채",
    "소송", "압류", "가압류", "상장폐지", "관리종목", "불성실공시", "감사의견", "횡령", "배임",
    "거래정지", "감자", "투자주의", "투자경고", "투자위험", "전환가액", "리픽싱",
]

NEGATIVE_KEYWORDS = [
    "상장폐지", "감사의견거절", "횡령", "배임", "부도", "회생절차", "파산", "거래정지", "관리종목지정",
]

NEUTRAL_IMPORTANT_KEYWORDS = [
    "최대주주", "임원", "타법인", "주주총회", "합병", "분할", "영업양수", "영업양도", "풍문", "조회공시",
]


@dataclass
class DartSignal:
    code: str
    name: str
    corpCode: str
    status: str
    score: int
    sentiment: str
    disclosureCount: int
    positiveCount: int
    cautionCount: int
    negativeCount: int
    latestTitle: str
    latestDate: str
    dartSignal: str
    riskMemo: str
    source: str = "dart_openapi"
    message: str = ""


def now_kst(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return datetime.now(KST).strftime(fmt)


def ymd(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def normalize_code(value: Any) -> str:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    return digits.zfill(6)[-6:] if digits else ""


def clean_text(value: Any, default: str = "-") -> str:
    text = str(value or "").strip()
    return text if text else default


def read_csv_flexible(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    for enc in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    return []


def write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def read_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def extract_candidates_from_json(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ["candidates", "items", "data", "results", "stocks", "rows"]:
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def get_first(row: Dict[str, Any], keys: Iterable[str], default: str = "") -> str:
    for key in keys:
        value = row.get(key)
        if value not in [None, "", "-"]:
            return str(value).strip()
    return default


def load_candidates() -> List[Dict[str, str]]:
    rows = []

    input_rows = read_csv_flexible(CANDIDATE_INPUT)
    for row in input_rows:
        code = normalize_code(get_first(row, ["code", "stockCode", "stock_code", "종목코드", "단축코드"]))
        name = get_first(row, ["name", "stockName", "stock_name", "종목명"], code)
        if code:
            rows.append({"code": code, "name": name})

    if not rows:
        data = read_json(CANDIDATES_JSON)
        for item in extract_candidates_from_json(data):
            code = normalize_code(get_first(item, ["code", "stockCode", "stock_code", "ticker", "symbol", "종목코드"]))
            name = get_first(item, ["name", "stockName", "stock_name", "종목명"], code)
            if code:
                rows.append({"code": code, "name": name})

    unique: Dict[str, str] = {}
    for item in rows:
        if item["code"] and item["code"] not in unique:
            unique[item["code"]] = item["name"] or item["code"]

    return [{"code": c, "name": n} for c, n in list(unique.items())[:MAX_CANDIDATES]]


def fetch_url_json(url: str, timeout: int = 20) -> Dict[str, Any]:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=timeout) as res:
        raw = res.read()
    return json.loads(raw.decode("utf-8", errors="ignore"))


def fetch_corp_code_map() -> Dict[str, str]:
    if not DART_API_KEY:
        return {}

    cache_path = ROOT / "dart_corp_code_cache.json"
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            if cache.get("stockToCorp"):
                return dict(cache["stockToCorp"])
        except Exception:
            pass

    import zipfile
    import io

    url = f"{CORP_CODE_URL}?crtfc_key={DART_API_KEY}"
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=30) as res:
        raw = res.read()

    stock_to_corp: Dict[str, str] = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        xml_name = zf.namelist()[0]
        xml_bytes = zf.read(xml_name)
        root = ET.fromstring(xml_bytes)
        for item in root.findall("list"):
            corp_code = clean_text(item.findtext("corp_code"), "")
            stock_code = normalize_code(item.findtext("stock_code"))
            if stock_code and corp_code:
                stock_to_corp[stock_code] = corp_code

    cache_path.write_text(json.dumps({"updatedAt": now_kst(), "stockToCorp": stock_to_corp}, ensure_ascii=False, indent=2), encoding="utf-8")
    return stock_to_corp


def classify_disclosures(titles: List[str]) -> Tuple[int, str, int, int, int, str]:
    positive = 0
    caution = 0
    negative = 0
    important = 0

    joined = " / ".join(titles)
    upper_joined = joined.upper()

    for title in titles:
        upper = title.upper()
        if any(k.upper() in upper for k in NEGATIVE_KEYWORDS):
            negative += 1
        elif any(k.upper() in upper for k in CAUTION_KEYWORDS):
            caution += 1
        elif any(k.upper() in upper for k in POSITIVE_KEYWORDS):
            positive += 1
        elif any(k.upper() in upper for k in NEUTRAL_IMPORTANT_KEYWORDS):
            important += 1

    score = 0
    score += min(20, positive * 8)
    score += min(6, important * 2)
    score -= min(24, caution * 8)
    score -= min(40, negative * 20)

    if negative > 0:
        sentiment = "부정"
    elif caution > 0 and positive == 0:
        sentiment = "주의"
    elif positive > 0 and caution == 0:
        sentiment = "긍정"
    elif positive > 0 and caution > 0:
        sentiment = "혼합"
    elif important > 0:
        sentiment = "중립"
    else:
        sentiment = "특이공시 없음"

    signal = "-"
    if titles:
        signal = f"최근 공시 {len(titles)}건 / {sentiment}: {titles[0][:80]}"
    risk = "공시 특이사항 제한적"
    if negative > 0:
        risk = "부정 공시 감지: 상장폐지·감사의견·횡령·거래정지 등 위험 공시 확인 필요"
    elif caution > 0:
        risk = "주의 공시 감지: 유증·CB/BW·소송·감자 등 희석/리스크 요인 확인 필요"
    elif positive > 0:
        risk = "긍정 공시 감지: 수주·계약·자사주·배당·투자 공시의 지속성 확인 필요"

    return score, sentiment, positive, caution, negative, risk


def fetch_disclosures_for_corp(corp_code: str, bgn_de: str, end_de: str) -> List[Dict[str, Any]]:
    params = {
        "crtfc_key": DART_API_KEY,
        "corp_code": corp_code,
        "bgn_de": bgn_de,
        "end_de": end_de,
        "page_no": "1",
        "page_count": "20",
    }
    url = f"{DISCLOSURE_URL}?{urlencode(params)}"
    data = fetch_url_json(url)
    status = str(data.get("status", ""))
    if status not in ["000", "013"]:  # 013 = 조회된 데이터 없음
        raise RuntimeError(f"DART status={status} message={data.get('message', '')}")
    return data.get("list", []) or []


def make_neutral_signal(code: str, name: str, message: str) -> DartSignal:
    return DartSignal(
        code=code,
        name=name,
        corpCode="-",
        status="neutral",
        score=0,
        sentiment="미연결",
        disclosureCount=0,
        positiveCount=0,
        cautionCount=0,
        negativeCount=0,
        latestTitle="-",
        latestDate="-",
        dartSignal="DART API 미연결 또는 조회 제한",
        riskMemo="DART_API_KEY 등록 후 공시 신호 확인 가능",
        message=message,
    )


def build_report_hints(existing_rows: List[Dict[str, str]], signals: List[DartSignal]) -> List[Dict[str, str]]:
    # 기존 news engine/report hints 값을 최대한 보존하면서 dartSignal/riskMemo를 보강
    by_code: Dict[str, Dict[str, str]] = {}
    for row in existing_rows:
        code = normalize_code(get_first(row, ["code", "종목코드", "Code"]))
        name = get_first(row, ["name", "종목명", "Name"], code)
        key = code or name
        if key:
            by_code[key] = dict(row)

    for sig in signals:
        key = sig.code or sig.name
        row = by_code.get(key, {"code": sig.code, "name": sig.name})
        row["code"] = sig.code
        row["name"] = sig.name

        existing_report = clean_text(row.get("reportSignal"), "-")
        existing_news = clean_text(row.get("newsSignal"), "-")
        existing_risk = clean_text(row.get("riskMemo"), "-")

        dart_report = f"공시신호 {sig.sentiment}({sig.score:+d}) - {sig.latestTitle}" if sig.latestTitle != "-" else sig.dartSignal
        row["reportSignal"] = dart_report if existing_report in ["-", ""] else f"{existing_report} / {dart_report}"
        row["newsSignal"] = existing_news
        row["riskMemo"] = sig.riskMemo if existing_risk in ["-", "", "공시 특이사항 제한적"] else f"{existing_risk} / {sig.riskMemo}"
        row["dartSignal"] = sig.dartSignal
        row["dartScore"] = str(sig.score)
        row["dartSentiment"] = sig.sentiment
        row["dartLatestDate"] = sig.latestDate
        by_code[key] = row

    # 필드 순서 고정 + 기존 추가 필드 보존
    preferred = [
        "code", "name", "reportSignal", "newsSignal", "riskMemo", "dartSignal", "dartScore", "dartSentiment", "dartLatestDate"
    ]
    extra = []
    for row in by_code.values():
        for k in row.keys():
            if k not in preferred and k not in extra:
                extra.append(k)
    fieldnames = preferred + extra
    rows = list(by_code.values())
    write_csv(REPORT_HINTS, rows, fieldnames)
    return rows


def main() -> None:
    started = now_kst()
    logs: List[str] = []
    candidates = load_candidates()
    logs.append(f"candidateCount={len(candidates)}")

    signals: List[DartSignal] = []
    bgn_de = ymd(datetime.now(KST) - timedelta(days=LOOKBACK_DAYS))
    end_de = ymd(datetime.now(KST))

    if not DART_API_KEY:
        logs.append("DART_API_KEY missing: neutral output generated")
        signals = [make_neutral_signal(c["code"], c["name"], "missing DART_API_KEY") for c in candidates]
    else:
        try:
            corp_map = fetch_corp_code_map()
            logs.append(f"corpCodeMapCount={len(corp_map)}")
        except Exception as e:
            corp_map = {}
            logs.append(f"corpCodeMapFetchFailed={e}")

        for idx, c in enumerate(candidates, start=1):
            code = c["code"]
            name = c["name"]
            corp_code = corp_map.get(code, "")
            if not corp_code:
                sig = make_neutral_signal(code, name, "corp_code not found")
                sig.status = "partial"
                signals.append(sig)
                logs.append(f"[{idx}/{len(candidates)}] {code} {name}: corp_code not found")
                continue

            try:
                disclosures = fetch_disclosures_for_corp(corp_code, bgn_de, end_de)
                titles = [clean_text(x.get("report_nm"), "-") for x in disclosures if clean_text(x.get("report_nm"), "-") != "-"]
                dates = [clean_text(x.get("rcept_dt"), "-") for x in disclosures]
                score, sentiment, pos, caution, neg, risk = classify_disclosures(titles)
                latest_title = titles[0] if titles else "-"
                latest_date = dates[0] if dates else "-"
                status = "ok" if disclosures else "empty"
                dart_signal = f"최근 {LOOKBACK_DAYS}일 공시 {len(disclosures)}건 / {sentiment} / 점수 {score:+d}"
                signals.append(DartSignal(
                    code=code,
                    name=name,
                    corpCode=corp_code,
                    status=status,
                    score=score,
                    sentiment=sentiment,
                    disclosureCount=len(disclosures),
                    positiveCount=pos,
                    cautionCount=caution,
                    negativeCount=neg,
                    latestTitle=latest_title,
                    latestDate=latest_date,
                    dartSignal=dart_signal,
                    riskMemo=risk,
                ))
                logs.append(f"[{idx}/{len(candidates)}] {code} {name}: {status} {sentiment} score={score:+d} count={len(disclosures)}")
            except Exception as e:
                sig = make_neutral_signal(code, name, str(e)[:160])
                sig.corpCode = corp_code
                sig.status = "fail"
                signals.append(sig)
                logs.append(f"[{idx}/{len(candidates)}] {code} {name}: fail {e}")
            time.sleep(SLEEP_SECONDS)

    payload = {
        "version": "V281_DART_SIGNAL_ENGINE",
        "updatedAt": now_kst(),
        "startedAt": started,
        "source": "dart_openapi",
        "lookbackDays": LOOKBACK_DAYS,
        "candidateCount": len(candidates),
        "signalCount": len(signals),
        "okCount": sum(1 for s in signals if s.status == "ok"),
        "emptyCount": sum(1 for s in signals if s.status == "empty"),
        "partialCount": sum(1 for s in signals if s.status == "partial"),
        "failCount": sum(1 for s in signals if s.status == "fail"),
        "apiKeyConfigured": bool(DART_API_KEY),
        "signals": [asdict(s) for s in signals],
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    existing = read_csv_flexible(REPORT_HINTS)
    hints = build_report_hints(existing, signals)

    summary = {
        "version": "V281_DART_SIGNAL_ENGINE",
        "updatedAt": now_kst(),
        "candidateCount": len(candidates),
        "signalCount": len(signals),
        "reportHintsRows": len(hints),
        "apiKeyConfigured": bool(DART_API_KEY),
        "positiveSignals": sum(1 for s in signals if s.positiveCount > 0),
        "cautionSignals": sum(1 for s in signals if s.cautionCount > 0),
        "negativeSignals": sum(1 for s in signals if s.negativeCount > 0),
        "status": "ok" if signals else "warning",
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_LOG.write_text("\n".join(logs), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
