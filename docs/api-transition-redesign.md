# GroundWatch 과제·기획·실제 API 운영 재설계

최신 변경 계획은 맨 아래 17절을 따릅니다. 앞 절의 서울시 공급원 고정·오늘 예측은 이전 구현의 설명이며, 새 공급원과 내일 예측이 구현되었다는 뜻이 아닙니다.

검토일: 2026-10-07. 상태: 사용자 전면 반영 승인에 따른 로컬 구현 기준입니다. 사용자 확정 범위는 유지하고 팀 공유·병합은 기존 파드 절차를 따릅니다. 기존 실행 결과의 의미를 바꾸거나 미실행 기능을 완료 처리하지 않습니다.

## 1. 기준과 재설계 결론

통합가이드 원문 PDF 7·9·17~19·39~41쪽, 원래 사업기획 PDF 1~9쪽, 현재 proposal.md·AGENTS.md·TODO.md·operations.md·demo.md, 데이터 설명·공통 계약·구현 계획과 실제 코드를 대조했습니다. 가이드 18쪽과 사업기획 7쪽은 렌더링해서 표와 제외 범위를 확인했습니다. 교수자 일정은 상위 docs/instructor-milestones.md를 따릅니다. 제출 형식·최종 마감과 팀원별 담당자는 여전히 미확정입니다.

서비스 방향은 **기업 환경·안전 담당자가 서울의 고정 관측소 자료와 예측 신뢰 상태를 확인하도록 돕는 일별 관측·모델 운영 서비스**입니다. 공개 관측소는 현장 계측이나 구 전체의 평균을 대신하지 않습니다. 경보는 모델 오차와 자료·서비스 상태에 대한 운영 신호이며 지반 위험 확률이나 공사 중지 판단이 아닙니다.

전체 재작성보다 데이터 공급과 이력 구조를 교체하는 것이 필요합니다. 현재 과거 자료 재생·LSTM·MLflow·후보 평가·롤백·데스크톱 세 화면은 유지합니다. API 수집을 일별 운영으로 연결하려면 다음을 함께 바꿉니다.

1. 데이터 공급의 최신성·식별자·단위·강수 결측 의미를 먼저 검증합니다.
2. 수위와 강수의 출처별 관측 이력을 DB에 저장하고 검증된 결합 스냅샷을 발행합니다.
3. 모델 학습 자료와 매일 바뀌는 예측 입력 자료의 버전을 분리합니다.
4. 일별 운영의 입력 종료일·예측 대상일·정답 도착 시각을 구분합니다.
5. 기획·API·화면·발표가 동일한 상태와 근거를 설명하도록 갱신합니다.

## 2. 과제 필수와 팀 확정 범위

| 구분 | 유지해야 하는 기준 | 재설계 반영 |
| --- | --- | --- |
| 팀 평가 | 문제·운영 설계40, 구현·발표60 | 기능 수를 늘리는 것보다 하나의 실행 흐름과 근거를 완성 |
| 기획서① | 이해관계자 불편, 장애·지연·품질 저하의 업무 영향 | 구매 기업·실사용 담당자·내부 운영자·발표 청중 구분 |
| 기획서② | 핵심 기능, 모델 역할, 응답·품질 운영 목표 | 일별 자료 공급 한계와 준비된 예측의 목표를 명시 |
| 기획서③ | 스키마·성능 게이트, 지표·임계값, 알림→재학습→재검증→유지/롤백 | 수집 장애와 모델 품질 저하를 별도 대응 |
| 기획서④ | 공급/업로드→학습→MLflow→FastAPI·Docker→기록→감지→조치 | API 수집·관측 DB·스냅샷 발행을 앞단에 추가 |
| 기획서⑤ | 실제 Method·URL·요청/응답·422 등 | 변경 후 Swagger·실제 HTTP 예시로 교체 |
| 기획서⑥ | 버전 전환, 컨테이너, 감지·재학습 상태 변화의 실제 화면 | API 운영 증빙과 과거/합성 검증을 구분 |
| 도메인 치환 | 예측 대상·입력·공급·게이트·변화 신호·재학습·알림·이해관계자 | 현재 지하수 도메인 매핑 유지, 공급·날짜 계약 수정 |
| 팀 확정 | B2B, 서울25구·구당1고정, 같은 기준일 전체 조회 | 25행 유지, 미준비는 null·사유, 임의 관측소 교체 금지 |
| 팀 확정 | 종로구 기본 상세·운영, 세 화면, 실제 단계·로그 | 기존 탐색 유지, 데이터 단계의 상태 추가 |
| 팀 확정 | Docker 한 명령, 2파드, 개인→파드→dev→main, PR 없음 | 새 공통 계약 검토와 기존 통합 경로 유지 |
| 개인 과제 | HAIC·서브노트5항목·핵심질문·Day별 증빙 | 팀 API 전환으로 대체하지 않음 |

API 실시간 연동·PostgreSQL·지도·클라우드는 교수자 필수라고 확인되지 않았습니다. API 연동은 사용자의 추가 요청입니다. 과제는 합성자료 사용을 허용하지만 합성 승격 성공을 실측 모델 개선으로 설명할 수 없습니다. 발표는20분 이내이며 실제 수집을 기다려30일 평가를 발표 때 완료하는 설계는 성립하지 않습니다.

## 3. 원래 기획과 최신 확정의 충돌 처리

