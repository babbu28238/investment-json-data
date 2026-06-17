# scripts/connect_search_real_data_a252.py
# A252: 검색 종목 조회 풀에 현재가/목표가/상승여력/손절선 연결
import json, re, time
from pathlib import Path
from datetime import datetime, timedelta
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup

try:
    from pykrx import stock
except Exception:
    stock = None

DATA = Path("data")
CAND = DATA / "stock_candidates_ai_scored.json"
LOOKUP = DATA / "all_stock_lookup_a251.json"
SUMMARY = DATA / "market_scanner_summary.json"
OUT = DATA / "search_real_data_a252.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Referer": "https://m.stock.naver.com/",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

def load(path, default):
    try: return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception: return default

def save(path, data):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def norm(raw):
    if isinstance(raw, list): return raw
    if isinstance(raw, dict):
        for k in ["candidates","data","items","stocks","top"]:
            if isinstance(raw.get(k), list): return raw[k]
    return []

def si(v, d=0):
    try: return int(float(str(v).replace(",", "").replace("원", "").strip()))
    except Exception: return d

def rp(v):
    if v <= 0: return 0
    unit = 500 if v >= 100000 else 100 if v >= 10000 else 10
    return int(round(v / unit) * unit)

def recent_dates(days=12):
    today = datetime.now()
    for i in range(days):
        yield (today - timedelta(days=i)).strftime("%Y%m%d")

def pykrx_price(code):
    if stock is None:
        return 0, "pykrx_unavailable"
    for d in recent_dates():
        try:
            df = stock.get_market_ohlcv_by_ticker(d)
            if code in df.index:
                close = int(df.loc[code]["종가"])
                if close > 0:
                    return close, f"pykrx:{d}"
        except Exception:
            pass
    return 0, "pykrx_empty"

def naver_price(code):
    url = f"https://m.stock.naver.com/domestic/stock/{code}/total"
    try:
        html = requests.get(url, headers=HEADERS, timeout=20).text
        text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        # 첫 영역의 현재가성 숫자 후보. 너무 느슨하므로 fallback으로만 사용.
        nums = []
        for m in re.findall(r"([0-9]{1,3}(?:,[0-9]{3})+)", text[:2500]):
            p = si(m)
            if p >= 1000:
                nums.append(p)
        return (nums[0] if nums else 0), url
    except Exception:
        return 0, url

def extract_target(code, cur):
    url = f"https://m.stock.naver.com/domestic/stock/{code}/total"
    try:
        html = requests.get(url, headers=HEADERS, timeout=20).text
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True) + " " + html[:200000]
        pats = [
            r"목표주가[^0-9]{0,80}([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{5,7})",
            r"목표가[^0-9]{0,80}([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{5,7})",
            r"컨센서스[^0-9]{0,160}([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{5,7})",
        ]
        vals = []
        for pat in pats:
            for m in re.findall(pat, text, re.I):
                p = si(m)
                if p >= 10000 and (cur <= 0 or cur * 0.5 <= p <= cur * 3.0) and p not in vals:
                    vals.append(p)
        return (vals[0] if vals else 0), vals, url
    except Exception:
        return 0, [], url

def load_lookup_items():
    lookup = load(LOOKUP, {})
    items = lookup.get("items", []) if isinstance(lookup, dict) else []
    if items:
        return items
    # fallback: use existing candidates
    return [
        {"code": str(x.get("code","")).zfill(6), "name": x.get("name",""), "market": x.get("market",""), "sector": x.get("sector","")}
        for x in norm(load(CAND, [])) if isinstance(x, dict)
    ]

run = datetime.now().isoformat(timespec="seconds")
existing = {str(x.get("code","")).zfill(6): x for x in norm(load(CAND, [])) if isinstance(x, dict)}
items = load_lookup_items()

out = []
details = []
price_count = target_count = 0

for item in items:
    code = str(item.get("code","")).zfill(6)
    name = item.get("name","")
    if not code or code == "000000" or not name:
        continue

    base = dict(existing.get(code, {}))
    base.setdefault("code", code)
    base.setdefault("name", name)
    base.setdefault("market", item.get("market",""))
    base.setdefault("sector", item.get("sector",""))
    base.setdefault("grade", "조회")
    base.setdefault("score", 0)

    price, price_source = pykrx_price(code)
    if price <= 0:
        price, price_source = naver_price(code)
    if price > 0:
        base["currentPrice"] = price
        base["close"] = price
        price_count += 1

    target, raw_targets, target_source = extract_target(code, price)
    if target > 0:
        target_count += 1
        base["targetMedianPrice"] = target
        base["realisticTargetPrice"] = rp(target * 0.80)
        base["observeTimingPrice"] = rp(target * 0.70)
        base["stopTimingPrice"] = rp(target * 0.60)
        upside = ((target - price) / price * 100.0) if price > 0 else 0
        base["targetUpsidePercent"] = round(upside, 1)
        base["reportTargetCount"] = 1
        base["reportTargetPricesText"] = f"{target:,}원"
        base["reportTargetReason"] = f"네이버 컨센서스 목표가 {target:,}원 기준. 현재가 {price:,}원 대비 상승여력 {upside:.1f}%."
    if price > 0:
        chart_stop = rp(price * 0.92)
        base["chartStopPrice"] = chart_stop
        base["chartStopReason"] = f"차트 기준 손절선: 현재가 {price:,}원 기준 약 -8% 구간 {chart_stop:,}원."
    base["lookupSource"] = "A252 검색 실데이터"
    base["isExternalLookup"] = False
    base["targetEngineVersion"] = "A252"
    base["updatedAt"] = run
    base["reason"] = base.get("reason") or f"{name} 검색 실데이터 연결 결과입니다."

    out.append(base)
    details.append({
        "code": code, "name": name, "price": price, "priceSource": price_source,
        "targetPrice": target, "rawTargets": raw_targets, "targetSource": target_source,
        "chartStopPrice": base.get("chartStopPrice", 0)
    })
    time.sleep(0.15)

out.sort(key=lambda x: int(x.get("score", 0)), reverse=True)
save(CAND, out)
summary = load(SUMMARY, {})
if not isinstance(summary, dict): summary = {}
summary.update({
    "version": "A252",
    "generatedAt": run,
    "status": "search_real_data",
    "candidateCount": len(out),
    "searchLookupCount": len(items),
    "searchPriceConnectedCount": price_count,
    "searchTargetConnectedCount": target_count,
    "output": "stock_candidates_ai_scored.json",
})
save(SUMMARY, summary)
save(OUT, {"version": "A252", "generatedAt": run, "summary": summary, "details": details})
print(json.dumps(summary, ensure_ascii=False, indent=2))
