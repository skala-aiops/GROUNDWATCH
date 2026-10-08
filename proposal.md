# GroundWatch 팀 기획 및 구현

SKALA 4기 광주3반 5조 · 발표 한형준. 현재 코드와 저장된 MVP 검증을 기준으로 정리했습니다. [발표 PDF](output/final/GroundWatch_발표기획서.pdf), [편집용 PPTX](output/source/GroundWatch_발표기획서.pptx), [페이지별 대본](output/source/발표대본.md), [요구사항 검수](output/source/proposal.md)를 함께 관리합니다.

## 1. 이해관계자와 Pain Point

지하수 업무 담당자는 관측소별 자료 날짜·다음 날 예측·최근 변화를 확인해야 합니다. 서비스 운영자는 입력 부족·모델 미준비·예측 오차 증가를 구분하고 재학습 뒤 실제 새 모델 사용 여부를 확인해야 합니다. GroundWatch는 이 정보를 한 흐름으로 제공하는 과제용 시제품입니다. 장애는 예측 조회 불가, 지연은 비교 업무 지연, 품질 저하는 오차가 커진 예측의 지속 사용으로 이어질 수 있습니다. 가이드 7번 도메인 매핑표의 8항목은 발표 4쪽에서 연결합니다.

구 전체 안전도·싱크홀 발생 확률·현장 조치 우선순위는 제공하지 않습니다. 공공기관 직접 판매는 B2G이며 과제 B2B 조건 인정 여부는 확인이 필요합니다. 교수자의 합성 시연 허용은 사용자 전달로 확인했습니다.

## 2. AI 해결책과 운영 목표

25개 구의 고정 관측소별로 연속 20일 수위·강수를 입력하여 다음 날 수위를 예측합니다. 마지막 수위에 LSTM 변화량을 더하는 residual 구조이며 구별 모델·scaler를 독립 관리합니다. 원관측 이후 구간은 합성 자료로 구분합니다. 원천과 생성 방식은 [데이터 설명](data/README.md)을 따릅니다.

모델 평가는 RMSE·MAE·persistence 비교를 사용합니다. RMSE는 수위 단위로 해석하고 큰 오차를 강조할 수 있어 주 지표로 사용했습니다. 음수·0이 있는 수위에 WAPE를 직접 적용하지 않습니다. 서비스 목표는 warm p95 1초 이하·HTTP 5xx 비율 1% 미만이며, 목표를 측정 결과처럼 쓰지 않습니다. 실측과 합성의 지표는 [검증 원문](evidence/README.md)에서 구분합니다.


[저장 측정](evidence/current-metrics-http.json)의 2026-10-08 09:36:17 KST 최근 300초 107요청에서 p95는 **0.653799084초**, 5xx는 **0/107**입니다. 시간 가용성 SLA나 지속 부하 보장을 뜻하지 않습니다. [초기 실제 관측 모델](evidence/initial-model-evaluation.json)의 종로구 검증 RMSE는 **0.0325186721 gl.-m**, persistence 대비 허용 상한은 **0.0374646500 gl.-m**입니다.

[이번 합성 시연](evidence/records/presentation-demo-http.json)의 동일 후속 정답 30일에서 기존 RMSE **0.023200616227536254**, 후보 **0.021048885048271414**, 감소율 **9.2744570151%**를 확인했습니다. guard도 통과해 v2로 교체했고 실제 응답에서 v2를 확인했습니다. [다른 합성 시연](evidence/records/chart-feedback-http.json)의 **2.51%** 개선 후보는 5% 기준 미달로 기존 모델을 유지했습니다. 두 시연 간 절대 오차를 직접 비교하거나 현장 비용·사고 예방 효과로 환산하지 않습니다.

## 3. 운영 설계

입력 검증 → 초기 학습 게이트 → 예측 저장 → 정답 공개 → 오차 감시 → 재학습 후보 → 후속 평가 → 조건부 교체 순서입니다. 정답이 없으면 평가하지 않으며 실패·부족 상태는 기존 모델 유지 또는 미준비로 표시합니다.