| 원래 사업기획 | 최신 기준 및 수정 방향 |
| --- | --- |
| B2G 1차 구매자, B2B 확장 | B2B 건설사·환경안전 관리 기업을 우선. B2G는 확장 가설 |
| 현장 관측정1개·현장 이상 선별 | 공개 관측소25곳. 실제 현장 연결 데이터는 없으므로 지역 관측 검토 보조로 범위 제한 |
| cm 양수, 강수×10 정수 | 원천 단위·부호 유지. 현재 과거 자료 gl.-m/mm와 API 단위를 독립 대조 |
| 756일 가상 CSV | 과거 공식 자료·합성 검증·실제 API 관측을 별도로 관리 |
| API·다중 관측소 제외 | 25개 고정 조회는 유지, API 운영은 새 변경 범위. 지도는 추가하지 않음 |
| API허브 RN_DAY | 실제 승인 서비스는 공공데이터포털 ASOS sumRn. 키·필드·정책을 혼용하지 않음 |
| Drift로 이상현장 우선순위 | 모델 오차 경보만으로 현장 위험 순위를 생성하지 않음. 확인 필요 상태와 담당자 기록 제공 |
| 다음 날 수위 | 일반 모델은 입력 종료일+1일. 일별 운영은 전일 입력으로 오늘 예측을 우선 목표로 제안 |

기업이 지불할 이유는 자료 취합·상태 확인·이력 추적 업무를 줄일 수 있다는 가설입니다. 실제 구매 의사·현장 대표성·검토시간 절감·사고 예방 효과는 측정하지 않았습니다. 원안의 법령·예산·사고 수치를 재사용하려면 발표 전에 해당 공식 원문과 날짜를 별도로 재확인합니다. 이 설계는 그 수치를 검증된 사업 성과로 채택하지 않습니다.

## 4. 현재 상태와 운영 연결의 차이

현재 예측은 공식 과거 CSV(2018-01-01~2024-03-18), 승인 대표 목록, 구별 모델과 재생 시계를 사용합니다. 현재 데이터 설명은52,591행이며 이번 설계 검토에서 원천 수집이나 모델 평가를 다시 실행한 것은 아닙니다.

실제 API 증거 external-api-verification.json에서 2026-09-30~10-06 수집 작업은 서울시0행, ASOS7행 중3행 유효·4행 격리, applied_to_forecasts=false입니다. 앞선 root 인증 조회와 특정 관측소·기간 자료 확보는 다른 상태입니다. HTTP200만으로 운영 입력 준비를 선언할 수 없습니다.

코드에서 확인한 변경 지점은 다음과 같습니다.

| 현재 구현 | 문제와 수정 방법 |
| --- | --- |
| external_observations의 원본/검증 JSON + 별도 queue | 출처별 수집 증거로 보존. 표준 관측 DB와 스냅샷 발행 과정으로 연결 |
| 서울시 요청에 관측소 이름만 사용, 기간은 로컬 필터 | 날짜 경로 필터를 검증 후 적용. API 정렬·페이지 이동으로 누락될 수 있으므로 이름/기간별 완전성 검사 |
| 서울시 최대10페이지 | 실제 공급자 범위 분할이 없어 기간을 줄여도 요청량이 줄지 않을 수 있음. 서버 필터·분할 전략 확인 전 backfill 시작 금지 |
| 수집 completed지만 양쪽 결합 입력은 없음 | 작업 종료, 공급자 완전성, 날짜별 자료 충족, 예측 준비 상태를 별도 표시 |
| latest_dataset이 마지막 ready 선택 | 출처·관측소·호환 계약별 명시적인 활성 snapshot 선택으로 변경 |
| queue_upload 실측 namespace=historical | historical/live/synthetic 용도 분리. 외부 원본이 실측이라는 이유로 historical에 자동 편입하지 않음 |
| ModelManager.check_ready의 dataset_version 완전 일치 | training_snapshot 고정, inference_snapshot 별도 기록, 모델 입력 계약 호환성으로 판정 |
| current가 오늘 입력을 요구하고 오늘+1 예측 | live의 target_date=오늘, input_end_date=어제 계약을 분리. 기존 replay as_of는 보존 |
| forecasts_v2 실제값 최초1회 label | 관측 정정·평가 버전 이력 추가. 최초 예측·당시 입력은 수정하지 않음 |
| objects JSON 중심 상태 저장 | 제약·조인·이력 추적이 필요한 관측·스냅샷·예측에 명시적 테이블 추가 |
| API·학습·수집 프로세스 분리, scheduler 없음 | 기존 분리 유지, 수집 일정·발행·추론·정답 대조 orchestration 추가 |
| 임의 이름/ASOS번호 입력 UI | 진단용으로 제한. 운영 수집은 승인 내부 station_id와 mapping_version으로 요청 |

## 5. 데이터 검증을 통과해야 하는 조건

서울시 VTsSec를 필수 공급원으로 요청했으므로 빈 응답을 다른 자료로 조용히 대체하지 않습니다. 첫 고정 관측소에서 공식 ID/이름·위치·관측기간·단위·기준면·부호·필터·최신 유효일을 대조합니다. 같은 기간의 기존 물순환 자료와 차이가 있으면 원인을 조사합니다. 자료가 오래되거나25곳에 대응하지 않으면 API 운영은 제한 상태로 두고 원천 변경안을 별도로 제시합니다. 기존 과거25곳 선정의 승인이 VTsSec 매핑 승인까지 의미하지 않습니다.

ASOS는 관측소 위치·운영기간·자료 품질과 지하수 관측소 거리를 비교해서 매핑합니다. 여러 지하수 관측소가 같은 ASOS를 사용하는 것은 허용하지만 중복 수집하지 않습니다. 108을 전 구에 사용해도 되는지는 비교 근거로 정하고 이를 확정 사실로 간주하지 않습니다. 관측소 이전·개명·폐지는 유효기간 있는 매핑으로 관리합니다.

강수의 공백은 현재 unknown입니다. 무강수·미량·미관측의 공식 의미와 품질 필드를 확인한 뒤 근거 있는 정책만 적용합니다. 공식 의미가 해결되지 않으면0으로 채우지 않습니다. 공백이 자주 발생하면20일 연속 입력을 확보하지 못할 수 있으므로 현재3/7일 성공을 모델 운영 가능의 증거로 쓰지 않습니다. 다른 강수 서비스·결측 마스크·수위 단독 모델은 입력 계약과 재학습이 필요한 대안이며 이번에 자동 채택하지 않습니다.

