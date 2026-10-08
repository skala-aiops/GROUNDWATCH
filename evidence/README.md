# 실행 증거

이 문서는 최신 검증의 진입점입니다. 과거 상태와 실패·검수 이력은 [날짜별 원문](records/2026-10-08.md)에 보존합니다. 아래 항목은 각각 당시 환경의 기록입니다.

## 팀 프로젝트 전용 코드 정리 — 2026-10-08

- 사용자 요청으로 앱에서 참조하지 않는 HAIC 가격 예측 전처리·모델·라우터·실습 감시·샘플·전용 테스트18개와TypeScript생성캐시1개를 제거했습니다. 원본 실습은 팀 저장소 밖 individual/practice/project/에 별도로 존재함을 확인했습니다.
- 지하수 서비스·전국 수집기·기상 원천·팀 증거·발표자료·로컬 비밀키와실행자료는 유지합니다. HAIC전용import잔존0건을확인했습니다.
- 제거 후 격리Docker빌드·기동통과, [전체팀테스트198통과·1skip](records/2026-10-08-national/team-only-cleanup-checks.txt). 이전202개기록에는제거한HAIC실습테스트5개가포함됐고이후추가서울CSV회귀1개가반영되어현재198개입니다. 프런트23개검증은서울기획복원항목을따릅니다.
- 원천CSV의CRLF·CP949는변환하지않고Git속성으로보존합니다. 다음전국확대·서울최신자료·장마성능·실제단면·후속평가설계는team-guide.md의후속적용설계에기록했습니다.

## 서울 구별 기본 기획 복원과 통합 검증 — 2026-10-08

- 기본은 서울25개 구별 고정 대표 관측소·현재 조회·종로구 선택입니다. 전국3곳은 같은 화면의 추가 자료 옵션입니다. 아래 이전의 ‘전국3곳 기본’ 기록은 중간 상태이며 현재 기본 기획이 아닙니다.
- 서울 현재 자료는2024-03-18까지여서0/25·STALE을 표시하며 저장 자료 검증에서는25/25 모델을 확인했습니다. 지도 강동구 클릭→둔촌지하수(seoul:SU-GDG-G1-0019) -18.850 GL→상세·모델 선택 유지 확인. 드래그4px초과는 구 선택에서 제외하며 실제 회전 후 종로구 선택 유지와3D→2D동일수위(-23.270) 전환을 확인했습니다. [최종 지도 상호작용](records/2026-10-08-national/seoul-final-interaction.jpg). [서울 지도](records/2026-10-08-national/seoul-default-overview.jpg).
- 서울 기존 강수 입력을 유지하면서 공식 서울108 장마CSV54연도를 사후 평가 참고로 연결했습니다. DB 미등록 시 보존CSV를 사용하고 결측 강수를 생성하지 않습니다. [서울 장마 회귀 검증](records/2026-10-08-national/seoul-context-checks.txt).
- [프런트23개 테스트·빌드](records/2026-10-08-national/seoul-default-checks.txt), [백엔드 전체202통과·1skip](records/2026-10-08-national/seoul-backend-pytest.txt). 별도 추가CSV회귀를 포함한 network service11개 테스트는 위 서울 장마 검증을 따릅니다. 전국 실험의 운영 승인·미래30일 승격 완료를 의미하지 않습니다.
- 모바일 서울 상세의 긴 선택창 넘침을 수정해 화면/문서 폭390px일치를 확인했습니다. [모바일](records/2026-10-08-national/seoul-default-mobile.jpg). 수위·연결 강수 차트에는 공식 장마 기간의 금색 배경을 추가했고 전국 무안180일 조회에서 두 차트의2026장마구간 렌더링을 확인했습니다. [장마 차트](records/2026-10-08-national/rainy-chart-final.jpg). [HTTP 범위 검증](records/2026-10-08-national/seoul-default-http-audit.json).
- 발표PPT/PDF37쪽·대본37구간·Q&A44문항9쪽을 서울 기본·전국 추가 범위로 정정하고 변경 페이지를 시각 검수했습니다. 코드ZIP은 현재소스389개파일로재생성했고비밀키검사·압축무결성검사를통과했습니다. main병합·커밋·푸시는하지않았습니다.

