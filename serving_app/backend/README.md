# GroundWatch 웹 백엔드

기존 FastAPI 애플리케이션에 `/api/v1`을 추가한 웹 파드 구현입니다. 기획서의 **관측정 1개, CSV 일자료, 20일 입력, 21건 판정, 41행 재학습** 구조와 ERD·디자인·API 설계 초안을 기반으로 합니다. 기존 HAIC 실습의 `/predict`, `/health`, `/data/*`, `/logs*`, 정적 화면과 학습 코드는 유지합니다.

## 실행과 문서

저장소 루트에서 기존 팀 시작 명령을 사용합니다.

```bash
docker compose up --build
```

- 신규 웹 API 문서: http://localhost:8100/api/v1/docs
- 신규 OpenAPI: http://localhost:8100/api/v1/openapi.json
- 기존 샘플 화면: http://localhost:8100/
- 기존 상태 확인: http://localhost:8100/health
- 종료: `Ctrl+C`, 컨테이너 정리: `docker compose down` (볼륨은 유지)

기존 컨테이너가 첫 시작 시 학습하는 모델은 **HAIC 주가 샘플**입니다. 신규 API는 이를 지하수 모델로 사용하지 않으며 예측·분석 요청에 `422 CONTRACT_MISMATCH`를 반환합니다. 모델 로딩 자체에 실패하면 `503 MODEL_NOT_READY`입니다. CSV·관측·이력 조회는 지하수 모델 없이 사용할 수 있습니다. 지하수 모델 학습이나 현장 안전 예측이 완료된 구현은 아닙니다.

## 구현한 기능

- `DEMO-01` 개발용 관측정 1개. 실제 관측정 이름·기준면을 확인한 등록 자료로 오인하지 않도록 이름에 표시합니다.
- 원본 CSV·관측값·자료 버전의 원자적 저장, 내용 중복 검사, 날짜만 추가하는 연장 업로드.
- 관측값, 예측값, 판정 근거, 대시보드, 실행·단계 이벤트 조회와 cursor 페이지 처리.
- 예측/분석의 요청 키 중복 방지, 관측정당 변경 작업 1개, 날짜·모델·자료 계보·live/replay 분리.
- 21개 연속 오차의 RMSE와 실제 평가 표본 저장. 기준 미설정은 `not_evaluated`, 표본 부족은 `insufficient_data`입니다.
- 첫 Drift에서 분석 중단, 같은 자료의 해당 날짜까지 41행을 사용하는 재학습 연결 인터페이스. 자식 run과 Gate 결과·실제 승격 여부를 별도 기록합니다.
- 재시작 시 저장 자료 복구, 미완료 작업 `interrupted` 처리. 자동 재실행·중복 배포는 하지 않습니다.

## 새 API 목록

아래 경로 앞에 `/api/v1`을 붙입니다. 성공은 `data`와 `meta.request_id`, 목록은 추가로 `meta.next_cursor`를 반환합니다. 오류는 `error.code/message/details`와 `meta.request_id`입니다.

| 메서드 | 경로 | 용도 |
| --- | --- | --- |
| GET | `/wells` | 관측정 목록 |
| GET / POST | `/wells/{well_id}/datasets` | 자료 버전 목록 / CSV 등록 |
| GET | `/datasets/{dataset_id}` | 자료 정보 |
| GET | `/wells/{well_id}/observations` | 관측 시계열 |
| GET | `/wells/{well_id}/dashboard` | 관측·예측·판정 요약 |
| GET / POST | `/wells/{well_id}/forecasts` | 예측 이력 / 다음날 예측 |
| POST | `/wells/{well_id}/analyses` | 과거자료 비동기 분석 접수 |
| GET | `/wells/{well_id}/runs` | 분석·재학습 목록 |
| GET | `/runs/{run_id}` | 실행 상태·결과 |
| GET | `/runs/{run_id}/events` | 실행 단계 이벤트 |
| GET | `/checks/{check_id}` | 판정과 실제 사용한 표본 |