최소 검증은 첫 관측소30일의 원본/정규값 대조, 최근20일 입력 충족 여부, 과거 학습·검증·테스트 기간 확보 가능성입니다. 이후25곳 전체의 최근 유효일·결합률·유효 window 수를 조사합니다. 미래 날짜는 격리하되 임의 연도로 수정하지 않습니다. 수위는 음수라는 이유만으로 제외하거나 절댓값을 취하지 않습니다.

## 6. 목표 흐름과 날짜 계약

```text
서울시 수위 API ─┐
                 ├→ 수집 worker → 비밀값 제거 원본 + 수집 이력
기상청 ASOS API ─┘                    ↓
                             관측 revision·품질 판정
                                      ↓
                 승인 매핑·품질정책 → 날짜 결합 → 불변 snapshot
                                                    ├→ 초기/후보 학습 → MLflow
                                                    └→ 일별 추론 → 예측 기록
                                                                    ↓
                     정답 도착 → 평가 revision → 21일 품질 감시 → 경보
                                                                    ↓
                       재학습 → 후보30일 비교 → 게이트 → 교체/기존 유지
웹 세 화면 ← FastAPI ← 관측·자료 준비·모델·작업·이벤트·예측 조회
```

CSV는 과거 자료 이관·재현·수동 복구·내보내기에 남깁니다. 일별 입력의 최신성 판단은 DB와 발행된 snapshot이 담당합니다. 기존 모델 함수에는 필요한 경우 snapshot에서 생성한 canonical CSV/manifest를 전달하는 어댑터를 둡니다. 매일 CSV 업로드가 학습을 강제하는 구조는 사용하지 않습니다.

예를 들어10월8일 오전에10월7일까지 두 출처가 모두 준비되면9월18일~10월7일의20일 입력으로10월8일 수위를 예측합니다. target_date=10월8일, input_end_date=10월7일, issued_at=실제 발행 시각입니다. 오전 발행은 그날 일평균 수위에 대한 예측이며24시간 사전 예보라고 표현하지 않습니다. 당일 강수 예보는 사용하지 않습니다. 자료가10월6일까지라면10월8일 예측을 만들 수 없습니다.

발행 시점 전에 확보된 관측 revision만 사용합니다. 수집 시각과 공급자가 선언한 공개 시각이 다르면 둘을 구분하며, 공개 시각을 모르면 수집 시각을 가용 시각으로 사용합니다. 늦게 도착한 정답으로 과거 target의 예측을 새로 만들어 실시간 성능에 넣지 않습니다. 재계산은 명시적인 backtest 종류로 분리합니다.

live는 target_date, replay는 기존 as_of(입력 종료일)를 사용합니다. 날짜가 같은 이름으로 다른 의미를 갖지 않도록 화면·응답에서 둘 다 표시합니다. 시간은 UTC 저장, 업무 날짜·일정은 Asia/Seoul입니다.

## 7. DB와 파일 저장소 설계

과제 MVP는 **SQLite를 유지하되 명시적 관측/이력 테이블과 migration을 추가**하는 안을 권장합니다. API 연동 자체가 PostgreSQL을 요구하지 않습니다. 여러 서버가 동시에 쓰는 운영·다중 고객 격리가 실제 범위에 들어오면 PostgreSQL 전환을 별도 결정합니다. tech_blog의 DB 규칙을 이 과제에 이식하지 않습니다. MLflow의 내부 테이블은 직접 수정하지 않습니다.

관측 DB와 기존 운영 DB는 같은 영속 볼륨에서 별도 파일로 관리할 수 있습니다. 서로 다른 DB 파일에 걸친 원자적 커밋을 가정하지 않습니다. validated snapshot 생성→publish 작업 기록→운영 DB에서 snapshot_id를 멱등 등록→활성 포인터 교체→ack 순서로 이어주고 중단 지점 재시작을 검증합니다.

| 논리 테이블 | 주요 필드·관계·제약 |
| --- | --- |
| groundwater_stations | station_id PK, district_code, 공식 ID, 이름, 좌표, 운영기간. 이름을 PK로 쓰지 않음 |
| weather_stations | weather_station_id PK, 공급원, 공식 코드, 좌표, 운영기간 |
| mapping_versions / station_mappings | 버전·승인 근거·유효기간, 내부 station→서울시 식별자→ASOS. 같은 버전/구에 대표1곳, 기간 중첩 금지 |
| ingestion_runs / ingestion_pages | 출처·승인 매핑·요청기간·attempt·상태·건수·오류코드·완전성, 페이지 raw hash/path. 키/인증 URL 미저장 |
| observation_revisions | source, source_station_id, metric, observed_date, revision, value nullable, unit, raw_value, quality_status, available_at, ingestion/page FK, content_hash |
| quality_findings | 관측 revision/수집 페이지 FK, 규칙·정책버전·사유·처리 상태. 잘못된 날짜 등 canonical화 이전 오류도 보존 |
| feature_snapshots / snapshot_members | snapshot_id PK, 매핑·전처리·특성계약·지문·기간·상태, station/date별 수위/강수 revision FK. 한 snapshot의 동일 station/date는1행 |
| active_snapshots | 목적(live/training)·계약·station별 활성 snapshot과 generation. 같은 기준일 batch 조회는 사용 snapshot 목록을 고정 |
| model_bindings / deployment_history | namespace, station_id, MLflow version/run, training_snapshot, contract_id, trained_through, 평가근거, alias 변경 이력 |
| forecast_runs / prediction_records | run_id, live/replay/backtest, station, target/input_end/issued_at, 모델·추론snapshot·입력지문·계약, 값/단위·상태·사유 |
| evaluation_revisions | prediction_id, actual_observation_revision FK, actual_available_at, residual, evaluation_version, 정책, superseded_by |
| monitor_checkpoints / operation_events | namespace·station·model·policy·평가버전 기준 처리 날짜/창, 경보와 재학습 중복 방지키 |

