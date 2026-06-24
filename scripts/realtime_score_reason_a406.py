# scripts/realtime_purpose_engine_a405.py
# A406: 주가 + 뉴스 + 리포트 + 차트 지표를 종합해 추천 점수와 추천 이유를 재계산한다.
# 외부 사이트 구조 변경 시 수집 실패할 수 있으므로 실패한 항목은 기존 데이터/fallback을 유지한다.

import json, re, math, statistics, time
from pathlib import Path
from datetime import datetime
import requests
from bs4 import BeautifulSoup

DATA = Path("data")
DATA.mkdir(exist_ok=True)

BASE_FILES = [
    DATA / "stock_candidates_ai_scored.json",
    DATA / "market_scanner_summary.json"
]
OUT = DATA / "realtime_recommendations_a405.json"
SUMMARY_OUT = DATA / "realtime_score_reason_summary_a406.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
}

UNIVERSE = [
    {"code":"042660","name":"한화오션","market":"KOSPI","sector":"조선/방산"},
    {"code":"329180","name":"HD현대중공업","market":"KOSPI","sector":"조선"},
    {"code":"034020","name":"두산에너빌리티","market":"KOSPI","sector":"원전/에너지"},
    {"code":"272210","name":"한화시스템","market":"KOSPI","sector":"방산"},
    {"code":"005930","name":"삼성전자","market":"KOSPI","sector":"반도체"},
    {"code":"000660","name":"SK하이닉스","market":"KOSPI","sector":"반도체"},
    {"code":"047810","name":"한국항공우주","market":"KOSPI","sector":"방산"},
    {"code":"005380","name":"현대차","market":"KOSPI","sector":"자동차"},
    {"code":"000270","name":"기아","market":"KOSPI","sector":"자동차"},
    {"code":"105560","name":"KB금융","market":"KOSPI","sector":"금융"},
    {"code":"035420","name":"NAVER","market":"KOSPI","sector":"인터넷"},
    {"code":"035720","name":"카카오","market":"KOSPI","sector":"인터넷"},
    {"code":"108490","name":"로보티즈","market":"KOSDAQ","sector":"로봇"},
    {"code":"277810","name":"레인보우로보틱스","market":"KOSDAQ","sector":"로봇"},
    {"code":"247540","name":"에코프로비엠","market":"KOSDAQ","sector":"2차전지"},
    {"code":"196170","name":"알테오젠","market":"KOSDAQ","sector":"바이오"},
    {"code":"010140","name":"삼성중공업","market":"KOSPI","sector":"조선"},
    {"code":"068270","name":"셀트리온","market":"KOSPI","sector":"바이오"},
    {"code":"012450","name":"한화에어로스페이스","market":"KOSPI","sector":"방산/항공"},
    {"code":"064350","name":"현대로템","market":"KOSPI","sector":"방산/철도"},
]

PRICE_RANGE = {
    "005930": (30000, 150000),
    "000660": (50000, 700000),
    "005380": (100000, 500000),
    "108490": (10000, 250000),
    "042660": (30000, 300000),
    "329180": (100000, 1500000),
    "034020": (20000, 250000),
    "272210": (20000, 250000),
}

POSITIVE = ["수주","계약","상향","목표가","증가","흑자","호조","실적","수혜","매수","성장","증설","정책","방산","원전","AI","반도체"]
NEGATIVE = ["하락","손실","적자","감소","리스크","부진","매도","하향","취소","소송","규제","경고","둔화"]

def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default

def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def normalize_candidates(raw):
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for k in ["candidates","data","items","stocks","top"]:
            if isinstance(raw.get(k), list):
                return raw[k]
    return []

def get_base_candidates():
    raw = load_json(DATA / "stock_candidates_ai_scored.json", [])
    base = normalize_candidates(raw)
    if base:
        return base
    return UNIVERSE

def si(v):
    try:
        return int(float(str(v).replace(",","").replace("원","").strip()))
    except Exception:
        return 0

def in_range(code, price):
    if price <= 0:
        return False
    lo, hi = PRICE_RANGE.get(code, (1000, 3000000))
    return lo <= price <= hi

