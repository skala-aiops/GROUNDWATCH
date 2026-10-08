# GroundWatch 공통 계약

프론트·백엔드·데이터·AI 파드가 현재 구현을 연결할 때 사용하는 계약입니다. 실제 스키마는 `/docs`에서 확인합니다. 대표 관측소는 사용자가 위임한 공개 원천 조사·품질 비교로 고정했습니다. 선정 근거와 출처는 data/README.md 및 evidence의 자료 감사 기록을 확인합니다.

## 2026-10-08 현재 날짜 과제 시연 변경

기본 화면은 `/forecasts?mode=current`를 사용합니다. 원관측 2024-03-18 이후~서울 오늘의 합성 확장 자료를 별도 synthetic namespace로 학습합니다. CSV의 선택 열 `origin`은 `observed`/`synthetic`이며 기존 원관측 값·날짜는 보존합니다. 원본 CSV의 기본 6열 계약은 유지합니다. 전체 합성 혼합 자료의 manifest는 `source_kind=synthetic`로 격리합니다. `/forecasts`의 `provenance`는 생성식·seed·원본해시·관측소별 실측/합성 경계를 제공하며, 행의 `input_origin`은 마지막 입력 출처입니다. 이력은 행별 `origin`과 다음날의 실제 저장된 예측점(정답·강수는 null)을 제공합니다.

기존 공급 재생과 외부 `/live` API는 내부 보존 기능이며 오늘 화면의 자료 공급 경로가 아닙니다. 합성 확장 모델 성능은 실제 서울 최신 관측 성능으로 설명하지 않습니다. 상세 설계는 `current-extension-design.md`입니다.

## 자료와 예측의 의미

서울 25개 구에서 고정 대표 관측소를 각각 하나 사용합니다. 이 과거 자료 명세는 외부 실측 API 매핑 승인과 별개입니다. 예측 대상은 직전 **연속 20일의 수위·강수량으로 구한 다음 달력 날짜의 관측소 수위**입니다. 구 전체 평균·싱크홀 확률·현장 안전 등급을 뜻하지 않습니다. 대상 날짜의 미래 강수량은 입력하지 않습니다.

Canonical CSV는 UTF-8 또는 UTF-8 BOM이며 다음 열을 갖습니다.

| 열 | 형식과 의미 |
| --- | --- |
| `station_id` | 출처로 식별한 고정 관측소 ID |
| `district_code` | 서울 자치구 5자리 문자열 코드 |
| `date` | `YYYY-MM-DD`, 미래 관측일 제외 |
| `groundwater_level` | 유한 실수, 수위 부호를 임의로 뒤집지 않음 |
| `rainfall_mm` | 유한한 0 이상 실수, 단위 mm |
| `level_unit` | manifest와 일치하는 검증된 단위 |

서울 원자료의 수위 표기는 `gl.-m`입니다. 지표 기준 수심과 해발 수위를 혼동하지 않으며, 다른 출처의 단위를 자동 변환하지 않습니다. 정확히 같은 관측소·날짜의 중복은 한 행만 남기고, 값이 충돌하면 해당 날짜 묶음을 격리합니다. 결측 강수량은 0으로 만들지 않습니다. 오류 행·충돌·제외 사유는 검증 보고서에 남습니다.

함께 업로드하는 manifest JSON에는 `approved: true`, 비어 있지 않은 `mapping_version`, 25개 구가 중복 없이 들어 있는 `stations`가 필요합니다. 각 관측소는 `district_code`, 고유한 `station_id`, 확인된 `level_unit`을 갖습니다. `station_name`은 화면용 이름입니다. 실제 관측은 `source_kind: "observed"`, 합성 검증 자료는 `source_kind: "synthetic"`로 구분합니다. `approved`는 기술적 입력 조건이며 팀의 실제 승인 절차를 대신하지 않습니다.

## API