이는 구현 목표 논리 스키마이며 모든 기존 객체를 한 번에 이관하라는 뜻은 아닙니다. jobs·request_metrics·기존 event는 재사용하고 이름/필드가 겹치면 어댑터를 사용합니다. 기존 forecasts_v2는 읽기 보존 후 새 prediction 기록을 병행합니다.

관측 metric은 groundwater_level/rainfall_mm 등을 명시하며 값·단위·품질은 묶어서 검사합니다. 품질 valid인 강수만 유한값·0이상 제약을 통과해야 합니다. 공백은 nullable+unknown으로 저장하고 feature 발행에서는 제외합니다. 같은 의미의 응답 반복은 content_hash로 중복 제거하고 마지막 확인 시각만 갱신합니다. 값이 바뀌면 revision을 추가합니다. 같은 응답 안의 충돌은 정정 순서로 추정하지 않고 격리합니다.

필수 인덱스는 관측(source, station, metric, date, revision), 가용시각, snapshot(station,date), 예측(namespace,station,target_date,issued_at), 대기작업(status,kind,created_at)입니다. FK·uniqueness·트랜잭션으로 중복과 끊어진 출처를 차단합니다. 원본 body와 모델/scaler는 파일 볼륨, 조회·상태·참조·hash는 DB에 둡니다. API 키는 환경변수에만 둡니다.

## 8. 자료·모델·캐시 버전 계약

다섯 식별자를 구분합니다. mapping_version은 관측소 대응, preprocessing_version은 단위·결측·품질 처리, feature_contract_id는 열순서·window20·단위·출처 의미, training_snapshot_id는 학습 자료, inference_snapshot_id는 이번 입력입니다. snapshot은 revision 목록과 정책을 포함해 지문화하고 단순 CSV 지문과 혼동하지 않습니다.

모델은 학습 snapshot·scaler·시간 분할·실제 MLflow 버전을 고정 보관합니다. 입력 자료에 하루 추가됐다는 이유로 기존 모델을 미준비 처리하거나 매일 재학습하지 않습니다. 관측소·단위·강수 매핑·전처리·특성 계약이 같을 때 새 snapshot을 사용할 수 있습니다. 다른 ASOS/단위/피처 정책은 새 계약과 재학습·게이트가 필요합니다.

현재 서울시 화면 강수와 새 ASOS의 출처가 다르므로 과거 ASOS를 결합한 새 데이터로 초기 학습부터 다시 평가합니다. 기존 모델을 복사해 live 성능이 검증됐다고 쓰지 않습니다. 과거 지하수 snapshot과 ASOS를 결합할 경우 hybrid_backtest 출처를 명시하고 VTsSec 과거/현재 의미가 같다는 검증 전에는 이를 live 학습에 승격하지 않습니다.

cache key는 namespace·station·model_version·contract·target_date·input_fingerprint입니다. 같은 target에 입력 정정으로 재계산하면 새 prediction revision을 만들고 최초 발행을 보존합니다. 사용자가 실제로 본 최초 결과와 사후 수정 결과의 성능을 분리합니다. GET 조회는 일별 예측을 매번 새로 발행하지 않으며 발행 job 결과를 읽습니다. 단일 sequence 추론은 실험용 호출로 유지하되 운영 실적 집계와 구분합니다.

## 9. 학습·감시·자동 대응

residual LSTM,20×2 입력, persistence 비교, train-only scaler, 날짜 공백을 가로지르지 않는 window는 유지합니다. 과거 최소180·최대730 유효 학습 정답, 검증/테스트 각60일, 재생90일은 기존 평가 프로토콜입니다. API 자료에서 동일 조건을 확보하지 못하면 미준비로 표시하고 평가 조건 변경안을 별도로 기록합니다. 성공을 만들기 위해 표본 수나 게이트를 몰래 줄이지 않습니다.

초기1.10·후보0.95·guard1.10,21일 RMSE·P95×1.5·연속2회·cooldown21일,41일 fine-tuning·후속30일 비교는 기존 과제 정책으로 유지합니다. 새 ASOS 모델의 검증 오차로 threshold를 새로 계산하며 기존 숫자를 그대로 복사하지 않습니다. baseline RMSE가0일 때 비율 지표를 나누지 않고 기존 절대 게이트 판정과 표본·0값을 기록합니다.

정답이 늦게 도착하면 기다립니다.21일은 연속된 유효 target 날짜이며21개 관측을 날짜 공백을 건너 모으지 않습니다. 후보30일도 날짜·정답 충족 조건을 명시하고 기존 gap 거절 정책을 유지합니다. 데이터 장애로 shadow가 불가능하면 이유를 남기며 게이트 실패와 구분합니다. 30일 기다림은 live에서 실제 시간이며, 발표는 격리 재생으로 검증합니다.

정답 정정은 평가 revision으로 재계산합니다. 과거 의사결정·경보를 삭제하거나 자동 소급 재학습하지 않습니다. 운영 경보는 당시 사용 평가 버전과 checkpoint를 고정하고 정정 영향은 검토 이벤트로 남깁니다. 동일 target 재조회·job 재시도·정답 정정이 경보 횟수를 중복 증가시키지 않아야 합니다.

수집 timeout/권한·한도/부분 페이지는 데이터 운영 이벤트, 입력 부족은 예측 미준비, 실제 오차 초과는 모델 품질 이벤트, p95/5xx는 서비스 이벤트입니다. 자료 장애로 모델을 재학습하거나 모델 교체로 사람의 현장 확인을 자동 해결하지 않습니다. RMSE 증가만으로 물리적 원인이나 통계적 drift가 입증됐다고 표현하지 않습니다.

## 10. 수집·작업·복구 운영

매일10:00 KST에 전일까지 최근7일을 재조회하는 초기안을 제안합니다. 이는 공급자 갱신 SLA가 아니며 실제 공개 지연을 측정해서 조정합니다. 최초 backfill은 승인 관측소/기간별로 분할하고 ASOS는 고유 기상지점별1회 수집합니다. 기간 필터와 정렬 안정성이 검증되지 않으면 서울시 전량 반복 호출로 우회하지 않습니다.

