# scripts/news_report_collector_fix_a407.py
# A407: 뉴스/리포트 수집 보강판
# 목적: 네이버 검색 HTML 1개 경로 의존을 제거하고,
# 1) 네이버 모바일 증권 뉴스 API
# 2) 네이버 모바일 종목 페이지 내 뉴스/공시 텍스트
# 3) 네이버 뉴스 검색 HTML
# 4) 네이버 금융 리서치/검색 문맥
# 다중 fallback으로 뉴스/리포트 요약을 채운다.

import json, re, time, math
from pathlib import Path
from datetime import datetime
import requests
from bs4 import BeautifulSoup

DATA = Path("data")
DATA.mkdir(exist_ok=True)

OUT = DATA / "realtime_recommendations_a405.json"
CAND_OUT = DATA / "stock_candidates_ai_scored.json"
SUMMARY_OUT = DATA / "market_scanner_summary.json"
DETAIL_OUT = DATA / "news_report_collector_debug_a407.json"
SCORE_SUMMARY_OUT = DATA / "realtime_score_reason_summary_a406.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 Chrome/124 Mobile Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
    "Referer": "https://m.stock.naver.com/",
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

POSITIVE = ["수주","계약","상향","목표가","증가","흑자","호조","실적","수혜","매수","성장","증설","정책","방산","원전","AI","반도체","선박","LNG","전력","로봇","수출"]
NEGATIVE = ["하락","손실","적자","감소","리스크","부진","매도","하향","취소","소송","규제","경고","둔화","불확실","차질"]

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

def clean_text(t):
    t = re.sub(r"\s+", " ", str(t or "")).strip()
    t = re.sub(r"\[[^\]]{1,20}\]", "", t).strip()
    return t

def dedup(items):
    seen, out = set(), []
    for x in items:
        x = clean_text(x)
        if len(x) < 8:
            continue
        key = re.sub(r"[^가-힣A-Za-z0-9]", "", x)[:80]
        if key and key not in seen:
            seen.add(key)
            out.append(x)
    return out

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

def get_json(url, timeout=15):
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    if r.status_code >= 400:
        raise RuntimeError(f"http {r.status_code}")
    return r.json()

def get_html(url, timeout=15):
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    if r.status_code >= 400:
        raise RuntimeError(f"http {r.status_code}")
    return r.text

def fetch_price(code):
    urls = [
        f"https://m.stock.naver.com/api/stock/{code}/basic",
        f"https://m.stock.naver.com/api/stock/{code}/integration",
        f"https://m.stock.naver.com/domestic/stock/{code}/total",
    ]
    raw = []
    for url in urls:
        try:
            if "/api/" in url:
                data = get_json(url)
                text = json.dumps(data, ensure_ascii=False)
            else:
                text = get_html(url)
            for pat in [
                r'"closePrice"\s*:\s*"([0-9,]+)"',
                r'"now"\s*:\s*"([0-9,]+)"',
                r'"localTradedAt"[^}]*"closePrice"\s*:\s*"([0-9,]+)"',
                r'"tradePrice"\s*:\s*([0-9]+)',
                r'"lastPrice"\s*:\s*"([0-9,]+)"',
            ]:
                for m in re.findall(pat, text):
                    p = si(m)
                    if p and p not in raw:
                        raw.append(p)
            if not raw and not "/api/" in url:
                plain = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
                for m in re.findall(r'([0-9]{1,3}(?:,[0-9]{3})+)', plain[:3000]):
                    p = si(m)
                    if p and p not in raw:
                        raw.append(p)
            for p in raw:
                if in_range(code, p):
                    return p, url, raw[:20]
        except Exception:
            continue
    return 0, "price_failed", raw[:20]

def fetch_news_from_stock_api(code, name):
    items = []
    debug = []
    endpoints = [
        f"https://m.stock.naver.com/api/news/stock/{code}?pageSize=10&page=1",
        f"https://m.stock.naver.com/api/stock/{code}/news?pageSize=10&page=1",
        f"https://m.stock.naver.com/api/news/stock/{code}",
        f"https://api.stock.naver.com/news/stock/{code}?pageSize=10&page=1",
    ]
    for url in endpoints:
        try:
            data = get_json(url)
            debug.append({"url":url, "type":"json", "ok":True})
            stack = [data]
            while stack:
                obj = stack.pop()
                if isinstance(obj, dict):
                    title = obj.get("title") or obj.get("headline") or obj.get("subject") or obj.get("officeName")
                    if title and (name in title or len(str(title)) >= 8):
                        items.append(str(title))
                    for v in obj.values():
                        if isinstance(v, (dict, list)):
                            stack.append(v)
                elif isinstance(obj, list):
                    stack.extend(obj)
        except Exception as e:
            debug.append({"url":url, "ok":False, "error":str(e)[:80]})
    return dedup(items)[:8], debug

