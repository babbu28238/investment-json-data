"""
CV253 live_quotes.json validation lock
- stock_candidates.json과 live_quotes.json의 기본 구조를 점검합니다.
- GitHub Actions 수집 후 병합 가능한 상태인지 빠르게 확인합니다.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "stock_candidates.json"
LIVE = ROOT / "live_quotes.json"
REPORT = ROOT / "live_quotes_validation_report.txt"


def read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"{path.name} not found at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def extract_candidates(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ["candidates", "stocks", "items", "data", "results", "stockCandidates", "recommendations", "rows"]:
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


def main() -> int:
    lines: List[str] = []
    errors: List[str] = []
    warnings: List[str] = []

    try:
        candidate_data = read_json(CANDIDATES)
        candidates = extract_candidates(candidate_data)
    except Exception as exc:
        candidates = []
        errors.append(f"stock_candidates.json 읽기 실패: {exc}")

    try:
        live_data = read_json(LIVE)
    except Exception as exc:
        live_data = {}
        errors.append(f"live_quotes.json 읽기 실패: {exc}")

    candidate_codes: Dict[str, str] = {}
    for item in candidates:
        code = normalize_code(get_first(item, ["code", "stockCode", "stock_code", "ticker", "symbol", "종목코드"]))
        name = get_first(item, ["name", "stockName", "stock_name", "displayName", "종목명"], code or "-")
        if code:
            candidate_codes[code] = name

    quotes_raw = live_data.get("quotes", []) if isinstance(live_data, dict) else []
    quotes = [q for q in quotes_raw if isinstance(q, dict)]
    quote_codes = {normalize_code(q.get("code")): q for q in quotes if normalize_code(q.get("code"))}

    missing_live = [code for code in candidate_codes if code not in quote_codes]
    extra_live = [code for code in quote_codes if code not in candidate_codes]
    ok_count = sum(1 for q in quotes if str(q.get("status", "")).lower() == "ok")
    partial_count = sum(1 for q in quotes if str(q.get("status", "")).lower() == "partial")
    fail_count = sum(1 for q in quotes if str(q.get("status", "")).lower() == "fail")

    if not candidates:
        errors.append("후보 데이터가 0건입니다. stock_candidates.json 구조 또는 파일 위치를 확인하세요.")
    if not quotes:
        errors.append("실시간 quote 데이터가 0건입니다. update_live_quotes.py 실행 결과를 확인하세요.")
    if missing_live:
        warnings.append(f"후보에는 있으나 live_quotes에 없는 종목: {len(missing_live)}건")
    if extra_live:
        warnings.append(f"live_quotes에는 있으나 후보에는 없는 종목: {len(extra_live)}건")
    if quotes and ok_count == 0:
        warnings.append("수집 성공(status=ok) 종목이 0건입니다. 네이버 파싱 또는 네트워크 상태 확인이 필요합니다.")

    lines.append("CV253 LIVE QUOTE VALIDATION REPORT")
    lines.append("=" * 42)
    lines.append(f"candidateCount: {len(candidates)}")
    lines.append(f"candidateCodeCount: {len(candidate_codes)}")
    lines.append(f"quoteCount: {len(quotes)}")
    lines.append(f"okCount: {ok_count}")
    lines.append(f"partialCount: {partial_count}")
    lines.append(f"failCount: {fail_count}")
    lines.append(f"missingLiveCount: {len(missing_live)}")
    lines.append(f"extraLiveCount: {len(extra_live)}")
    lines.append("")

    if warnings:
        lines.append("WARNINGS")
        lines.extend(f"- {w}" for w in warnings)
        lines.append("")
    if errors:
        lines.append("ERRORS")
        lines.extend(f"- {e}" for e in errors)
        lines.append("")

    if missing_live[:20]:
        lines.append("missingLiveSample")
        lines.extend(f"- {code} {candidate_codes.get(code, '')}" for code in missing_live[:20])
        lines.append("")

    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
