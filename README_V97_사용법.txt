# V97 GitHub Actions 자동 실행 패키지

## 목적
V96까지는 Colab을 직접 열고 실행해야 했습니다.
V97은 GitHub Actions를 사용해 GitHub가 정해진 시간에 자동으로 `stock_candidates.json`을 생성하고 업데이트하도록 만드는 단계입니다.

## 들어있는 파일
- `.github/workflows/update_stock_candidates.yml`
- `scripts/generate_stock_candidates.py`
- `report_hints.csv`
- `README_V97_사용법.txt`

## 적용 위치
GitHub 저장소 `investment-json-data`의 최상위 폴더에 그대로 업로드해야 합니다.

최종 구조:

```text
investment-json-data/
├─ stock_candidates.json
├─ report_hints.csv
├─ scripts/
│  └─ generate_stock_candidates.py
└─ .github/
   └─ workflows/
      └─ update_stock_candidates.yml
```

## GitHub에서 업로드하는 방법
1. 이 ZIP 압축 해제
2. GitHub 저장소 `investment-json-data` 접속
3. `Add file → Upload files`
4. 압축 해제된 파일과 폴더를 업로드
5. `Commit changes`

## 자동 실행 시간
워크플로우는 평일 한국시간 16:30에 실행되도록 설정했습니다.

```yaml
- cron: "30 7 * * 1-5"
```

GitHub Actions의 cron은 UTC 기준입니다.
UTC 07:30은 한국시간 16:30입니다.

## 수동 실행 방법
GitHub 저장소에서:

```text
Actions
→ Update stock candidates
→ Run workflow
→ Run workflow
```

를 누르면 즉시 실행할 수 있습니다.

## 실행 성공 확인
Actions 실행 후 저장소에 아래 파일이 업데이트되면 성공입니다.

```text
stock_candidates.json
v97_generation_summary.json
v97_collection_errors.txt
```

그 다음 앱에서:

```text
더보기 → 외부 데이터 연동 → URL에서 JSON 불러오기
→ 파싱 결과 50개 확인
→ 앱에 저장
```

을 하면 됩니다.

## 주의
- 현재 V97은 가격·기술·이슈 기반 안정 버전입니다.
- 수급 조회는 비활성화되어 있습니다.
- GitHub Actions 환경에서 KRX/pykrx 조회가 막힐 가능성이 있습니다. 그 경우 Actions 로그를 보고 V97.1에서 보완합니다.