## 전체 화면·산출물 일치 점검 — 2026-10-08

- 전국 지도·Three.js 수위 비교·서울 GL 개념 단면과2D 전환을 같은 데이터 선택에 연결했습니다. 서울 상세의3D 전환도 제공하고 로딩 중0곳·강수 미연결 오인 표시를 조회 중 상태로 수정했습니다. 기준면/수위 단위가 확인되지 않으면3D 미터 축을 생성하지 않습니다. 가이드는 다음 날 예측·당일 추정·persistence를 구분합니다.
- [프런트23개 테스트·빌드](records/2026-10-08-national/whole-ui-checks.txt), 격리 Compose18104 빌드·healthy 확인. 기존 백엔드 전체201통과/1skip은 별도 기록이며 이번 변경은 프런트·설명·산출물입니다.
- 실제 브라우저: 지도 이름3개 유지, 광주108.150·제주89.364m 선택→상세3D 갱신, 같은 값2D 전환, 서울GL3D/2D, 강수2026-07-17 보령120.4mm 선택 시 무안 지하수 선택 유지. [강수 화면](records/2026-10-08-national/whole-ui-rain.jpg). 모델 관리의운영 승격/모델 미준비 예측 버튼 차단, 장마 평가 조회 확인. 브라우저error로그0.
- [모바일](records/2026-10-08-national/whole-ui-mobile.jpg):390px화면/문서폭390px,Three.js canvas와제주89.364m비교값확인. 실제지층·관정도면은미확보이며개념도를실제도면으로설명하지않습니다.
- 발표PPT/PDF37쪽·대본37구간·Q&A44문항/9쪽을Three.js범위와23개테스트기준으로갱신하고변경페이지를시각검수했습니다. 편집/제출파일사본해시일치확인. 코드ZIP도같은현재소스로갱신했습니다. main병합·커밋·푸시는하지않았습니다.

## Three.js 수위 비교도 반영 — 2026-10-08

전국 해발 수위 비교를 Three.js 면 비교로 변경했습니다. 청록 실측·금색 추정/비교 면, 원천 수위 기준과 표시 축척·날짜를 표시합니다. 임의의 지표나 지층을 생성하지 않습니다. 2D SVG는 3D 보기 해제 또는 WebGL 실패 시 대체 표시로만 유지합니다. 실제 브라우저에서 회전과 관측소 변경 시 값 갱신을 확인했습니다. [프런트22개 테스트·빌드](records/2026-10-08-national/three-water-checks.txt)·[실제 3D 화면](records/2026-10-08-national/three-water-level.jpg). 아래 SVG 화면은 이전 중간 수정 기록입니다.

## 단면·수위·강수 화면 점검 — 2026-10-08

- 전국 해발 수위는 서울 GL 개념 단면 조건에 맞지 않아 숫자만 표시되던 상태였습니다. 실제 관정 도면을 가정하지 않는 수위 비교도를 추가하고 제목·기준면·실측/추정 날짜·persistence 구분을 반영했습니다. 서울의 GL 3D 개념 단면은 유지하며 실제 지질 단면이라고 설명하지 않습니다.
- [원천 HTTP 점검](records/2026-10-08-national/diagram-source-audit.json): 전국3곳 각각280개 수위·280개 강수 값. 마지막 날짜2026-10-07, 무안20.350m·광주108.150m·제주89.364m이며 elevation 기준입니다. 실제 지층·관정 시공 도면은 미확보입니다.
- 브라우저에서3곳 선택에 따른 비교도 값·기준·날짜 변경, 수위/강수 차트, 서울 GL 단면 및390px 모바일 가로 넘침 없음 확인. [수위 비교도](records/2026-10-08-national/water-level-diagram.jpg)·[서울 개념 단면](records/2026-10-08-national/seoul-section-audit.jpg). 차트30/90/180 선택이31/91/181개를 표시하던 off-by-one을 수정했습니다.
- [검증](records/2026-10-08-national/diagram-checks.txt): 프런트22개 테스트·production build 통과. 지도·모델·원천의 운영 승인 상태는 변경하지 않았습니다. main 병합·커밋·푸시는 하지 않았습니다.