def fetch_news_from_search(name):
    items, debug = [], []
    urls = [
        f"https://search.naver.com/search.naver?where=news&sm=tab_jum&query={requests.utils.quote(name)}",
        f"https://m.search.naver.com/search.naver?where=m_news&query={requests.utils.quote(name)}",
        f"https://news.search.naver.com/search.naver?where=news&query={requests.utils.quote(name)}",
    ]
    for url in urls:
        try:
            html = get_html(url)
            soup = BeautifulSoup(html, "html.parser")
            debug.append({"url":url, "ok":True, "chars":len(html)})
            selectors = ["a.news_tit", "a.api_txt_lines", "a.link_tit", "a[href*='n.news.naver.com']", "a"]
            for sel in selectors:
                for a in soup.select(sel)[:50]:
                    t = a.get_text(" ", strip=True)
                    if name in t or any(k in t for k in POSITIVE + NEGATIVE):
                        items.append(t)
                if len(items) >= 5:
                    break
        except Exception as e:
            debug.append({"url":url, "ok":False, "error":str(e)[:80]})
    return dedup(items)[:8], debug

def fetch_news(code, name):
    items1, d1 = fetch_news_from_stock_api(code, name)
    items2, d2 = fetch_news_from_search(name)
    items = dedup(items1 + items2)[:8]
    if not items:
        return "뉴스 수집 결과 없음", 45, [], {"stock_api":d1, "search":d2}
    summary = " / ".join(items[:3])
    score = sentiment_score(summary, 50)
    return summary[:320], score, items, {"stock_api":d1, "search":d2}

def fetch_report_from_naver_finance(code, name):
    items, debug = [], []
    urls = [
        f"https://finance.naver.com/item/news_read.naver?article_id=&office_id=&code={code}",
        f"https://finance.naver.com/research/company_list.naver?searchType=itemCode&itemCode={code}",
        f"https://finance.naver.com/item/coinfo.naver?code={code}",
        f"https://m.stock.naver.com/domestic/stock/{code}/research",
    ]
    for url in urls:
        try:
            html = get_html(url)
            soup = BeautifulSoup(html, "html.parser")
            text = soup.get_text(" ", strip=True)
            debug.append({"url":url, "ok":True, "chars":len(html)})
            for pat in [
                r'[^.。\n]{0,40}목표가[^.。\n]{0,80}',
                r'[^.。\n]{0,40}투자의견[^.。\n]{0,80}',
                r'[^.。\n]{0,40}매수[^.。\n]{0,80}',
                r'[^.。\n]{0,40}리포트[^.。\n]{0,80}',
                r'[^.。\n]{0,40}증권[^.。\n]{0,80}',
            ]:
                items += re.findall(pat, text)
            for a in soup.find_all("a")[:120]:
                t = a.get_text(" ", strip=True)
                if name in t and any(k in t for k in ["목표가","투자의견","매수","리포트","증권"]):
                    items.append(t)
        except Exception as e:
            debug.append({"url":url, "ok":False, "error":str(e)[:80]})
    return dedup(items)[:8], debug

def fetch_report_from_search(name):
    items, debug = [], []
    queries = [
        f"{name} 목표가 증권사",
        f"{name} 리포트 목표가",
        f"{name} 투자의견 매수",
    ]
    for q in queries:
        url = f"https://search.naver.com/search.naver?query={requests.utils.quote(q)}"
        try:
            html = get_html(url)
            soup = BeautifulSoup(html, "html.parser")
            debug.append({"query":q, "ok":True, "chars":len(html)})
            for tag in soup.find_all(["a","span","div"])[:200]:
                t = clean_text(tag.get_text(" ", strip=True))
                if name in t and any(k in t for k in ["목표가","투자의견","매수","리포트","증권","상향","하향"]):
                    items.append(t)
        except Exception as e:
            debug.append({"query":q, "ok":False, "error":str(e)[:80]})
    return dedup(items)[:8], debug

def fetch_report(code, name):
    items1, d1 = fetch_report_from_naver_finance(code, name)
    items2, d2 = fetch_report_from_search(name)
    items = dedup(items1 + items2)[:8]
    if not items:
        return "리포트 수집 결과 없음", 45, [], {"finance":d1, "search":d2}
    summary = " / ".join(items[:3])
    score = sentiment_score(summary, 50)
    return summary[:320], score, items, {"finance":d1, "search":d2}

