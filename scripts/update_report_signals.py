#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V283 REPORT SIGNAL ENGINE

역할:
- stock_candidates_input.csv 또는 stock_candidates.json 후보를 읽음
- 네이버 금융 공개 리서치/종목 리포트 페이지를 조회해 최근 리포트 힌트를 수집
- 리포트 제목/증권사/일자 기반으로 간단한 상향·하향·긍정·주의 신호를 점수화
- 기존 V224 mapper가 그대로 읽을 수 있도록 report_hints.csv를 생성/갱신
- report_signals.json, report_signals_summary.json, report_signals_log.txt 생성

주의:
- 공개 웹 페이지 구조가 바뀌면 일부 수집이 실패할 수 있음
- 실패해도 액션 전체를 실패시키지 않고 중립 힌트를 생성함
- 유료 컨센서스/목표가 데이터는 포함하지 않음. 추후 FnGuide/증권사 API 계약 시 확장 가능
"""

from __future__ import annotations

import csv
import html
import json
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()

CANDIDATE_INPUT = ROOT / "stock_candidates_input.csv"
CANDIDATES_JSON = ROOT / "stock_candidates.json"
REPORT_HINTS = ROOT / "report_hints.csv"
REPORT_JSON = ROOT / "report_signals.json"
SUMMARY_JSON = ROOT / "report_signals_summary.json"
LOG_TXT = ROOT / "report_signals_log.txt"

MAX_CANDIDATES = 80
MAX_REPORTS_PER_STOCK = 6
REQUEST_SLEEP = 0.25

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)

POSITIVE_KEYWORDS = [
    "상향", "목표가 상향", "매수", "BUY", "Buy", "Outperform", "비중확대", "호실적", "실적 개선",
    "턴어라운드", "성장", "수주", "증가", "확대", "개선", "기대", "수혜", "강세", "재평가",
]
NEGATIVE_KEYWORDS = [
    "하향", "목표가 하향", "매도", "SELL", "Sell", "중립", "부진", "실적 부진", "감소", "우려",
    "리스크", "불확실", "적자", "손실", "둔화", "비용", "압박",
]

@dataclass
class Candidate:
    code: str
    name: str
    market: str = ""
    sector: str = ""
    rank: int = 9999

@dataclass
class ReportItem:
    title: str
    provider: str
    published: str
    link: str
    positiveHits: List[str]
    negativeHits: List[str]
    score: int


def now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def normalize_code(value: Any) -> str:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    return digits.zfill(6)[-6:] if digits else ""


def clean_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def first(row: Dict[str, Any], keys: Iterable[str], default: str = "") -> str:
    lowered = {str(k).lower(): k for k in row.keys()}
    for key in keys:
        if key in row and str(row.get(key, "")).strip():
            return str(row.get(key)).strip()
        lk = key.lower()
        if lk in lowered and str(row.get(lowered[lk], "")).strip():
            return str(row.get(lowered[lk])).strip()
    return default


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


def read_json_candidates(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ["candidates", "items", "data", "results", "stocks", "rows", "recommendations"]:
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def load_candidates() -> List[Candidate]:
    rows = read_csv_rows(CANDIDATE_INPUT)
    if not rows:
        rows = read_json_candidates(CANDIDATES_JSON)

    out: List[Candidate] = []
    seen = set()
    for idx, row in enumerate(rows, start=1):
        code = normalize_code(first(row, ["code", "stockCode", "stock_code", "종목코드", "단축코드", "ticker", "symbol"]))
        name = first(row, ["name", "stockName", "stock_name", "종목명", "displayName"], code or f"후보{idx}")
        market = first(row, ["market", "시장"], "")
        sector = first(row, ["sector", "industry", "업종", "섹터"], "")
        rank_text = first(row, ["rank", "ranking", "순위"], str(idx))
        try:
            rank = int(float(str(rank_text).replace(",", "")))
        except Exception:
            rank = idx
        key = code or name
        if key and key not in seen:
            seen.add(key)
            out.append(Candidate(code=code, name=name, market=market, sector=sector, rank=rank))
    return sorted(out, key=lambda x: x.rank)[:MAX_CANDIDATES]


def fetch_url(url: str, timeout: int = 12) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as res:
        return res.read()


def decode_bytes(raw: bytes) -> str:
    for enc in ["euc-kr", "cp949", "utf-8"]:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def keyword_hits(text: str, keywords: List[str]) -> List[str]:
    lower = text.lower()
    return [k for k in keywords if k.lower() in lower]


def score_title(title: str) -> Tuple[int, List[str], List[str]]:
    pos = keyword_hits(title, POSITIVE_KEYWORDS)
    neg = keyword_hits(title, NEGATIVE_KEYWORDS)
    score = len(pos) * 8 - len(neg) * 10
    # 리포트 제목에 목표가가 있으면 투자 판단 관련성이 높다.
    if "목표" in title or "TP" in title.upper():
        score += 2
    return score, pos[:5], neg[:5]


def naver_report_urls(candidate: Candidate) -> List[str]:
    # 네이버 금융 리서치 페이지는 itemName 검색과 code 검색을 모두 시도한다.
    urls = []
    if candidate.name:
        urls.append(
            "https://finance.naver.com/research/company_list.naver?" +
            f"searchType=itemName&itemName={quote_plus(candidate.name, encoding='euc-kr')}"
        )
    if candidate.code:
        urls.append(
            "https://finance.naver.com/research/company_list.naver?" +
            f"searchType=stockCode&stockCode={candidate.code}"
        )
    urls.append("https://finance.naver.com/research/company_list.naver")
    return urls


def absolutize_naver_link(link: str) -> str:
    link = html.unescape(link or "").strip()
    if link.startswith("http"):
        return link
    if link.startswith("/"):
        return "https://finance.naver.com" + link
    if link:
        return "https://finance.naver.com/research/" + link
    return ""


def parse_naver_reports(page_html: str, candidate: Candidate) -> List[ReportItem]:
    reports: List[ReportItem] = []

    # company_list table rows. 구조가 바뀌어도 제목/링크/증권사/날짜를 최대한 복원한다.
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", page_html, flags=re.S | re.I)
    for row_html in rows:
        text = clean_text(row_html)
        if not text or candidate.name not in text:
            # 검색 결과가 전체 목록일 경우 종목명이 없으면 제외
            continue
        if "종목명" in text and "제목" in text:
            continue

        link_match = re.search(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', row_html, flags=re.S | re.I)
        title = clean_text(link_match.group(2)) if link_match else text
        link = absolutize_naver_link(link_match.group(1)) if link_match else ""

        # td 분리 후 뒤쪽에서 증권사/날짜 후보 추출
        cells = [clean_text(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.S | re.I)]
        cells = [c for c in cells if c]
        provider = "-"
        published = "-"
        for c in cells:
            if re.search(r"\d{2}\.\d{2}\.\d{2}|\d{4}\.\d{2}\.\d{2}", c):
                published = c
        # 증권사명은 날짜가 아닌 짧은 셀에서 탐색
        for c in cells[::-1]:
            if c != published and len(c) <= 20 and ("증권" in c or "투자" in c or "리서치" in c or c in ["메리츠", "삼성", "NH", "키움", "신한"]):
                provider = c
                break

        if not title or len(title) < 3:
            continue
        score, pos, neg = score_title(title)
        reports.append(ReportItem(title=title, provider=provider, published=published, link=link, positiveHits=pos, negativeHits=neg, score=score))
        if len(reports) >= MAX_REPORTS_PER_STOCK:
            break

    return reports


def analyze_candidate(candidate: Candidate) -> Dict[str, Any]:
    errors: List[str] = []
    reports: List[ReportItem] = []

    for url in naver_report_urls(candidate):
        try:
            html_text = decode_bytes(fetch_url(url))
            found = parse_naver_reports(html_text, candidate)
            if found:
                reports = found
                break
        except (HTTPError, URLError, TimeoutError, Exception) as e:
            errors.append(str(e)[:180])
        time.sleep(REQUEST_SLEEP)

    total_score = sum(r.score for r in reports)
    positive_count = sum(1 for r in reports if r.score > 0)
    negative_count = sum(1 for r in reports if r.score < 0)
    latest_title = reports[0].title if reports else "최근 공개 리포트 확인 필요"
    latest_provider = reports[0].provider if reports else "-"
    latest_date = reports[0].published if reports else "-"

    if not reports:
        signal = "리포트 중립: 최근 공개 리포트 확인 필요"
        risk = "리포트 데이터 미확인: 뉴스·수급·차트 신호와 함께 검토"
        grade = "neutral"
        score = 50
    else:
        raw = 50 + min(25, total_score) - min(25, abs(min(0, total_score)))
        score = max(0, min(100, int(raw)))
        if score >= 68:
            grade = "positive"
            signal = f"리포트 긍정: {latest_title} ({latest_provider}, {latest_date})"
            risk = "리포트 긍정 신호 확인. 목표가/실적 추정 변화는 추가 확인 필요"
        elif score <= 40:
            grade = "negative"
            signal = f"리포트 주의: {latest_title} ({latest_provider}, {latest_date})"
            risk = "리포트 부정·주의 신호 확인. 추격매수 전 리스크 확인 필요"
        else:
            grade = "neutral"
            signal = f"리포트 중립: {latest_title} ({latest_provider}, {latest_date})"
            risk = "리포트 방향성 중립. 수급·뉴스·차트 조건 동시 확인"

    return {
        "code": candidate.code,
        "name": candidate.name,
        "market": candidate.market,
        "sector": candidate.sector,
        "rank": candidate.rank,
        "reportScore": score,
        "reportGrade": grade,
        "reportSignal": signal,
        "reportRiskMemo": risk,
        "reportCount": len(reports),
        "positiveReportCount": positive_count,
        "negativeReportCount": negative_count,
        "latestReportTitle": latest_title,
        "latestReportProvider": latest_provider,
        "latestReportDate": latest_date,
        "errors": errors,
        "reports": [asdict(r) for r in reports],
    }


def read_existing_report_hints() -> Dict[str, Dict[str, str]]:
    rows = read_csv_rows(REPORT_HINTS)
    out: Dict[str, Dict[str, str]] = {}
    for row in rows:
        code = normalize_code(first(row, ["code", "종목코드", "stockCode"]))
        name = first(row, ["name", "종목명", "stockName"], "")
        key = code or name
        if key:
            out[key] = dict(row)
    return out


def write_report_hints(candidates: List[Candidate], analyses: List[Dict[str, Any]]) -> None:
    existing = read_existing_report_hints()
    analysis_map = {(a.get("code") or a.get("name")): a for a in analyses}
    rows: List[Dict[str, str]] = []

    for c in candidates:
        key = c.code or c.name
        base = existing.get(key, {})
        a = analysis_map.get(key, {})
        existing_news = base.get("newsSignal") or base.get("뉴스신호") or "-"
        existing_risk = base.get("riskMemo") or base.get("리스크") or "-"
        report_signal = str(a.get("reportSignal") or base.get("reportSignal") or base.get("리포트신호") or "리포트 확인 필요")
        report_risk = str(a.get("reportRiskMemo") or "")
        if existing_risk and existing_risk != "-" and report_risk:
            risk = f"{existing_risk} / {report_risk}"
        else:
            risk = report_risk or existing_risk or "-"
        rows.append({
            "code": c.code,
            "name": c.name,
            "reportSignal": report_signal,
            "newsSignal": existing_news,
            "riskMemo": risk,
            "reportScore": str(a.get("reportScore", "")),
            "reportGrade": str(a.get("reportGrade", "")),
            "latestReportTitle": str(a.get("latestReportTitle", "")),
            "latestReportProvider": str(a.get("latestReportProvider", "")),
            "latestReportDate": str(a.get("latestReportDate", "")),
        })

    fieldnames = [
        "code", "name", "reportSignal", "newsSignal", "riskMemo",
        "reportScore", "reportGrade", "latestReportTitle", "latestReportProvider", "latestReportDate",
    ]
    with REPORT_HINTS.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    started = now_kst()
    candidates = load_candidates()
    log_lines = [f"V283 REPORT SIGNAL ENGINE startedAt={started}", f"candidateCount={len(candidates)}"]

    analyses: List[Dict[str, Any]] = []
    for idx, candidate in enumerate(candidates, start=1):
        result = analyze_candidate(candidate)
        analyses.append(result)
        log_lines.append(
            f"[{idx}/{len(candidates)}] {candidate.code} {candidate.name} "
            f"score={result['reportScore']} reports={result['reportCount']} grade={result['reportGrade']}"
        )
        print(log_lines[-1])
        time.sleep(REQUEST_SLEEP)

    write_report_hints(candidates, analyses)

    payload = {
        "version": "V283_REPORT_SIGNAL_ENGINE",
        "updatedAt": now_kst(),
        "startedAt": started,
        "source": "naver_finance_research_public_pages",
        "candidateCount": len(candidates),
        "analyzedCount": len(analyses),
        "reportHitCount": sum(1 for a in analyses if int(a.get("reportCount", 0)) > 0),
        "positiveCount": sum(1 for a in analyses if a.get("reportGrade") == "positive"),
        "negativeCount": sum(1 for a in analyses if a.get("reportGrade") == "negative"),
        "signals": analyses,
    }
    REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "version": payload["version"],
        "updatedAt": payload["updatedAt"],
        "candidateCount": payload["candidateCount"],
        "analyzedCount": payload["analyzedCount"],
        "reportHitCount": payload["reportHitCount"],
        "positiveCount": payload["positiveCount"],
        "negativeCount": payload["negativeCount"],
        "topSignals": [
            {
                "code": a.get("code"),
                "name": a.get("name"),
                "reportScore": a.get("reportScore"),
                "reportGrade": a.get("reportGrade"),
                "reportSignal": a.get("reportSignal"),
            }
            for a in analyses[:10]
        ],
    }
    SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    LOG_TXT.write_text("\n".join(log_lines), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