자료 단위 조회에는 `dataset_id`를 지정합니다. 날짜는 `from`, `to`(양끝 포함), 목록은 `limit`(기본 50, 최대 100)와 `cursor`를 사용합니다. 기간 조회는 최대 756일이며 관측·예측의 기본 표시 범위는 최근 60일입니다. 예측 목록의 기본 범위에는 다음날 예측 1개도 포함합니다. 알 수 없는/중복된 query 필드는 422로 거절합니다.

예측/분석 POST에는 UUID 형식의 `Idempotency-Key`가 필수입니다. 동일 키·본문은 기존 결과를 반환하고, 다른 본문에 같은 키는 409입니다. 실행 중인 작업과 충돌하면 `409 RUN_IN_PROGRESS`입니다. 비동기 접수는 202이고 실제 완료는 run 조회로 확인합니다. 분석 완료와 자식 재학습·배포 완료는 구분합니다.

## CSV 형식

UTF-8 CSV, 아래 순서의 헤더, 41~10,000행, 파일 10 MiB 이하입니다. 날짜는 KST 일자료 기준이며 미래 날짜를 허용하지 않습니다.

```csv
observed_date,groundwater_depth_cm,rainfall_mm
2025-01-01,118.5,0.0
2025-01-02,119.0,2.4
```

위 두 행은 형식 예시이며 전체 업로드 파일이 아닙니다. 깊이는 **지표면 기준 cm, 양수**, 강수량은 **mm, 0 이상, 소수 첫째 자리까지**입니다. 깊이가 커지면 지하수면이 더 깊어진 것입니다. 날짜 중복·누락·역순, 빈 값, NaN/Infinity, 음수 강수량은 거절합니다. 무강수 `0.0`과 결측을 구분합니다.

업로드 form은 `file`, `source_kind`(`simulated`/`measured`), 시뮬레이션일 때 `scenario`(`baseline`/`drift`), 선택 `parent_dataset_id`입니다. 입력자가 지정한 `measured`는 자료의 진위나 단위 검증을 보증하지 않습니다.

기존 자료를 연장할 때 부모 자료의 전체 행을 동일하게 포함하고 이후 날짜를 추가해야 합니다. **MVP는 부모당 연장본 1개**만 허용합니다. 이미 연장본이 있다면 그 최신 자료를 부모로 지정합니다. 과거값을 수정한 자료는 별도 루트 업로드로 다룹니다. 이는 설계 초안의 1:N 자기참조보다 엄격한 구현이며, 한 예측에 서로 다른 익일 실측이 연결되는 문제를 막습니다.

연장 자료 등록 후 과거 live 예측의 대상일 실측을 연결하고 해당 모델의 내부 분석 run을 실행합니다. 등록 201 응답은 이 분석의 완료를 의미하지 않습니다. 다른 모델·별도 업로드·live/replay의 오차를 하나의 21건 창으로 섞지 않습니다.

## 저장 구조와 범위

SQLite 파일 기본 위치는 `runtime/groundwatch.db`입니다. 기존 Compose의 `/app/runtime` 볼륨에 저장되므로 Docker 설정·공용 의존성을 추가하지 않았습니다. `well`, `dataset`, `observation`, `model_version`, `forecast`, `monitoring_check`, `check_member`, `pipeline_run`, `pipeline_event`를 사용합니다.

원본 CSV는 별도 파일 경로 대신 `dataset.raw_csv` BLOB으로 저장합니다. 설계의 `object_key` 대신 원본과 관측값을 같은 트랜잭션으로 확정하기 위한 선택이며 API에는 원본 bytes를 노출하지 않습니다. 실측·예측 숫자는 유한한 float로 저장하므로 과학적 정밀도가 더 필요하면 데이터·AI 파드와 decimal 저장 기준을 추가로 합의해야 합니다.

DB당 단일 서버 프로세스만 지원하고 시작 시 파일 잠금으로 중복 worker를 거절합니다. worker 내부에서는 SQLite WAL을 사용해 읽기와 변경을 분리합니다. 외부 메시지 큐, 분산 worker, 자동 재시도, 인증·기관 권한, 실시간 수집, 지도·다중 관측정은 구현 범위 밖입니다. 기존 샘플 API도 인증 없는 개발용 상태입니다.

## AI 파드 연결 지점

`adapter.py`의 `ModelGateway` 인터페이스가 연결 지점입니다.

