#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V901 FORCE PORTFOLIO LIVE QUOTES

Purpose:
- Keep the existing live_quotes.json structure.
- Add missing quote rows for portfolio/holding stocks even when they are not in the final candidate universe.
- Fix HANSU app issue: portfolio quote match 2/4 -> 4/4.

Default forced holdings are based on the current HANSU portfolio:
005930 삼성전자, 034020 두산에너빌리티, 272210 한화시스템, 042660 한화오션
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

KST = timezone(timedelta(hours=9))
ROOT = Path.cwd()
LIVE_QUOTES_PATH = ROOT / "live_quotes.json"
STOCK_CANDIDATES_PATH = ROOT / "stock_candidates.json"
REPORT_PATH = ROOT / "v901_force_portfolio_quotes_report.json"

NAVER_ITEM_MAIN = "https://finance.naver.com/item/main.naver"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
}
TIMEOUT = 10

FORCE_PORTFOLIO_CODES: Dict[str, str] = {
    "005930": "삼성전자",
    "034020": "두산에너빌리티",
    "272210": "한화시스템",
    "042660": "한화오션",
}


def now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def normalize_code(value: Any) -> str:
    s = str(value or "").strip()
    if s.endswith(".0"):
        s = s[:-2]
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits.zfill(6)[-6:] if digits else ""


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_number(text: Any) -> str:
    s = str(text or "").replace("\xa0", " ").strip()
    m = re.search(r"[-+]?\d[\d,]*", s)
    return m.group(0) if m else "-"


def fetch_naver_quote(code: str, fallback_name: str = "") -> Optional[Dict[str, Any]]:
    code = normalize_code(code)
    if not code:
        return None
    try:
        r = requests.get(NAVER_ITEM_MAIN, params={"code": code}, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200 or not r.text:
            return None
        soup = BeautifulSoup(r.text, "lxml")

        name = fallback_name
        title = soup.select_one("div.wrap_company h2 a") or soup.select_one("div.wrap_company h2")
        if title:
            name = title.get_text(strip=True) or fallback_name

        price = "-"
        price_node = soup.select_one("p.no_today span.blind")
        if price_node:
            price = parse_number(price_node.get_text(" ", strip=True))

        change_rate = "-"
        no_exday = soup.select_one("p.no_exday")
        if no_exday:
            txt = no_exday.get_text(" ", strip=True)
            m = re.search(r"[-+]?\d+(?:\.\d+)?%", txt)
            if m:
                change_rate = m.group(0)

        volume = "-"
        for tr in soup.select("table.no_info tr"):
            row_text = tr.get_text(" ", strip=True)
            if "거래량" in row_text:
                blinds = [b.get_text(strip=True) for b in tr.select("span.blind")]
                if blinds:
                    volume = parse_number(blinds[0])
                    break

        status = "ok" if price != "-" else "partial"
        return {
            "code": code,
            "name": name or fallback_name or code,
            "price": price,
            "changeRate": change_rate,
            "volume": volume,
            "updatedAt": now_kst(),
            "source": "naver_finance_force_portfolio",
            "status": status,
            "message": "forced portfolio quote" if status == "ok" else "forced portfolio quote price parse failed",
        }
    except Exception as exc:
        return {
            "code": code,
            "name": fallback_name or code,
            "price": "-",
            "changeRate": "-",
            "volume": "-",
            "updatedAt": now_kst(),
            "source": "naver_finance_force_portfolio",
            "status": "partial",
            "message": f"forced portfolio quote failed: {exc}",
        }


def get_quotes_container(raw: Any) -> List[Dict[str, Any]]:
    if isinstance(raw, dict):
        quotes = raw.get("quotes", [])
        return quotes if isinstance(quotes, list) else []
    if isinstance(raw, list):
        return raw
    return []


def collect_forced_codes() -> Dict[str, str]:
    forced = dict(FORCE_PORTFOLIO_CODES)

    # Optional future local files from GitHub/app export.
    for file_name in ["portfolio_positions.json", "portfolio_holdings.json", "watchlist_holdings.json"]:
        raw = read_json(ROOT / file_name, [])
        rows = raw.get("positions", raw.get("holdings", raw)) if isinstance(raw, dict) else raw
        if isinstance(rows, list):
            for item in rows:
                if isinstance(item, dict):
                    code = normalize_code(item.get("code") or item.get("stockCode") or item.get("symbol"))
                    name = str(item.get("name") or item.get("stockName") or "").strip()
                    if code:
                        forced.setdefault(code, name or code)
    return forced


def main() -> None:
    raw_live = read_json(LIVE_QUOTES_PATH, {"quotes": []})
    quotes = get_quotes_container(raw_live)
    existing_by_code = {normalize_code(q.get("code")): q for q in quotes if isinstance(q, dict)}

    forced = collect_forced_codes()
    missing = {code: name for code, name in forced.items() if code not in existing_by_code or str(existing_by_code[code].get("price", "-")).strip() in ["", "-"]}

    added_or_replaced: List[str] = []
    failed: List[str] = []
    for code, name in missing.items():
        quote = fetch_naver_quote(code, name)
        if quote:
            existing_by_code[code] = quote
            added_or_replaced.append(code)
            if quote.get("status") != "ok":
                failed.append(code)
        else:
            failed.append(code)
        time.sleep(0.05)

    # Preserve existing order, then append forced missing that were not originally present.
    output_quotes: List[Dict[str, Any]] = []
    seen = set()
    for q in quotes:
        code = normalize_code(q.get("code"))
        if code in existing_by_code and code not in seen:
            output_quotes.append(existing_by_code[code])
            seen.add(code)
    for code in forced:
        if code in existing_by_code and code not in seen:
            output_quotes.append(existing_by_code[code])
            seen.add(code)

    ok_count = sum(1 for q in output_quotes if q.get("status") == "ok" and str(q.get("price", "-")).strip() not in ["", "-"])
    partial_count = sum(1 for q in output_quotes if q.get("status") != "ok" or str(q.get("price", "-")).strip() in ["", "-"])

    if isinstance(raw_live, dict):
        out = dict(raw_live)
        out["version"] = "V901_FORCE_PORTFOLIO_LIVE_QUOTES"
        out["updatedAt"] = now_kst()
        out["quoteCount"] = len(output_quotes)
        out["okCount"] = ok_count
        out["partialCount"] = partial_count
        out["quotes"] = output_quotes
    else:
        out = output_quotes

    write_json(LIVE_QUOTES_PATH, out)

    report = {
        "version": "V901_FORCE_PORTFOLIO_QUOTES_REPORT",
        "updatedAt": now_kst(),
        "forcedCodes": forced,
        "beforeQuoteCount": len(quotes),
        "afterQuoteCount": len(output_quotes),
        "addedOrReplaced": added_or_replaced,
        "failed": failed,
        "checks": {
            "liveQuotesExists": LIVE_QUOTES_PATH.exists(),
            "stockCandidatesExists": STOCK_CANDIDATES_PATH.exists(),
            "portfolioCodesCovered": {code: code in {normalize_code(q.get("code")) for q in output_quotes} for code in forced},
        },
    }
    write_json(REPORT_PATH, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
