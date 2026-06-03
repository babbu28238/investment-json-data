#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CV280 NEWS SIGNAL ENGINE

역할:
- stock_candidates_input.csv 또는 stock_candidates.json 후보를 읽음
- 종목별 Google News RSS를 조회
- 뉴스 제목/요약 기반으로 간단한 긍정/부정/중립 점수화
- report_hints.csv를 생성/갱신하여 기존 V224 mapper가 newsSignal/riskMemo를 stock_candidates.json에 반영하도록 함
- news_signals.json, news_signals_summary.json 생성

출력:
- report_hints.csv
- news_signals.json
- news_signals_summary.json
- news_signals_log.txt
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
from urllib.error import URLError, HTTPError
import xml.etree.ElementTree as ET

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()

CANDIDATE_INPUT = ROOT / "stock_candidates_input.csv"
CANDIDATES_JSON = ROOT / "stock_candidates.json"
REPORT_HINTS = ROOT / "report_hints.csv"
NEWS_JSON = ROOT / "news_signals.json"
SUMMARY_JSON = ROOT / "news_signals_summary.json"
LOG_TXT = ROOT / "news_signals_log.txt"

MAX_CANDIDATES = 80
MAX_NEWS_PER_STOCK = 8
REQUEST_SLEEP = 0.25

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)

POSITIVE_KEYWORDS = [
    "수주", "계약", "공급", "상향", "목표가 상향", "호실적", "실적 개선", "흑자", "성장",
    "증가", "확대", "강세", "급등", "신고가", "돌파", "반등", "개선", "기대", "수혜",
    "투자", "증설", "승인", "인수", "합병", "자사주", "배당", "매수", "긍정", "AI", "반도체",
    "원전", "방산", "조선", "로봇", "수출", "정책", "지원", "턴어라운드", "레벨업",
]

NEGATIVE_KEYWORDS = [
    "하향", "목표가 하향", "적자", "손실", "감소", "부진", "약세", "급락", "하락",
    "리스크", "우려", "압박", "규제", "소송", "검찰", "조사", "유상증자", "CB", "BW",
    "감자", "상장폐지", "거래정지", "불확실", "차질", "중단", "철회", "취소", "매도", "부정",
]

NOISE_KEYWORDS = ["인사", "부고", "동정", "채용", "날씨", "스포츠", "연예"]

@dataclass
class Candidate:
    code: str
    name: str
    market: str = ""
    sector: str = ""
    rank: int = 9999

@dataclass
class NewsItem:
    title: str
    link: str
    published: str
    source: str
    positiveHits: List[str]
    negativeHits: List[str]
    score: int


def now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def normalize_code(value: Any) -> str:
    raw = str(value or "").strip()
    digits = re.sub(r"[^0-9]", "", raw)
    return digits.zfill(6)[-6:] if digits else ""


def clean_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def first(row: Dict[str, Any], keys: Iterable[str], default: str = "") -> str:
    lowered = {str(k).lower(): k for k in row.keys()}
    for key in keys:
        if key in row and str(row.get(key, "")).strip():
            return str(row.get(key)).strip()
        lk = key.lower()
        if lk in lowered and str(row.get(lowered[lk], "")).strip():
            return str(row.get(lowered[lk])).strip()
    return default


def read_csv_candidates(path: Path) -> List[Candidate]:
    if not path.exists():
        return []
    rows = []
    for enc in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
        try:
            with path.open("r", encoding=enc, newline="") as f:
                rows = list(csv.DictReader(f))
            break
        except UnicodeDecodeError:
            continue
    candidates = []
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
        if code or name:
            candidates.append(Candidate(code=code, name=name, market=market, sector=sector, rank=rank))
    return candidates


