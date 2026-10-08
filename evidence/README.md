# 실행 증거

최종 제출본의 동작 검증 진입점입니다. 원문 응답·실패 결과·합성/실측 구분을 보존합니다.

## 제출본 기준 최종 검증 — 2026-10-08

- [통합 최종 검증](records/2026-10-08-national/simulation-final-verification.json): Python226통과·1skip, 프런트30통과·production build, Docker healthy·HTTP·화면·재기동·자료 보존.
- [최종 테스트 원문](records/2026-10-08-national/simulation-final-tests.txt), [실제 HTTP](records/2026-10-08-national/simulation-final-http.json).
- [서울25개 기본 화면](records/2026-10-08-national/final-seoul-overview.png), [전국 합성 별도 범위](records/2026-10-08-national/final-national-simulation.png), [실제 전국 강수](records/2026-10-08-national/final-national-rainfall.png), [모바일 수위 비교](records/2026-10-08-national/final-mobile-water.png).
- [합성 다년 평가](records/2026-10-08-national/synthetic-seasonal-summary.json):17개 시나리오·34모델,5%개선0곳, 장마·강한 강수 pooled RMSE 악화. 실측 성능이나 운영 승격 증거가 아님.
- 실제3곳과 합성17개를 분리합니다. 모델 준비는 서울23/25·전국 실측1/3·합성16/17개이며 미준비를 완료로 표시하지 않습니다.

## 과제 필수 동작 증거

- [서울 합성 승격 시연 HTTP](records/presentation-demo-http.json): 동일 새 정답30일9.27%개선·guard 통과·v1→v2 실제 응답. 실제 미래30일 운영 증거가 아님.
- [후보 탈락 시연](records/chart-feedback-http.json):2.51%개선으로 기준 미달, 기존 모델 유지.
- [초기 실측 평가](initial-model-evaluation.json): 종로구 특정 검증 구간 결과, 최신 실측 성능과 구분.
- [저장 서비스 지표](current-metrics-http.json): 당시300초107요청·p95 0.653799084초·5xx0/107. 장기SLA 아님.
- [전국3곳 실측 계절 비교](records/2026-10-08-national/seasonal-evaluation.json): 제주 개선·다른2곳 악화, 계절 표본 부족·운영 미승인.
- [ASOS 원천 대조](records/2026-10-08-national/asos-hub-reconciliation.json): 활용 승인 후 실제 응답, 빈값을0으로 대체하지 않음.

단계별 테스트·화면·환경 중단·재개와 과거 상태는 [날짜별 기록](records/2026-10-08.md)에 보존합니다. 현재 기획·API·자료·운영 기준은 각각 [기획서](../proposal.md), [API 계약](../docs/contracts.md), [데이터 설명](../data/README.md), [운영 기준](../docs/operations.md)을 따릅니다.
