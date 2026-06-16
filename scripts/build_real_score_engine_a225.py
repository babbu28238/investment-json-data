# scripts/build_real_score_engine_a225.py
# HSinvest A225 REAL SCORE ENGINE
# 가격만 연결된 상태에서 벗어나 차트·수급·뉴스 점수를 실제 데이터 기반으로 재계산한다.

import json
from pathlib import Path
from datetime import datetime, timedelta
import math

import numpy as np
import pandas as pd

DATA = Path("data")
CANDIDATES = DATA / "stock_candidates_ai_scored.json"
SUMMARY = DATA / "market_scanner_summary.json"
DETAIL = DATA / "score_engine_detail_a225.json"
PRICE_SUMMARY = DATA / "price_update_summary.json"

NEWS_FILES = [
    DATA / "news_signals.json",
    DATA / "news_data.json",
    DATA / "news_signals_summary.json",
]

def ymd(dt):
    return dt.strftime("%Y%m%d")

def safe_int(v, default=0):
    try:
        if pd.isna(v):
            return default
        return int(float(str(v).replace(",", "")))
    except Exception:
        return default

def safe_float(v, default=0.0):
    try:
        if pd.isna(v):
            return default
        return float(str(v).replace(",", ""))
    except Exception:
        return default

def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def normalize_candidates(raw):
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ["candidates", "data", "items", "stocks", "top"]:
            if isinstance(raw.get(key), list):
                return raw[key]
    return []

def latest_date_range(days=180):
    end = datetime.now()
    start = end - timedelta(days=days)
    return ymd(start), ymd(end)

def calc_rsi(close, period=14):
    close = pd.Series(close).astype(float)
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    value = rsi.iloc[-1]
    return float(value) if not pd.isna(value) else 50.0

def score_chart(stock, code):
    start, end = latest_date_range(220)
    df = stock.get_market_ohlcv_by_date(start, end, code)

    if df is None or df.empty or len(df) < 60:
        return {
            "score": 0,
            "reason": "차트 데이터 부족",
            "indicators": {},
            "close": 0,
            "volume": 0,
            "tradingValue": 0,
            "changeRate": 0.0,
            "priceDate": "",
        }

    df = df.copy()
    close = df["종가"].astype(float)
    volume = df["거래량"].astype(float)

    c = safe_int(close.iloc[-1])
    prev = safe_int(close.iloc[-2]) if len(close) >= 2 else c
    change_rate = round((c / prev - 1) * 100, 2) if prev > 0 else 0.0

    ma5 = close.rolling(5).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1]
    ma120 = close.rolling(120).mean().iloc[-1] if len(close) >= 120 else np.nan
    vol20 = volume.rolling(20).mean().iloc[-1]
    rsi = calc_rsi(close)

    high20 = close.rolling(20).max().iloc[-2] if len(close) >= 21 else close.max()
    ret20 = (c / close.iloc[-20] - 1) * 100 if len(close) >= 20 and close.iloc[-20] > 0 else 0
    ret60 = (c / close.iloc[-60] - 1) * 100 if len(close) >= 60 and close.iloc[-60] > 0 else 0

    score = 0
    reasons = []

    # 35점 만점
    if c > ma20:
        score += 7; reasons.append("종가 20일선 상회")
    if ma20 > ma60:
        score += 7; reasons.append("20일선이 60일선 상회")
    if not pd.isna(ma120) and ma60 > ma120:
        score += 5; reasons.append("60일선이 120일선 상회")
    if c >= high20:
        score += 5; reasons.append("20일 신고가권 돌파")
    if 45 <= rsi <= 70:
        score += 5; reasons.append(f"RSI {rsi:.1f}로 과열 전 구간")
    elif 70 < rsi <= 80:
        score += 2; reasons.append(f"RSI {rsi:.1f} 과열 주의")
    if vol20 > 0 and volume.iloc[-1] >= vol20 * 1.2:
        score += 3; reasons.append("거래량 20일 평균 대비 증가")
    if ret20 > 0 and ret60 > 0:
        score += 3; reasons.append("20일·60일 수익률 동시 양호")

    score = int(min(35, score))
    tv = safe_int(df["거래대금"].iloc[-1]) if "거래대금" in df.columns else c * safe_int(volume.iloc[-1])

    return {
        "score": score,
        "reason": " / ".join(reasons) if reasons else "차트 우위 신호 제한",
        "indicators": {
            "ma5": round(float(ma5), 2),
            "ma20": round(float(ma20), 2),
            "ma60": round(float(ma60), 2),
            "ma120": None if pd.isna(ma120) else round(float(ma120), 2),
            "rsi14": round(float(rsi), 2),
            "ret20": round(float(ret20), 2),
            "ret60": round(float(ret60), 2),
            "volume": safe_int(volume.iloc[-1]),
            "volume20Avg": safe_int(vol20),
            "high20": safe_int(high20),
        },
        "close": c,
        "volume": safe_int(volume.iloc[-1]),
        "tradingValue": tv,
        "changeRate": change_rate,
        "priceDate": str(df.index[-1]).replace("-", "")[:8],
    }