def fetch_price(code):
    url = f"https://m.stock.naver.com/domestic/stock/{code}/total"
    try:
        html = requests.get(url, headers=HEADERS, timeout=15).text
        candidates = []
        for pat in [
            r'"closePrice"\s*:\s*"([0-9,]+)"',
            r'"now"\s*:\s*"([0-9,]+)"',
            r'"tradePrice"\s*:\s*([0-9]+)',
            r'"lastPrice"\s*:\s*"([0-9,]+)"',
        ]:
            for m in re.findall(pat, html):
                p = si(m)
                if p and p not in candidates:
                    candidates.append(p)
        text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        for m in re.findall(r'([0-9]{1,3}(?:,[0-9]{3})+)', text[:2500]):
            p = si(m)
            if p and p not in candidates:
                candidates.append(p)
        for p in candidates:
            if in_range(code, p):
                return p, "naver_mobile", candidates[:12]
        return 0, "price_not_valid", candidates[:12]
    except Exception as e:
        return 0, f"price_error:{str(e)[:80]}", []

def fetch_news(name):
    url = f"https://search.naver.com/search.naver?where=news&query={requests.utils.quote(name)}"
    try:
        html = requests.get(url, headers=HEADERS, timeout=15).text
        soup = BeautifulSoup(html, "html.parser")
        texts = []
        for a in soup.select("a.news_tit")[:5]:
            t = a.get_text(" ", strip=True)
            if t and t not in texts:
                texts.append(t)
        if not texts:
            for a in soup.find_all("a")[:80]:
                t = a.get_text(" ", strip=True)
                if name in t and len(t) > 8 and t not in texts:
                    texts.append(t)
                if len(texts) >= 5:
                    break
        blob = " / ".join(texts[:3])
        score = sentiment_score(blob, base=50)
        summary = blob if blob else "뉴스 수집 결과 없음"
        return summary[:240], score, texts[:5]
    except Exception as e:
        return f"뉴스 수집 실패: {str(e)[:60]}", 45, []

def fetch_report(name, code):
    # 공개 리포트 접근은 사이트별 제한이 있어 네이버/검색 결과 텍스트 중심으로 요약한다.
    q = f"{name} 증권사 리포트 목표가"
    url = f"https://search.naver.com/search.naver?query={requests.utils.quote(q)}"
    try:
        html = requests.get(url, headers=HEADERS, timeout=15).text
        soup = BeautifulSoup(html, "html.parser")
        texts = []
        for tag in soup.find_all(["a","span","div"])[:180]:
            t = tag.get_text(" ", strip=True)
            if name in t and any(k in t for k in ["리포트","목표가","투자의견","증권","매수"]):
                t = re.sub(r"\s+", " ", t)
                if 10 < len(t) < 160 and t not in texts:
                    texts.append(t)
            if len(texts) >= 5:
                break
        blob = " / ".join(texts[:3])
        score = sentiment_score(blob, base=50)
        return (blob if blob else "리포트 수집 결과 없음")[:240], score, texts[:5]
    except Exception as e:
        return f"리포트 수집 실패: {str(e)[:60]}", 45, []

def fetch_chart(code, current_price):
    # 네이버 일봉 API는 환경별로 차단될 수 있어 실패 시 현재가 기반 최소 지표를 사용한다.
    try:
        url = f"https://m.stock.naver.com/api/stock/{code}/price?pageSize=60&page=1"
        data = requests.get(url, headers=HEADERS, timeout=15).json()
        prices = []
        for row in data if isinstance(data, list) else data.get("priceInfos", []):
            close = si(row.get("closePrice") or row.get("close") or row.get("tradePrice"))
            if close > 0:
                prices.append(close)
        prices = list(reversed(prices[-60:]))
        if len(prices) < 20:
            raise ValueError("not enough chart data")
        ma5 = sum(prices[-5:]) / 5
        ma20 = sum(prices[-20:]) / 20
        ma60 = sum(prices[-60:]) / 60 if len(prices) >= 60 else ma20
        last = prices[-1]
        chart_score = 50
        reasons = []
        if last > ma5 > ma20:
            chart_score += 20; reasons.append("5일선이 20일선 위")
        if last > ma20:
            chart_score += 10; reasons.append("현재가가 20일선 위")
        if ma20 > ma60:
            chart_score += 10; reasons.append("중기 추세 우상향")
        if last < ma20:
            chart_score -= 15; reasons.append("현재가가 20일선 아래")
        return f"현재가 {last:,}원, MA5 {ma5:,.0f}, MA20 {ma20:,.0f}. " + ", ".join(reasons), max(0,min(100,chart_score)), {"ma5":round(ma5), "ma20":round(ma20), "ma60":round(ma60)}
    except Exception:
        if current_price > 0:
            return f"차트 API 미확인. 현재가 {current_price:,}원 기준 손절선을 보수적으로 산출.", 50, {}
        return "차트 지표 수집 실패", 40, {}

def sentiment_score(text, base=50):
    if not text:
        return base
    score = base
    for k in POSITIVE:
        if k in text: score += 4
    for k in NEGATIVE:
        if k in text: score -= 5
    return max(0, min(100, score))

