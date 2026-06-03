"""
CV252 실제 현재가 수집기
- 입력: stock_candidates.json
- 출력: live_quotes.json
- 수집원: 네이버 금융 종목 페이지
- GitHub Actions에서 자동 실행 가능

주의:
네이버 페이지 구조가 바뀌면 selector를 조정해야 합니다.
앱은 live_quotes.json이 없거나 일부 종목 수집에 실패해도 기존 후보 JSON으로 계속 동작합니다.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "stock_candidates.json"
OUT = ROOT / "live_quotes.json"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)

@dataclass
class LiveQuote:
    code: str
    name: str
    price: str
    changeRate: str
    volume: str
    updatedAt: str
    source: str = "naver_finance"
    status: str = "ok"
    message: str = ""


def now_kst(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return datetime.now(KST).strftime(fmt)


def read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"{path.name} not found")
    return json.loads(path.read_text(encoding="utf-8"))


def extract_candidates(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in [
            "candidates", "stocks", "items", "data", "results",
            "stockCandidates", "recommendations", "rows"
        ]:
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def normalize_code(value: Any) -> str:
    raw = str(value or "").strip()
    digits = re.sub(r"[^0-9]", "", raw)
    if not digits:
        return ""
    return digits.zfill(6)[-6:]


def get_first(item: Dict[str, Any], keys: Iterable[str], default: str = "") -> str:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return default


def compact_number(value: str) -> str:
    value = re.sub(r"\s+", "", value or "")
    return value if value else "-"


def fetch_html(url: str, timeout: int = 10) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as res:
        raw = res.read()
    # 네이버 금융은 euc-kr/cp949 계열일 수 있음
    for enc in ("euc-kr", "cp949", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def strip_tags(html: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def parse_naver_quote(html: str) -> Dict[str, str]:
    # 현재가: <p class="no_today"><span class="blind">72,800</span></p>
    price = "-"
    m = re.search(r'<p[^>]+class="no_today"[^>]*>.*?<span[^>]+class="blind"[^>]*>([^<]+)</span>', html, flags=re.S)
    if m:
        price = compact_number(m.group(1))

    # 등락률: <span class="blind">+1.10%</span> 또는 1.10%
    change_rate = "-"
    rate_candidates = re.findall(r'<span[^>]+class="blind"[^>]*>([+\-]?[0-9.,]+%)</span>', html, flags=re.S)
    if rate_candidates:
        change_rate = compact_number(rate_candidates[0])

    # 거래량: 텍스트에서 '거래량 1,234,567' 패턴 우선
    volume = "-"
    text = strip_tags(html)
    vm = re.search(r"거래량\s*([0-9,]+)", text)
    if vm:
        volume = compact_number(vm.group(1))
    else:
        # 백업: 거래량 td 주변의 blind 값
        vm = re.search(r"거래량.*?<span[^>]+class=\"blind\"[^>]*>([0-9,]+)</span>", html, flags=re.S)
        if vm:
            volume = compact_number(vm.group(1))

    return {"price": price, "changeRate": change_rate, "volume": volume}


def fetch_naver_quote(code: str, name: str) -> LiveQuote:
    updated_at = now_kst()
    if not code:
        return LiveQuote(code="-", name=name or "-", price="-", changeRate="-", volume="-", updatedAt=updated_at, status="fail", message="missing code")

    url = f"https://finance.naver.com/item/sise.naver?code={code}"
    try:
        html = fetch_html(url)
        parsed = parse_naver_quote(html)
        status = "ok" if parsed["price"] != "-" else "partial"
        message = "" if status == "ok" else "price parse failed"
        return LiveQuote(code=code, name=name or code, updatedAt=updated_at, status=status, message=message, **parsed)
    except (HTTPError, URLError, TimeoutError, Exception) as e:
        return LiveQuote(code=code, name=name or code, price="-", changeRate="-", volume="-", updatedAt=updated_at, status="fail", message=str(e)[:160])


def main() -> None:
    started_at = now_kst()
    candidates = extract_candidates(read_json(CANDIDATES))

    unique: Dict[str, str] = {}
    for item in candidates:
        code = normalize_code(get_first(item, ["code", "stockCode", "stock_code", "ticker", "symbol", "종목코드"]))
        name = get_first(item, ["name", "stockName", "stock_name", "displayName", "종목명"], code or "-")
        if code and code not in unique:
            unique[code] = name

    quotes: List[LiveQuote] = []
    for idx, (code, name) in enumerate(unique.items(), start=1):
        quote = fetch_naver_quote(code, name)
        quotes.append(quote)
        print(f"[{idx}/{len(unique)}] {code} {name} -> {quote.price} {quote.changeRate} {quote.volume} {quote.status}")
        time.sleep(0.25)

    payload = {
        "version": "CV252_REALTIME_NAVER_COLLECTOR",
        "updatedAt": now_kst(),
        "source": "naver_finance",
        "candidateCount": len(candidates),
        "quoteCount": len(quotes),
        "okCount": sum(1 for q in quotes if q.status == "ok"),
        "partialCount": sum(1 for q in quotes if q.status == "partial"),
        "failCount": sum(1 for q in quotes if q.status == "fail"),
        "startedAt": started_at,
        "quotes": [asdict(q) for q in quotes],
    }

    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {OUT} / quotes={len(quotes)} ok={payload['okCount']} fail={payload['failCount']}")


if __name__ == "__main__":
    main()