아래 경로의 기본 접두사는 `/api/v1`입니다. 조회는 `200`, 비동기 작업 접수는 `202`입니다. **202는 완료·게이트 통과·새 모델 서빙 성공을 뜻하지 않습니다.** 반환된 `job_id` 또는 작업 `id`로 상태와 결과를 확인합니다.

| Method · 경로 | 요청과 응답 |
| --- | --- |
| GET `/districts` | 선택 `dataset_id`; `{districts, mapping_version}` |
| GET `/forecasts` | 선택 `as_of`, `mode`, `replay_id`, `dataset_id`; `{forecasts, as_of, ready_count, total, mode, replay_id}` |
| GET `/districts/{code}/history` | 선택 `dataset_id`, `replay_id`; `{history, unit}`, 최근 최대 180행 |
| POST `/districts/{code}/predict` | JSON `{sequence:[{station_id,date,groundwater_level,rainfall_mm,level_unit}, ...]}`; 정확히 연속 20일, 등록 모델 버전과 다음 날 예측. 모델 미준비 `503` |
| POST `/datasets` | multipart `file` CSV, `manifest` JSON; 데이터 ID·검증 작업 ID 반환 |
| GET `/datasets` | `{datasets}`, 검증 상태·보고서 포함, 서버 파일 경로 제외 |
| POST `/jobs/train` | JSON `{dataset_id, district_code?}`; 한 구 또는 전체 초기 학습 작업 |
| GET `/jobs` · `/jobs/{id}` | 선택 replay_id; 기본 최신 자료 namespace의 최대 100작업 또는 단일 작업. all_namespaces=true로 전체 조회 |
| POST `/jobs/{id}/retry` | 실패·중단 작업만 다시 접수 |
| GET `/models` | 선택 `replay_id`; `{models}`, 실제 MLflow 모델 버전 포함 |
| POST `/models/{code}/rollback` | 선택 `replay_id`; JSON `{reason, version?}`; 이전 검증 모델 복귀 작업 |
| GET `/events` | 선택 `replay_id`; `{events}`. 생략하면 최신 준비 데이터 namespace 이벤트. `all_namespaces=true`일 때만 전체 |
| POST `/events/{id}/ack` · `/resolve` | JSON `{reason}`; 확인·조치 상태 변경, `200` |
| POST `/replays` | JSON `{dataset_id,start_date,end_date?,scenario,shift_start?,shift_amount?}`; 세션과 초기화 학습 작업 반환 |
| GET `/replays` | `{replays}`, 진행 기준일 `as_of` 포함 |
| POST `/replays/{id}/advance` | JSON `{days:1}`; 1~180일 진행 작업 접수 |

`mode`는 `historical_replay` 또는 `current`입니다. `/forecasts`의 `current`는 현재 선택 자료(기본은 공식 과거 관측과 합성 확장 자료)의 오늘 입력으로 내일을 예측하며 외부 수집을 실행하지 않습니다. 현재 화면은 위 변경에 따라 `/forecasts?mode=current`를 사용합니다. `/live/forecasts`와 외부 수집은 보류한 확장 계약입니다. `replay_id`가 있으면 재생 시계보다 미래인 기준일을 조회할 수 없습니다. 재생은 `historical` 또는 `level_shift` 시나리오이며, 후자는 `shift_start` 이후 수위에 `shift_amount`를 더한 모의 자료입니다. 변화 시작일은 재생 시작일 이후여야 합니다.

예측 행에는 `district_code`, `district_name`, 관측소 정보, `observed_date`, `forecast_date`, `prediction`, `unit`, `model_version`, `dataset_version`, `mapping_version`, `source_kind`, `quality_status`, `inspection_status`, `reason`이 포함됩니다. 준비가 안 되면 `prediction: null`이며, 25행을 반환했다고 25개 예측이 준비된 것은 아닙니다. `DATA_REQUIRED`, `MODEL_NOT_READY`, `DATA_GAP`, `STALE_DATA`, `NORMAL`, `WARN`을 구분합니다. 이벤트 상태는 `OPEN`, `ACKNOWLEDGED`, `RESOLVED`입니다. 모델 생성·평가 등 정보 기록은 `RECORDED`이며 사람의 조치 버튼을 제공하지 않습니다.