상태는 queued/running/completed/failed/interrupted 작업 상태와 source_complete/coverage/feature_ready/forecast_ready를 분리합니다. HTTP200·페이지 완료·유효 입력20일·예측 발행은 각각 다른 조건입니다. 동일한 source·mapping·station·range의 활성 작업을 막고 완료 후 최근7일 재수집은 허용합니다. 완료 작업을 무조건 재사용하면 정정을 못 받으므로 request idempotency와 논리 조회 범위를 구분합니다. 현재 Store.enqueue가 IntegrityError를 ValueError로 바꾸는데 ingestion은 IntegrityError만 잡는 부분도 정리합니다.

timeout·5xx는 제한 재시도, 인증 오류는 중단,429는 공급자 대기/한도 정책 적용, 원본 페이지와 offset을 checkpoint로 저장합니다. 총 건수 같음만으로 페이지 누락을 막을 수 없으므로 날짜/관측 키 커버리지·중복도 확인합니다. 수집이 부분 실패하면 원본은 남기고 영향 관측소 snapshot 발행을 보류합니다. 정상 다른 관측소는 별도 발행할 수 있으나 같은 기준일 준비 수를 정확히 표시합니다.

수집→검증→snapshot→추론→정답대조→감시→후보평가를 영속 job 의존관계로 잇습니다. 동일 작업 중단 후 재시도는 단계별 멱등이어야 합니다. 별도 scheduler는 job만 등록하고 TensorFlow를 직접 실행하지 않습니다. 학습 worker·수집 worker 분리는 유지하며 모든 worker의 heartbeat·마지막 성공/실패를 조회합니다.

서울시 공식 주소는 현재 HTTP이며 TLS 확인이 해결되지 않았습니다. 이를 숨기지 않고 정기 운영 전 전송경로와 공급자 대안을 검토합니다. 인증 URL·키를 요청 로그·traceback·응답·Git·PDF에 남기지 않습니다. 인터넷 공개 운영은 현재 범위와 별도이며 공개 전 쓰기 API 인증/권한·요청 제한이 필요합니다. 이번에 임의 로그인 제품이나 클라우드 배포를 추가하지 않습니다.

## 11. API와 화면 변경안

기존 /api/v1 경로를 최대한 유지하되 필드 의미를 바꾸는 경우 새 live 경로/DTO를 사용합니다. 아래 경로는 제안이며 현재 실행 계약은 contracts.md에 남겨 혼동을 막습니다.

| 기능 | 제안 계약 |
| --- | --- |
| 승인 수집 | POST /api/v1/ingestions: start_date/end_date, station_ids, mapping_version, request_id. 임의 이름 입력은 진단으로 분리 |
| 수집 조회/재시도 | GET /ingestions/{id}, POST /ingestions/{id}/retry. 기존 jobs retry와 단일 책임으로 통합 |
| 데이터 신선도 | GET /api/v1/data-freshness?target_date=YYYY-MM-DD: source별 last_observed/last_collected/지연/결합상태 |
| 자료 snapshot | GET /datasets는 용도·계약·coverage 추가. 기존 업로드는 historical 기본, live 편입은 승인 발행 job만 수행 |
| 오늘 예측 | GET /api/v1/live/forecasts?target_date=YYYY-MM-DD:25행, 요청 기준일·input_end·snapshot·issued_at·준비 수 |
| 과거 재생 | 기존 forecasts(mode=historical_replay, as_of, replay_id) 유지, live 자료와 자동 혼합 금지 |
| 모델·작업·이벤트 | 기존 조회 유지, namespace/station/source/event_type 필터·버전 추적 추가 |
| 준비/health | API alive, worker alive, 모델 호환 준비, input 준비,25개 forecast 준비를 구분 |

오류는 schema422, 충돌409, 없는 식별자404, 실제 공급자 장애는 비동기 작업 실패로 제공합니다. 전체 조회의 일부 미준비는200+행별 null/사유로 표시합니다. 모델 준비만으로 전체 입력 준비503/200을 결정하지 않습니다. 외부 공급자 오류 본문·키는 반환하지 않습니다.

전체 현황은25개 구 표를 유지하고 오늘 예측/과거 재생을 명확히 구분합니다. 각 행에 입력 종료일·예측일·발행 시각·자료 지연·자료 상태·모델 품질·현장 확인을 표시합니다. 같은 target 날짜에서 준비된 개수만 집계합니다. 모델 경보를 구별 위험도 색상이나 점수로 바꾸지 않습니다.

상세는 종로구 기본, 수위/강수 원천·ASOS·매핑·단위·기간·실측/예측·정정 여부·21일 품질을 보여줍니다. 운영 화면의 기존7단계는 유지하되 앞단을 수집/검증/결합/발행으로 펼치고, source별 실패·coverage·worker·후속정답 대기를 확인할 수 있게 합니다. 같은 로그를 여러 패널에 복제하지 않습니다.

## 12. 파일별 수정 계획과 파드 경계