## 실측 자료 중심 화면 정리 — 2026-10-08

- 기본 화면은 실제 수위·연결 강수 이력이 각각 280일 있는 무안무안·광주도척·제주조천 3곳만 표시합니다. 모델 준비 1/3이며 나머지 2곳은 persistence 비교값입니다. 서울 과거 실측 25곳과 합성 시연은 `서울 과거 자료 · 시연` 범위에서 별도로 조회합니다.
- 원천 위치 목록 1,048곳은 보존하되 기본 지도에서 제외했습니다. API 응답 계약은 유지합니다. 관측소 이름 버튼을 누르면 해당 ID가 선택되며 빈 지도나 회전 드래그로 다른 관측소를 선택하지 않습니다. 앞선 픽셀 점 선택 구현은 이름 버튼으로 대체했습니다. 화면 왕복 시 첫 이름이 사라지는 문제는 지도 마커 전용 포털 영역으로 수정했습니다.
- 미연결 예보·특보 및 원천 진단 패널은 사용자 화면에서 제외하고 미사용 패널 컴포넌트 2개도 제거했습니다. 강수 지도 선택창은 실제 전국 3D 지도에서만 표시하며 서울 과거 자료·목록 보기에는 표시하지 않습니다. 확보된 전국 강수 지도·이력과 장마 성능 비교는 유지하며 원천 파일은 삭제하지 않았습니다. 사용 가이드는 버튼으로 열 때만 표시합니다.
- [프런트 검증](records/2026-10-08-national/supported-scope-checks.txt): 19개 테스트 및 production build 통과. 격리 Compose 18104 재빌드·기동 완료. 아래 통합 전체 테스트는 백엔드 변경 전후의 별도 검증 기록입니다.
- 실제 브라우저에서 이름 버튼·목록 선택, 지역 필터·검색, 서울 과거 25곳 조회, 강수 날짜 변경과 390px 모바일 제주조천·광주도척 선택을 확인했습니다. 모바일 문서 폭 390px/화면 폭 390px. [기본 화면](records/2026-10-08-national/supported-overview.jpg)·[최종 클릭 확인](records/2026-10-08-national/supported-click-final.jpg)·[모바일](records/2026-10-08-national/supported-mobile.jpg). 모델 운영 승인·실측 후속 30일 승격은 완료 상태가 아닙니다.
- 발표 PPT/PDF 37쪽, 대본 37구간, Q&A 44문항/9쪽을 같은 범위로 갱신했습니다. 코드 ZIP도 현재 소스로 다시 묶었습니다. main 병합·커밋·푸시는 하지 않았습니다.

## 이전 중간 지도 클릭 수정 기록 — 2026-10-08

지하수 점의 기본 world-unit 클릭 범위로 빈 바다를 눌러도 다른 관측소가 선택되는 문제를 재현했습니다. 화면 픽셀 기준 5px 이내에서 커서에 가장 가까운 점 하나를 선택하고, 확대·회전 이후에도 같은 기준을 유지하도록 변경했습니다. 관측점은 고정 6px 원으로 표시하며 4px 초과 드래그는 선택으로 처리하지 않습니다. 실제 18104 브라우저에서 제주조천·제주한경 선택과 빈 영역의 선택 유지 확인. [프런트 검증](records/2026-10-08-national/map-click-frontend-checks.txt): 19개 테스트와 production build 통과. [수정 화면](records/2026-10-08-national/map-click-fixed.jpg). 이전 발표자료의 16개 테스트는 그 산출물 생성 당시 기록이며 최신 지도 수정 검증은 이 항목을 따릅니다.

## 기존 서비스 전국 통합 검증 — 2026-10-08