def round_price(v):
    if v <= 0: return 0
    unit = 500 if v >= 100000 else 100 if v >= 10000 else 10
    return int(round(v/unit)*unit)

def calc_price_score(price, target):
    if price <= 0:
        return 0
    if target <= 0:
        return 45
    upside = (target-price)/price*100
    if upside >= 50: return 90
    if upside >= 30: return 80
    if upside >= 15: return 65
    if upside >= 5: return 55
    return 40

def get_existing_target(c):
    for k in ["targetMedianPrice","targetPrice","naverTargetPrice","consensusTargetPrice"]:
        v = si(c.get(k,0))
        if v > 0:
            return v
    return 0


def build_price_reason(price, target, price_score, status):
    if status == "검증필요" or price <= 0:
        return "현재가 수집이 실패했거나 정상 범위를 벗어나 가격 점수를 낮게 산정했습니다."
    if target <= 0:
        return f"현재가 {price:,}원은 확인됐지만 목표가가 없어 가격 점수는 중립권으로 산정했습니다."
    upside = (target-price)/price*100
    if upside >= 50:
        level = "상승여력이 매우 큼"
    elif upside >= 30:
        level = "상승여력이 큼"
    elif upside >= 15:
        level = "상승여력이 보통 이상"
    elif upside >= 5:
        level = "상승여력이 제한적"
    else:
        level = "상승여력이 낮음"
    return f"현재가 {price:,}원, 목표가 {target:,}원 기준 상승여력 {upside:.1f}%로 {level}에 해당하여 {price_score}점으로 산정했습니다."

def build_news_reason(summary, score):
    if not summary or "수집 결과 없음" in summary or "수집 실패" in summary:
        return "관련 최신 뉴스가 충분히 수집되지 않아 뉴스 점수는 중립 또는 보수적으로 산정했습니다."
    pos = [k for k in POSITIVE if k in summary]
    neg = [k for k in NEGATIVE if k in summary]
    bits = []
    if pos: bits.append("긍정 키워드: " + ", ".join(pos[:5]))
    if neg: bits.append("부정 키워드: " + ", ".join(neg[:5]))
    if not bits: bits.append("뚜렷한 긍·부정 키워드가 제한적")
    return f"뉴스 제목/요약에서 {'; '.join(bits)}이 확인되어 뉴스 점수 {score}점으로 산정했습니다."

def build_report_reason(summary, score):
    if not summary or "수집 결과 없음" in summary or "수집 실패" in summary:
        return "증권사 리포트/목표가 관련 문맥이 충분히 수집되지 않아 리포트 점수는 중립 또는 보수적으로 산정했습니다."
    pos = [k for k in POSITIVE if k in summary]
    neg = [k for k in NEGATIVE if k in summary]
    bits = []
    if "목표가" in summary: bits.append("목표가 관련 문맥")
    if "매수" in summary: bits.append("매수 의견 문맥")
    if pos: bits.append("긍정 키워드 " + ", ".join(pos[:4]))
    if neg: bits.append("부정 키워드 " + ", ".join(neg[:4]))
    if not bits: bits.append("리포트 언급은 있으나 방향성은 제한적")
    return f"리포트/검색 문맥에서 {'; '.join(bits)}이 확인되어 리포트 점수 {score}점으로 산정했습니다."

def build_chart_reason(chart_summary, chart_score):
    if not chart_summary or "실패" in chart_summary:
        return "차트 데이터가 충분하지 않아 차트 점수는 보수적으로 산정했습니다."
    return f"{chart_summary} 이 조건을 기준으로 차트 점수 {chart_score}점으로 산정했습니다."

def build_final_reason(price_score, news_score, report_score, chart_score, final_score):
    return f"최종점수는 가격 35%, 뉴스 20%, 리포트 20%, 차트 25% 가중치로 계산했습니다. 계산값: 가격 {price_score}×0.35 + 뉴스 {news_score}×0.20 + 리포트 {report_score}×0.20 + 차트 {chart_score}×0.25 = {final_score}점."