- `active_model(well_id)`: UUID, 관측정, Registry 이름·버전, `feature_contract=gw-depth-rain/v1`, 학습·Gate 종료일을 포함한 `ModelInfo`.
- `predict(model, sequence)`: 날짜·깊이 cm·강수량 mm가 있는 20행을 받아 cm 값을 반환. 모델 버전은 호출 전후 고정되어야 합니다.
- `retrain(model, rows, policy, emit)`: 같은 자료의 41행, 정책, 실제 단계 이벤트 callback을 받습니다. 시간순 21개 시퀀스의 앞 16개 학습 / 뒤 5개 Gate 결과와 `TrainingResult`를 반환합니다. 이 작은 평가셋으로 일반화 성능을 주장하지 않습니다.

기본 `ExistingModelGateway`는 기존 로더를 재사용합니다. 로딩한 모델에 `groundwatch_metadata: ModelInfo`와 `predict_depth(sequence)`가 명시되어 있을 때만 예측 연결을 허용합니다. 현재 HAIC `LoadedModel`에는 이 계약이 없으므로 거절됩니다. 메타데이터 이름만 추가해 주가 모델을 사용하는 것은 허용되는 도메인 전환이 아닙니다.

재학습은 기존 `fine_tune()`을 직접 호출하지 않습니다. 그 함수는 샘플 단위·Registry·scaler를 사용하기 때문입니다. 합의된 지하수 gateway를 `BackendService(settings, gateway)`에 주입해야 합니다. 기본 gateway의 재학습은 `RETRAIN_NOT_READY` 오류로 기록합니다. 테스트의 `StubGateway`는 이 연결 흐름만 검증하며 제품 실행에서 사용하지 않습니다.

합의된 강수량 ×10 변환·학습 때 사용한 scaler·모델 실제 승격은 AI gateway의 책임입니다. 웹은 Gate 점수·정책·시간 분리·후보 메타데이터와 실제 active 모델 변경을 대조합니다. 학습 또는 Gate에서 이미 사용한 대상일은 해당 모델의 분석에서 제외합니다.

## 설정

다음은 **백엔드 프로세스가 읽는 환경변수**입니다. 현재 Compose에는 새 설정을 전달하도록 변경하지 않았으므로 호스트 `.env`에 넣는 것만으로 적용되지는 않습니다. 실제 값과 Compose 전달 설정은 양쪽 파드의 합의 후 추가해야 합니다.

| 변수 | 기본값 | 의미 |
| --- | --- | --- |
| `GROUNDWATCH_DB_PATH` | `runtime/groundwatch.db` | DB 위치 |
| `GROUNDWATCH_RMSE_THRESHOLD_CM` | 없음 | 모니터링 기준 |
| `GROUNDWATCH_GATE_THRESHOLD_CM` | 없음 | 재학습 Gate 기준 |
| `GROUNDWATCH_POLICY_VERSION` | `unconfigured` | 합의한 판정 정책 식별자 |
| `GROUNDWATCH_AUTO_RETRAIN` | `false` | 두 기준과 정책 버전 설정 시에만 활성화 가능 |
| `GROUNDWATCH_STALE_AFTER_DAYS` | 없음 | 데이터 지연 기준 |

임계값 4를 지하수 기준으로 재사용하지 않았습니다. 데이터 지연 기준도 미설정이면 `unknown`입니다. 실제 도메인 계약·기준이 합의되었다고 기록하지 않으며 `docs/contracts.md`를 임의로 생성하지 않았습니다.

## 검증

기존 팀 실행이 준비되면 컨테이너에서 기존 회귀 테스트와 신규 HTTP 테스트를 실행합니다.

```bash
docker compose exec serving-app python -m unittest discover -s tests -v
```

신규 테스트는 임시 DB·테스트 전용 gateway와 실제 loopback HTTP를 사용합니다. 원자적 CSV 등록, 중복·연장·분기 거절, 익일 실측 연결, 20/21건 판정, 모델 변경 후 창 분리, 정답 누수 차단, 비동기·재학습 상태, 오류 응답, 페이지 이동, 재시작 보존을 확인합니다. 실제 지하수 모델의 정확도·학습·현장 효과 검증은 별도 작업입니다.