현재 정책은 연속 21일 RMSE의 반복 초과 감지, 최근 41일 후보 학습, 이후 새 정답 30일 평가입니다. 후보가 기존보다 5% 이상 개선되고 과거 구간 guard를 통과해야 실제 모델을 교체합니다. 임계값·cooldown·복귀·장애 대응의 기준은 [운영 기준](docs/operations.md)에 모았습니다. 이는 모델 품질 정책이며 지반 안전 기준이 아닙니다.

기본 상황은 추가 수위 변화 없음, 드리프트 시연은 별도 세션의 22일째부터 +0.2 변화입니다. 예측·감지·재학습·평가는 실제 실행하며 교체 결과를 미리 만들지 않습니다. 외부 알림 발송·현장 위험 판단은 구현 범위가 아닙니다.


드리프트의 가능한 상황은 장마·가뭄에 따른 강수·수위 관계 변화, 양수·배수 조건 변화, 센서 교체·영점 보정입니다. [USGS 수위 변동 설명](https://www.usgs.gov/water-science-school/science/water-qa-why-do-water-levels-wells-rise-and-fall), [가뭄과 지하수](https://www.usgs.gov/water-science-school/science/drought-and-groundwater-levels), [계측 자료 정정 안내](https://water.usgs.gov/osw/RevisionsGuidance.html)에 근거한 가능한 시나리오이며 서울 관측 원인 확인 결과는 아닙니다. 현재 코드는 원인 대신 예측 오차 증가를 감지합니다.

입력은 연속 20일·고정 관측소·날짜·단위·유한 수위·0 이상 강수를 검사합니다. 초기 게이트는 persistence 검증 RMSE의 110% 이하입니다. 감지 임계는 검증 rolling 21일 RMSE의 95백분위 × 1.5이며 연속 2회 초과와 cooldown 21일을 적용합니다. 후보는 새 정답 30일에서 기존 RMSE의 95% 이하, guard는 초기 검증 RMSE의 110% 이하여야 합니다. 모델 로드·smoke 예측 성공 후 전환하고 실패하면 기존을 유지합니다. 이전 승격 모델 복귀는 사유를 기록하는 명시적 요청입니다.

서비스 지표는 최근 300초 최소 20요청에서 p95 > 1초 또는 5xx 비율 ≥ 1%를 60초마다 확인합니다. 준비 부족은 ready 503, 품질 알림은 SQLite 이벤트·화면으로 구분합니다.

## 4. 아키텍처와 데이터 흐름

```text
CSV + manifest → FastAPI 업로드·검증 → worker 학습 → MLflow 등록 → FastAPI 서빙 → SQLite 예측·로그
예측 기록 → 새 정답 저장 → 21일 오차 계산 → 드리프트 감지 → 운영 알림 → 재학습 작업 큐
```

Compose의 serving-app 단일 컨테이너에서 API와 worker를 실행하고 자료·모델·이력을 볼륨에 보존합니다. MLflow는 로컬 SQLite tracking/registry와 파일 artifact를 사용하며 별도 MLflow 서버가 아닙니다. 호스트 8100→컨테이너 8099로 연결합니다. 발표 14~15쪽 구성도는 왼쪽에서 오른쪽으로 읽습니다. 외부 API 수집은 별도 경로이며 현재 기본 자료 공급원이 아닙니다. 교수님 HAIC 원본과 도메인 변경·파일 책임은 [팀 로직 안내](docs/team-guide.md#교수님-원본과-달라진-점)에 정리했습니다.

## 5. API 설계와 확인 방법

현황은 GET `/api/v1/forecasts`, 상세는 GET `/api/v1/districts/{code}/history`, 운영 상태는 GET `/api/v1/pipeline`을 사용합니다. 학습·재생·복귀 요청은 202로 접수하고 작업 조회에서 완료·실패를 확인합니다. 잘못된 입력은 422, 준비 부족은 해당 API의 503·상태 필드로 구분합니다.

전체 요청·응답은 [API 계약](docs/contracts.md)과 실행 중 자동 명세를 따릅니다. 25행 응답과 25개 예측 준비, 생존과 입력·모델 준비, 후보 등록과 실제 새 버전 서빙을 구분합니다. 같은 날짜 입력·저장 예측 차이는 숫자와 관측점의 색으로 표시하고 미래 정답은 만들지 않습니다.


발표 16~19쪽에 실제 엔드포인트와 요청/응답·오류를 배치했습니다. 추론은 POST `/api/v1/districts/{code}/predict`의 sequence 20개, 업로드는 POST `/api/v1/datasets`의 multipart file+manifest, 학습은 POST `/api/v1/jobs/train`, 순차 배치 검증은 POST `/api/v1/replays/{id}/advance`의 days 1~180입니다. 이벤트·작업·모델은 GET `/events`, `/jobs`, `/jobs/{id}`, `/models`로 조회하고 복귀는 POST `/models/{code}/rollback`에 reason·version을 보냅니다(health 외 /api/v1 접두사). `/health/live`, `/health/ready`, `/health/runtime`은 생존·준비·컨테이너 진단입니다. 입력 오류 422, 업로드 크기 초과 413, 초기화 중 자료 진행 409, 준비 부족 503을 구분합니다.

보존 HAIC의 `/predict/batch-test`·`/logs`는 현재 GroundWatch 라우터에 없으므로 팀의 실제 호출로 설명하지 않습니다. HTTP 로그는 `/app/logs`, 이벤트·작업 로그성 기록은 위 조회 API로 확인합니다. [실제 200·422 원문](evidence/records/chart-feedback-http.json)을 보존했습니다.

## 6. 실행 화면과 시연

발표 20~28쪽에 컨테이너, 요청 전 v1, 변화 후 감지, 품질 알림, 재학습 작업, 후속 평가, 실제 v2 서빙, 요청 후 예측, 관측일별 강수를 각각 크게 배치했습니다. 직접 캡처한 원본은 `evidence/records/presentation-*.png`, 요청·응답·시각은 [실제 시연 HTTP](evidence/records/presentation-demo-http.json)에 있습니다.

동일 세션 `6d00ba18f44f451387219c278c82fb93`에서 요청 전 대상일 2026-07-11·예측 -22.60530148077798·v1을 확인했습니다. 수위 +0.2 변화 후 품질 경보와 후보 생성, 후속 정답 30일의 9.27% 개선 및 guard 통과, 요청 후 대상일 2026-09-02·예측 -21.47403704590814·실제 v2 응답을 확인했습니다. 전후 예측은 날짜가 다르므로 값 자체의 변화가 정확도 개선의 증거는 아닙니다. 정확도는 동일 후속 정답 RMSE로 비교합니다.

캡처 중 기존 8100 컨테이너가 제거되어 원본 tracking 볼륨을 읽기 전용 복사한 뒤 별도 18103 컨테이너·5174 화면 프리뷰에서 동일 시연을 이어갔습니다. interrupted 작업과 추가 진행 요청을 원문에 남겼습니다. 최신 UI의 표준 Compose 재배포 검증과 구분합니다.

## 팀원 및 역할

| 이름 | 역할 | 사진 |
| --- | --- | --- |
| 조건우 | PM·기획 및 일정 관리 | [사진](output/source/assets/profiles/조건우.png) |
| 박건우 | 프론트엔드·백엔드 개발 | [사진](output/source/assets/profiles/박건우.jpg) |
| 이병주 | 프론트엔드·백엔드 개발 | [사진](output/source/assets/profiles/이병주.png) |
| 최은주 | AI 모델·AIOps | [사진](output/source/assets/profiles/최은주.png) |
| 장서연 | AI 모델·AIOps | [사진](output/source/assets/profiles/장서연.png) |
| 한형준 | 데이터 분석·전처리 및 발표 | [사진](output/source/assets/profiles/한형준.jpg) |

역할 배정은 개인별 직접 작성·기여 증명을 대신하지 않습니다.