def score_supply(stock, code):
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=90)
    start = ymd(start_dt)
    end = ymd(end_dt)

    score = 0
    reasons = []
    indicators = {}

    try:
        # 투자자별 거래대금: 외국인합계, 기관합계 등
        df = stock.get_market_trading_value_by_date(start, end, code)
        if df is None or df.empty:
            raise ValueError("empty trading value")

        cols = list(df.columns)
        foreign_col = next((c for c in cols if "외국인" in str(c)), None)
        inst_col = next((c for c in cols if "기관" in str(c)), None)
        pension_col = next((c for c in cols if "연기금" in str(c)), None)
        trust_col = next((c for c in cols if "투신" in str(c)), None)
        finance_col = next((c for c in cols if "금융투자" in str(c)), None)

        def sum_last(col, n):
            if not col:
                return 0
            return safe_int(df[col].tail(n).sum())

        foreign5 = sum_last(foreign_col, 5)
        foreign20 = sum_last(foreign_col, 20)
        inst5 = sum_last(inst_col, 5)
        inst20 = sum_last(inst_col, 20)
        pension20 = sum_last(pension_col, 20)
        trust20 = sum_last(trust_col, 20)
        finance20 = sum_last(finance_col, 20)

        indicators = {
            "foreign5": foreign5,
            "foreign20": foreign20,
            "institution5": inst5,
            "institution20": inst20,
            "pension20": pension20,
            "trust20": trust20,
            "finance20": finance20,
            "columns": [str(c) for c in cols],
        }

        # 30점 만점
        if foreign20 > 0:
            score += 7; reasons.append("외국인 20일 순매수")
        if foreign5 > 0:
            score += 4; reasons.append("외국인 5일 순매수")
        if inst20 > 0:
            score += 7; reasons.append("기관 20일 순매수")
        if inst5 > 0:
            score += 4; reasons.append("기관 5일 순매수")
        if pension20 > 0:
            score += 3; reasons.append("연기금 20일 순매수")
        if trust20 > 0:
            score += 2; reasons.append("투신 20일 순매수")
        if finance20 > 0:
            score += 1; reasons.append("금융투자 20일 순매수")
        if foreign20 > 0 and inst20 > 0:
            score += 2; reasons.append("외국인·기관 동시 유입")

        score = int(min(30, score))
    except Exception as e:
        indicators = {"error": str(e)}
        reasons = ["수급 데이터 조회 실패"]
        score = 0

    return {
        "score": score,
        "reason": " / ".join(reasons) if reasons else "수급 우위 신호 제한",
        "indicators": indicators,
    }

def load_news_items():
    items = []
    for path in NEWS_FILES:
        raw = load_json(path, [])
        if isinstance(raw, dict):
            for key in ["items", "news", "signals", "data", "articles"]:
                if isinstance(raw.get(key), list):
                    raw = raw[key]
                    break
        if isinstance(raw, list):
            items.extend([x for x in raw if isinstance(x, dict)])
    return items