def fetch_chart(code, current_price):
    try:
        urls = [
            f"https://m.stock.naver.com/api/stock/{code}/price?pageSize=60&page=1",
            f"https://api.stock.naver.com/stock/{code}/price?pageSize=60&page=1",
        ]
        prices = []
        for url in urls:
            try:
                data = get_json(url)
                rows = data if isinstance(data, list) else data.get("priceInfos", []) or data.get("data", [])
                for row in rows:
                    close = si(row.get("closePrice") or row.get("close") or row.get("tradePrice"))
                    if close > 0:
                        prices.append(close)
                if len(prices) >= 20:
                    break
            except Exception:
                continue
        prices = list(reversed(prices[-60:]))
        if len(prices) < 20:
            raise ValueError("not enough chart data")
        ma5 = sum(prices[-5:]) / 5
        ma20 = sum(prices[-20:]) / 20
        ma60 = sum(prices[-60:]) / 60 if len(prices) >= 60 else ma20
        last = prices[-1]
        score = 50
        reasons = []
        if last > ma5 > ma20:
            score += 20; reasons.append("5일선이 20일선 위")
        if last > ma20:
            score += 10; reasons.append("현재가가 20일선 위")
        if ma20 > ma60:
            score += 10; reasons.append("20일선이 60일선 위")
        if last < ma20:
            score -= 15; reasons.append("현재가가 20일선 아래")
        return f"현재가 {last:,}원, MA5 {ma5:,.0f}, MA20 {ma20:,.0f}. " + ", ".join(reasons), max(0,min(100,score)), {"ma5":round(ma5), "ma20":round(ma20), "ma60":round(ma60)}
    except Exception:
        if current_price > 0:
            return f"차트 API 미확인. 현재가 {current_price:,}원 기준 손절선을 보수적으로 산출.", 50, {}
        return "차트 지표 수집 실패", 40, {}

def sentiment_score(text, base=50):
    score = base
    for k in POSITIVE:
        if k in text:
            score += 4
    for k in NEGATIVE:
        if k in text:
            score -= 5
    return max(0, min(100, score))

def round_price(v):
    if v <= 0:
        return 0
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

def get_target(c):
    for k in ["targetMedianPrice","targetPrice","naverTargetPrice","consensusTargetPrice"]:
        v = si(c.get(k,0))
        if v > 0:
            return v
    return 0

def build_price_reason(price, target, score, status):
    if status == "검증필요" or price <= 0:
        return "현재가 수집 실패 또는 정상 범위 이탈로 가격 점수를 낮게 산정했습니다."
    if target <= 0:
        return f"현재가 {price:,}원은 확인됐지만 목표가가 없어 가격 점수는 중립권으로 산정했습니다."
    upside = (target-price)/price*100
    return f"현재가 {price:,}원, 목표가 {target:,}원 기준 상승여력 {upside:.1f}%를 반영해 가격 점수 {score}점으로 산정했습니다."

def build_news_reason(summary, score, count):
    if count <= 0 or "수집 결과 없음" in summary:
        return "종목 관련 뉴스가 충분히 수집되지 않아 뉴스 점수는 중립/보수적으로 산정했습니다."
    pos = [k for k in POSITIVE if k in summary]
    neg = [k for k in NEGATIVE if k in summary]
    bits = [f"수집 기사 {count}건"]
    if pos: bits.append("긍정 키워드 " + ", ".join(pos[:5]))
    if neg: bits.append("부정 키워드 " + ", ".join(neg[:5]))
    return f"{'; '.join(bits)}을 반영해 뉴스 점수 {score}점으로 산정했습니다."

def build_report_reason(summary, score, count):
    if count <= 0 or "수집 결과 없음" in summary:
        return "리포트/목표가 관련 문맥이 충분히 수집되지 않아 리포트 점수는 중립/보수적으로 산정했습니다."
    bits = [f"수집 문맥 {count}건"]
    if "목표가" in summary: bits.append("목표가 언급")
    if "매수" in summary: bits.append("매수 의견 언급")
    if "상향" in summary: bits.append("상향 문맥")
    if "하향" in summary: bits.append("하향 문맥")
    return f"{'; '.join(bits)}을 반영해 리포트 점수 {score}점으로 산정했습니다."

def build_chart_reason(summary, score):
    if not summary or "실패" in summary:
        return "차트 데이터가 부족해 보수적으로 산정했습니다."
    return f"{summary} 이를 반영해 차트 점수 {score}점으로 산정했습니다."

def build_final_reason(price_score, news_score, report_score, chart_score, final_score):
    return f"가격 35%, 뉴스 20%, 리포트 20%, 차트 25% 가중치로 계산했습니다. 가격 {price_score}×0.35 + 뉴스 {news_score}×0.20 + 리포트 {report_score}×0.20 + 차트 {chart_score}×0.25 = {final_score}점."