화면의 모델 복귀는 사유 입력을 받지 않고 고정 `reason="화면에서 이전 모델 복귀 요청"`을 전송합니다. API의 reason 필수 조건과 복귀 이력은 유지합니다. 이벤트 확인·조치의 사유 입력은 별도입니다.

## 오류·격리·버전

- `422`: 잘못된 날짜·구 코드·enum·JSON 필드, 필수 파일 누락, CSV/manifest 스키마 오류, 부적절한 재생 날짜 등입니다. 입력 JSON의 알 수 없는 필드는 거절합니다.
- `413`: CSV 150 MiB 또는 manifest 1 MiB 초과입니다.
- `404`: 없는 데이터·작업·재생·이벤트 ID입니다.
- `409`: 같은 scope 작업이 이미 대기·실행 중, 재생 초기화 미완료, 재시도 불가능한 작업, 이미 해결한 이벤트 등입니다.
- 파일 업로드의 행 단위 품질 검증·학습·게이트 실패는 접수 후 작업의 `failed` 또는 모델별 결과로 확인합니다. HTTP 성공만으로 완료 처리하지 않습니다.

실제 자료 모델은 `historical`, 합성 자료는 `synthetic_<hash>`, 재생 모델은 해당 재생 ID namespace를 사용합니다. 모델·scaler·예측·정답·오차 창은 구 코드와 namespace로 격리합니다. 재생 조회·이벤트 조치·롤백의 namespace를 일치시킵니다. 기본 모델 조회는 최신 준비 데이터의 namespace를 사용하므로 합성 결과를 실제 성능으로 해석하지 않습니다.

MLflow 등록명은 `GroundWatch_<namespace>_<district_code>`, 서빙 alias는 `champion`입니다. 응답의 버전은 등록 버전이며, 예측 캐시는 namespace·구·버전·예측일·원천 데이터 ID를 구분합니다. CSV SHA-256 데이터 버전과 CSV+manifest 업로드 ID는 서로 다른 식별자입니다.

## 파드 경계

웹 파드는 입력 폼·응답·차트·상태 표시를, 데이터·AI 파드는 정규화·단위·학습·게이트·모델 식별을 담당합니다. 데이터 열·단위·날짜·오류·버전 계약을 바꾸면 양쪽 파드가 영향과 예시를 먼저 공유하고 이 문서를 함께 갱신합니다. 저장소 AGENTS의 개인 → 파드 → dev → main 절차를 따르며 이슈·PR은 사용하지 않습니다.

## 학습 시간 경계

각 20일 입력과 다음 날 정답은 연속이어야 합니다. 학습은 과거의 유효한 최대 730개 표본(최소 180개), validation 60일, test 60일을 사용합니다. 학습 표본 사이의 결측 구간을 연결하지 않습니다. 25개 구 공통 replay 정답 기간은 2023-12-20~2024-03-18이며 최초 재생 기준일은 2023-12-19입니다. scaler는 학습 입력·정답 날짜에서만 적합합니다. 최초 학습과 재학습의 학습 종료일보다 이전 기준일 예측은 차단합니다. 정상 재생과 인위적 수위 변화 재생은 독립 namespace입니다.

정규 CSV의 선택 열 `dataset_version`은 출처 스냅샷 표기이며, 시스템 식별은 CSV SHA-256을 사용합니다. 단일 예측 JSON에는 ObservationInput에 정의한 필드만 전달합니다.

## 재검수로 보강한 계약

