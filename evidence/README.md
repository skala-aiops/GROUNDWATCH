# 실행 증거

이 문서는 최신 검증의 진입점입니다. 과거 상태와 실패·검수 이력은 [날짜별 원문](records/2026-10-08.md)에 보존합니다. 이번 문서 정리에서는 저장된 결과를 대조했으며 학습·서비스 테스트를 재실행하지 않았습니다.

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
