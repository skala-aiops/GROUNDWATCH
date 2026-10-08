# API·데이터 계약

현재 요청 스키마의 기준은 `serving_app/groundwater_api.py`와 실행 중인 [자동 API 명세](http://localhost:8100/docs)입니다. 이 문서는 날짜·출처·상태처럼 스키마만으로 이해하기 어려운 의미를 설명합니다. 정책 수치는 [운영 기준](operations.md)을 따릅니다.

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