- 개인 브랜치의 기존 `/dashboard/` 안에 관측소 현황·상세·모델 관리를 유지하며 전국 목록, 강수 지도, 관측소별 강수 이력과 장마 평가를 연결했습니다. 별도 전국 대시보드 진입점을 제거했습니다. main 병합·커밋·푸시는 하지 않았습니다.
- 격리 Compose `groundwatch-national-check`/18104에서 실제 빌드·healthy와 [통합 HTTP](records/2026-10-08-national/integrated-network-http.json)를 확인했습니다. 17개 시도/1,048개 위치 목록 중 실측 280일을 연결한 곳은 3곳이며, 현재 실험 LSTM 1곳과 명시된 persistence 비교값 2곳을 제공합니다. 목록 수는 모델 준비 수가 아닙니다.
- [실제 초기 모델 결과](records/2026-10-08-national/initial-national-models.json): 3곳 M0/M1 총 6개 학습. 운영 미승인 실험이며 초기 M0 탈락 관측소의 M1을 임의 승격하지 않습니다.
- [장마·비장마·강한 강수 실측 평가](records/2026-10-08-national/seasonal-evaluation.json): 학습 종료 5월31일, 검증 6월, 동일 평가 7월1일~10월7일 99정답. M1의 M0 대비 전체 RMSE 감소율은 제주조천 +29.43%, 무안무안 −12.17%, 광주도척 −15.92%입니다. 강수 특징 추가의 효과는 관측소마다 달랐습니다. 장마·강한 강수 표본 30개 미만은 계절 승격 근거가 아닙니다. 과거 평가이며 미래 발행 예측 30일 검증과 구분합니다.
- [통합 파이프라인 HTTP](records/2026-10-08-national/integrated-pipeline-http.json): 실험 감시 정책과 장마 결과, 3곳의 D−1 지하수 API 실제 자동 수집 ready 확인. 운영 승인·승격은 차단합니다. 예보 격자 연결과 특보 빈 응답 의미는 미확인으로 유지합니다.
- [호스트 전체 테스트](records/2026-10-08-national/integrated-host-tests.txt): 197 통과/3 skip. [최종 Docker 전체 테스트](records/2026-10-08-national/integrated-container-tests.txt)는 201 통과/1 skip이며 실제 TensorFlow 학습·저장·재로드 검사를 포함합니다. 프런트 production build 및 16개 테스트 통과. [통합 지도](records/2026-10-08-national/integrated-rainfall.jpg)에서 기존 관제 화면의 전국 강수 레이어와 같은 관측소의 실험 예측을 확인했습니다.

- 같은 관측소의 [모델 관리·장마 비교](records/2026-10-08-national/integrated-models.jpg)와 [390px 모바일](records/2026-10-08-national/integrated-mobile.jpg)을 실제 브라우저에서 확인했습니다. 재기동 후 초기/계절 모델 버전과 완료 시각을 유지했고, 3곳 수집은 동일 날짜를 재호출하지 않았습니다. 브라우저 console error 0. 3D 의존 chunk 약904KB 빌드 경고는 남습니다.

- 최종 교체 조건 검증에서 기존·후보 RMSE가 모두 0인 경우를 5% 개선으로 처리하지 않도록 수정하고 실제 후보 평가·승격 재검증 테스트를 통과했습니다. D−1 입력으로 D일에 발행한 값은 화면에 당일 수위 추정으로 표시합니다. 현재 실측 발행 예측은 정답 연결 대기 상태이며 과거 평가를 실제 후속 30일 승격으로 소급하지 않습니다.
- 발표자료 [편집 원문](../output/source/GroundWatch_발표기획서.pptx)·[PDF](../output/final/GroundWatch_발표기획서.pdf) 37쪽, [발표 대본](../output/source/발표대본.md) 37개 구간, [예상 질문·답변](../output/final/GroundWatch_발표_예상질문과답변.pdf) 44문항·9쪽을 최신 범위로 갱신하고 전 페이지를 시각 검수했습니다.

아래는 진행 당시의 이전 기록이며, 최신 구현·검증 상태는 위 통합 검증을 우선합니다.

## 공식 장마 자료 확보 — 2026-10-08