def main():
    run = datetime.now().isoformat(timespec="seconds")
    base = get_base_candidates()
    result, debug_rows = [], []
    for c in base[:80]:
        code = str(c.get("code") or c.get("stockCode") or "").zfill(6)
        name = str(c.get("name") or c.get("stockName") or "")
        if not code or not name:
            continue
        market = c.get("market","")
        sector = c.get("sector","")
        old_price = si(c.get("currentPrice") or c.get("close") or 0)
        target = get_target(c)

        price, price_source, raw_prices = fetch_price(code)
        if price <= 0 and in_range(code, old_price):
            price = old_price
            price_source = "previous_valid_price"

        if target > 0 and price > 0 and (target < price*0.5 or target > price*3.0):
            target = 0

        status = "정상" if price > 0 else "검증필요"

        news_summary, news_score, news_items, news_debug = fetch_news(code, name)
        report_summary, report_score, report_items, report_debug = fetch_report(code, name)
        chart_summary, chart_score, chart = fetch_chart(code, price)

        price_score = calc_price_score(price, target)
        final_score = round(price_score*0.35 + news_score*0.20 + report_score*0.20 + chart_score*0.25)
        if status == "검증필요":
            final_score = min(final_score, 45)

        realistic = round_price(target*0.80) if target else 0
        observe = round_price(target*0.70) if target else 0
        stop_t = round_price(target*0.60) if target else 0
        chart_stop = round_price(price*0.92) if price else 0
        upside = round((target-price)/price*100, 1) if price and target else 0.0

        recommendation_reason = f"{name}: 현재가 {price:,}원, 목표가 {target:,}원, 뉴스 {news_score}점, 리포트 {report_score}점, 차트 {chart_score}점을 종합해 {final_score}점으로 산출." if price else f"{name}: 가격 검증 필요로 추천 점수를 보수적으로 산출."

        item = dict(c)
        item.update({
            "code": code,
            "name": name,
            "market": market,
            "sector": sector,
            "currentPrice": price if status == "정상" else 0,
            "close": price if status == "정상" else 0,
            "targetMedianPrice": target if status == "정상" else 0,
            "targetPrice": target if status == "정상" else 0,
            "realisticTargetPrice": realistic if status == "정상" else 0,
            "observeTimingPrice": observe if status == "정상" else 0,
            "stopTimingPrice": stop_t if status == "정상" else 0,
            "chartStopPrice": chart_stop if status == "정상" else 0,
            "targetUpsidePercent": upside if status == "정상" else 0.0,
            "priceValidationStatus": status,
            "priceValidationReason": "실시간 가격 수집 성공" if status == "정상" else "실시간 가격 수집 실패/검증 필요",
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
            "priceScoreReason": build_price_reason(price, target, price_score, status),
            "newsScoreReason": build_news_reason(news_summary, news_score, len(news_items)),
            "reportScoreReason": build_report_reason(report_summary, report_score, len(report_items)),
            "chartScoreReason": build_chart_reason(chart_summary, chart_score),
            "finalScoreReason": build_final_reason(price_score, news_score, report_score, chart_score, final_score),
            "chartStopReason": f"현재가 {price:,}원 기준 약 -8% 구간 {chart_stop:,}원." if chart_stop else "현재가 검증 필요",
            "updatedAt": run,
            "priceSource": price_source,
            "newsItems": news_items,
            "reportItems": report_items,
            "chartIndicators": chart,
            "targetEngineVersion": "A407"
        })
        result.append(item)
        debug_rows.append({
            "code": code,
            "name": name,
            "priceSource": price_source,
            "rawPrices": raw_prices,
            "newsCount": len(news_items),
            "reportCount": len(report_items),
            "newsDebug": news_debug,
            "reportDebug": report_debug,
        })
        time.sleep(0.15)

    result.sort(key=lambda x: x.get("realtimeScore", x.get("score",0)), reverse=True)
    save_json(OUT, result)
    save_json(CAND_OUT, result)

    summary = {
        "version": "A407",
        "generatedAt": run,
        "status": "news_report_collector_fix",
        "candidateCount": len(result),
        "priceConnectedCount": sum(1 for x in result if x.get("currentPrice",0)>0),
        "newsSummaryCount": sum(1 for x in result if x.get("newsItems")),
        "reportSummaryCount": sum(1 for x in result if x.get("reportItems")),
        "chartSummaryCount": sum(1 for x in result if x.get("chartSummary")),
        "invalidPriceCandidateCount": sum(1 for x in result if x.get("priceValidationStatus")=="검증필요"),
        "output": "realtime_recommendations_a405.json"
    }
    save_json(SUMMARY_OUT, summary)
    save_json(SCORE_SUMMARY_OUT, {"summary": summary, "top": result[:20]})
    save_json(DETAIL_OUT, {"summary": summary, "debug": debug_rows})
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