def main():
    run = datetime.now().isoformat(timespec="seconds")
    base = get_base_candidates()
    out = []
    for idx, c in enumerate(base[:80]):
        code = str(c.get("code") or c.get("stockCode") or "").zfill(6)
        name = str(c.get("name") or c.get("stockName") or "")
        if not code or not name:
            continue
        market = c.get("market","")
        sector = c.get("sector","")
        old_score = si(c.get("score",0))
        old_price = si(c.get("currentPrice") or c.get("close") or 0)
        old_target = get_existing_target(c)

        price, price_source, raw_prices = fetch_price(code)
        if price <= 0:
            price = old_price if in_range(code, old_price) else 0

        target = old_target
        if target > 0 and price > 0 and (target < price*0.5 or target > price*3.0):
            target = 0

        price_status = "정상" if price > 0 else "검증필요"
        news_summary, news_score, news_items = fetch_news(name)
        report_summary, report_score, report_items = fetch_report(name, code)
        chart_summary, chart_score, chart = fetch_chart(code, price)

        price_score = calc_price_score(price, target)
        final_score = round(price_score*0.35 + news_score*0.20 + report_score*0.20 + chart_score*0.25)
        if price_status == "검증필요":
            final_score = min(final_score, 45)

        realistic = round_price(target*0.80) if target else 0
        observe = round_price(target*0.70) if target else 0
        stop_t = round_price(target*0.60) if target else 0
        chart_stop = round_price(price*0.92) if price else 0
        upside = round((target-price)/price*100, 1) if price and target else 0.0

        reason_parts = []
        if price > 0: reason_parts.append(f"현재가 {price:,}원")
        if target > 0: reason_parts.append(f"목표가 {target:,}원, 상승여력 {upside:.1f}%")
        reason_parts.append(f"뉴스 {news_score}점")
        reason_parts.append(f"리포트 {report_score}점")
        reason_parts.append(f"차트 {chart_score}점")
        recommendation_reason = f"{name}: " + ", ".join(reason_parts) + f"을 종합해 {final_score}점으로 산출."

        item = dict(c)
        item.update({
            "code": code, "name": name, "market": market, "sector": sector,
            "currentPrice": price if price_status == "정상" else 0,
            "close": price if price_status == "정상" else 0,
            "targetMedianPrice": target if price_status == "정상" else 0,
            "targetPrice": target if price_status == "정상" else 0,
            "realisticTargetPrice": realistic if price_status == "정상" else 0,
            "observeTimingPrice": observe if price_status == "정상" else 0,
            "stopTimingPrice": stop_t if price_status == "정상" else 0,
            "chartStopPrice": chart_stop if price_status == "정상" else 0,
            "targetUpsidePercent": upside if price_status == "정상" else 0.0,
            "priceValidationStatus": price_status,
            "priceValidationReason": "실시간 가격 수집 성공" if price_status == "정상" else "실시간 가격 수집 실패/검증 필요",
            "score": final_score,
            "realtimeScore": final_score,
            "priceScore": price_score,
            "newsScore": news_score,
            "reportScore": report_score,
            "chartScore": chart_score,
            "newsSummary": news_summary,
            "reportSummary": report_summary,
            "chartSummary": chart_summary,
            "recommendationReason": recommendation_reason,
            "reason": recommendation_reason,
            "priceScoreReason": build_price_reason(price, target, price_score, price_status),
            "newsScoreReason": build_news_reason(news_summary, news_score),
            "reportScoreReason": build_report_reason(report_summary, report_score),
            "chartScoreReason": build_chart_reason(chart_summary, chart_score),
            "finalScoreReason": build_final_reason(price_score, news_score, report_score, chart_score, final_score),
            "chartStopReason": f"현재가 {price:,}원 기준 약 -8% 구간 {chart_stop:,}원." if chart_stop else "현재가 검증 필요",
            "updatedAt": run,
            "priceSource": price_source,
            "rawPrices": raw_prices,
            "newsItems": news_items,
            "reportItems": report_items,
            "chartIndicators": chart,
            "targetEngineVersion": "A406"
        })
        out.append(item)
        time.sleep(0.15)

    out.sort(key=lambda x: x.get("realtimeScore", x.get("score",0)), reverse=True)
    save_json(OUT, out)
    save_json(DATA / "stock_candidates_ai_scored.json", out)

    summary = {
        "version": "A406",
        "generatedAt": run,
        "status": "realtime_purpose_engine",
        "candidateCount": len(out),
        "priceConnectedCount": sum(1 for x in out if x.get("currentPrice",0)>0),
        "newsSummaryCount": sum(1 for x in out if x.get("newsSummary")),
        "reportSummaryCount": sum(1 for x in out if x.get("reportSummary")),
        "chartSummaryCount": sum(1 for x in out if x.get("chartSummary")),
        "invalidPriceCandidateCount": sum(1 for x in out if x.get("priceValidationStatus")=="검증필요"),
        "output": "realtime_recommendations_a405.json"
    }
    save_json(DATA / "market_scanner_summary.json", summary)
    save_json(SUMMARY_OUT, {"summary": summary, "top": out[:20]})
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