- 같은 CSV+manifest 재업로드는 같은 자료·검증 작업 ID를 반환하고 ready 자료를 validating으로 되돌리지 않습니다. 원본 파일 SHA를 나타내는 source_sha256과 별개로 canonical_sha256이 있으면 현재 CSV와 반드시 일치해야 합니다.
- current는 서울 시간의 오늘만 허용하며 replay와 함께 사용할 수 없습니다. 오래된 최종 관측은 STALE_DATA·freshness_days·null 예측으로 표시합니다.
- /health/ready는 등록 목록뿐 아니라 25개 모델의 실제 로딩·관측소/단위/자료/매핑 일치·예측을 검사하며 준비 부족은 503입니다. 입력 연속성 forecast_ready_count는 모델 ready_count와 구분합니다.
- 재생 초기화는 요청한 25개가 모두 통과해야 ready입니다. 일부 실패는 partial과 구별 결과를 반환하고 날짜 진행을 차단합니다.
- 이력은 요청한 원천 자료만 사용합니다. 같은 날짜의 여러 버전 예측은 predictions에 보존하며 대표 prediction_model_version과 version_history를 함께 반환합니다.
- GET /api/v1/monitoring은 선택 replay_id 범위의 21일 RMSE·임계값·연속 초과·후보·마지막 감시일을 반환합니다. 같은 정답일의 재실행은 초과 횟수·이벤트·재학습 작업을 중복 증가시키지 않습니다.
- GET /metrics/summary 또는 /api/v1/metrics/summary는 최근 seconds(기본300)의 요청 수·p95·5xx 비율·4xx 수·초당 처리량을 반환합니다. 60초마다 최소20건일 때 p95>1초 또는 5xx≥1%를 평가합니다. 요청 성공률은 시간 기준 가동률 SLA가 아닙니다.
- 요청마다 X-Request-ID를 반환하며 경로 패턴·응답 코드·지연을 영속 기록합니다. 요청 본문과 업로드 내용은 로그에 남기지 않습니다.

## 실제 HTTP 예시

검증일 2026-10-07. 전체 원문은 [HTTP 기록](../evidence/reaudit-http.json)에 있습니다.

`GET /api/v1/forecasts?as_of=2024-03-17` → 200. 아래는 25행 중 첫 관측소 행입니다.

```json
{
  "district_code": "11110",
  "district_name": "종로구",
  "station_id": "SU-JNO-G1-0007",
  "station_name": "홍익대대학로캠퍼스",
  "source_station_name": "홍익대대학로캠퍼스",
  "level_unit": "gl.-m",
  "source_note": "Official Seoul public observation page queried using this exact obsvCode. Source table labels groundwater gl.-m and rainfall mm; numeric signs preserved without conversion. Each input20+target1 calendar window validated. Representative fixed by user-delegated coverage-based selection, not model accuracy.",
  "source_reference": "https://swo.seoul.go.kr/ugrwtr/retrieveAsstnObsrDta.do",
  "id_reference": "https://swo.seoul.go.kr/ugrwtr/retrieveAsstnObsrName.do",
  "partitions": {
    "train": {
      "target_count": 730,
      "first_target": "2021-03-12",
      "last_target": "2023-08-21",
      "input_start": "2021-02-20"
    },
    "validation": {
      "target_count": 60,
      "first_target": "2023-08-22",
      "last_target": "2023-10-20",
      "input_start": "2023-08-02"
    },
    "test": {
      "target_count": 60,
      "first_target": "2023-10-21",
      "last_target": "2023-12-19",
      "input_start": "2023-10-01"
    },
    "replay": {
      "target_count": 90,
      "first_target": "2023-12-20",
      "last_target": "2024-03-18",
      "input_start": "2023-11-30"
    }
  },
  "rainfall_source_note": "Official groundwater observation page rainfall(mm) series; underlying rain gauge code not independently identified.",
  "observed_date": "2024-03-17",
  "forecast_date": "2024-03-18",
  "prediction": -23.258878335356712,
  "unit": "gl.-m",
  "model_version": "2",
  "dataset_version": "8a99ad7c8d4da3c9be1fcea8044281fcf538b7fdc29aa376604e9f0334193870",
  "mapping_version": "groundwatch-seoul-v1",
  "quality_status": "NORMAL",
  "inspection_status": "NONE",
  "mode": "historical_replay",
  "replay_id": null,
  "generated_at": "2026-10-07T11:09:06.785101+00:00",
  "freshness_days": 0,
  "reason": null,
  "source_kind": "observed",
  "source_dataset_id": "38a5ef2d183de0cd6a9b32781fbfebd9a3982c19f5d18c8897bfd16c9d4f35d7"
}
```

