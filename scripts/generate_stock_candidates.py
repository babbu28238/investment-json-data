# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from pykrx import stock

OUTPUT_JSON = "stock_candidates.json"
SUMMARY_JSON = "v97_generation_summary.json"
ERROR_LOG = "v97_collection_errors.txt"
REPORT_HINTS_CSV = "report_hints.csv"

LOOKBACK_DAYS = 180
SLEEP_SECONDS = 0.12
DISABLE_FLOW_QUERY = True


def ymd(dt):
    return dt.strftime("%Y%m%d")


def safe_float(v, d=0.0):
    try:
        if v is None or pd.isna(v):
            return d
        return float(v)
    except Exception:
        return d


def safe_int(v, d=0):
    try:
        if v is None or pd.isna(v):
            return d
        return int(float(v))
    except Exception:
        return d


def safe_bool(v):
    return str(v).strip().lower() in ["true", "1", "yes", "y", "상향", "o", "ok"]


def norm(code):
    return str(code).strip().zfill(6)


def recent_market_date(code="005930"):
    today = datetime.today()
    for i in range(20):
        d = today - timedelta(days=i)
        try:
            df = stock.get_market_ohlcv_by_date(ymd(d), ymd(d), code)
            if df is not None and not df.empty:
                return ymd(d)
        except Exception:
            pass
    raise RuntimeError("최근 거래일을 찾지 못했습니다.")


def rsi(close, period=14):
    close = pd.Series(close).astype(float)
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    rs = gain.rolling(period).mean() / loss.rolling(period).mean().replace(0, np.nan)
    val = 100 - (100 / (1 + rs))
    return safe_float(val.iloc[-1], 50)


def macd(close):
    close = pd.Series(close).astype(float)
    m = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    s = m.ewm(span=9, adjust=False).mean()
    return safe_float(m.iloc[-1]), safe_float(s.iloc[-1])


def cloud_breakout(df):
    if df is None or len(df) < 60:
        return False
    high = df["고가"].astype(float)
    low = df["저가"].astype(float)
    close = df["종가"].astype(float)
    conv = (high.rolling(9).max() + low.rolling(9).min()) / 2
    base = (high.rolling(26).max() + low.rolling(26).min()) / 2
    span_a = (conv + base) / 2
    span_b = (high.rolling(52).max() + low.rolling(52).min()) / 2
    top = max(safe_float(span_a.iloc[-1]), safe_float(span_b.iloc[-1]))
    return safe_float(close.iloc[-1]) > top and top > 0


def weekly_breakout(df):
    try:
        w = df.copy()
        w.index = pd.to_datetime(w.index)
        wk = pd.DataFrame()
        wk["시가"] = w["시가"].resample("W-FRI").first()
        wk["고가"] = w["고가"].resample("W-FRI").max()
        wk["저가"] = w["저가"].resample("W-FRI").min()
        wk["종가"] = w["종가"].resample("W-FRI").last()
        return cloud_breakout(wk.dropna())
    except Exception:
        return False


def grade(score):
    if score >= 88:
        return "S"
    if score >= 78:
        return "A"
    if score >= 66:
        return "B"
    if score >= 52:
        return "C"
    return "D"


def make_scores(price_chg, rsi_val, macd_val, macd_sig, ma20, ma60, price, wb, db, reports, target_up):
    technical = 40
    if price > ma20 > 0:
        technical += 8
    if price > ma60 > 0:
        technical += 8
    if wb:
        technical += 10
    if db:
        technical += 6
    if macd_val > macd_sig:
        technical += 6
    if 45 <= rsi_val <= 70:
        technical += 6
    elif rsi_val > 80:
        technical -= 6
    if price_chg > 0:
        technical += 3
    if price_chg > 7:
        technical -= 4

    technical = int(max(0, min(80, technical)))
    flow = 0
    issue = min(6, reports * 2) + (4 if target_up else 0)
    issue = int(max(0, min(10, issue)))
    total = int(max(0, min(100, technical + flow + issue)))
    return technical, flow, issue, total