def extract_candidates_json(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ["candidates", "stocks", "items", "data", "results", "stockCandidates", "recommendations", "rows"]:
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def read_json_candidates(path: Path) -> List[Candidate]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    candidates = []
    for idx, row in enumerate(extract_candidates_json(data), start=1):
        code = normalize_code(first(row, ["code", "stockCode", "stock_code", "종목코드", "ticker", "symbol"]))
        name = first(row, ["name", "stockName", "stock_name", "종목명", "displayName"], code or f"후보{idx}")
        market = first(row, ["market", "시장"], "")
        sector = first(row, ["sector", "industry", "업종", "섹터"], "")
        rank = int(row.get("rank", idx) or idx) if str(row.get("rank", idx)).replace(".", "", 1).isdigit() else idx
        candidates.append(Candidate(code=code, name=name, market=market, sector=sector, rank=rank))
    return candidates


def load_candidates() -> List[Candidate]:
    candidates = read_csv_candidates(CANDIDATE_INPUT)
    if not candidates:
        candidates = read_json_candidates(CANDIDATES_JSON)
    seen = set()
    unique = []
    for c in sorted(candidates, key=lambda x: x.rank):
        key = c.code or c.name
        if key and key not in seen:
            seen.add(key)
            unique.append(c)
    return unique[:MAX_CANDIDATES]


def fetch_url(url: str, timeout: int = 12) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as res:
        return res.read()


def google_news_rss_query(candidate: Candidate) -> str:
    # 종목명이 가장 중요하고, 잡음 감소를 위해 주식/증권 키워드를 붙임
    query = f'"{candidate.name}" 주식 OR 증권 OR 실적 OR 수주 OR 목표가 OR 공시'
    return f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=ko&gl=KR&ceid=KR:ko"


def parse_google_rss(xml_bytes: bytes) -> List[Dict[str, str]]:
    items = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return items
    channel = root.find("channel")
    if channel is None:
        return items
    for item in channel.findall("item"):
        title = clean_text(item.findtext("title", ""))
        link = clean_text(item.findtext("link", ""))
        pub = clean_text(item.findtext("pubDate", ""))
        source = "Google News"
        source_el = item.find("source")
        if source_el is not None and source_el.text:
            source = clean_text(source_el.text)
        if title:
            items.append({"title": title, "link": link, "published": pub, "source": source})
    return items


def keyword_hits(text: str, keywords: List[str]) -> List[str]:
    return [k for k in keywords if k.lower() in text.lower()]


def is_noise(title: str) -> bool:
    return any(k in title for k in NOISE_KEYWORDS)


def score_news_title(title: str) -> Tuple[int, List[str], List[str]]:
    pos = keyword_hits(title, POSITIVE_KEYWORDS)
    neg = keyword_hits(title, NEGATIVE_KEYWORDS)
    score = len(pos) * 7 - len(neg) * 9
    if is_noise(title):
        score -= 6
    return score, pos[:5], neg[:5]


def analyze_candidate(candidate: Candidate) -> Dict[str, Any]:
    url = google_news_rss_query(candidate)
    errors = []
    raw_items: List[Dict[str, str]] = []
    try:
        raw_items = parse_google_rss(fetch_url(url))[:MAX_NEWS_PER_STOCK]
    except (HTTPError, URLError, TimeoutError, Exception) as e:
        errors.append(str(e)[:180])

    news_items: List[NewsItem] = []
    total = 0
    pos_count = 0
    neg_count = 0
    neutral_count = 0

    for item in raw_items:
        score, pos, neg = score_news_title(item["title"])
        total += score
        if score > 0:
            pos_count += 1
        elif score < 0:
            neg_count += 1
        else:
            neutral_count += 1
        news_items.append(NewsItem(
            title=item["title"], link=item["link"], published=item["published"], source=item["source"],
            positiveHits=pos, negativeHits=neg, score=score
        ))

    # 0~100 스케일. 기본 50에서 뉴스 점수 반영
    normalized = max(0, min(100, 50 + total))
    if not raw_items:
        normalized = 50

    headline = news_items[0].title if news_items else "뉴스 없음"
    if normalized >= 70:
        label = "뉴스 긍정"
    elif normalized <= 35:
        label = "뉴스 부정/주의"
    elif raw_items:
        label = "뉴스 중립"
    else:
        label = "뉴스 부족"

    risk = "부정 키워드 확인 필요" if neg_count > 0 else "뉴스 리스크 특이사항 제한적"
    signal = f"{label}: 긍정 {pos_count} / 부정 {neg_count} / 중립 {neutral_count} / 점수 {normalized}"
    if headline and headline != "뉴스 없음":
        signal = f"{signal} / 대표뉴스: {headline[:80]}"

    return {
        "code": candidate.code,
        "name": candidate.name,
        "market": candidate.market,
        "sector": candidate.sector,
        "newsScore": normalized,
        "newsLabel": label,
        "positiveCount": pos_count,
        "negativeCount": neg_count,
        "neutralCount": neutral_count,
        "headline": headline,
        "newsSignal": signal,
        "riskMemo": risk,
        "errors": errors,
        "items": [asdict(x) for x in news_items],
    }


def read_existing_report_hints() -> Dict[str, Dict[str, str]]:
    if not REPORT_HINTS.exists():
        return {}
    rows = []
    for enc in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
        try:
            with REPORT_HINTS.open("r", encoding=enc, newline="") as f:
                rows = list(csv.DictReader(f))
            break
        except UnicodeDecodeError:
            continue
        except Exception:
            return {}
    result = {}
    for row in rows:
        code = normalize_code(row.get("code") or row.get("종목코드") or row.get("Code"))
        name = str(row.get("name") or row.get("종목명") or "").strip()
        key = code or name
        if key:
            result[key] = {k: str(v or "") for k, v in row.items()}
    return result


def write_report_hints(candidates: List[Candidate], analyses: Dict[str, Dict[str, Any]]) -> None:
    existing = read_existing_report_hints()
    rows = []
    for c in candidates:
        key = c.code or c.name
        base = existing.get(key, existing.get(c.name, {})).copy()
        analysis = analyses.get(key, {})
        rows.append({
            "code": c.code,
            "name": c.name,
            "reportSignal": base.get("reportSignal") or base.get("리포트신호") or base.get("report_signal") or "리포트 확인 필요",
            "newsSignal": analysis.get("newsSignal", base.get("newsSignal") or base.get("뉴스신호") or "뉴스 확인 필요"),
            "riskMemo": analysis.get("riskMemo", base.get("riskMemo") or base.get("리스크") or "뉴스/리포트 리스크 확인 필요"),
            "newsScore": str(analysis.get("newsScore", "")),
            "newsHeadline": analysis.get("headline", ""),
            "updatedAt": now_kst(),
        })

    with REPORT_HINTS.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["code", "name", "reportSignal", "newsSignal", "riskMemo", "newsScore", "newsHeadline", "updatedAt"])
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    started = now_kst()
    candidates = load_candidates()
    analyses: Dict[str, Dict[str, Any]] = {}
    logs = [f"CV280 NEWS SIGNAL ENGINE startedAt={started}", f"candidateCount={len(candidates)}"]

    for idx, c in enumerate(candidates, start=1):
        key = c.code or c.name
        analysis = analyze_candidate(c)
        analyses[key] = analysis
        logs.append(f"[{idx}/{len(candidates)}] {c.code} {c.name} -> {analysis['newsLabel']} {analysis['newsScore']}")
        time.sleep(REQUEST_SLEEP)

    write_report_hints(candidates, analyses)

    payload = {
        "version": "CV280_NEWS_SIGNAL_ENGINE",
        "updatedAt": now_kst(),
        "source": "google_news_rss",
        "candidateCount": len(candidates),
        "signals": list(analyses.values()),
    }
    NEWS_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "version": "CV280_NEWS_SIGNAL_ENGINE",
        "updatedAt": now_kst(),
        "candidateCount": len(candidates),
        "positiveCandidates": sum(1 for x in analyses.values() if x.get("newsScore", 50) >= 70),
        "negativeCandidates": sum(1 for x in analyses.values() if x.get("newsScore", 50) <= 35),
        "neutralCandidates": sum(1 for x in analyses.values() if 35 < x.get("newsScore", 50) < 70),
        "topNews": [
            {"code": x["code"], "name": x["name"], "newsScore": x["newsScore"], "headline": x["headline"]}
            for x in sorted(analyses.values(), key=lambda y: y.get("newsScore", 0), reverse=True)[:10]
        ],
    }
    SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    LOG_TXT.write_text("\n".join(logs), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
