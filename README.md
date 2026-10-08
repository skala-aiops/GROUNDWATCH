# GroundWatch

서울 25개 구 대표 관측소의 다음 날 지하수위를 예측하고, 서비스 운영자가 모델 오차와 재학습 상태를 확인하는 SKALA 팀 과제 시제품입니다. 기본 자료는 공식 과거 관측과 과제용 합성 확장입니다. 현장 안전 등급이나 싱크홀 발생 확률을 제공하지 않습니다.

## 실행

Docker를 실행한 뒤 저장소 루트에서 다음 명령을 사용합니다.

```bash
docker compose up --build
```

- 화면: http://localhost:8100/ (React 대시보드 `/dashboard/`로 이동)
- 기존 화면: http://localhost:8100/legacy/
- API 명세: http://localhost:8100/docs
- 생존 확인: http://localhost:8100/health/live
- 입력·모델 준비 확인: http://localhost:8100/health/ready

Docker 빌드에서 `frontend/`의 React·TypeScript·Vite 화면을 Node 단계로 빌드하고 FastAPI가 정적 파일을 제공합니다. 프론트 개발용 API 프록시는 8100을 사용합니다. 최초 자료 검증과 구별 학습은 자동입니다. 준비가 끝나기 전에는 수치를 만들지 않습니다. 일반 조회와 기본 시연에는 CSV 업로드나 외부 API 키가 필요하지 않습니다. 외부 수집 설정은 로컬 `.env`에 두고 Git에 올리지 않습니다. 포트 변경은 `GROUNDWATCH_PORT`로 지정합니다. 종료는 `docker compose down`이며 모델·자료가 든 볼륨은 유지합니다.

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

발표용 [GroundWatch_발표기획서.pdf](output/final/GroundWatch_발표기획서.pdf), 편집 가능한 [PPTX 원문](output/source/GroundWatch_발표기획서.pptx), [페이지별 대본](output/source/발표대본.md)을 관리합니다. [요구사항 검수](output/source/proposal.md)에서 여섯 필수 흐름과 페이지를 확인합니다. 과제 기획의 기준 문서는 [proposal.md](proposal.md)입니다. `건우짱.pdf`는 위 최종 파일명으로 정리했습니다. 실제 제출·발표 완료는 별도로 확인합니다.

## 협업과 문서 관리

브랜치·커밋·AI 작업 규칙은 [AGENTS.md](AGENTS.md)를 따릅니다. 개인 작업 → 해당 파드 → dev → main 순서로 통합합니다.

기능 변경은 해당 기준 문서의 기존 내용을 수정합니다. 같은 설명을 여러 파일에 복제하거나 변경 때마다 새 설계 문서를 만들지 않습니다. 과거 검토는 `docs/archive/`, 날짜별 실행 기록은 `evidence/records/`에 보존합니다. 현행 문서에는 과거 상태를 현재처럼 섞어 쓰지 않습니다.

검증 명령은 `docker compose exec serving-app python -m unittest discover -s tests -v`와 `node tests/replay_ui.test.cjs`입니다. 프론트 검증은 `frontend/`에서 `npm ci`, `npm test`, `npm run build`입니다. 공용 Docker 기동에는 호스트 npm 설치가 필요하지 않습니다. 최근 저장된 실행 결과와 환경 제한은 실행 증거에서 확인합니다.