`GET /api/v1/forecasts?as_of=invalid` → 422.

```json
{
  "detail": [
    {
      "type": "date_from_datetime_parsing",
      "loc": [
        "query",
        "as_of"
      ],
      "msg": "Input should be a valid date or datetime, input is too short",
      "input": "invalid",
      "ctx": {
        "error": "input is too short"
      }
    }
  ]
}
```

GET /health/runtime은 실제 Docker 실행 여부·컨테이너 hostname·API PID·현재 존재하는 학습 worker PID·조회시각을 반환합니다. 프로세스 존재 확인이며 학습 성공·클라우드 SLA를 뜻하지 않습니다. 운영 화면에 같은 값을 표시합니다.

## 관측소별 파이프라인 화면

GET /api/v1/pipeline?district_code=11110&replay_id=선택값은 실제 자료 검증·오차 감시·품질 경보·재학습·후보 평가·모델 교체·서빙 확인의7단계를 반환합니다. 기본 관측소는 목록 첫 종로구이며 전체25구 조회를 대체하거나 관측소 순위를 뜻하지 않습니다. stages의 status/detail은 실제 작업·정답·이벤트·교체 이력·저장 예측에서 계산합니다. 아직 실행하지 않은 단계는 pending, 교체 거절은 rejected, 작업 실패는 failed, 후속 정답 부족은 후보번호와 대기일을 표시합니다.

운영 화면의 ‘기본 상황 시연’/‘수위 변화 시연’은 동일한 POST /replays 계약을 사용합니다. 기본 시작은 고정 replay_start 전날, 종료는 자료 마지막 날짜, 변화 시작은 replay_start+23일, 변화량+0.2입니다. 이후 ‘저장 자료 1일 진행’/‘저장 자료 21일 진행’으로 실제 worker 작업을 요청하며 조회는 자동 갱신합니다. 중복 새로고침·별도 예측 확인·남은기간 진행 버튼은 제외했습니다. 진행 중 중복 요청과 종료 후 진행은 차단합니다. 일반 운영은 30초, 모델 준비·진행·활성 작업이 있는 검증 기록은 3초 간격으로 갱신합니다. 정답 시계나 실제자료 수집주기가 아닙니다. pipeline의 `active_jobs`와 `latest_advance_job`을 사용해 실제 대기·실행·처리 일수·실패를 표시합니다. 최근50개 감지·작업·평가 기록을 화면에 표시합니다.

## 공식 API 수집

GET /api/v1/external-sources는 키 설정 여부와 최근 작업을 반환합니다. POST /api/v1/ingestions는 start_date, end_date(과거 최대31일), seoul_station(공식 이름), weather_station(ASOS번호)를 받아202 작업을 등록합니다. GET /api/v1/ingestions/{job_id}로 출처별 수신·유효·격리 수와 원본 SHA256을 조회합니다. 키 원문은 반환하지 않습니다. 별도 worker·queue·external 저장소를 사용하며 applied_to_forecasts는 현재 false입니다. 입력한 관측소 조건은 승인된25개 예측 매핑을 뜻하지 않습니다.

## API 전환 반영 계약 (2026-10-07)

기존 historical_replay/as_of와 구별 단일 추론 계약은 유지합니다. 제거한 화면의 current 선택에 대응했던 보류 API는 GET /api/v1/live/forecasts이며 target_date(기본 서울 오늘)와 input_end_date(전일)를 구분합니다.25행을 항상 반환하고 미준비는 prediction/model_version/issued_at=null, data_status/quality_status와 사유를 반환합니다. observed_date는 실제 검증 관측일이며 필요 입력일로 위조하지 않습니다.

