# API·데이터 계약

현재 요청 스키마의 기준은 `serving_app/groundwater_api.py`와 실행 중인 [자동 API 명세](http://localhost:8100/docs)입니다. 이 문서는 날짜·출처·상태처럼 스키마만으로 이해하기 어려운 의미를 설명합니다. 정책 수치는 [운영 기준](operations.md)을 따릅니다.

추가 전국 실험 경로는 `serving_app/national_api.py`의 `/api/v2`입니다. 서울 `/api/v1`의 25개 고정 관측소·필드·기본 자료를 대체하지 않습니다. 아래 전국 설명은 현재 추가 구현의 요청·상태 의미이며, 양 파드의 공통 계약 합의 완료나 전국 서비스 출시 완료를 선언한 문서가 아닙니다.

## 데이터와 날짜

Canonical CSV는 UTF-8/BOM, 열은 `station_id,district_code,date,groundwater_level,rainfall_mm,level_unit`입니다. 합성 확장은 선택 열 `origin=observed/synthetic`을 추가합니다. 관측소·구·단위 명세 manifest에는 approved, mapping_version, 25개 고정 stations가 필요합니다. 기술적 승인 필드가 외부 실측 매핑 승인까지 대신하지 않습니다.

날짜는 YYYY-MM-DD, 수위는 유한 실수, 강수는 0 이상이며 결측을 0으로 대체하지 않습니다. 관측소·단위·날짜 중복 충돌과 연속 20일을 검증합니다. 부호를 바꾸지 않으며 미래 정답을 입력하지 않습니다. 데이터 출처·단위·생성식은 [데이터 설명](../data/README.md)을 따릅니다.

- observed_date: 최근 입력 날짜. forecast_date: 다음 날 예측 대상일.
- mode=current: 서울 오늘까지 입력으로 내일을 예측합니다. 외부 API를 새로 호출하는 모드가 아닙니다.
- mode=historical_replay: 선택 자료/시연의 기준일로 검증합니다. replay_id가 있으면 시연 시계보다 미래를 조회하지 못합니다.
- dataset_id·namespace·관측소·모델 버전을 분리합니다. 합성 혼합 데이터 전체는 synthetic namespace이며 행별 출처는 별도 유지합니다.

## 기본 화면 API

접두사는 `/api/v1`입니다. 조회는 200, 비동기 접수는 202이며 202는 작업·평가·교체 완료가 아닙니다. 작업 ID로 결과를 다시 확인합니다.

| Method·경로 | 입력·의미 |
| --- | --- |
| GET /districts | dataset_id 선택, 고정 관측소 목록 |
| GET /forecasts | as_of·mode·replay_id·dataset_id 선택, forecasts·ready_count·provenance |
| GET /districts/{code}/history | dataset_id·replay_id 선택, 최근 입력 최대 180행 + 저장된 다음 날 예측점 |
| POST /districts/{code}/predict | sequence 정확히 20개, 관측소·날짜·수위·강수·단위, replay_id 선택 |
| GET /pipeline | district_code·replay_id 선택, 모델·감지·작업·후보 평가·진행 상태 |
| POST /datasets | multipart file CSV·manifest JSON, 검증 작업 접수 |
| POST /jobs/train | dataset_id·district_code 선택, 초기 학습 접수 |
| GET /jobs · /jobs/{id} | 작업 목록·단일 작업 상태 |
| POST /jobs/{id}/retry | 실패·중단 작업 재접수 |
| GET /models | replay_id 선택, 실제 모델 버전 |
| POST /models/{code}/rollback | reason 필수·version 선택, replay_id 선택 |
| GET /events | replay_id 선택, 운영 이벤트 |
| POST /events/{id}/ack · /resolve | reason 필수, 운영 확인·조치 |
| GET · POST /replays | 목록 또는 dataset_id·start_date·end_date 선택·scenario·변화 설정으로 생성 |
| POST /replays/{id}/advance | days 1~180, 저장 자료 순차 처리 접수 |

잘못된 날짜·구·요청 형식은 422, 준비되지 않은 단일 추론은 503입니다. 자세한 오류는 detail로 반환합니다. 전체 25행 반환과 25개 예측 준비는 다르며 prediction이 null일 수 있습니다. 모델 없음·자료 부족·날짜 공백·오래된 입력·품질 경보를 구분합니다.

## 예측과 화면 비교

forecasts 행에는 구·관측소·단위, observed_date, forecast_date, prediction, model_version, 자료/매핑 버전, source_kind, input_origin, quality_status, reason이 있습니다. provenance는 실측·합성 구간·생성식·해시를 제공하고 생성 시각은 결정적 자료 식별자와 구분합니다.

latest_comparison은 최근 입력의 `{date,actual,prediction,model_version}`입니다. 같은 namespace·관측소·원본 dataset·대상 날짜에 저장된 예측 중 가장 최근 생성 버전을 사용합니다. 예측이 없으면 prediction은 null, 입력이 없으면 객체가 null 또는 없을 수 있습니다. 화면은 셋째 자리 표시값을 비교해 입력 숫자만 높음 빨강·낮음 파랑으로 표시합니다. 미래 예측과 비교하지 않습니다.

이력의 미래 예측점은 groundwater_level/rainfall_mm이 null입니다. 임의 정답·강수를 채우지 않습니다. 같은 날짜 여러 모델의 predictions는 보존하며 화면 선택값의 prediction_model_version을 함께 확인합니다.

## 작업·진행·복귀

pipeline의 active_jobs와 latest_advance_job은 id·kind·status·result·error를 제공합니다. 날짜 진행 result의 processed/total/as_of는 실제 처리 결과입니다. 후보 생성과 후속 정답 30일 평가·교체·실패를 별도로 표시합니다. 드리프트 설정은 drift_demo의 shift_start·shift_amount·applied로 확인합니다.

화면의 복귀 요청은 `{reason:"화면에서 이전 모델 복귀 요청"}`을 보냅니다. 사유 입력창을 없애도 API 계약·이력은 유지합니다. 모델·이벤트·작업 기본 목록은 선택 namespace에 한정하며 all_namespaces는 개발 진단용입니다.

## 준비·진단·외부 수집

`/health/live`는 생존, `/health/ready`는 관측소별 입력·모델 준비, `/health/runtime`은 프로세스 진단입니다. `/metrics/summary`는 요청 수·응답시간·오류율을 제공합니다.

외부 수집 상태는 `/api/v1/external-sources`, 수집 작업은 `/ingestions`, 실측 전용 snapshot·학습·예측은 `/live/*`입니다. 키 설정·수집 이력·승인 매핑·입력·모델·발행 상태를 나눕니다. 현재 기본 화면 자료에 적용되지 않았으며 수집 이력만으로 실측 예측 준비를 판단하지 않습니다. endpoint별 요청은 자동 API 명세를 따릅니다. presentation_start_date와 simulation 표시 달력은 보존된 이전 공급 도구 계약이며 기본 오늘 예측과 혼동하지 않습니다.

## 추가 전국 실험 API `/api/v2`

전국 예측·모델 namespace는 `national_observed_v1`입니다. 지역 코드는 검색 속성이고 `station_id`가 작업·예측·감시·모델의 기본 키입니다. 같은 지역의 여러 관측소를 허용합니다. 전국 관측소 카탈로그·강수 관측망 조회와 예측용 registry는 별개이며, 카탈로그에 있는 모든 관측소가 예측 가능하다는 뜻은 아닙니다.

| Method·경로 | 현재 구현 의미 |
| --- | --- |
| GET /sources | 전국 원천·자료 준비 상태. 모델·전국 예측 완료와 구분 |
| GET /groundwater/catalog | 확보한 전국 지하수 관측소 목록. 예측용 승인 registry와 별개 |
| GET /groundwater/samples | 확보한 GIMS3개 지점의 원천 수위·심도 시계열. 단위·기준면 승인 및 모델 준비와 분리 |
| GET /rainfall/network | 확보한 강수 관측망·날짜 자료 조회 |
| GET /rainfall/stations/{station_id}/history | 확보한 해당 강수 관측지점의 이력 |
| GET /rainfall/aws-daily/network | 별도 지상·AWS 완료일 강수. date 선택, ASOS 일강수와 지점 모집단 분리 |
| GET /rainfall/aws-daily/stations/{station_id}/history | 현재 AWS 완료일 파일이 제공하는 지점·날짜 이력 |
| GET /rainfall/aws-snapshot | 별도 AWS 분자료 시점 누적 강수·품질·좌표 연결 상태 |
| GET /rainfall/collection-status | 기상 수집 worker의 enabled·상태·요청/성공 checkpoint |
| GET /rainfall/boundary | 전국 강수 화면의 지도 배경 |
| GET · POST /stations | 지역·verified·cursor·limit 목록 조회 또는 근거를 포함한 관측소 등록 |
| GET /stations/{station_id} | 단일 관측소 metadata |
| POST /stations/{station_id}/observations | 수위·강수 일자료 revision batch 등록, 전체 검증 후 transaction 저장 |
| GET /stations/{station_id}/history | start/end 선택, 저장한 일자료 조회 |
| GET /stations/{station_id}/pipeline | 자료 준비·모델·작업·예측·monitor 상태 |
| GET /stations/{station_id}/forecast | target_date 선택, 저장된 발행 예측 조회. 조회가 모델 실행·새 발행을 뜻하지 않음 |
| POST /stations/{station_id}/training-jobs | M0/M1 초기학습 접수. validation_targets·holdout_targets·max_epochs 선택 |
| POST /stations/{station_id}/prediction-jobs | input_end_date 선택, 저장 자료20일로 예측 접수 |
| POST /stations/{station_id}/fine-tuning-jobs | 활성 모델과 같은 입력 계약의41일 파인튜닝 접수 |
| POST /stations/{station_id}/evaluation-jobs | version 필수, 학습 이후30일 후보 평가 접수 |
| POST /stations/{station_id}/promotion-jobs | version 필수, 저장된 prospective 평가 근거를 재검증한 교체 접수 |
| POST /stations/{station_id}/rollback-jobs | version·reason 필수, 이전 활성 이력으로 복귀 접수 |
| GET /jobs/{job_id} | 전국 전용 작업 상태·결과 |
| POST /jobs/{job_id}/retry | failed/interrupted 작업만 재접수 |
| GET · POST /rainy-periods | 연도·지역별 사후 장마 기간 조회·근거 포함 등록, evaluation_only |

관측소 metadata에는 provider·source_station_id·region_code·level_unit·level_reference·verified·evidence·source_kind가 필요합니다. `station_id`는 슬래시 없는 URL-safe 문자열입니다. 기존 metadata는 불변이며 변경할 때 새 관측소 버전 ID를 사용합니다. 좌표 미확인은 null로 남길 수 있습니다. `verified=true`를 요청에 넣는 것이 원천 단위나 팀 승인 확인을 대신하지 않습니다. source_kind가 synthetic인 등록 자료는 보존할 수 있지만 전국 observed 모델 작업 실행은 거절합니다.

일자료에는 date·groundwater_level·rainfall_mm·level_unit·level_reference·available_at·collected_at·revision_id·source_sha256가 필요합니다. 시각은 timezone을 포함한 ISO8601이고 내부 비교는 UTC로 정규화합니다. 같은 revision 내용을 변경할 수 없고, 같은 날짜의 서로 다른 값이 동일 공개·수집 시각으로 충돌하면 conflict로 격리합니다. 결측을0으로 등록하지 않습니다. 관측 batch의 수위·강수 값은 유한 수치이며, 준비·모델 경로는 quality가 valid인 자료만 허용합니다.

snapshot은 해당20일의 자료가 **정보 마감시각 전에 공개되고 수집되었는지** 확인합니다. 입력 마지막 날짜는 마감시각의 KST 날짜보다 앞서야 합니다. `input_end_date`에서 하루 뒤가 `target_date`이고 `horizon_days=1`은 두 날짜의 차이입니다. 기본 worker는 당일D에 전일D-1 입력으로 D를 추정하므로 `forecast_timing=same_day_estimate`입니다. 서울 기본 화면의 ‘오늘 입력으로 내일 예측’과 혼동하지 않습니다. 과거 대상일을 지금 다시 계산한 결과는 `mode=historical_replay`, `forecast_timing=historical_reconstruction`이며 실제 과거 발행으로 인정하지 않습니다.

발행 예측은 station_id·model_version·feature_contract_id·input_end_date·target_date·prediction·issued_at·snapshot_id·단위·기준면·source_kind·mode·forecast_timing을 기록합니다. 재시도 시 같은 발행 기록을 재사용하며, 그 이후 만든 후보에 과거 발행 증거를 새로 붙이지 않습니다. 원천 revision과 snapshot이 달라진 별도 예측 기록은 보존하되 같은 대상일 후보 비교 증거는 최초의 날짜별 pair로 고정합니다.

### 전국 후보 평가와 상태

학습 접수 예시는 `{"variant":"M1","validation_targets":30,"holdout_targets":730}`입니다. 기간 수치는 운영 가설이며, 긴 holdout만으로 장마·강한 강수 표본이 충분하거나 개선된다고 보장하지 않습니다. 새로운 특징 계약은 새 초기학습으로 만들고, 동일 계약 파인튜닝은 model·scaler·특징 순서·단위·기준면을 바꾸지 않습니다.

최초 M0의 초기 허용 기준은 별도 holdout의 persistence 대비110%입니다. M1은 비교용 활성 M0가 없으면 `baseline_required`입니다. 기존 모델이 있을 때 새 모델 등록은 `awaiting_shadow`이고 서비스 모델은 유지합니다. 전국21일 감지 임계값은 초기 validation이 아닌 **동결 initial holdout의 rolling21 RMSE P95 ×1.5**이며 파인튜닝 때 기준 버전을 유지합니다. 상세 게이트와 자동 실행 조건은 [전국 운영 기준](operations.md#전국-실험-경로-apiv2)을 따릅니다.

후속 평가에는 cutoff 다음 날부터 연속30일의 실제 정답과 두 모델의 사전 발행 pair가 필요합니다. pair에는 candidate_version·champion_version·target_date·각 예측값·공통 issued_at·snapshot_id를 저장합니다. 정답 available_at보다 늦은 발행, 대상일 종료 후 발행, 다른 비교 버전, 날짜 공백은 교체 근거가 될 수 없습니다. 같은 날짜 pair는 같은 입력 snapshot·발행시각을 공유하며, 계약이 다른 모델은 각자 특징을 만들어 예측합니다. 임의로 과거 자료에서 재생성한 pair는 발행 증거로 인정하지 않습니다.

| 상태 | 의미 |
| --- | --- |
| awaiting_shadow | 첫30일 정답이 아직 부족함 |
| awaiting_issued_predictions | 정답 구간은 있으나 사전 발행 pair가1~29개뿐임 |
| retrospective_evaluation | 사전 발행 증거 없이 과거 자료로 비교함. 교체 불가 |
| insufficient_seasonal_evidence | M1의 장마·비장마·강한 강수 최소 표본 부족. 통과 아님 |
| gate_passed | 저장된 prospective 근거와 품질 게이트 통과. 실제 활성 참조와 작업 결과 확인 필요 |
| rejected · blocked | 성능 미달 또는 비교 모델 변경·근거 부족 등으로 기존 모델 유지 |
| active | 해당 버전이 활성화된 기록. 현재 선택 여부는 모델 목록의 active boolean으로 확인 |

감시는 `pipeline.monitor`에서 모델 버전·RMSE·threshold·breaches·last_trigger·last_processed_target_date·last_reason을 확인합니다. 같은 날짜 조회로 연속 초과 횟수나 학습 정답을 늘리지 않습니다. 최초 정답 revision을 보존하고 자료 수정으로 기존 판단 근거를 덮어쓰지 않습니다.

POST 작업 접수202는 자료 승인·학습·교체 성공이 아닙니다. 전국 전용 job을 조회해 queued/running/completed/failed/interrupted와 result를 확인합니다. 자료나 모델이 준비되지 않으면 작업 실행에서 실패할 수 있으며, 저장된 발행 예측이 없으면 forecast 조회는503입니다. 자동 worker는 `GROUNDWATCH_NATIONAL_SCHEDULER_ENABLED=false`가 기본이며, 켜도 최초 학습·외부 자료 수집·단위 승인을 대신하지 않습니다.

실험 v2 `GET /api/v2/rainfall/aws-snapshot`은 별도 AWS 단일 시점 원천을 반환합니다. `observed_at`은 KST 오프셋 포함, `temporal_contract`는 `minute_snapshot_accumulations_not_completed_daily_rainfall`, 지점 ID는 `kma_aws:`입니다. `observations[].rainfall_mm`과 `quality`는 RN-15m/RN-60m/RN-12H/RN-DAY 별 값과 품질입니다. 원천 -50 이하 sentinel은 null, 실제 0은 0입니다. 위치 미연결 지점은 좌표를 추정하지 않으며 ASOS 일강수와 합치거나 모델 학습 자료로 자동 승인하지 않습니다. 자료 파일 부재는 503입니다.

AWS 완료일 강수는 `temporal_contract=completed_calendar_day_KST_rn_day`, 지점 ID는 `kma_ground_aws_daily:`입니다. source의 `obs=rn_day` 결과를 완료된 KST 날짜별 강수로 조회하며 분자료 `RN-DAY`와 서로 대체하지 않습니다. 응답에는 date·available_dates·counts·stations·collected_at·단위·출처가 있습니다. available_dates는 현재 읽은 파일에 확보된 범위이며 전체 과거 기간 보장을 뜻하지 않습니다.

두 AWS 경로는 `${GROUNDWATCH_STATE_DIR}/weather/national_aws_{daily|snapshot}.json`을 우선 읽고, 해당 runtime 파일이 없을 때만 bundled `data/` 파일을 사용합니다. `NationalService.root`는 `${GROUNDWATCH_STATE_DIR}/national`이므로 기상 경로는 그 부모 아래 `weather/`입니다. 별도 ASOS `/rainfall/network` 자료는 이 파일들로 교체하지 않습니다. worker 실패 후 runtime 정상 파일이 남아 있으면 그 자료를 유지하며 과거 bundled 자료로 몰래 바꾸지 않습니다.

`groundwater/samples`는 `national_groundwater_samples.json`의3개 원천 관측소·확보 기간·date별 elev/lev와 원문 값·원본 해시·품질 보고를 제공합니다. 공식 원천 표시를 따라 elev는 `수위(el.m)`, lev는 `심도(m)`로 표기하며 서울 GL 수위로 변환하지 않습니다. observations.groundwater_level은 원천 elev를 그대로 표시하는 alias이고 학습용 정규화 계약이 아닙니다. 개별 관측소의 기준면·좌표 이력·강수 매핑·학습 승인은 미완료이므로 verified/model_ready/training_approved/mapping_approved는 false입니다. 이 파일 생성은 raw30개 SHA검증과 응답·날짜·숫자 검증을 거치며 결측·중복을0으로 대체하지 않습니다.

`collection-status`는 `weather_state.json`의 enabled·checked_at·status·streams를 반환합니다. streams.snapshot/daily는 attempted_request·attempted_at·completed_request·completed_at·raw_sha256·artifact·observations·status와 민감정보 없는 reason을 가집니다. status는 disabled/blocked/degraded/ready이고, state 파일이 아직 없으면 not_started입니다. ready와 최신성은 별개이므로 화면에서는 관측 대상시각·날짜·collected_at을 함께 확인해야 합니다. 수집을 꺼도 보존 자료를 조회할 수 있으며, 파일 존재나 HTTP200을 자동 수집 성공·지하수 모델 준비로 해석하지 않습니다.

전국 AWS 완료 일강수 이력은 `data/national_aws_history.json.gz`에 보존합니다. `station_metadata_by_date[YYYY-MM-DD]`는 해당 날짜 공식 응답의 좌표·이름을 사용하며, 합집합 메타데이터로 과거 좌표를 추정하지 않습니다. 기존 AWS 일강수 조회 API는 이력과 runtime 최신 완료일을 결합하며 동일 날짜는 마지막 정상 runtime 자료를 우선합니다. 원천에 없는 날짜는 404이고 없는 값은 결측으로 남깁니다.

`GET /api/v2/groundwater/samples`는 광주도척·무안무안·제주조천의 확보된 실측 280일을 반환합니다. `source_kind=observed`, 수위 `elev`와 심도 `lev`, 원천 문자열·해시·품질을 보존합니다. 원천 단위 표기 el.m/m는 해당 자료의 표기이며 `level_reference_status`·매핑 승인·학습 승인과 별개입니다. 이 조회는 모델 registry 등록이나 v1 대표 관측소 승인을 수행하지 않습니다.

### 기존 관제 서비스의 전국 통합 계약 변경안

단일 관측소 선택을 `station_id`로 식별하고 provider·지역·legacy_district_code를 분리합니다. 서울 v1 모델·시연 이력은 기존 엔진을 호출하고, 전국 실측은 원천 관측소별 엔진을 같은 network 조회 어댑터로 노출합니다. 별도 전국 대시보드를 유지하지 않습니다. 현재 사용자 요청에 따라 구현 중인 변경안이며 팀 담당자의 합의가 완료됐다고 주장하지 않습니다.

전국 station metadata는 `source_contract_verified`, `mapping_status`(unverified/experimental/approved), `operational_approved`, `mapping_version`, `evidence`를 구분합니다. 검증된 원천 계약과 명시적 실험 매핑의 학습·예측은 허용하되 운영 승격을 차단합니다. 기존 verified 관측소의 계약은 유지합니다. 모델·예측에는 동일 매핑 버전과 experimental/operational 범위를 보존합니다.

기본 UI는 서울25개 구별 고정 대표 관측소이며 현재 조회·종로구 선택으로 시작합니다. 전국 추가 자료 옵션에서 원천 계약 확인·실측 수위 확보 상태인3곳을 표시합니다. 서울의 현재 조회와 저장 자료 검증·합성 시연은 구분합니다. `/api/v2/network/stations`의 원천 전체 목록 응답은 변경하지 않으며 UI 표시 범위가 API 카탈로그 수를 뜻하지 않습니다.

서울 network history의 weather_context.rainy_region은 kma_asos:108이며 공식 서울 지점의 사후 장마 기간을 평가용으로 조회합니다. 기존 서울 원천 강수 날짜 결합은 유지하고 source_station_id를108로 바꾸거나 강수 입력 매핑 승인으로 해석하지 않습니다.

수위·연결 강수 차트의 금색 배경은 선택 구간과 겹치는 공식 장마 기간(사후 평가용)입니다. 다른 참고 기상지점 강수에는 지하수 관측소의 장마 라벨을 임의 적용하지 않습니다.


## 서울 추가 실측의 현재 조회 표시

`/api/v2/network/stations?mode=current`와 같은 경로의 관측소 history는 기존 서울 대표 관측소에 한해 검증된 추가 실측 스냅샷을 표시합니다. API 경로와 기존 필드는 유지하며 `data_source.observation_display_only`, `observation_snapshot_id`, `observation_collected_at`을 추가합니다. 이 읽기 연결은 학습 데이터셋 등록·매핑 승인·모델 활성화·승격을 수행하지 않습니다. 서울 원천의 같은 날짜 강수를 유지하며 ASOS 강수로 대체하지 않습니다.

예를 들어 2026-10-08 현재 종로구는 `observed_date=2026-09-30`, `freshness_days=8`, `quality_status=STALE_DATA`, `prediction=null`입니다. `data_source.observed_through`는 추가 실측 종료일, `input_through=null`은 해당 스냅샷이 기존 모델의 검증된 입력으로 연결되지 않았다는 뜻입니다. 기존 `dataset_version`은 기존 모델 자료 식별자이며 추가 실측 식별자는 별도 `observation_snapshot_id`입니다. history는 같은 추가 실측의 최근 최대180행이며 예측을 소급 생성하거나 과거 다른 자료의 예측을 붙이지 않습니다. 현재 추가 실측의 `capabilities.train`은 false이고 파이프라인의 기존 모델·감시 기록은 동결 자료 이력으로 안내합니다.

CSV 해시·동결 원본 해시·25개 고정 관측소·단위·중복 날짜·유한 수치 검증 실패 시 추가 실측 전체를 사용하지 않습니다. 서버 시작 시 읽기 스냅샷을 검증하므로 파일 갱신 후에는 재시작이 필요합니다. `historical_replay`, 합성 자료, 재생 세션에는 추가 실측을 연결하지 않으며 `/api/v1`과 원본 CSV·관측소 manifest·모델 Registry는 그대로 유지합니다. 이 additive 읽기 계약은 현재 구현 범위이며 양 파드 합의 완료를 뜻하지 않습니다.

### 전국 합성 관제 격리 계약

사용자가 자료 부족 부분의 시뮬레이션 보완을 승인한 개인 브랜치 구현입니다. 기존 v1·실측 station 계약을 변경하지 않고 `/api/v2/network/stations` 목록에 `provider=groundwatch_simulation`, `source_kind=synthetic`, `station_id=sim-gims-<원천후보ID>`, `source_station_id=sim-<원천후보ID>`를 추가합니다. UI는 별도 자료 범위로 필터링합니다. 이 ID의 상세와 모델 작업은 기존 v2 경로를 사용하고, 작업·모델 namespace는 `national_synthetic_v1`입니다. 운영 승인·운영 승격은 허용하지 않습니다.

`level_unit=m`, `level_reference=simulation_relative_datum`은 임의 상대 기준면입니다. `source_contract_verified=true`라도 `source_contract_scope=simulation_generator`이며 실제 원천 단위/좌표의 승인이라는 뜻이 아닙니다. `simulation_clock=true`의 일별 available_at은 가상 시계이고 실제 수집시각으로 해석하지 않습니다. history.origin=synthetic과 source_kind를 보존합니다. 합성 장마 분류는 `source_kind=synthetic`·scenario_evaluation_only이며 공식 통계와 분리합니다. 동일 후보의 실제 `kwater:<ID>` 항목을 덮어쓰지 않습니다.
