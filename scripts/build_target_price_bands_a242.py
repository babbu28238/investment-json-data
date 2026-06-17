# scripts/build_target_price_bands_a242.py
# A242: A241에서 candidateCount 0으로 stock_candidates를 비우는 문제 방지
import json, re, statistics, sys
from pathlib import Path
from datetime import datetime

DATA = Path("data")
CANDIDATES = DATA / "stock_candidates_ai_scored.json"
SUMMARY = DATA / "market_scanner_summary.json"
OUT = DATA / "target_price_bands_a242.json"

CANDIDATE_SOURCES = [
    DATA / "stock_candidates_ai_scored.json",
    DATA / "stock_candidates.json",
    DATA / "market_candidates.json",
    DATA / "market_universe.json",
    DATA / "final_stock_candidates.json",
    DATA / "final_stock_candidates_a207.json",
    DATA / "ai_scored_candidates.json",
]

SCAN_PATTERNS = [
    "*report*.json", "*reports*.json", "*research*.json", "*target*.json",
    "*consensus*.json", "news_data.json", "news_signals.json", "stock_candidates_ai_scored.json"
]

PRICE_PATTERNS = [
    re.compile(r"(?:목표주가|목표가|TP|target price|target)[^0-9]{0,30}([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,7})", re.I),
    re.compile(r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,7})\s*원[^\n]{0,25}(?:목표주가|목표가|TP)", re.I),
]

def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def save_json(path, data):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def normalize_list(raw):
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ["candidates", "data", "items", "stocks", "top", "universe"]:
            if isinstance(raw.get(key), list):
                return raw[key]
    return []

def load_candidates_guarded():
    tried = []
    for path in CANDIDATE_SOURCES:
        raw = load_json(path, None)
        arr = normalize_list(raw)
        tried.append({"path": str(path), "count": len(arr)})
        # 종목코드가 있는 dict만 후보로 인정
        valid = []
        for x in arr:
            if isinstance(x, dict):
                code = str(x.get("code") or x.get("stockCode") or x.get("ticker") or "").zfill(6)
                name = str(x.get("name") or "")
                if code and code != "000000" and name:
                    y = dict(x)
                    y.setdefault("code", code)
                    y.setdefault("name", name)
                    valid.append(y)
        if valid:
            return valid, str(path), tried
    return [], "", tried

def safe_int(v, default=0):
    try:
        return int(float(str(v).replace(",", "").replace("원", "").strip()))
    except Exception:
        return default

def round_price(v):
    return int(round(v / 100.0) * 100) if v > 0 else 0

def extract_prices(text):
    found = []
    for pat in PRICE_PATTERNS:
        for m in pat.findall(text):
            p = safe_int(m)
            if 1000 <= p <= 3000000:
                found.append(p)
    return found

def file_texts():
    seen, out = set(), []
    for pattern in SCAN_PATTERNS:
        for path in DATA.glob(pattern):
            if path in seen or not path.exists():
                continue
            seen.add(path)
            try:
                out.append((path.name, path.read_text(encoding="utf-8")))
            except Exception:
                pass
    return out

def aliases(c):
    code = str(c.get("code") or c.get("stockCode") or c.get("ticker") or "").zfill(6)
    name = str(c.get("name") or "")
    arr = {code, name, name.replace(" ", "")}
    if name.endswith("지주"):
        arr.add(name.replace("지주", ""))
    return [x for x in arr if x]

def existing_target_prices(c):
    vals = []
    for key in [
        "targetPrice", "target", "목표가", "목표주가", "consensusTargetPrice",
        "reportTargetPrice", "target_price", "medianTargetPrice"
    ]:
        p = safe_int(c.get(key))
        if 1000 <= p <= 3000000:
            vals.append(p)
    # 문자열 안의 목표가도 추출
    for key in ["reason", "detailReport", "reasonDetail", "newsReason", "fundamentalReason"]:
        txt = str(c.get(key) or "")
        vals.extend(extract_prices(txt))
    return vals