- 기상자료개방포털 로그인 후 전체 지점·1973~2026년 CSV 다운로드. 실제 파일 66지점 × 54연도 = 3,564행이며 화면 표시 3,478건과의 차이는 미확인입니다. [정규화 CSV](../data/rainy_seasons_kma.csv)·[출처 및 해시](../data/rainy_seasons_kma_manifest.json)·[사용 범위](../data/README.md)를 보존했습니다.
- 로컬 전국 SQLite에 평가 전용 장마 기간 3,564건을 저장했습니다. FastAPI TestClient에서 `/api/v2/rainy-periods` HTTP 200 및 서울(108) 2026년 7월 1일~26일 조회를 확인했습니다. 실행 중 컨테이너 배포 검증은 아닙니다.
- 수집·저장소·API 관련 테스트 23개 통과. 지하수 관측소와 기상지점의 연결 및 장마철 실제 모델 성능 평가는 아직 완료하지 않았습니다.

## 모델 교체 자격 보강 — 2026-10-08

- 개인 브랜치 `feat/aiops/geonwoo/model-promotion-policy`의 로컬 구현·검증입니다. 기존 운영 컨테이너·자료·모델을 변경하지 않았고 표준 Compose 재배포·실측 성능 검증·커밋·푸시는 수행하지 않았습니다.
- [전체 테스트](records/2026-10-08-model-promotion-policy-tests.txt): 107개 통과, 실패·skip 0. 실제 TensorFlow 학습·직렬화·재로드 검사 포함. 미평가·탈락 후보 직접 교체 차단, 과거 성능 기준, 평가 중 버전 변경, alias·이력 저장 실패 시 기존 예측 유지, HTTP 버전·재로드를 확인했습니다.
- [실제 TensorFlow·MLflow·HTTP 결과](records/2026-10-08-model-promotion-policy-http.json)·[원문 로그](records/2026-10-08-model-promotion-policy-http-log.txt): 격리 합성 자료에서 후속 30일 RMSE 0.0357775831→0.0294161300 및 과거 guard 통과. 컨테이너 내부 실제 HTTP 200 응답에서 v1→v2 전환을 확인했습니다.
- 추가 v3 후보의 미평가 직접 교체를 차단했고, 평가 탈락 후 같은 입력의 v2 버전·예측값과 서버·ModelManager 재시작 후 상태를 확인했습니다. 탈락 검증용 정답은 기존 모델 예측으로 재귀 생성한 합성 자료로, 기존 RMSE 0은 이 정책 검증 자료의 생성 규칙이며 실측 정확도가 아닙니다.
- 운영 볼륨·호스트 포트 없이 로컬 기존 이미지에서 파생한 별도 검증 이미지와 컨테이너 loopback HTTP를 사용했습니다. [재현 스크립트](../scripts/verify_model_promotion_policy.py)는 저장소 루트의 프로젝트 환경에서 실행하며 기존 [합성 학습 검증](../scripts/verify_model_promotion.py)을 사용합니다. 모델 정책과 단일 프로세스 잠금 범위는 [운영 기준](../docs/operations.md)을 따릅니다.

## 발표 전후 캡처·그래프 개선 — 2026-10-08

- [실제 요청·응답](records/presentation-demo-http.json): 동일 합성 세션 6d00ba의 v1 예측, +0.2 변화, 품질 경보, 후보 생성, 정답 30일 평가, v2 실제 예측. RMSE 0.0232006162→0.0210488850, 9.274457% 감소 및 guard 통과.
- 직접 캡처: [요청 전](records/presentation-predict-before.png)·[감지](records/presentation-trigger.png)·[알림](records/presentation-alert-log.png)·[재학습 작업](records/presentation-retrain-log.png)·[평가 그래프](records/presentation-evaluation.png)·[교체 후](records/presentation-after.png)·[요청 후](records/presentation-predict-after.png)·[컨테이너](records/presentation-container.png).
- 기존 8100 컨테이너 제거 후 원본 tracking 볼륨을 읽기 전용 복사하여 별도 18103 컨테이너·5174 화면 프리뷰에서 이어갔습니다. interrupted 이력과 이어간 요청을 원문에 남겼습니다. 최신 UI의 표준 Compose 배포 검증과 구분합니다.
- [강수 그래프](records/presentation-rainfall.png): 관측 날짜 표시·0mm 점·결측 공백·가로 이동. 후보 비교는 동일 평가 구간 RMSE와 실제 평가 상태를 사용합니다.
- 프론트 테스트 10개·TypeScript/Vite 빌드 통과. [실제 추론 200·입력 오류 422](records/chart-feedback-http.json)와 [발표 필수 항목 검수](../output/source/proposal.md)를 연결했습니다.