GET /api/v1/data-freshness는 source별 마지막 검증 관측일·수집시각·상태·20일 입력 수와 repository 집계를 제공합니다. /live/mappings, /live/models, /live/jobs, /live/events, /live/monitoring, /live/pipeline, /live/districts/{code}/history는 historical과 분리한 조회입니다.

POST /live/snapshots는 station_id, mapping_version, start_date, end_date를 받아201 불변 snapshot을 발행합니다. 승인 매핑·양쪽 출처 완전성·모든 날짜 유효값이 필요합니다. POST /live/snapshots/{id}/activate는 명시적으로 live 포인터를 교체합니다. POST /live/training-jobs는 snapshot_id와 replay_start로202 작업을 접수합니다. POST /live/prediction-jobs는 snapshot_id를 받아 전일까지20일 입력을 확인해202로 접수합니다. 실제 미준비/학습 실패는 작업 상태로 확인합니다. /live/models/{code}/rollback은 사유와 선택 version을 받아202로 접수합니다. 역사 namespace 모델을 조작하지 않습니다.

수집 POST는 기존 start_date/end_date/seoul_station/weather_station의 진단용 계약을 유지합니다. 실제 일별 수집은 DB의 승인 mapping으로만 생성합니다. POST /ingestions/{id}/retry는 실패·중단만 재시도하며 새 job_id를 반환합니다. schema422, 없는ID404, 활성 중복409, 일부 미준비 전체조회200 계약을 유지합니다.

training_snapshot_id는 학습에 고정, inference_snapshot_id는 이번 입력, feature_contract_id는 관측소/단위/강수원천/정책/열순서/window를 묶습니다. 호환 계약이면 dataset_version이 바뀌어도 모델을 재사용하며 legacy 모델은 live에 배정하지 않습니다. 자료 발행·모델 등록·champion 교체·실제 예측 발행은 서로 다른 상태입니다.

## 현재 API 예측의 평가 상태

`/live/forecasts`는 `quality_status`의 예측 준비·발행 상태와 별도로 `model_evaluation_status`를 반환합니다. `EVALUATION_PENDING`은 정답 평가 대기, `EVALUATION_PASSED`는 저장된 평가 기준 충족, `WARN`은 오차 확인 필요입니다. 평가 날짜는 `evaluation_as_of`입니다. 어떤 값도 현장 안전 등급을 뜻하지 않습니다.

현재 `/live/districts/{code}/history`는 승인된 활성 매핑과 같은 특징 계약의 최근 180일 관측·저장 예측을 날짜별로 반환합니다. 정답이 아직 없는 예측 날짜는 관측값이 null이며, 동일 날짜의 모델별 예측은 predictions에 보존합니다. 기관 현장 확인 기록을 뜻하지 않습니다.

### 업로드·재생·작업·로그 예시

아래는 저장된 합성 자동 검증의 실제 응답에서 관련 필드를 발췌한 예시입니다. 지금 새 학습을 실행한 결과가 아닙니다. 전체 응답은 evidence/reaudit-automatic-pipeline.json에 있습니다.

POST /api/v1/datasets, multipart file=synthetic.csv·manifest=manifest.json →202

```json
{
  "dataset_id": "2d89f57e960f3b79a67edacb4c1cb3cae5bccb93154ae02393e39c054f65d578",
  "job_id": "12a96761332840e6a537b6fc1b4d6e93",
  "status": "validating"
}
```

POST /api/v1/replays, JSON {dataset_id, start_date:"2021-02-13", end_date:"2021-05-14", scenario:"historical"} →202

```json
{
  "id": "85848dec46fc4abca77f22457becc953",
  "job_id": "133a07fd3f5c4cba88d40f84966e1ae7",
  "status": "initializing",
  "as_of": "2021-02-13"
}
```

POST /api/v1/replays/{id}/advance, JSON {"days":90} →202

```json
{
  "id": "b63bbddf452e4f99b13264467268f37e",
  "kind": "advance",
  "status": "completed"
}
```

GET /api/v1/jobs/{id}, 본문 없음 →200

```json
{
  "id": "133a07fd3f5c4cba88d40f84966e1ae7",
  "kind": "train",
  "status": "completed"
}
```