def main():
    run_id = datetime.now().isoformat(timespec="seconds")
    candidates, source, tried = load_candidates_guarded()
    texts = file_texts()

    if not candidates:
        summary = load_json(SUMMARY, {})
        if not isinstance(summary, dict):
            summary = {}
        summary.update({
            "version": "A242",
            "generatedAt": run_id,
            "status": "target_price_source_empty_guard",
            "candidateCount": 0,
            "targetPriceCandidateCount": 0,
            "candidateSource": "",
            "candidateSourcesTried": tried,
            "message": "후보 JSON이 비어 있어 stock_candidates_ai_scored.json을 덮어쓰지 않았습니다."
        })
        save_json(SUMMARY, summary)
        save_json(OUT, {"version": "A242", "generatedAt": run_id, "summary": summary, "details": []})
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        raise SystemExit(0)

    details, updated = [], 0
    for c in candidates:
        code = str(c.get("code") or c.get("stockCode") or c.get("ticker") or "").zfill(6)
        name = str(c.get("name") or "")
        found, sources = [], []

        for p in existing_target_prices(c):
            found.append(p)
            sources.append({"source": "candidate_existing", "price": p, "snippet": "existing candidate field/text"})

        a_list = aliases(c)
        for fname, txt in texts:
            if not any(a and a in txt for a in a_list):
                continue
            for a in a_list:
                start = 0
                while a:
                    idx = txt.find(a, start)
                    if idx == -1:
                        break
                    sn = txt[max(0, idx - 350): idx + 800]
                    for p in extract_prices(sn):
                        found.append(p)
                        sources.append({"source": fname, "price": p, "snippet": sn[:260]})
                    start = idx + len(a)

        uniq = []
        for p in found:
            if p not in uniq:
                uniq.append(p)

        if uniq:
            med = int(statistics.median(uniq))
            realistic = round_price(med * 0.80)
            observe = round_price(med * 0.70)
            stop = round_price(med * 0.60)
            c["targetMedianPrice"] = med
            c["realisticTargetPrice"] = realistic
            c["observeTimingPrice"] = observe
            c["stopTimingPrice"] = stop
            c["reportTargetCount"] = len(uniq)
            c["reportTargetPricesText"] = ", ".join(f"{p:,}원" for p in sorted(uniq))
            c["reportTargetReason"] = f"리포트 목표주가 {len(uniq)}건 중앙값 {med:,}원 기준: 현실목표 {realistic:,}원(80%), 관찰 {observe:,}원(70%), 손절 {stop:,}원(60%)."
            c["targetEngineVersion"] = "A242"
            c["updatedAt"] = run_id
            updated += 1
        else:
            c["targetEngineVersion"] = "A242"

        details.append({
            "code": code,
            "name": name,
            "prices": sorted(uniq),
            "median": c.get("targetMedianPrice", 0),
            "realisticTargetPrice": c.get("realisticTargetPrice", 0),
            "observeTimingPrice": c.get("observeTimingPrice", 0),
            "stopTimingPrice": c.get("stopTimingPrice", 0),
            "sources": sources[:10],
        })

    candidates.sort(key=lambda x: int(x.get("score", 0)), reverse=True)
    save_json(CANDIDATES, candidates)

    summary = load_json(SUMMARY, {})
    if not isinstance(summary, dict):
        summary = {}
    summary.update({
        "version": "A242",
        "generatedAt": run_id,
        "status": "target_price_bands_source_guarded",
        "candidateCount": len(candidates),
        "targetPriceCandidateCount": updated,
        "candidateSource": source,
        "candidateSourcesTried": tried,
        "output": "stock_candidates_ai_scored.json",
    })
    save_json(SUMMARY, summary)
    save_json(OUT, {"version": "A242", "generatedAt": run_id, "summary": summary, "details": details})
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
