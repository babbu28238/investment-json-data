#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V227 TELEGRAM MESSAGE BUILDER

목적:
- stock_candidates.json을 읽어서 텔레그램 전송용 메시지 생성
- 실제 발송 전 단계: 메시지 txt/json만 생성
- 이후 V228에서 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID를 사용해 실제 발송 가능

입력:
- stock_candidates.json

출력:
- telegram_message.txt
- telegram_message.json
- v227_telegram_summary.json
"""

import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()

IN_FILE = ROOT / "stock_candidates.json"
OUT_TXT = ROOT / "telegram_message.txt"
OUT_JSON = ROOT / "telegram_message.json"
OUT_SUMMARY = ROOT / "v227_telegram_summary.json"

def now_text():
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

def clean(value, default="-"):
    if value is None:
        return default
    s = str(value).strip()
    return s if s else default

def load_candidates():
    if not IN_FILE.exists():
        raise FileNotFoundError("stock_candidates.json 파일이 없습니다.")

    data = json.loads(IN_FILE.read_text(encoding="utf-8"))

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ["candidates", "stocks", "items", "data", "results", "stockCandidates", "recommendations"]:
            if isinstance(data.get(key), list):
                return data[key]

    raise ValueError("지원하지 않는 stock_candidates.json 구조입니다.")

def grade_order(item):
    grade = clean(item.get("grade"), "C").upper()
    order = {"S": 0, "A": 1, "B": 2, "C": 3}
    return order.get(grade, 9)

def score_of(item):
    try:
        return int(item.get("score", 0))
    except Exception:
        return 0

def one_line_signal(item):
    chart = clean(item.get("weeklyCloud"), "")
    daily = clean(item.get("dailySignal"), "")
    supply = clean(item.get("dataStatus", {}).get("supplySummary") if isinstance(item.get("dataStatus"), dict) else "", "")
    report = clean(item.get("reportSignal"), "")
    news = clean(item.get("newsSignal"), "")

    parts = []
    if chart and chart != "-":
        parts.append(chart)
    if daily and daily != "-":
        parts.append(daily)
    if supply and supply != "-":
        parts.append(supply)
    if report and report != "-":
        parts.append(report)
    if news and news != "-":
        parts.append(news)

    return " · ".join(parts[:3]) if parts else "신호 확인 필요"

def build_message(candidates):
    sorted_items = sorted(candidates, key=lambda x: (grade_order(x), -score_of(x), int(x.get("rank", 9999) or 9999)))

    priority = [x for x in sorted_items if clean(x.get("grade"), "").upper() in ["S", "A"] or score_of(x) >= 80]
    watch = [x for x in sorted_items if x not in priority]

    lines = []
    lines.append("📈 오늘의 투자 후보")
    lines.append(f"생성시각: {now_text()}")
    lines.append("")
    lines.append(f"전체 후보: {len(candidates)}개")
    lines.append(f"우선 확인: {len(priority)}개")
    lines.append("")

    if priority:
        lines.append("🔥 우선 확인 후보")
        for idx, item in enumerate(priority[:7], start=1):
            name = clean(item.get("name"))
            code = clean(item.get("code"))
            score = score_of(item)
            grade = clean(item.get("grade"), "-")
            entry = clean(item.get("entryPrice"), "조건 확인")
            stop = clean(item.get("stopLoss"), "기준 확인")
            target = clean(item.get("targetPrice"), "분할 익절")
            strategy = clean(item.get("strategy"), "-")
            risk = clean(item.get("riskMemo"), "-")
            signal = one_line_signal(item)

            lines.append(f"{idx}. {name} ({code}) | {grade}등급 / {score}점")
            lines.append(f"   - 신호: {signal}")
            lines.append(f"   - 진입: {entry} / 손절: {stop} / 목표: {target}")
            if strategy != "-":
                lines.append(f"   - 전략: {strategy}")
            if risk != "-":
                lines.append(f"   - 리스크: {risk}")
            lines.append("")
    else:
        lines.append("🔥 우선 확인 후보 없음")
        lines.append("")

    if watch:
        lines.append("👀 관찰 후보")
        for idx, item in enumerate(watch[:5], start=1):
            lines.append(f"{idx}. {clean(item.get('name'))} ({clean(item.get('code'))}) | {clean(item.get('grade'), '-')}등급 / {score_of(item)}점")
        lines.append("")

    lines.append("※ 본 메시지는 자동 생성된 후보 요약이며, 실제 매매 전 현재가·거래량·뉴스·공시·손절 기준을 반드시 확인하세요.")

    return "\n".join(lines), sorted_items, priority, watch

def main():
    candidates = load_candidates()
    message, sorted_items, priority, watch = build_message(candidates)

    OUT_TXT.write_text(message, encoding="utf-8")
    OUT_JSON.write_text(json.dumps({
        "version": "V227_TELEGRAM_MESSAGE_BUILDER",
        "generatedAt": now_text(),
        "message": message,
        "priorityCount": len(priority),
        "watchCount": len(watch),
        "topCandidates": sorted_items[:10],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    OUT_SUMMARY.write_text(json.dumps({
        "version": "V227",
        "generatedAt": now_text(),
        "input": "stock_candidates.json",
        "outputs": ["telegram_message.txt", "telegram_message.json", "v227_telegram_summary.json"],
        "candidateCount": len(candidates),
        "priorityCount": len(priority),
        "watchCount": len(watch),
        "status": "SUCCESS"
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(message)

if __name__ == "__main__":
    main()
