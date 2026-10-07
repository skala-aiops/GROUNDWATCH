# 서울 구별 지하수 모델

사용자 요청에 따라 기존 HAIC의 `serving_app/lstm_model.py` 구조를 재사용하고 지하수 전처리·학습·서빙 연결을 추가했다. HAIC 가격 모델과 임계값을 지하수에 사용하지 않는다.

## 실행

로컬 작업 폴더에는 `data/groundwater/bundle.zip`이 준비되어 있다. 다른 환경에는 이 파일과 `bundle.json`을 함께 전달한다. 서울시 공개 관측 자료에서 추출한 25개 관측소 자료·학습된 Keras 파일·정규화 값·평가 기록을 포함한다. 원본 전체 CSV와 실행 DB는 포함하지 않는다. 모델 ZIP은 Git 제외 대상이다.

```bash
docker compose up --build
```

http://localhost:8100/ 에서 관측소를 선택한다. `모델 평가`는 25개 구의 시험 오차를 비교한다. 첫 복원 후에는 영속 볼륨을 재사용하며 불필요하게 재학습하지 않는다. 종료는 `Ctrl+C` 또는 `docker compose down`이며 볼륨 삭제 옵션은 사용하지 않는다.

현재 환경의 학습 기록은 MLflow SQLite·아티팩트 볼륨에 저장했다. 제공 ZIP에는 MLflow DB와 서버 이력을 넣지 않았다. 다른 환경의 복원은 파일 기반 추론과 웹 DB 모델 등록을 제공하며, manifest의 MLflow run ID는 원래 학습 환경의 출처 식별자다. 새 환경의 MLflow 이력까지 필요하면 별도 후보 경로로 재학습한다.

## 데이터와 학습

- 구마다 관측종료 표시가 없는 1개 관측소. 120개 이상의 연속 21일 창 및 41일 이상의 연속 구간이 필요하다. 마지막 사용 가능 구간 종료일, 유효 창 수, 이름 순으로 선택한다. 평가 오차를 보고 관측소를 선택하지 않는다.
- 서울시 원본 조회표의 수위 `gl.-m`를 지표면 아래 깊이 cm로 변환한다. 강수량은 mm, 모델 내부만 ×10한다. 근거: https://swo.seoul.go.kr/ugrwtr/retrieveAsstnObsrDta.do
- 동일 날짜·관측소의 같은 값은 하나로 합친다. 서로 다른 수위·강수량 값이 있으면 해당 날짜를 제외한다. 0 이하 깊이는 양수 깊이 계약에 따라 제외한다. 실제 피압수·결측 표기 여부는 추가 확인 대상이며 임의 변환하지 않는다.
- 날짜 누락은 보간하지 않는다. 최근 20일 연속 입력과 다음 날 실측이 있는 경우만 학습한다. 다른 관측소 자료를 섞지 않는다.
- 날짜 순서 약 70% 학습, 15% 검증, 15% 시험. 마지막 21일은 시험에 남긴다. 정규화 통계는 학습 종료일까지만 계산한다. 검증으로 조기 종료하며 시험 자료를 모델 선택에 사용하지 않는다.
- 제공 구조 LSTM 32→32→16, Dense 16→1을 재사용한다. 입력은 20×2, 학습 목표는 전날 대비 깊이 변화량을 학습 구간 표준편차로 나눈 값이다. 추론은 마지막 실측 깊이에 예측 변화량을 더한다. 최대 35 epoch, seed 42, batch 128, patience 6이다.
- 기준선은 전날 실측값 유지. 검증 RMSE가 기준선 이하인지 기록한다. 25개 모두 연구용 후보로 조회·추론하며 검증 통과와 운영 승격은 구분한다. 시험 결과가 나쁜 모델을 숨기지 않는다.
- 운영 임계값·자동 재학습·운영 승격은 미설정이다. 웹에서 오차는 계산하지만 위험 판정은 `not_evaluated`다. `retrain` 연결은 명시적으로 준비되지 않았음을 반환한다.

## 재현 및 검증

호스트의 Python·npm 설치는 기본 기동에 필요 없다. 다음은 개발자가 학습을 다시 비교할 때만 사용하는 선택 절차다. 기존 후보를 덮어쓰지 않도록 새 경로를 지정한다.

```bash
docker compose exec serving-app python scripts/train_groundwater.py --output serving_app/models/groundwater/experiment-02 --epochs 35
```

다른 CSV를 사용하려면 `scripts/prepare_groundwater.py --source <원본CSV> --output <새 준비 폴더>`로 구별 자료를 만든 후 학습의 `--prepared`에 전달한다. 위 명령은 현재 묶음에 포함된 정제 자료를 사용한다. 재학습 결과를 화면에 자동 교체하지 않는다.

```bash
docker compose exec serving-app python scripts/verify_groundwater.py
docker compose exec serving-app python -m unittest discover -s tests -v
```

첫 명령은 실제 HTTP 요청으로 25개 관측소에 다음 날 예측과 과거 분석을 생성하고 최근 21건 RMSE를 실측과 다시 계산한다. 같은 입력 재실행은 동일한 멱등 키를 사용한다. 결과는 모델 볼륨의 `groundwater/results`에 저장한다. `scripts/export_groundwater.py`는 구별 성능·시험 예측·HTTP 결과를 CSV로 내보낸다.

추가한 조회 API는 `GET /api/v1/model-reports`, `GET /api/v1/wells/{well_id}/model-report`다. 기존 예측·관측·실행 API 형식은 유지한다. 모델 보고서는 구·관측소·학습 종료일·검증 종료일·시험 기간·단위 출처·실측 성능을 제공한다. 새 조회 항목은 이 개인 브랜치의 구현이며 팀 공통 계약 합의를 대신하지 않는다.
