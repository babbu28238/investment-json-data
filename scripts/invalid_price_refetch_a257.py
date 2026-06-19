# scripts/invalid_price_refetch_a257.py
# A257: 검증필요 종목 현재가를 네이버 모바일 페이지에서 정밀 재수집
import json, re, time
from pathlib import Path
from datetime import datetime
import requests
from bs4 import BeautifulSoup

DATA = Path("data")
CAND = DATA / "stock_candidates_ai_scored.json"
SUMMARY = DATA / "market_scanner_summary.json"
OUT = DATA / "invalid_price_refetch_a257.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Referer": "https://m.stock.naver.com/",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
}

# 보수적 정상 가격 범위. A253보다 일부 종목 범위를 보정.
PRICE_RANGE = {
    "005930": (30000, 150000),      # 삼성전자
    "000660": (50000, 600000),      # SK하이닉스
    "005380": (100000, 500000),     # 현대차
    "108490": (10000, 200000),      # 로보티즈
    "298040": (100000, 2500000),    # 효성중공업
    "042660": (30000, 300000),
    "272210": (20000, 250000),
    "329180": (100000, 800000),
    "034020": (30000, 250000),
}

def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default

def save(path, data):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def norm(raw):
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for k in ["candidates", "data", "items", "stocks", "top"]:
            if isinstance(raw.get(k), list):
                return raw[k]
    return []

def si(v, default=0):
    try:
        return int(float(str(v).replace(",", "").replace("원", "").strip()))
    except Exception:
        return default

def rp(v):
    if v <= 0:
        return 0
    unit = 500 if v >= 100000 else 100 if v >= 10000 else 10
    return int(round(v / unit) * unit)

def in_range(code, price):
    if price <= 0:
        return False
    lo, hi = PRICE_RANGE.get(code, (1000, 3000000))
    return lo <= price <= hi

def fetch_naver_mobile_price(code):
    url = f"https://m.stock.naver.com/domestic/stock/{code}/total"
    try:
        res = requests.get(url, headers=HEADERS, timeout=20)
        html = res.text
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)

        # 1) JSON 상태값/price 관련 패턴 우선
        candidates = []
        patterns = [
            r'"closePrice"\s*:\s*"([0-9,]+)"',
            r'"compareToPreviousClosePrice"\s*:\s*"[+-]?[0-9,]+"\s*,\s*"closePrice"\s*:\s*"([0-9,]+)"',
            r'"now"\s*:\s*"([0-9,]+)"',
            r'"lastPrice"\s*:\s*"([0-9,]+)"',
            r'"tradePrice"\s*:\s*([0-9]+)',
        ]
        for pat in patterns:
            for m in re.findall(pat, html):
                p = si(m)
                if p > 0 and p not in candidates:
                    candidates.append(p)

        # 2) 텍스트 시작부에서 종목명 다음에 나오는 가격성 숫자
        for m in re.findall(r'([0-9]{1,3}(?:,[0-9]{3})+)', text[:1500]):
            p = si(m)
            if p > 0 and p not in candidates:
                candidates.append(p)

        # 정상 범위 내 첫 값
        for p in candidates:
            if in_range(code, p):
                return p, url, candidates[:20], "accepted"

        return 0, url, candidates[:20], "no_valid_price"
    except Exception as e:
        return 0, url, [], f"error:{str(e)[:120]}"

def fetch_target(code, cur):
    url = f"https://m.stock.naver.com/domestic/stock/{code}/total"
    try:
        html = requests.get(url, headers=HEADERS, timeout=20).text
        text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True) + " " + html[:200000]
        vals = []
        for pat in [
            r"목표주가[^0-9]{0,80}([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{5,7})",
            r"목표가[^0-9]{0,80}([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{5,7})",
            r"컨센서스[^0-9]{0,160}([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{5,7})",
        ]:
            for m in re.findall(pat, text, re.I):
                p = si(m)
                if p >= 10000 and cur > 0 and cur * 0.5 <= p <= cur * 3.0 and p not in vals:
                    vals.append(p)
        return vals[0] if vals else 0, vals
    except Exception:
        return 0, []