def make_recent_issue(base, wb, db, reports):
    parts = []
    if wb:
        parts.append("주봉 구름대 돌파")
    if db:
        parts.append("일봉 구름대 돌파")
    parts.append("수급 조회 비활성화")
    if reports > 0:
        parts.append(f"리포트 {reports}건")
    return (base if base else "이슈 확인 필요") + " / " + ", ".join(parts)


def load_hints():
    if not Path(REPORT_HINTS_CSV).exists():
        raise FileNotFoundError("report_hints.csv 파일이 없습니다.")
    df = pd.read_csv(REPORT_HINTS_CSV, dtype={"code": str})
    hints = {}
    for _, r in df.iterrows():
        code = norm(r["code"])
        hints[code] = {
            "name": str(r.get("name", code)).strip(),
            "market": str(r.get("market", "KOSPI")).strip(),
            "industry": str(r.get("industry", "미분류")).strip(),
            "reportCount": safe_int(r.get("reportCount", 0)),
            "targetPriceUp": safe_bool(r.get("targetPriceUp", False)),
            "recentIssue": str(r.get("recentIssue", "")).strip() if not pd.isna(r.get("recentIssue", "")) else "",
        }
    return hints


def generate_stock_candidates():
    hints = load_hints()
    base_date = recent_market_date()
    print("관심종목 수:", len(hints))
    print("분석 기준 거래일:", base_date)

    items = []
    errors = []
    end = datetime.strptime(base_date, "%Y%m%d")
    start = end - timedelta(days=LOOKBACK_DAYS)

    for idx, (code, h) in enumerate(hints.items(), 1):
        try:
            ohlcv = stock.get_market_ohlcv_by_date(ymd(start), base_date, code)
            if ohlcv is None or ohlcv.empty or len(ohlcv) < 60:
                raise RuntimeError("OHLCV 데이터 부족")

            close = ohlcv["종가"].astype(float)
            price = safe_int(close.iloc[-1])
            prev = safe_float(close.iloc[-2], price)
            price_chg = ((price - prev) / prev * 100) if prev > 0 else 0
            ma20 = safe_float(close.rolling(20).mean().iloc[-1])
            ma60 = safe_float(close.rolling(60).mean().iloc[-1])
            rsi_val = rsi(close)
            macd_val, macd_sig = macd(close)
            db = cloud_breakout(ohlcv)
            wb = weekly_breakout(ohlcv)

            tech, flow, issue, total = make_scores(
                price_chg, rsi_val, macd_val, macd_sig, ma20, ma60, price,
                wb, db, h["reportCount"], h["targetPriceUp"]
            )

            item = {
                "name": h["name"],
                "code": code,
                "market": h["market"],
                "industry": h["industry"],
                "grade": grade(total),
                "previousGrade": None,
                "score": total,
                "technicalScore": tech,
                "flowScore": flow,
                "issueScore": issue,
                "flowDataStatus": "disabled",
                "currentPrice": price,
                "priceChangeRate": round(price_chg, 2),
                "weeklyCloudBreakout": bool(wb),
                "dailyCloudBreakout": bool(db),
                "reportCount": h["reportCount"],
                "targetPriceUp": bool(h["targetPriceUp"]),
                "foreignNetBuy": False,
                "pensionNetBuy": False,
                "institutionNetBuy": False,
                "recentIssue": make_recent_issue(h["recentIssue"], wb, db, h["reportCount"]),
            }
            items.append(item)
            print(f"[성공] {idx}/{len(hints)} {code} {h['name']} {item['grade']} {item['score']}")
        except Exception as e:
            msg = f"{code}: {e}"
            errors.append(msg)
            print("[실패]", msg)
        time.sleep(SLEEP_SECONDS)

    items.sort(key=lambda x: x["score"], reverse=True)

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

    with open(ERROR_LOG, "w", encoding="utf-8") as f:
        f.write("\n".join(errors))

    summary = {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "baseDate": base_date,
        "totalCandidates": len(items),
        "errorCount": len(errors),
        "flowQueryDisabled": DISABLE_FLOW_QUERY,
    }
    with open(SUMMARY_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("=" * 60)
    print("생성 완료:", OUTPUT_JSON)
    print("생성 후보 수:", len(items))
    print("오류 수:", len(errors))
    return items


if __name__ == "__main__":
    generate_stock_candidates()
