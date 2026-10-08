# GroundWatch 백엔드

FastAPI로 관측 자료·예측·모델 관리 API와 빌드된 React 화면을 제공합니다. 학습·수집·감시는 worker가 처리합니다. 전체 실행은 [루트 README](../README.md), API 형식은 [공통 계약](../docs/contracts.md), 모델 정책은 [운영 기준](../docs/operations.md)을 따릅니다.

## 실행과 API 확인

저장소 루트에서 실행합니다.

```bash
docker compose up --build
```

API 명세는 http://localhost:8100/docs 에서 확인합니다. Docker 내부 포트는 8099, 기본 호스트 포트는 8100입니다. 환경변수·키·포트 변경과 장애 대응은 루트 실행 안내를 따릅니다.

## 모듈별 역할

| 파일 | 역할 |
| --- | --- |
| `main.py` | 앱 생성·라우터 연결·오류 처리·요청 계측·정적 화면 제공 |
| `*_api.py` | HTTP 경로·요청 검증·서비스 호출·응답 |
| `*_service.py` | 업무 규칙·조회·작업 조율 |
| `groundwater_store.py`·`*_repository.py` | SQLite 상태·작업·관측 자료 저장 |
| `*_models.py` | 학습·추론·평가·모델 버전 관리 |
| `*_worker.py` | 학습·수집·감시 작업 실행 |
| `worker_runtime.py` | TensorFlow 작업 잠금·프로세스 실행 |

Python 패키지는 `backend/`입니다. API·서비스·모델·worker는 모듈 이름으로 구분하며, 테스트는 `backend/tests/`에서 관리합니다.

## Python 컨벤션

- 모듈·함수·변수는 `snake_case`, 클래스는 `PascalCase`, 상수는 `UPPER_SNAKE_CASE`를 사용합니다.
- 공개 함수와 요청 경계에는 타입을 명시하고, docstring·주석은 처리 이유와 예외 조건을 설명합니다.
- 경로는 `pathlib.Path`로 다루고 실행 위치에 따라 데이터 저장 경로가 바뀌지 않도록 설정된 root를 사용합니다.
- Secret은 환경변수로 주입합니다. 키가 들어 있는 URL·헤더·응답을 로그나 예외 메시지에 그대로 남기지 않습니다.
- 포맷터·린터가 자동 실행된다고 가정하지 않습니다. 현재 저장소에는 이를 강제하는 공용 검사 설정이 없습니다.

## 라우터·서비스·저장소 컨벤션

- 라우터는 HTTP 입력과 상태 코드를, 서비스는 업무 규칙을, 저장소는 영속 상태 접근을 담당합니다. 라우터에 학습 루프나 SQL을 추가하지 않습니다.
- 입력은 Pydantic과 명시적 범위 검사로 검증합니다. 기존 strict 요청 모델의 추가 필드 금지·비유한 값 금지 조건을 유지합니다.
- 누락·검증 실패·상태 충돌·준비 부족을 구분합니다. 기존 `detail` 오류 형식과 상태 코드를 변경할 때는 공통 계약과 영향 테스트를 먼저 확인합니다.
- SQLite 변경은 저장소의 트랜잭션·잠금 규칙을 따릅니다. UI 응답을 맞추기 위해 DB나 모델 파일을 직접 덮어쓰지 않습니다.
- 긴 작업은 작업 등록과 상태 조회를 분리합니다. 중복 요청·재기동 시 기존 작업을 다시 실행하거나 결과를 중복 기록하지 않도록 확인합니다.

## 데이터·모델·worker 컨벤션

- 관측소 식별자·namespace·자료 출처·단위·모델 버전을 함께 유지합니다. 서울 기본 자료·전국 실측·합성 실험을 섞지 않습니다.
- 날짜 공백과 결측은 보존하고 강수 결측을 0으로 채우지 않습니다. 관측일·입력 종료일·예측 대상일을 구분합니다.
- 전처리·학습·승격 기준은 [운영 기준](../docs/operations.md)을 따릅니다. 화면 표시를 위해 예측값이나 게이트 결과를 조정하지 않습니다.
- 후보 등록·평가·승격을 구분하고 실제 응답의 `model_version`으로 서빙 상태를 확인합니다.
- TensorFlow 작업은 `worker_runtime.py`의 잠금과 프로세스 격리 경로를 사용합니다. API 프로세스에서 임의로 학습을 병렬 실행하지 않습니다.
- 외부 API 실패는 기존 정상 자료를 유지하면서 사유를 기록합니다. 인증 실패·공급자 장애·자료 없음을 구분합니다.

## 검증

공용 이미지에는 테스트 의존성이 포함됩니다. 서비스를 기동한 뒤 저장소 루트에서 실행합니다.

```bash
docker compose exec backend python -m backend.worker_runtime --state-root /app/runtime/groundwatch --locked-command python -m pytest backend/tests -q
```

위 명령은 `backend/tests/` 전체를 실행합니다. API·저장소·데이터·모델·worker 검증이 함께 있으므로 빠른 확인이 필요하면 변경에 해당하는 파일을 지정합니다.

```bash
docker compose exec backend python -m backend.worker_runtime --state-root /app/runtime/groundwatch --locked-command python -m pytest backend/tests/integration/test_network_service.py backend/tests/integration/test_national_api.py -q
```

- 단위 검증은 입력 경계·계산·상태 전이를 확인하고, 통합 검증은 서비스·저장소·API 연결을 확인합니다.
- 테스트는 임시 저장 경로와 테스트 자료를 사용합니다. 운영 자료나 실제 서비스 모델을 테스트용으로 변경하지 않습니다.
- 모델 변경은 시간 분리·정답 누수·결측·단위·버전 식별을 검증합니다. 합성 시연 결과를 실측 성능으로 설명하지 않습니다.
- pytest 통과와 실제 HTTP·브라우저 동작을 구분합니다. 기능 변경에 해당하는 실제 요청과 상태 변화도 확인합니다.

저장된 검증 결과와 실행 조건은 [실행 증거](../evidence/README.md)에 보존합니다. 프론트엔드 검증은 [프론트엔드 README](../frontend/README.md)를 따릅니다.

파트별 테스트는 다음 경로를 지정해 실행합니다.

| 경로 | 검증 대상 |
| --- | --- |
| `backend/tests/integration/` | HTTP·서비스·저장소·화면 배포 연결 |
| `backend/tests/data/` | 원천 파싱·연속 입력·결측·합성 격리 |
| `backend/tests/aiops/` | 모델 생명주기·드리프트·후보 평가·worker |
| `backend/tests/support/` | 공유 테스트 더블·자료 생성 도우미, 테스트 수집 대상 아님 |

예: 위 전체 명령의 마지막 `backend/tests`를 `backend/tests/aiops`로 바꾸면 AIOps 검증만 실행합니다.