| 대상 | 수정 내용 | 의존성·담당 범위 |
| --- | --- | --- |
| data/representatives.json·data/README.md | 기존 목록 보존, API 승인 매핑/정책 버전 추가 | 데이터·AI, 소스 검증 후 |
| external_observations.py·external_worker.py | 기간/페이지·관측 revision·정정·retry·coverage·발행 연계 | 데이터·AI |
| groundwater_store.py 및 새 observation repository/migrations | 명시적 관측·snapshot·예측/평가 이력, 멱등·migration | 양 파드 공통 계약, 파일 담당 합의 |
| data/groundwater.py | snapshot 어댑터·contract 검증, 현재 CSV loader 보존 | 데이터·AI |
| groundwater_models.py | 학습/추론 버전 분리·계약 호환·새 출처 재학습·cache | 데이터·AI |
| groundwater_service.py·worker | live 날짜·활성snapshot·발행·정답/monitor 이력 | 공통 서비스, 양 파드 연동 |
| groundwater_api.py·main.py | live DTO·freshness·오류·health·조회와 발행 분리 | 웹 및 공통 계약 |
| static/groundwatch.js·external-data.js·index.html | 세 화면·날짜·자료/모델 상태·승인 수집 UI | 웹 |
| compose.yaml·start_container.py·.env.example | scheduler/worker 감독·영속경로·키 최소 주입·일정 설정 | 공통 실행 계약 |
| tests/·scripts/verify_* | 날짜·정정·동시성·전체 루프 회귀와 실제 HTTP | 각 구현 담당, 통합은 공동 검증 |
| proposal.md |6항목 유지, B2B·자료 공급·오늘예측·아키텍처·실제 API/화면 갱신 | 구현된 사실과 계획 구분 |
| implementation-plan·contracts·operations·interface-design | 새 계약 확정 후 중복 초안 정리, 이 설계를 상세 근거로 연결 | 양 파드 합의 후 |
| demo.md·output/pdf/·evidence | API 실제 입력과 과거/합성 결과 분리, 새 화면·버전 증거 확보 후 PDF 재생성 | 발표·검수 |
| TODO.md·README·source-and-scope | 완료 상태·시작/복구·출처·AI/팀원 기여 갱신 | 확인된 결과만 기록 |

팀원 이름은 지정하지 않습니다. common DTO·DB·공유 service·Compose는 계약과 파일 담당을 먼저 정하고 병렬 수정하지 않습니다. 사용자가 설계 완료 후 전면 반영을 승인했으므로 관련 로컬 공통 계약도 구현합니다. 팀원 합의가 있었다고 꾸미거나 공유 브랜치 병합·푸시를 수행하지 않습니다.

## 13. 실행 순서와 단계별 완료 기준

| 단계 | 작업 | 다음 단계로 갈 근거 |
| --- | --- | --- |
| A. 원천 적합성 | 고정1곳의 VTsSec 의미/필터/최신성·ASOS 공백 의미 검증,25곳 coverage 조사 | 원본30일 대조·20일 window·과거 학습기간·매핑 근거. 불충족이면 대안 설계 |
| B. 계약·DB | 날짜·매핑·품질·버전 DTO, 관측 revision/snapshot migration | 임시 복사 DB migration·중복/정정/FK·부분실패·재시작 검증 |
| C.1곳 전체 연결 | 두 실제 API→관측→snapshot→새 ASOS 초기 모델→live 추론 | 실제 입력으로 target/issued_at·출처·모델 응답 확인. 과거 재생 회귀 |
| D.25곳 확장 | 승인 매핑·공유 ASOS 수집·동일target batch·관측소별 활성 |25행 준비 수/누락 사유·다른24곳 격리·동일target 일관성 |
| E.일별 운영 | 일정·정정재조회·retry·정답대조·오차/후보평가 | 실패 복구·정답 지연·정정 멱등·후보/기존 유지·재시작. live 장기평가는 대기 표시 |
| F.화면·증빙·발표 | 실제 API DTO 연결·6항목 기획서·19분 시연·PDF 갱신 | 실제 HTTP/화면/로그·기존 및 새 회귀·렌더 검수. 제출 완료는 별도 |

최초 검증에서 최신 자료가 없으면 live 활성화만 보류하고 DB·API·화면·복구 구조는 구현합니다. 제한된 API 수집 상태를 설명합니다. 과제 핵심 AIOps 시연은 기존 과거 재생과 명시적 합성 검증으로 유지할 수 있습니다. 사용자가 요청한 API 운영 완료를 과거 시연으로 대신 완료 처리하지 않습니다.

## 14. 필수 검증 시나리오와 전환·복구

정상 두 출처 수집, 무강수 명시0, 공백/미량/미관측, 미래날짜, 중복·충돌, 페이지 중 데이터 추가, 빈 응답,401/403/429/timeout, 한 출처 실패, scheduler 중복·중단 재시작, 관측소 개명/이전, 단위 불일치, 동일값 재수집·실제 정정,20일 공백, 가용시각 이후 자료 누수, 하루 추가 후 기존 모델 호환, 새 강수 계약의 구모델 거절을 검증합니다.

예측 최초 발행·입력 정정 재발행·정답 정정·monitor 중복 방지,21일/30일 연속성, 초기/후보 게이트 실패 유지, 실제 새 버전 HTTP, 롤백·다른24곳 격리, 자료 미준비와 API alive 구분도 확인합니다. 합성 테스트가 실제 공급자 의미를 증명하지 않으므로 원천 대조는 따로 수행합니다.

기존 데이터·원본·DB·MLflow·모델·예측·로그는 보존합니다. migration 전 일관된 DB 백업과 볼륨·모델 참조 목록을 확보하고 별도 새 경로에서 이관합니다. 기존 snapshot은 historical로 읽기 유지하며 근거 없는 revision/시각은 unknown으로 남깁니다. 새 계약이 없는 모델은 legacy로 표시하고 live에 자동 배정하지 않습니다.

첫 연결은 feature flag와 별도 live namespace로 검증합니다. snapshot 발행·alias/cache 교체는 실패 시 기존 검증 포인터를 유지합니다. live source가 바뀌어 구모델과 호환되지 않으면 과거 모델로 숫자를 대신 제공하지 않고 미준비를 반환합니다. rollback은 해당 계약에서 검증한 모델에만 허용합니다. 새 운영 확인 후에만 기본 화면/기본 자료를 바꾸며 볼륨 삭제로 검증하지 않습니다.

## 15. 문서 갱신 원칙과 미확정 결정

