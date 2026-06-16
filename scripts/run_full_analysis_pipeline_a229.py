# scripts/run_full_analysis_pipeline_a229.py
# HSinvest A229 FULL ANALYSIS PIPELINE
# 여러 Actions를 따로 실행하지 않고 가격→차트/뉴스→수급→최종검증을 한 번에 실행한다.

import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

DATA = Path("data")
CANDIDATES = DATA / "stock_candidates_ai_scored.json"
SUMMARY = DATA / "market_scanner_summary.json"
PIPELINE_SUMMARY = DATA / "full_pipeline_summary_a229.json"

STEPS = [
    ("A222_PRICE", "scripts/overwrite_candidate_real_close_a222.py"),
    ("A225_SCORE", "scripts/build_real_score_engine_a225.py"),
    ("A228_SUPPLY", "scripts/build_supply_engine_a228.py"),
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

def run_step(name, script):
    p = Path(script)
    if not p.exists():
        return {
            "name": name,
            "script": script,
            "status": "skip",
            "message": "script not found",
        }

    proc = subprocess.run(
        [sys.executable, script],
        text=True,
        capture_output=True,
        timeout=3600,
    )

    return {
        "name": name,
        "script": script,
        "status": "ok" if proc.returncode == 0 else "fail",
        "returnCode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
    }

def safe_int(v, default=0):
    try:
        return int(float(str(v).replace(",", "")))
    except Exception:
        return default

def final_verify():
    candidates = load_json(CANDIDATES, [])
    if isinstance(candidates, dict):
        for key in ["candidates", "data", "items", "stocks", "top"]:
            if isinstance(candidates.get(key), list):
                candidates = candidates[key]
                break
    if not isinstance(candidates, list):
        candidates = []

    price_count = sum(1 for x in candidates if isinstance(x, dict) and safe_int(x.get("currentPrice", x.get("close", 0))) > 0)
    chart_count = sum(1 for x in candidates if isinstance(x, dict) and safe_int(x.get("chartScore", 0)) > 0)
    supply_count = sum(1 for x in candidates if isinstance(x, dict) and safe_int(x.get("supplyScore", 0)) > 0)
    news_count = sum(1 for x in candidates if isinstance(x, dict) and safe_int(x.get("newsScore", 0)) > 0)

    return {
        "candidateCount": len(candidates),
        "priceCount": price_count,
        "chartScoreCount": chart_count,
        "supplyScoreCount": supply_count,
        "newsScoreCount": news_count,
        "ready": len(candidates) >= 20 and price_count >= 20 and chart_count >= 20 and supply_count >= 20,
    }

def main():
    run_id = datetime.now().isoformat(timespec="seconds")
    results = []

    for name, script in STEPS:
        results.append(run_step(name, script))

    verify = final_verify()

    summary = load_json(SUMMARY, {})
    if not isinstance(summary, dict):
        summary = {}

    summary.update({
        "version": "A229",
        "generatedAt": run_id,
        "status": "full_pipeline_ready" if verify["ready"] else "full_pipeline_partial",
        "pipeline": "A222_PRICE -> A225_SCORE -> A228_SUPPLY",
        **verify,
    })
    save_json(SUMMARY, summary)

    save_json(PIPELINE_SUMMARY, {
        "version": "A229",
        "generatedAt": run_id,
        "steps": results,
        "verify": verify,
        "summary": summary,
    })

    print(json.dumps(summary, ensure_ascii=False, indent=2))

    # 핵심 단계 실패 시 Action 실패 처리
    failed = [x for x in results if x["status"] == "fail"]
    if failed:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
