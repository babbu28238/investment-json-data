# scripts/merge_news_signals_into_candidates_a236.py
# HSinvest A236 NEWS MERGE ENGINE
# news_data.json / news_signals.json / news_signals_summary.json을 후보 JSON에 병합한다.

import json
from pathlib import Path
from datetime import datetime

DATA = Path("data")
CANDIDATES = DATA / "stock_candidates_ai_scored.json"
SUMMARY = DATA / "market_scanner_summary.json"
MERGE_SUMMARY = DATA / "news_merge_summary_a236.json"

NEWS_FILES = [
    DATA / "news_signals.json",
    DATA / "news_data.json",
    DATA / "news_signals_summary.json",
]

POSITIVE = [
    "수주", "계약", "공급", "승인", "실적", "흑자", "증가", "상승", "호재", "목표가",
    "매수", "증설", "수혜", "협력", "개선", "턴어라운드", "인상", "신규", "진출"
]
NEGATIVE = [
    "하락", "적자", "감소", "손실", "리스크", "소송", "제재", "경고", "매도",
    "부진", "취소", "지연", "압박", "과징금", "악재"
]

def safe_int(v, default=0):
    try:
        return int(float(str(v).replace(",", "")))
    except Exception:
        return default

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

def normalize_candidates(raw):
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ["candidates", "data", "items", "stocks", "top"]:
            if isinstance(raw.get(key), list):
                return raw[key]
    return []

def normalize_news(raw):
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ["items", "news", "signals", "data", "articles", "results"]:
            if isinstance(raw.get(key), list):
                return raw[key]
        # dict 자체가 종목별 뉴스 묶음일 수 있음
        arr = []
        for k, v in raw.items():
            if isinstance(v, list):
                for x in v:
                    if isinstance(x, dict):
                        y = dict(x)
                        y.setdefault("groupKey", k)
                        arr.append(y)
        if arr:
            return arr
    return []

def load_news_items():
    items = []
    for path in NEWS_FILES:
        raw = load_json(path, [])
        for item in normalize_news(raw):
            if isinstance(item, dict):
                item = dict(item)
                item["_sourceFile"] = path.name
                items.append(item)
    return items

def text_of(item):
    return json.dumps(item, ensure_ascii=False)

def title_of(item):
    for key in ["title", "headline", "subject", "summary", "content", "name"]:
        v = item.get(key)
        if v:
            return str(v).strip()
    return text_of(item)[:90]

def match_news(candidate, news_items):
    code = str(candidate.get("code") or "").zfill(6)
    name = str(candidate.get("name") or "")
    aliases = set([code, name])
    # 일부 종목명 공백/지주/보통주 변형 대응
    if name:
        aliases.add(name.replace(" ", ""))
        aliases.add(name.replace("지주", ""))
        aliases.add(name.replace("보통주", ""))

    matched = []
    for item in news_items:
        text = text_of(item)
        if any(a and a in text for a in aliases):
            matched.append(item)
    return matched

def score_news(matched):
    pos = 0
    neg = 0
    titles = []

    for item in matched[:30]:
        text = text_of(item)
        pos += sum(1 for w in POSITIVE if w in text)
        neg += sum(1 for w in NEGATIVE if w in text)
        t = title_of(item)
        if t:
            titles.append(t[:90])

    score = 0
    if matched:
        score += min(6, len(matched))
        score += min(12, pos * 2)
        score -= min(8, neg * 2)

    score = max(0, min(20, int(score)))

    if matched:
        reason = f"뉴스 {len(matched)}건 매칭, 긍정 키워드 {pos}개, 부정 키워드 {neg}개"
        if titles:
            reason += " / 주요: " + " | ".join(titles[:2])
    else:
        reason = "종목 매칭 뉴스 없음"

    return score, reason, {
        "matchedCount": len(matched),
        "positiveKeywordCount": pos,
        "negativeKeywordCount": neg,
        "titles": titles[:5],
        "sources": [x.get("_sourceFile", "") for x in matched[:10]],
    }

def grade(total):
    if total >= 85:
        return "A"
    if total >= 75:
        return "B+"
    if total >= 65:
        return "B"
    if total >= 55:
        return "C+"
    return "C"

def recompute(item):
    chart = safe_int(item.get("chartScore", 0))
    supply = safe_int(item.get("supplyScore", 0))
    news = safe_int(item.get("newsScore", 0))
    fundamental = safe_int(item.get("fundamentalScore", item.get("macroScore", 0)))
    risk = safe_int(item.get("riskScore", 0))
    total = max(0, min(100, chart + supply + news + fundamental + risk))
    item["score"] = total
    item["grade"] = grade(total)

def main():
    run_id = datetime.now().isoformat(timespec="seconds")
    candidates = normalize_candidates(load_json(CANDIDATES, []))
    news_items = load_news_items()

    merged = 0
    positive = 0
    details = []

    for item in candidates:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or item.get("stockCode") or item.get("ticker") or "").zfill(6)
        name = item.get("name", "")

        matched = match_news(item, news_items)
        score, reason, indicators = score_news(matched)

        item["newsScore"] = score
        item["newsReason"] = f"[뉴스 {score}/20] {reason}"
        item["newsIndicators"] = indicators
        item["newsEngineVersion"] = "A236"
        item["updatedAt"] = run_id

        recompute(item)

        item["reasonDetail"] = (
            f"{name}({code}) 최종점수 {item.get('score', 0)}점({item.get('grade', '')}). "
            f"산식: 차트 {item.get('chartScore', 0)}/35 + 수급 {item.get('supplyScore', 0)}/30 + "
            f"뉴스 {item.get('newsScore', 0)}/20 + 기본 {item.get('fundamentalScore', item.get('macroScore', 0))}/10 + "
            f"리스크 {item.get('riskScore', 0)}/10. 뉴스 근거: {reason}. 수급 근거: {item.get('supplyReason', '')}."
        )
        item["detailReport"] = item["reasonDetail"]
        item["reason"] = item["reasonDetail"]

        if matched:
            merged += 1
        if score > 0:
            positive += 1

        details.append({
            "code": code,
            "name": name,
            "newsScore": score,
            "reason": reason,
            "indicators": indicators,
            "matchedCount": len(matched),
            "score": item.get("score", 0),
            "grade": item.get("grade", ""),
        })

    candidates = [x for x in candidates if isinstance(x, dict)]
    candidates.sort(key=lambda x: int(x.get("score", 0)), reverse=True)
    save_json(CANDIDATES, candidates)

    summary = load_json(SUMMARY, {})
    if not isinstance(summary, dict):
        summary = {}

    summary.update({
        "version": "A236",
        "generatedAt": run_id,
        "status": "news_merge_engine",
        "candidateCount": len(candidates),
        "newsItemCount": len(news_items),
        "newsMergedCount": merged,
        "newsScoreCount": positive,
        "output": "stock_candidates_ai_scored.json",
    })
    save_json(SUMMARY, summary)
    save_json(MERGE_SUMMARY, {
        "version": "A236",
        "generatedAt": run_id,
        "summary": summary,
        "details": details,
        "newsSample": news_items[:5],
    })

    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
