# GroundWatch

서울 25개 구 대표 관측소의 최신 가용 관측 다음 날 지하수위를 예측하고, 서비스 운영자가 모델 오차와 재학습 상태를 확인하는 SKALA 팀 과제 시제품입니다. 기본 화면은 서울시 지하수·기상청 강수 API 자료로 학습한 별도 모델을 사용합니다. 공식 과거 CSV와 과제용 합성 확장은 별도 시연 모드에 보존합니다. 현장 안전 등급이나 싱크홀 발생 확률을 제공하지 않습니다.

## 실행

Docker를 실행한 뒤 저장소 루트에서 다음 명령을 사용합니다.

```bash
docker compose up --build
```

- 화면: http://localhost:8100/ (React 대시보드 `/dashboard/`로 이동)
- 기존 화면: http://localhost:8100/legacy/
- API 명세: http://localhost:8100/docs
- 생존 확인: http://localhost:8100/health/live
- 기존 시연 경로 입력·모델 준비: http://localhost:8100/health/ready
- 실제 API 관측·예측 준비: http://localhost:8100/api/v1/api-observations (`observation_count`, `ready_count`)

Docker 빌드에서 `frontend/`의 React·TypeScript·Vite 화면을 Node 단계로 빌드하고 FastAPI가 정적 파일을 제공합니다. 프론트 개발용 API 프록시는 8100을 사용합니다. 실제 API 수집에는 서버 `.env`의 키와 `GROUNDWATCH_COLLECTION_ENABLED=true`가 필요합니다. 키를 브라우저에 입력하거나 Git에 올리지 않습니다. worker는 수집 자료로 미준비 모델을 학습하고 기존 모델은 재사용해 예측을 발행합니다. 준비 전에는 수치를 만들지 않습니다. 별도 과제 시연에는 외부 키와 CSV 업로드가 필요하지 않습니다. 포트 변경은 `GROUNDWATCH_PORT`로 지정합니다. 종료는 `docker compose down`이며 모델·자료가 든 볼륨은 유지합니다.

## 읽는 순서

| 알고 싶은 내용 | 기준 문서 |
| --- | --- |
| 누구를 위한 서비스인지, 사용법과 전체 흐름 | [팀 사용·로직 안내](docs/team-guide.md) |
| 과제 목적·운영 설계·구조·API·실제 화면 | [기획서](proposal.md) |
| 자료의 출처·기간·단위·합성 생성식 | [데이터 설명](data/README.md) |
| 감지·재학습·평가·복귀·장애 대응 | [운영 기준](docs/operations.md) |
| 요청·응답과 날짜·자료 계약 | [API 계약](docs/contracts.md) |
| 확인된 결과와 원본 증거 | [실행 증거](evidence/README.md) |
| 실제 남은 확인 사항 | [TODO](TODO.md) |

## 제출 자료

발표 PDF는 별도 세션에서 관리합니다. 원격 main에 반영된 파일은 [output/source/건우짱.pdf](output/source/건우짱.pdf)이며, 이번 코드·문서 변경에서는 발표 파일을 편집하거나 검수하지 않습니다. 과제 기획의 코드 기준 문서는 [proposal.md](proposal.md)입니다. 실제 제출·발표 완료는 별도로 확인합니다.

## 협업과 문서 관리

브랜치·커밋·AI 작업 규칙은 [AGENTS.md](AGENTS.md)를 따릅니다. 개인 작업 → 해당 파드 → dev → main 순서로 통합합니다.

기능 변경은 해당 기준 문서의 기존 내용을 수정합니다. 같은 설명을 여러 파일에 복제하거나 변경 때마다 새 설계 문서를 만들지 않습니다. 과거 검토는 `docs/archive/`, 날짜별 실행 기록은 `evidence/records/`에 보존합니다. 현행 문서에는 과거 상태를 현재처럼 섞어 쓰지 않습니다.

검증 명령은 `docker compose exec serving-app python -m unittest discover -s tests -v`와 `node tests/replay_ui.test.cjs`입니다. 프론트 검증은 `frontend/`에서 `npm ci`, `npm test`, `npm run build`입니다. 공용 Docker 기동에는 호스트 npm 설치가 필요하지 않습니다. 최근 저장된 실행 결과와 환경 제한은 실행 증거에서 확인합니다.

## 실제 API 관측 연결

기본 React 조회 모드는 `실제 API 관측·예측`입니다. 서버의 외부 worker가 서울시 VTsSec와 기상청 ASOS 서울 108을 호출하고 날짜별로 결합합니다. 수위는 `API 원값`, 강수 빈값은 null로 보존하며 모델에는 학습 구간 강수 중앙값과 결측 표시를 입력합니다. 3개 입력 특성의 모델·scaler·예측·운영 이력을 `api_native_masked_v1`에 분리합니다. 기존 gl.-m 시연 모델에 API 원값을 넣지 않습니다.

자동 수집은 KST 10시 이후 하루 1회이며 실패 시 1시간 이후 재시도합니다. 60초마다 실행 조건을 확인하고, 한 번의 수집은 여러 페이지 API 요청으로 이루어집니다. 최신 유효 지하수 관측 기준 365일을 최대 120페이지에서 검증해 수집합니다. 화면의 수동 수집은 별도 작업입니다. 원본·결합 자료·해시별 입력 스냅샷은 `runtime/groundwatch/external/feed/`에 보존합니다.

`모델 관리 · 시연`에서 실제 수집·발행 예측 오차·드리프트·재학습·30일 후보 평가·교체/유지·복귀를 확인합니다. 시험 구간 예측은 드리프트 감시에 사용하지 않습니다. 발행 당시 미수신 정답이 이후 수집되어야 진행하며, 공급자 지연을 오늘 관측으로 바꾸지 않습니다. 2026-10-08 검증에서 실제 자료 예측은 25/25곳 준비됐고 최신 지하수 관측일은 2026-08-31입니다. 구별 관측일·예측일과 검증 결과는 [실행 증거](evidence/README.md)를 확인합니다.