def score_news(candidate, news_items):
    code = str(candidate.get("code", "")).zfill(6)
    name = str(candidate.get("name", ""))

    matched = []
    for item in news_items:
        text = json.dumps(item, ensure_ascii=False)
        if code in text or (name and name in text):
            matched.append(item)

    score = 0
    pos = 0
    neg = 0
    titles = []

    positive_words = ["수주", "계약", "실적", "흑자", "증가", "상승", "호재", "목표가", "매수", "증설", "승인", "수혜", "공급"]
    negative_words = ["하락", "적자", "감소", "손실", "리스크", "소송", "제재", "경고", "매도", "부진", "취소"]

    for item in matched[:20]:
        text = json.dumps(item, ensure_ascii=False)
        title = str(item.get("title") or item.get("headline") or item.get("summary") or "")[:80]
        if title:
            titles.append(title)
        p = sum(1 for w in positive_words if w in text)
        n = sum(1 for w in negative_words if w in text)
        pos += p
        neg += n

    if matched:
        score += min(6, len(matched))
        score += min(10, pos * 2)
        score -= min(8, neg * 2)
    score = int(max(0, min(20, score)))

    if matched:
        reason = f"뉴스 {len(matched)}건 매칭, 긍정 키워드 {pos}개, 부정 키워드 {neg}개"
        if titles:
            reason += " / 주요: " + " | ".join(titles[:2])
    else:
        reason = "종목 매칭 뉴스 없음"

    return {
        "score": score,
        "reason": reason,
        "matchedCount": len(matched),
        "positiveKeywordCount": pos,
        "negativeKeywordCount": neg,
        "titles": titles[:5],
    }

def grade(score):
    if score >= 85:
        return "A"
    if score >= 75:
        return "B+"
    if score >= 65:
        return "B"
    if score >= 55:
        return "C+"
    return "C"

def action_label(score, risk_score):
    if score >= 85 and risk_score >= 8:
        return "관찰 후 분할"
    if score >= 75:
        return "눌림 확인"
    if score >= 65:
        return "관심 유지"
    return "대기"