기획서6항목은 유지합니다.①기업 업무·②일별 운영 목표·③수집과 품질 분리·④새 흐름·⑤실제 DTO·⑥신규 증빙으로 갱신합니다. 기존52,591행 성능/90일 재생/합성 승격은 해당 데이터·기간 결과로 남기고 ASOS 모델의 성능처럼 재사용하지 않습니다. 출력 PDF는 현재 검증된 과거 구현의 판본이며 새 live 설계가 이미 구현된 판본으로 바꾸지 않습니다.

발표19분은 문제/범위3분, 원천·DB·날짜3분, 실제 조회/API3분, 과거·합성 AIOps5분, 복구/버전3분, 한계/다음검증2분으로 제안합니다. 실제 공급자 장애 시 사전 저장된 실제 원본·작업 기록임을 표시하고 성공 응답으로 위장하지 않습니다. 현장 업무 효과는 PoC 지표로만 남깁니다.

아직 확정해야 할 것은 VTsSec 적합성·전송경로, ASOS 공백 의미·25곳 매핑, 새 출처 학습자료 충분성, live 발행 시각·지연 기준, 공통 파일 담당, 새 API/DB 계약입니다. DB는 SQLite 유지, 매일10시·최근7일 정정재조회, 전일입력 오늘예측은 이 설계의 권장안이며 기존 팀 합의로 위장하지 않습니다.

이 문서는 원천·코드·과제·기획 재검토와 설계를 완료한 기록입니다. API 운영 전환·새 학습·DB migration·새 PDF·발표/제출 완료를 뜻하지 않습니다.

## 근거

