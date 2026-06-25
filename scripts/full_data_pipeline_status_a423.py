# scripts/full_data_pipeline_status_a423.py
# A423 FIX2: Full Data Pipeline 상태 파일 생성기
# 배포 조건이 부족해도 workflow를 실패시키지 않고 JSON에 원인을 기록한다.

import json
from pathlib import Path
from datetime import datetime

DATA = Path("data")
SUMMARY = DATA / "market_scanner_summary.json"
OUT = DATA / "data_pipeline_status_a423.json"

def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception as e:
        return {"_loadError": str(e)}

def save(path, data):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def to_int(v):
    try:
        return int(v or 0)
    except Exception:
        return 0

def main():
    s = load(SUMMARY, {})
    issues = []
    warnings = []

    universe_source = str(s.get("universeSource", ""))
    universe_count = to_int(s.get("universeCount"))
    included_count = to_int(s.get("includedCount"))
    price = to_int(s.get("priceConnected"))
    news = to_int(s.get("newsConnected"))
    report = to_int(s.get("reportConnected"))
    chart = to_int(s.get("chartConnected"))
    supply = to_int(s.get("supplyConnected"))
    supply_partial = to_int(s.get("supplyPartial"))
    macro = to_int(s.get("macroApplied"))

    if not (universe_source.startswith("pykrx:") or universe_source == "naver_market_sum"):
        issues.append(f"universeSource가 {universe_source}입니다. pykrx 또는 naver_market_sum이어야 합니다.")
    if universe_count < 1000:
        issues.append(f"universeCount가 {universe_count}개입니다. 국내 전체 상장 종목 기준으로 부족합니다.")
    if included_count < 500:
        issues.append(f"includedCount가 {included_count}개입니다. 가격 연결 종목 수가 부족합니다.")
    if price <= 0:
        issues.append("priceConnected가 0입니다. 주가 데이터 연결 실패입니다.")
    if chart <= 0:
        issues.append("chartConnected가 0입니다. 차트/이동평균 데이터 연결 실패입니다.")
    if supply <= 0 and supply_partial <= 0:
        issues.append("수급 연결/부분수집이 모두 0입니다.")

    if news <= 0:
        warnings.append("newsConnected가 0입니다. 뉴스 수집 경로 확인이 필요합니다.")
    if report <= 0:
        warnings.append("reportConnected가 0입니다. 리포트/목표가 수집 경로 확인이 필요합니다.")
    if macro <= 0:
        warnings.append("macroApplied가 0입니다. 업종/테마와 매크로 항목 연결이 약합니다.")

    deploy_ready = len(issues) == 0
    result = {
        "version": "A423_FIX2",
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "deployReady": deploy_ready,
        "status": "배포 가능" if deploy_ready else "배포 준비 아님",
        "summary": s,
        "issues": issues,
        "warnings": warnings,
        "nextAction": "앱 배포 가능" if deploy_ready else "issues 항목을 해결한 뒤 Full Data Pipeline A423을 다시 실행하세요."
    }

    save(OUT, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
