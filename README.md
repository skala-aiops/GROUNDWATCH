# GroundWatch

서울25개 구별 대표 관측소의 수위·강수와 모델 품질을 확인하는 SKALA 팀 과제 시제품입니다. 기본은 서울25개 구 관제이며 종로구 대표 관측소를 먼저 선택합니다. 전국 광주도척·무안무안·제주조천3곳의 공식 수위·강수280일은 추가 자료 확장 옵션입니다. 서울 과거 실측·합성 시연·전국 추가 실측의 기간과 모델 이력을 구분합니다. 현장 안전 등급이나 싱크홀 발생 확률을 제공하지 않습니다.

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

Docker 빌드에서 `frontend/`의 React·TypeScript·Vite 화면을 Node 단계로 빌드하고 FastAPI가 정적 파일을 제공합니다. 프론트 개발용 API 프록시는 8100을 사용합니다. 최초 자료 검증과 구별 학습은 자동입니다. 준비가 끝나기 전에는 수치를 만들지 않습니다. 일반 조회와 기본 시연에는 CSV 업로드나 외부 API 키가 필요하지 않습니다. 이미지 빌드에는 패키지 다운로드 네트워크가 필요하며, 기본 자료·실험 모델은 컨테이너에서 준비합니다. 외부 수집 설정은 로컬 `.env`에 두고 Git에 올리지 않습니다. 포트 변경은 `GROUNDWATCH_PORT`로 지정합니다. 종료는 `docker compose down`이며 모델·자료가 든 볼륨은 유지합니다.

기본 화면은 ‘서울25개 구별 대표 관측소’ 범위의 현재 조회이며, 종로구(11110)가 기본 선택입니다. 3D 구 경계 지도에서 구를 선택하고 GL 기준 개념 단면·수위·강수·장마 정보와 모델 관리를 확인합니다. 서울 추가 실측22,582행을2026-09-30까지 확보했습니다. 10월1일 이후 합성 확장은 실제 관측과 구분하고 실제 관측 종료일·모델 입력 종료일을 함께 확인합니다. 추가 실측 확보가 기존 모델 재평가·승격 완료를 뜻하지는 않습니다. ‘저장 자료 검증’에서는 선택 날짜의25개 관측소별 모델 준비 상태를 확인하며, 합성 재학습 시연은 실제 관측과 구분합니다.

전국3곳은 자료 범위에서 선택하는 추가 실측 옵션이며 기존 해발 수위 비교도·실제 강수 지도·3곳 장마 성능 비교를 유지합니다. 위치 원천 목록1,048개는 확보 카탈로그 수이고 모든 지점의 실측·예측 제공을 뜻하지 않습니다. 미연결 예보·특보·원천 진단 패널은 제외하고 원본은 보존합니다. 기본 Compose는 설정된 수집·스케줄러를 실행하되 키나 유효 자료가 없으면 기존 정상 자료를 유지합니다. 외부 수집에는 로컬 `.env`의 승인된 `KMA_APIHUB_KEY`·`GIMS_API_KEY`가 필요하며, 모듈 직접 실행 시 환경변수 미지정 fallback은 false입니다. 자세한 원천·기간은 [자료 안내](data/README.md)를 따릅니다.

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

발표용 [GroundWatch_발표기획서.pdf](output/final/GroundWatch_발표기획서.pdf), 편집 가능한 [PPTX 원문](output/source/GroundWatch_발표기획서.pptx), [페이지별 대본](output/source/발표대본.md), [발표 예상 질문·답변 PDF](output/final/GroundWatch_발표_예상질문과답변.pdf)을 관리합니다. 최종 발표는37쪽(기존 필수 흐름1~28, 전국 확장29~36, 팀원37)이며 예상 질문·답변은44문항입니다. [요구사항 검수](output/source/proposal.md)에서 여섯 필수 흐름과 페이지를 확인합니다. 동작 코드는 [제출 ZIP](output/final/AIOps_조별%20과제_광주_3반_GroundWatch_동작코드.zip)으로 제공합니다. 과제 기획의 기준 문서는 [proposal.md](proposal.md)입니다. 실제 제출·발표 완료는 별도로 확인합니다.

## 협업과 문서 관리

브랜치·커밋·AI 작업 규칙은 [AGENTS.md](AGENTS.md)를 따릅니다. 개인 작업 → 해당 파드 → dev → main 순서로 통합합니다.

기능 변경은 해당 기준 문서의 기존 내용을 수정합니다. 같은 설명을 여러 파일에 복제하거나 변경 때마다 새 설계 문서를 만들지 않습니다. 과거 검토는 `docs/archive/`, 날짜별 실행 기록은 `evidence/records/`에 보존합니다. 현행 문서에는 과거 상태를 현재처럼 섞어 쓰지 않습니다.

검증 명령은 `docker compose exec serving-app python -m serving_app.worker_runtime --state-root /app/runtime/groundwatch --locked-command python -m pytest tests -q`와 `node tests/replay_ui.test.cjs`입니다. 프론트 검증은 `frontend/`에서 `npm ci`, `npm test`, `npm run build`입니다. 공용 Docker 기동에는 호스트 npm 설치가 필요하지 않습니다. 최근 저장된 실행 결과와 환경 제한은 실행 증거에서 확인합니다.

확보된 3개 지하수 관측소는 공식 제원명의 기상지점과 실험 매핑으로 연결해 수위·강수 학습과 장마 구간 평가를 수행합니다. 기본 Compose는 출처가 기록된 이 자료로 초기 실험 모델을 준비합니다(`GROUNDWATCH_EXPERIMENTAL_MODELS_ENABLED`, 기본 true). 원천·단위 확인과 운영 승인은 구분하며 실험 예측에는 범위를 표시하고 운영 승인 없는 모델 승격은 차단합니다.


최종 검증은 Python **226통과·1skip**, 프런트 **30통과** 및 production build입니다. 실제 HTTP·데스크톱/모바일·3D/2D 전환·컨테이너 재기동과 자료 보존은 [최종 검증](evidence/records/2026-10-08-national/simulation-final-verification.json)을 따릅니다. 전국 합성17개 시·도 시나리오29,597행은 실제3곳과 별도 자료 범위입니다. 현재 모델 준비는 서울23/25개·전국 실측1/3개·전국 합성16/17개이며 실패·미준비를 숨기지 않습니다. 합성34개 M0/M1 다년 비교에서5%개선 관측소는0곳이고 장마·강한 강수 오차는 악화됐습니다. 실제 운영 승격이나 장마 정확도 개선을 입증한 결과가 아닙니다.