## React 프론트 채택 — 2026-10-08

`team-test/frontend`를 `team/frontend`로 채택하고 최신 비즈니스 로직을 유지했습니다. 출처·외부 수집 진단·실제 드리프트 설정을 새 화면에 연결했습니다.

- 표준 Docker Compose 빌드 성공 후 8100 컨테이너를 교체했고 healthy를 확인했습니다. 아래 기본 이미지 조회 실패는 이전 검증 당시 상태입니다.
- [전체 테스트 로그](records/react-adoption-tests.txt): 99개 실행, 실패 0·skip 1. 프론트 테스트 5개·TypeScript/Vite 빌드·기존 재생 UI 테스트 통과.
- 전환 전후 25개 모델 버전·예측값·자료 ID 동일. main.py 외 비즈니스 Python 파일 해시 변경 없음. 기존 자료·모델 볼륨 유지.
- [새 화면](records/react-adoption-overview.jpg): 현황·상세·모델 관리·수집 진단을 브라우저에서 확인, 콘솔 오류 0건. 운영 자료에 새 재학습을 실행하지 않았습니다.

발표 PDF의 5·13·15쪽도 최신 테스트·React 구성·실제 화면으로 갱신하고 렌더링을 확인했습니다. 원본 디자인과 16쪽 팀원 페이지는 유지했습니다. 편집 원문과 제출 PDF를 함께 갱신했습니다. team-test 이전·백업 검증은 [정리 기록](records/team-test-retirement.json)에 있습니다.

## 최신 MVP 검증 — 2026-10-08

- 환경: localhost:8101의 격리 Docker 파생 이미지. 기존 8100 운영 자료·이미지는 변경하지 않았습니다.
- [전체 테스트 로그](mvp-final-tests.txt): 97개 실행, 실패 0·skip 1.
- [실제 HTTP](mvp-final-http.json): 생존·준비·예측·외부 진단·시연 조회 200, 오늘 입력·모델 준비 25/25.
- [드리프트 화면](mvp-drift-final.jpg)·[텍스트](mvp-browser-final.txt): 최신 22일째 변화 시연의 감지·재학습·후속 평가·v1→v2 실제 예측 사용.
- [기본 상황 화면](mvp-basic-final.jpg)·[텍스트](mvp-basic-final.txt): 추가 수위 변화 없음·준비 완료·정답 0일 초기 상태.
- [수집 진단 화면](mvp-collection.jpg): 설정·매핑·입력·모델·발행 상태 구분. 외부 실측 연결 성공의 증거가 아닙니다.

Docker Hub 기본 이미지 조회 시간 초과로 표준 빌드는 완료하지 못했습니다. 기존 로컬 운영 이미지를 기반으로 변경 소스를 복사한 파생 이미지에서 검증했습니다. 초기 bind mount 서버의 종료 코드 135 원인은 미확정이며 named volume 환경에서 시연을 완료했습니다. 자세한 이미지 ID·세션·환경 제한은 날짜별 원문을 확인합니다.

문서 통합·링크·최종 PDF 검수는 [문서 정리 기록](records/2026-10-08-document-cleanup.md)에 있습니다.

## 자료·평가 기준 증거

- [공식 자료 범위](official-data-coverage.json)·[고정 분할](frozen-data-manifest.json): 원관측과 구별 시간 경계.
- [실측 모델 평가](initial-model-evaluation.json): 최초 실제 모델 지표. 최신 합성 성능과 구분.
- [합성 확장 HTTP](current-extension-http.json): 공식 과거+합성 확장, 오늘→내일 예측과 출처.
- [입력·예측 비교 테스트](comparison-tests.txt)·[화면](ui-comparison-detail.png): 같은 날짜 비교, 당시 94개 테스트.
- [이전 드리프트 결과](drift-demo-http.json): 당시 후보 탈락·후속 정답 부족. 최신 교체 결과로 덮어쓰지 않음.