- 과제 원문: 루트 SKALA_AIOps_통합가이드_최종_배포.pdf, PDF 순서7·9·17~19·39~41쪽.
- 원래 기획: /Users/baggeon-u/Downloads/GroundWatch_사업기획_MLOps_AIOps.pdf,1~9쪽. 최신 사용자 확정과 충돌하는 부분은 위 표에서 구분했습니다.
- 저장소: proposal.md, AGENTS.md, TODO.md, operations.md, demo.md, data/README.md, docs/contracts.md, docs/archive/implementation-plan.md, docs/archive/external-api-design.md, docs/archive/review-2026-10-07.md.
- 코드: serving_app/groundwater_store.py, groundwater_service.py, groundwater_models.py, groundwater_api.py, external_observations.py, external_worker.py, data/groundwater.py, compose.yaml, scripts/start_container.py.
- 실행 근거: evidence/external-api-verification.json. 이전 모델/재생 수치는 data/README.md·evidence/README.md의 기존 결과이며 이번 설계에서 재실행하지 않았습니다.
- [서울시 보조지하수 관측망 관측정보](https://data.seoul.go.kr/dataList/OA-15611/A/1/datasetView.do), [서울시 상세 API](https://data.seoul.go.kr/dataList/openApiView.do?infId=OA-15611&srvType=A): 목록 페이지 재조회, 상세는 이번 웹 조회 오류로 기존 명세 기록과 코드를 대조했습니다.
- [기상청 ASOS 일자료 공식 명세](https://www.data.go.kr/data/15059093/openapi.do):2026-10-07 재조회. 일자료 종료일 D-1, ASOS 지점 인자·sumRn·인증 및 호출 조건 확인 근거입니다.

## 16. 구현 반영 결과와 남은 원천 조건

사용자 위임 범위의 로컬 구현과 문서 반영을 완료했습니다. DB·수집/검증·immutable snapshot·live API·학습/추론 버전 분리·일별 scheduler·지연 정답 감시·격리된 화면 경로가 구현되었습니다. 운영 매핑은 등록과 명시 선택을 분리했습니다. snapshot 발행은 관측 DB transaction, 운영 job은 운영 DB transaction으로 멱등 처리하며, 두 DB 간 하나의 transaction을 가정하지 않습니다. worker 반복 실행은 이미 발행된 snapshot/예측 ID를 재사용합니다. 초기 live 모델은 시간 분리 검증 기간을 정한 명시적 학습 요청으로 생성합니다.

회귀86개 중85개 통과·1개 제외이며 새 live 학습/추론 검사는 결정적 fixture입니다. 실제 HTTP200·브라우저에서 과거25/25·오늘0/25를 확인했습니다. 기존1,014개 모델·자료의 해시는 동일하고 DB3개 무결성은 정상입니다. 검증 근거는 ../evidence/api-transition-verification.json입니다.

실제 API에서 오늘 예측이 운영 중인 상태는 아닙니다. 서울시 식별·단위/기준면·기간 필터, ASOS 매핑과 공백 강수 의미가 원천 조건으로 남아 있습니다. 기존 모델을 호환 모델로 가장하거나 공백을0으로 채워 완료를 만들지 않았습니다. 기존 읽기용 발표 PDF는 API 전환 전 기록으로 보존하며 최신 설명은 ../demo.md와 API 전환 기획 PDF를 따릅니다.

## 17. 현재 날짜 기준 미래 예측 전환 계획

2026-10-07 사용자 요청: 기존 입력·공급원을 반드시 재사용할 필요 없이 과거 공공데이터로 학습하고 현재 날짜 이후를 예측합니다. 계획 후 구현·검증을 진행하며, 관련 없는 기능과 원본·기존 증거는 보존합니다. 서울25구 전체 관측소를 국가측정망으로 대응시켰다고 간주하지 않습니다.

### 실행 순서와 완료 기준

1. **공급원 검증과 인증**: GIMS 국가지하수측정자료조회서비스의 키 발급·서비스 상세 명세를 확인합니다. 관측소 제원, 최근30일과 과거 학습기간을 실제 조회해 최신 관측일·연속성·기준면·단위를 확인합니다. 서울 내 후보를 우선 확인하고, 없으면 전국의 후보를 별도 시험 대상으로 표시합니다. 최근 자료가 확인되지 않으면 공급원 채택과 운영 모델 교체를 진행하지 않습니다. GIMS의 '실시간' 메타데이터만으로 전일 관측 확보를 주장하지 않습니다.
2. **최소 데이터 계약 확정**: 공급자와 고유 station_id, 위치·단위·기준면·매핑 유효기간을 저장합니다. 국가측정망은 기존 구 코드에 억지로 배정하지 않습니다. 승인된1~3곳의 시험 운영부터 시작하며 기존 서울25곳의 과거 조회는 유지합니다. 기존 SQLite의 revision·수집 이력·불변 snapshot을 재사용하고, 필요한 경우에만 호환되는 migration을 추가합니다.
3. **날짜·학습 계약 변경**: issued_at(발행시각), input_end_date(마지막 입력일), forecast_date(예측일), horizon_days(입력일에서 예측일까지)를 구분합니다. 한국 시간 오늘의 다음 날을 목표로 합니다. 10월7일 발행·10월6일 입력이면10월8일 예측으로 horizon=2입니다. 입력 지연이 달라지면 검증된 horizon 모델만 선택하고 없으면 예측 불가 사유를 반환합니다. 기존 하루 뒤 모델의 출력 날짜만 바꾸지 않습니다. 새 계약·모델 namespace로 기존 학습과 구분합니다.
4. **가벼운 모델 비교**: 같은 시간순 학습/검증/최종평가 기간과 같은 horizon에서 마지막 수위 유지 기준, Ridge, 기존 LSTM을 비교합니다. 수위 이력·변화량·과거 강수 누적·계절 정보를 후보로 하고 scaler·특징 선택은 학습 구간에만 적합합니다. 수위 단독 모델도 비교해서 강수 결측 때문에 운영이 막히는 경우를 평가합니다. 결측 강수를 임의0으로 채우지 않습니다. 최종평가를 반복해 튜닝하지 않고 RMSE/MAE·기준 대비 성능·실행시간으로 선택합니다. 자료가 부족하면 그 사실을 기록합니다.
5. **최신 강수 예보 연결**: 기상청 단기예보 서비스의 별도 활용 승인 여부를 확인하고 관측소 위치에 맞는 격자와 발표시각을 저장합니다. 첫 버전에서는 관측 기반 수위 예측 옆에 예보를 표시합니다. 예보 원문과 issued_at·valid_at을 축적하고, 과거 발표 예보를 확보하여 발행시점 기준 검증이 가능해진 뒤에만 예보 입력 모델을 비교합니다. 실제 미래 강수량을 예보처럼 학습 입력에 넣지 않습니다.
6. **운영·화면·과제 반영**: 기존 worker에서 최신 자료 수집→품질 검증→snapshot→내일 예측을 실행합니다. 작업·예측 중복을 방지하고 나중에 도착한 실제값으로 평가합니다. 화면은 관측소·최종 관측일·예측 대상일·자료 지연·모델 버전과 평가 상태를 구분합니다. 자동 재학습/후보 게이트/MLflow/롤백/Docker 흐름을 유지합니다. proposal·contracts·팀 설명·운영·실행 증거를 실제 구현에 맞게 갱신하고 제출 증빙은 통합가이드와 대조합니다.
7. **검증과 전환**: 날짜 경계·시간대·관측 지연·결측·미승인 관측소·정답 누수·모델 호환성을 테스트합니다. 실제 인증 API→DB→학습→내일 예측→HTTP→브라우저를 확인하고 Docker 재기동 후 유지 여부를 확인합니다. 미래 실제값이 아직 도착하지 않았다면 '예측 발행 완료, 실제 오차 평가 대기'로 기록합니다. 기존 운영 경로의 전환은 새 경로 검증 후에만 수행합니다.

### 인증과 현재 실행 상태

- GIMS는 자체 활용신청 후 발급한 인증키를 요청에 포함하는 방식입니다. 공공데이터포털 ASOS 키를 GIMS 키로 재사용하지 않습니다. 공식 안내: https://www.gims.go.kr/apiIntro.do ; 서비스 목록: https://www.gims.go.kr/opnApiList.do . 실제 브라우저에서 현재 비로그인 상태를 확인하고 발급 안내를 열었습니다. 회원가입·본인인증은 사용자 입력이 필요할 수 있습니다.
- 기상청 ASOS는 기존 설정을 사용하되 실제 승인과 호출을 재확인합니다. 단기예보는 별도 서비스 활용신청이 필요하며 인증키 문자열의 신규 발급과 서비스 추가 승인을 구분합니다. https://www.data.go.kr/data/15084084/openapi.do . 기존 승인 여부는 미확인입니다.
- 키는 서버 .env에만 저장하고 출력·Git·이미지·브라우저 응답에 포함하지 않습니다. 아직 발급되지 않은 키나 미확인 상세 명세를 가정한 수집기는 만들지 않습니다.
- 이번 단계에서 계획 작성·현재 코드의 하루 뒤 계약 확인·공식 발급 절차 확인을 실행했습니다. 새 공급원 실제 자료 확보·새 모델 학습·내일 예측 운영은 아직 완료하지 않았습니다.

## 18. 인증 신청 오류 후 실행 범위 조정

2026-10-07 사용자 결정으로 GIMS 전환을 보류하고 기존 공식 과거 자료의 학습·예측 경로를 우선 사용합니다. GIMS 신청 양식에는 로컬 APP URL과 실제 Python 사용을 명시하고 제출했으나 apiManagement.do에서 시스템 오류가 발생했습니다. 접수·발급 여부는 미확인이므로 중복 제출하지 않습니다. 오류 화면은 /tmp/groundwatch-gims-submit-error.png에 보존했습니다.

17절의 새 공급원·현재 기준 내일 예측은 후속 계획으로 남깁니다. 과거 자료를 현재 날짜로 이동하거나 기존 하루 뒤 모델을 이틀 뒤 모델로 표시하지 않습니다. 기본 화면을 과거 자료 모드로 전환하고 기준일 다음 날 예측과 실시간 예측의 차이를 안내합니다. 이미 존재하는 실측 모델은 실제 API 응답과 기록을 검증하며, 모델·입력 변경 없이 초기 학습을 불필요하게 반복하지 않습니다.