GET /api/v1/events, 본문 없음 →200, {events:[...]}에 감지·재학습·평가·교체 이력을 반환합니다. 원문 events 필드는 위 증빙에서 확인합니다. GET /health/live →200, {"status":"alive","service":"GroundWatch"}를 이번 검수에서도 확인했습니다. GET /health/ready는 모델 준비 부족 시503입니다. 업로드 필수 파일 누락422, 존재하지 않는 작업404, 중복 진행409이며202는 완료를 뜻하지 않습니다.

## 보존한 공급 시뮬레이션 API (시작 UI 제외)

2026-10-07 당시 화면의 ‘새 시뮬레이션 시작’은 POST /api/v1/replays에 presentation_start_date를 추가하며 historical 시나리오만 사용합니다. GET /forecasts와 /pipeline의 simulation 객체는 원관측 source_as_of/source_forecast_date와 표시용 presentation_as_of/presentation_forecast_date를 구분합니다. 실제 date/as_of/forecast_date는 그대로이며 예측 행의 presentation_observed_date/presentation_forecast_date, history의 presentation_date만 추가합니다. source_kind=observed는 값의 실제 출처이고 시연 날짜의 실측이라는 뜻은 아닙니다.

새 namespace에서 초기 검증 모델을 복사하거나 기존 초기 학습을 실행하고25개 준비 후 하루씩 진행합니다. /replays/{id}/advance의 days는 시뮬레이션에서1만 허용합니다. 진행은 기존 worker가 예측 저장→정답 공개→오차 감시·필요시 재학습 순으로 수행합니다. 다음 날 예측만 있는 history 행은 관측·강수 null입니다. SQLite의 세션 시작일을 보존하므로 새로고침·재시작에도 시연 시계가 유지됩니다. 설계는 [공급 시뮬레이션 설계](supply-simulation-design.md), 실제 결과는 [HTTP 검증](../evidence/supply-simulation-http.json)을 따릅니다.

당시 시연 구성(2026-10-07, 현재 시작 UI 제외): 교수자 시뮬레이션 허용은 사용자 전달로 확인했습니다. 메인에는 작은 시연 환경 표시를 유지하고 시작·하루 공급 제어는 운영 화면에 둡니다. 공급만 재현하며 예측·오차 감시·재학습·후보 평가는 실제 실행합니다. 팀 설명은 [팀 로직 설명](team-logic-guide.md)의 확정 범위를 따릅니다.

`GET /metrics/summary` 및 `/api/v1/metrics/summary`는 실제 요청 로그의 `mean_seconds`(산술 평균 응답시간, 초), `p95_seconds`, `error_rate`(5xx 비율), `throughput_per_second`를 반환합니다. 요청이 없으면 평균과 p95는 null입니다. 평균은 강의의 기본 집계이며 기존 p95 경보 조건은 유지합니다.

## 드리프트 시연 표시 보완 (2026-10-08)

`GET /pipeline`에 기존 필드를 유지하고 `drift_demo`를 추가했습니다. 수위 변화 시연일 때 `shift_start`, `shift_amount`, `applied`, `monitoring_note`를 반환하며 기본 상황은 null입니다. 원본 파일을 변경하지 않고 시연 namespace에서 변화 시작일 이후 수위만 더합니다. 기본 변화 시작은 첫 정답의 22일째이며 21일 정상 구간 뒤 변화를 공개합니다. 기존에 생성한 시연의 날짜·변화량은 그대로 보존합니다.

화면에서 드리프트는 예측 오차 기준의 감지를 뜻합니다. 입력 분포·입력과 정답 관계의 변화를 통계적으로 확정한 뜻은 아닙니다. `남은 자료 끝까지 진행`은 기존 advance API에 남은 일수(최대180)를 보내며, worker는 하루씩 순차 처리하고 감지일의 재학습을 마친 뒤 다음 정답을 공개합니다. 평가·교체 결과를 강제로 성공시키지 않습니다.