원본 응답·로그·화면은 그대로 보존합니다. 공식 과거 실측 평가·합성 과제 시연·실제 최신 서울 관측 성능은 서로 다른 범위입니다. 모델 등록·작업 접수·후보 생성·평가 통과·실제 새 모델 서빙·외부 배포·과제 제출도 각각 구분합니다.

## 2026-10-08 전국 관측 화면·실험 v2 검증

- 실제 ASOS 66개 지점 × 선택 62일 수집 요청 132개 완료. 유효 숫자 1,444개, 원천 빈값 2,648개는 0으로 변환하지 않음. 장마 3,564행 및 GIMS 후보 좌표 1,023개 확보. 전국 지하수 모델 승인·실측 성능 개선은 미확인.
- 분리 Docker 프로젝트 `groundwatch-national-check`, 포트 18104에서 빌드·기동·생존·실제 HTTP·재기동 후 조회 확인. 검증 시 기존 서울 최초 학습만 1 epoch, 합성 확장/외부 자동 수집 off이며 운영 품질 검증과 구분.
- 최종 Python pytest 151 통과/1 skip, 프런트 10 통과 및 production build 통과. 최초 검증에서 pytest 누락·오래된 source 상태 기대값 실패를 수정한 후 재실행.
- 날짜 변경·관측소 검색/선택·지하수 후보 레이어, 데스크톱/390px 모바일 3D 렌더 확인. 장마 패널을 선택 관측소만 표시하도록 수정. 브라우저 확장 업데이트 요구로 마지막 viewport 복원/탭 보존 호출은 완료하지 못함.
- [검증 수치](records/2026-10-08-national/verification.json), [Python 결과](records/2026-10-08-national/pytest.txt), [데스크톱 화면](records/2026-10-08-national/desktop.jpg). 3D 의존 chunk 약 904KB 경고는 남으며 지연 로드함.

### AWS·예보·특보 추가 검증

- AWS 완료 일강수 723개 지점과 시간 누적 736개 지점의 인증 API 응답을 확보했습니다. 별도 기상 worker를 테스트 Docker에서 활성화하여 실제 수집·원본 저장·API runtime 우선 조회를 확인했습니다. 기본 설정은 비활성이고 전국 모델 학습과 분리됩니다.
- 단기예보 활용신청 완료 후 정상 응답 907행에서 POP/PCP/PTY 225개를 검증했습니다. 격자 55/127은 지역 연결 미확인 샘플이며 관측·모델 입력에 혼용하지 않습니다. 특보 HTTP 200·0행 응답은 ‘특보 없음’으로 확정하지 않습니다.
- [Python 전체 결과](records/2026-10-08-national/weather-tests.txt): 169 통과/1 skip. 프런트 빌드와 기존 테스트 10개 통과. 실제 AWS 723지점 [3D 화면](records/2026-10-08-national/aws-desktop.jpg), [수집 상태](records/2026-10-08-national/weather-collection-http.json), [예보 HTTP](records/2026-10-08-national/forecast-http.json), [특보 HTTP](records/2026-10-08-national/warning-http.json)를 보존했습니다.
- 전국 지하수 3곳은 각각 280일 연속 수위 원본을 확보했으며, 강수 연결 승인·기준면 검증·실제 전국 모델 성능 평가는 아직 완료하지 않았습니다.

280일 AWS 완료 일강수 201,206관측을 gzip 이력으로 제공하며, 원본 해시와 전체 재파싱을 검증했습니다. [7월 1일 지도 HTTP](records/2026-10-08-national/aws-history-network-http.json), [지점 280일 이력 HTTP](records/2026-10-08-national/aws-history-station-http.json), [실제 3D 화면](records/2026-10-08-national/aws-history-desktop.jpg)을 확인했습니다. 해당 날짜 722지점 중 240지점은 유효한 0mm였습니다. 날짜별 좌표 변경 보존과 runtime 최신일 우선 병합 테스트를 포함합니다.