def main():
    from pykrx import stock

    raw = load_json(CANDIDATES, [])
    candidates = normalize_candidates(raw)
    news_items = load_news_items()
    run_id = datetime.now().isoformat(timespec="seconds")

    details = []
    updated = 0
    failed = 0

    for item in candidates:
        if not isinstance(item, dict):
            continue

        code = str(item.get("code") or item.get("stockCode") or item.get("ticker") or "").zfill(6)
        name = str(item.get("name", ""))
        if not code or code == "000000":
            failed += 1
            continue

        try:
            chart = score_chart(stock, code)
        except Exception as e:
            chart = {"score": 0, "reason": f"차트 계산 실패: {e}", "indicators": {}, "close": 0, "volume": 0, "tradingValue": 0, "changeRate": 0.0, "priceDate": ""}

        try:
            supply = score_supply(stock, code)
        except Exception as e:
            supply = {"score": 0, "reason": f"수급 계산 실패: {e}", "indicators": {}}

        news = score_news(item, news_items)

        fundamental_score = 10 if str(item.get("fundamentalReason", "")).strip() else 6
        risk_score = 10
        if "주의" in chart["reason"] or news.get("negativeKeywordCount", 0) >= 2:
            risk_score -= 3
        if chart["score"] <= 5:
            risk_score -= 2
        risk_score = max(0, min(10, risk_score))

        total = int(round(chart["score"] + supply["score"] + news["score"] + fundamental_score + risk_score))
        total = max(0, min(100, total))

        if chart.get("close", 0) > 0:
            item["currentPrice"] = chart["close"]
            item["close"] = chart["close"]
            item["volume"] = chart.get("volume", 0)
            item["tradingValue"] = chart.get("tradingValue", 0)
            item["changeRate"] = chart.get("changeRate", 0.0)
            item["priceDate"] = chart.get("priceDate", "")
            item["priceSource"] = "pykrx_chart_ohlcv"

        item["score"] = total
        item["grade"] = grade(total)
        item["action"] = action_label(total, risk_score)

        item["chartScore"] = chart["score"]
        item["supplyScore"] = supply["score"]
        item["newsScore"] = news["score"]
        item["fundamentalScore"] = fundamental_score
        item["riskScore"] = risk_score

        item["chartIndicators"] = chart.get("indicators", {})
        item["supplyIndicators"] = supply.get("indicators", {})
        item["newsIndicators"] = {
            "matchedCount": news.get("matchedCount", 0),
            "positiveKeywordCount": news.get("positiveKeywordCount", 0),
            "negativeKeywordCount": news.get("negativeKeywordCount", 0),
            "titles": news.get("titles", []),
        }

        item["chartReason"] = f"[차트 {chart['score']}/35] {chart['reason']}"
        item["supplyReason"] = f"[수급 {supply['score']}/30] {supply['reason']}"
        item["newsReason"] = f"[뉴스 {news['score']}/20] {news['reason']}"
        item["fundamentalReason"] = f"[기본 {fundamental_score}/10] 기존 펀더멘털 문장 및 업종 흐름 반영"
        item["riskReason"] = f"[리스크 {risk_score}/10] 차트 과열·부정 뉴스·데이터 부족 여부 반영"

        detail = (
            f"{name}({code}) 최종점수 {total}점({item['grade']}). "
            f"산식: 차트 {chart['score']}/35 + 수급 {supply['score']}/30 + 뉴스 {news['score']}/20 "
            f"+ 기본 {fundamental_score}/10 + 리스크 {risk_score}/10. "
            f"차트 근거: {chart['reason']}. "
            f"수급 근거: {supply['reason']}. "
            f"뉴스 근거: {news['reason']}."
        )
        item["reasonDetail"] = detail
        item["detailReport"] = detail
        item["reason"] = detail
        item["scoreEngineVersion"] = "A225"
        item["updatedAt"] = run_id

        details.append({
            "code": code,
            "name": name,
            "totalScore": total,
            "chartScore": chart["score"],
            "supplyScore": supply["score"],
            "newsScore": news["score"],
            "fundamentalScore": fundamental_score,
            "riskScore": risk_score,
            "price": item.get("currentPrice", 0),
            "chartIndicators": chart.get("indicators", {}),
            "supplyIndicators": supply.get("indicators", {}),
            "newsIndicators": item["newsIndicators"],
        })
        updated += 1

    candidates = [x for x in candidates if isinstance(x, dict)]
    candidates.sort(key=lambda x: int(x.get("score", 0)), reverse=True)

    CANDIDATES.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = load_json(SUMMARY, {})
    if not isinstance(summary, dict):
        summary = {}
    summary.update({
        "version": "A225",
        "generatedAt": run_id,
        "candidateCount": len(candidates),
        "scoreUpdatedCount": updated,
        "scoreFailedCount": failed,
        "priceCount": sum(1 for x in candidates if safe_int(x.get("currentPrice", x.get("close", 0))) > 0),
        "chartScoreCount": sum(1 for x in candidates if safe_int(x.get("chartScore", 0)) > 0),
        "supplyScoreCount": sum(1 for x in candidates if safe_int(x.get("supplyScore", 0)) > 0),
        "newsScoreCount": sum(1 for x in candidates if safe_int(x.get("newsScore", 0)) > 0),
        "status": "real_score_engine",
        "scoreFormula": "chart35+supply30+news20+fundamental10+risk10",
        "output": "stock_candidates_ai_scored.json",
    })
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    PRICE_SUMMARY.write_text(json.dumps({
        "version": "A225",
        "generatedAt": run_id,
        "priceCount": summary["priceCount"],
        "source": "pykrx_chart_ohlcv",
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    DETAIL.write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8")

    print(summary)

if __name__ == "__main__":
    main()