run = datetime.now().isoformat(timespec="seconds")
cands = norm(load(CAND, []))
details = []
attempted = recovered = still_invalid = 0

for c in cands:
    if not isinstance(c, dict):
        continue

    code = str(c.get("code") or "").zfill(6)
    name = str(c.get("name") or "")
    status = str(c.get("priceValidationStatus") or "")

    if status != "검증필요":
        continue

    attempted += 1
    price, source, raw_prices, result = fetch_naver_mobile_price(code)

    row = {
        "code": code,
        "name": name,
        "oldStatus": status,
        "refetchPrice": price,
        "rawPrices": raw_prices,
        "source": source,
        "result": result,
    }

    if price > 0:
        target, raw_targets = fetch_target(code, price)
        c["currentPrice"] = price
        c["close"] = price
        c["priceValidationStatus"] = "정상"
        c["priceValidationReason"] = f"{name} 네이버 모바일 현재가 재수집 성공: {price:,}원."
        c["chartStopPrice"] = rp(price * 0.92)
        c["chartStopReason"] = f"차트 기준 손절선: 재검증 현재가 {price:,}원 기준 약 -8% 구간 {c['chartStopPrice']:,}원."
        if target > 0:
            c["targetMedianPrice"] = target
            c["realisticTargetPrice"] = rp(target * 0.80)
            c["observeTimingPrice"] = rp(target * 0.70)
            c["stopTimingPrice"] = rp(target * 0.60)
            c["targetUpsidePercent"] = round((target - price) / price * 100.0, 1)
            c["reportTargetCount"] = 1
            c["reportTargetPricesText"] = f"{target:,}원"
            c["reportTargetReason"] = f"네이버 컨센서스 목표가 {target:,}원 기준. 현재가 {price:,}원 대비 상승여력 {c['targetUpsidePercent']:.1f}%."
        else:
            c["targetMedianPrice"] = 0
            c["realisticTargetPrice"] = 0
            c["observeTimingPrice"] = 0
            c["stopTimingPrice"] = 0
            c["targetUpsidePercent"] = 0.0
            c["reportTargetReason"] = f"{name} 현재가는 재수집 성공, 네이버 목표가는 미확인."
        c["stopGuideReason"] = f"재검증 현재가 기준 차트 손절 {c['chartStopPrice']:,}원. 목표가가 확인되면 중장기 손절도 함께 참고합니다."
        c["invalidPriceUxMessage"] = ""
        recovered += 1
        row["targetPrice"] = target
        row["rawTargets"] = raw_targets
        row["newStatus"] = "정상"
    else:
        c["currentPrice"] = 0
        c["close"] = 0
        c["targetMedianPrice"] = 0
        c["realisticTargetPrice"] = 0
        c["observeTimingPrice"] = 0
        c["stopTimingPrice"] = 0
        c["targetUpsidePercent"] = 0.0
        c["chartStopPrice"] = 0
        c["priceValidationStatus"] = "검증필요"
        c["priceValidationReason"] = f"{name} 네이버 모바일 현재가 재수집 실패. 수동 확인 필요."
        c["invalidPriceUxMessage"] = "가격 재수집 실패: 수동 확인 필요"
        still_invalid += 1
        row["newStatus"] = "검증필요"

    c["targetEngineVersion"] = "A257"
    c["updatedAt"] = run
    details.append(row)
    time.sleep(0.2)

save(CAND, cands)
summary = load(SUMMARY, {})
if not isinstance(summary, dict):
    summary = {}
summary.update({
    "version": "A257",
    "generatedAt": run,
    "status": "invalid_price_refetch",
    "candidateCount": len(cands),
    "invalidRefetchAttemptCount": attempted,
    "invalidRefetchRecoveredCount": recovered,
    "invalidRefetchStillInvalidCount": still_invalid,
    "output": "stock_candidates_ai_scored.json",
})
save(SUMMARY, summary)
save(OUT, {"version": "A257", "generatedAt": run, "summary": summary, "details": details})
print(json.dumps(summary, ensure_ascii=False, indent=2))
