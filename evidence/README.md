# 실행 증거

최종 제출본의 동작 검증 진입점입니다. 원문 응답·실패 결과·합성/실측 구분을 보존합니다.

## 최신 구조 개편 검증 — 2026-10-09

- [최종 검증 결과](records/2026-10-09-final/verification.json): Python245통과·1skip, 프론트 단위35·통합5·Chrome E2E4통과, 호환 화면·production build 통과.
- [실제 UI·API](records/2026-10-09-final/live-ui.json): 최신 Docker 이미지, 별도 복사 볼륨, 서울25개 고정 관측소·3D/2D·모델 관리·모바일 확인. 페이지 오류0건.
- [관측소 현황](records/2026-10-09-final/overview-slide.png) · [저장 모델 수위 비교](records/2026-10-09-final/detail-slide.png) · [모바일](records/2026-10-09-final/mobile.png).
- 생존200·현재 준비503을 구분하고 저장 자료 모드(2026-07-31 입력 → 08-01 예측)의 모델v1·실제 예측을 확인했습니다. 재기동 후 같은 버전·예측·자료를 유지했습니다. 신규 실측 성능이나 미래30일 승격의 증거는 아닙니다.

## 최신 제출 소스 검증 — 2026-10-09

- [최신 검증 결과](records/2026-10-09-final/verification.json): 백엔드245통과·1skip(선택적 실제 TensorFlow 학습 smoke), 프론트 단위35·통합5·E2E4통과, 호환 화면·production build 통과.
- [최신 관제 화면](records/2026-10-09-final/overview-slide.png): 복사한 격리 볼륨에서 실제 HTTP·화면·모바일·3D/2D 확인. 외부 수집·추가 학습은 비활성화한 검증이며 새 성능 평가가 아님.
- Docker 빌드·기동·재기동 후 저장된 과거 예측의 버전·값 일치 확인. live200·ready503으로 현재 입력·모델 준비 부족을 유지.

## 이전 통합 검증 — 2026-10-08

- [통합 실제 HTTP](records/2026-10-08-national/integration-final-http.json): 생존200·화면200·목록/이력/파이프라인200. ready503은 관측일·모델 준비 조건 미충족이며 Docker health와 구분합니다. 10월9일 확인에서 서울 실제 API는 키 미준비로 관측/예측0곳, 전날 입력은 STALE로 표시했습니다.
- [실제 API 대기 화면](records/2026-10-08-national/integration-native-api.png): 미준비 수치와7단계 대기 상태를 표시합니다.
- [dev 통합 후 전체 테스트](records/2026-10-08-national/integration-final-tests.txt): Python245통과·1skip, 프런트32통과·production build. 실제 API 모델 승격과 기존 전국 모델을 함께 검증했습니다. 아래226/30은 전국 기능 통합 당시의 이전 검증입니다.

## 전국 기능 검증 — 2026-10-08

- [통합 최종 검증](records/2026-10-08-national/simulation-final-verification.json): Python226통과·1skip, 프런트30통과·production build, Docker healthy·HTTP·화면·재기동·자료 보존.
- [최종 테스트 원문](records/2026-10-08-national/simulation-final-tests.txt), [실제 HTTP](records/2026-10-08-national/simulation-final-http.json).
- [서울25개 기본 화면](records/2026-10-08-national/final-seoul-overview.png), [전국 합성 별도 범위](records/2026-10-08-national/final-national-simulation.png), [실제 전국 강수](records/2026-10-08-national/final-national-rainfall.png), [모바일 수위 비교](records/2026-10-08-national/final-mobile-water.png).
- [합성 다년 평가](records/2026-10-08-national/synthetic-seasonal-summary.json):17개 시나리오·34모델,5%개선0곳, 장마·강한 강수 pooled RMSE 악화. 실측 성능이나 운영 승격 증거가 아님.
- 실제3곳과 합성17개를 분리합니다. 2026-10-08 검증 당시 모델 준비는 서울23/25·전국 실측1/3·합성16/17개였으며 미준비를 완료로 표시하지 않습니다.

## 과제 필수 동작 증거

- [서울 합성 승격 시연 HTTP](records/presentation-demo-http.json): 동일 새 정답30일9.27%개선·guard 통과·v1→v2 실제 응답. 실제 미래30일 운영 증거가 아님.
- [후보 탈락 시연](records/chart-feedback-http.json):2.51%개선으로 기준 미달, 기존 모델 유지.
- [초기 실측 평가](initial-model-evaluation.json): 종로구 특정 검증 구간 결과, 최신 실측 성능과 구분.
- [저장 서비스 지표](current-metrics-http.json): 당시300초107요청·p95 0.653799084초·5xx0/107. 장기SLA 아님.
- [전국3곳 실측 계절 비교](records/2026-10-08-national/seasonal-evaluation.json): 제주 개선·다른2곳 악화, 계절 표본 부족·운영 미승인.
- [ASOS 원천 대조](records/2026-10-08-national/asos-hub-reconciliation.json): 활용 승인 후 실제 응답, 빈값을0으로 대체하지 않음.

단계별 테스트·화면·환경 중단·재개와 과거 상태는 [날짜별 기록](records/2026-10-08.md)에 보존합니다. 현재 기획·API·자료·운영 기준은 각각 [제안서 PDF](../deliverables/final/AIOps_조별%20과제_광주_3반_GroundWatch.pdf), [API 계약](../docs/contracts.md), [데이터 설명](../data/README.md), [운영 기준](../docs/operations.md)을 따릅니다.

## 기록 보존 기준

문서에서 참조하는 검증 결과와 과거 실패·한계 기록은 보존합니다. 참조 없는 동일 내용의 캡처 `reaudit-pipeline.png`는 제거하고 동일 원본 `reaudit-operations.png`를 유지했습니다. 특정 로컬 DB namespace에 고정된 일회성 분석 도구 `scripts/analyze_monitor_policy.py`는 제거했으며 기존 검증 결과는 변경하지 않았습니다.
