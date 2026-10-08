# GroundWatch 실제 관측자료

`groundwater_observations.csv`는 서울특별시 물순환정보 공개시스템의 공개 관측자료에서 가져온 실제 일별 수위·강수 자료입니다. 조회일은 2026-10-07이며, 저장 기간은 2018-01-01~2024-03-18입니다. 25개 구별 고정 관측소와 공식 관측소 코드는 `representatives.json`에 기록했습니다. 사용자가 공공자료 조사와 선정을 위임한 근거로 확정했으며, 별도의 팀 회의가 있었다고 기록하지 않습니다.

출처: [서울특별시 물순환정보 공개시스템 관측자료](https://swo.seoul.go.kr/ugrwtr/retrieveAsstnObsrDta.do). 자료 설명과 이용허락은 [서울 열린데이터광장 보조지하수 관측망 관측정보](https://data.seoul.go.kr/dataList/OA-15611/A/1/datasetView.do)의 공공누리 제1유형(출처표시, 상업적 이용 및 변경 가능)을 확인했습니다. 출처표시는 서울특별시 물순환정보 공개시스템 / 서울 열린데이터광장입니다. 원본 HTML, 개별 요청 URL과 해시는 `runtime/official/sources/`, `../evidence/official-data-coverage.json`에 보존했습니다. 원본 HTML은 Git에 포함하지 않습니다.

수위는 공식 화면 표기의 `gl.-m`, 강수는 `mm`입니다. 원천의 음수와 0을 유지하며 절댓값, 부호 반전, cm 변환을 하지 않았습니다. 강수는 관측자료 화면이 제공한 값이며 그 값의 기상 관측소 코드는 독립적으로 확인되지 않았습니다. 결측·충돌·비수치 행은 제외했고 결측 강수를 0으로 만들거나 공백 날짜를 보간하지 않았습니다.

25개 구 전체에 같은 연속 410일을 요구하면 제공 자료가 충족하지 않습니다. 대신 각 입력은 반드시 연속 달력 20일과 다음 날 정답으로 만들고, 과거의 유효한 윈도우만 학습합니다. 학습은 미래 평가를 보기 전에 정한 설정으로 가장 최근의 유효 정답 730개까지만 사용합니다. 오래된 자료와 실행 비용을 제한하면서 약 두 해의 관측 표본을 유지하려는 선택이며, 결측 때문에 실제 달력 기간은 730일보다 길 수 있습니다. 각 구의 검증·테스트는 각각 연속 정답 60일이며, 공통 운영 재생은 2023-12-20~2024-03-18의 90일입니다. 각 구의 학습·검증·테스트 날짜와 자료 SHA-256은 `../evidence/frozen-data-manifest.json`에 기록했습니다. 날짜가 빠진 두 구간을 한 시퀀스로 연결하지 않습니다.

이 자료는 과거 관측 재생과 예측 검증용입니다. 오늘의 실시간 수위, 구 전체 평균, 싱크홀 발생 확률 또는 현장 안전 판단 자료로 표현하지 않습니다. 대표 관측소는 자동 교체하지 않습니다.

## 팀 설명과 결합 기준

현재 수위·강수는 같은 서울시 공개 관측HTML의 날짜 인덱스로 묶었으며 기상청ASOS를 현재CSV에join한 것이 아닙니다. station_id와date로 관측을 식별하고, 고정manifest에서 구·관측소·단위를 연결합니다. 누락 강수를0으로 채우지 않습니다. 팀원이 원본→정규화→20일윈도우→시간분할→모델→API→시연까지 따라가는 상세 설명과25개 관측소별 행수는 [팀 로직 설명](../docs/team-guide.md#데이터가-화면까지-오는-과정)에 있습니다.

## 과제용 오늘 날짜 합성 확장 (2026-10-08)

원본 CSV와 representatives.json은 변경하지 않습니다. 기동 시 data/current_extension.py가 기존 행을 보존하고, 마지막 실측 다음 날부터 서울 오늘까지 별도 runtime/groundwatch/current-extension/YYYY-MM-DD에 자료를 생성합니다. CSV 추가 열 origin과 manifest provenance에 실측·합성 경계, 원본 해시, seed, 생성식을 저장합니다. 전체 혼합 자료는 source_kind=synthetic으로 등록하여 별도 모델·scaler·예측·평가를 사용합니다. 2026-10-08 기준 실측 52,591행 + 합성 23,350행입니다.

같은 달 과거 강수를 재표본화하고 수위는 월별 중앙값으로 완만히 회귀시키는 과제용 생성식입니다. 실제 최신 서울 관측이나 수문학적으로 검증된 모형이 아닙니다. 합성 자료 학습의 평가 수치를 원본 실측 성능과 합치지 않습니다. 원본 HTML의 수위·강수 연결 방식과 단위는 위 설명을 유지합니다.

합성 생성식은 과거 같은 달 표본에서 수위·강수 쌍을 재표본화하고 `level += 0.03*(월별 중앙값-level) + 0.015*(표본 수위-월별 중앙값)`으로 이어갑니다. 고정 seed는 20261008이며 관측소 코드별 난수열을 사용합니다. CSV/manifest의 결정적 해시와 실제 생성 시각 generation.json은 분리합니다. 같은 내용의 재생성으로 불필요한 새 학습 자료를 만들지 않습니다. 현재 source kind와 행별 origin을 확인하며 출처 미상을 실측으로 간주하지 않습니다.

## 공식 장마 기간 자료 수입

2026-10-08 기상청 로그인 후 내려받은 `STCS_장마_20261008173111.csv`를 실제 분석·수입했습니다. 출처는 [기상청 장마 통계](https://data.kma.go.kr/climate/rainySeason/selectRainySeasonList.do)이며 검색조건은 전체 지점, 1973~2026년입니다. CP949 원본은 154,871바이트이고 SHA256은 `0d7b8f1e7ca1054498102c876e9bab92c21ecf15d1bf2f43ed4ab764bf4a8910`입니다. 원본은 개인정보·인증정보가 없는 통계 CSV이며 `runtime/official/rainy/`에 변경 없이 보존합니다.

공유용 정규 CSV는 [rainy_seasons_kma.csv](rainy_seasons_kma.csv), 출처·해시·연도별 범위는 [rainy_seasons_kma_manifest.json](rainy_seasons_kma_manifest.json)입니다. 실제 CSV 데이터는 **3,564행 = 66개 지점 × 54개 연도**이며 모든 연도에 66개 지점 행이 있습니다. 빈 날짜·잘못된 기간·기간 일수 불일치·충돌로 격리된 행은 0개입니다. 다운로드 화면의 3,478건과 실제 파일 행 수 차이는 원인을 확인하지 못했으며 실제 파일을 근거로 기록합니다. 강수량 합계가 빈 90개 행은 0으로 바꾸지 않고 원문으로 보존합니다. 장마 시작·종료일이 유효하므로 기간 평가 라벨로는 수입합니다. 이 완전성은 내려받은 파일 내부 범위이며 해당 지점의 과거 관측 운영·강수 자료 완전성을 입증하지 않습니다.

지점별 라벨은 `kma_asos:108`처럼 기상 관측지점 번호를 명시합니다. 광역 행정구역으로 추정하거나 지하수 관측소와 자동 연결하지 않습니다. 지하수 관측소의 검증된 강수 지점 매핑을 따로 확정해야 장마 구간 평가에 적용할 수 있습니다. 이 자료는 **사후 평가 전용**이며 당시 알 수 있었던 입력이나 실시간 장마 여부로 사용하지 않습니다. 기존 서울 v1 모델·입력·승격 정책은 바꾸지 않습니다.

명시적 원본 수입과 별도 전국 SQLite 적재 명령은 다음과 같습니다. 원본 경로는 실제 다운로드 위치로 지정합니다. 동일 원본과 산출 디렉터리로 반복하면 수집시각을 유지하여 동일 기간을 중복 저장하지 않습니다. 앱 시작 시 원본 전체를 자동 재수입하지 않습니다.

```bash
python3 scripts/import_national_data.py kma-rainy /path/to/STCS_장마.csv --output-dir runtime/official/rainy --repository runtime/groundwatch/national/observations.sqlite3
```

단위 테스트는 저장한 예시 CSV의 파싱·격리·반복 수입을 검증하며, 실제 파일의 확보 및 3,564행 적재 확인과 구분합니다.

## 전국 관측소 좌표와 실제 수위 API 확보

2026-10-08 공식 GIMS 공개 현황 지도와 인증 API를 실제 조회했습니다. 목록은 [전국 측정망 현황](https://www.gims.go.kr/natnObsvStts.do)의 공식 지도 코드가 사용하는 [ArcGIS 관측소 레이어](https://www.gims.go.kr/arcgis/rest/services/jihasu/Monitor/MapServer/0)에서 확보했습니다. 원래 좌표계는 TM_Korea이며 조회 시 `outSR=4326`을 지정했고 응답의 `wkid=4326`을 확인했습니다. 임의 TM 변환이나 이름 기반 위치 추정은 하지 않았습니다.

공개 원본 1,039개 feature 중 좌표가 `NaN`인 16개를 격리하여 **실좌표 1,023개**를 [national_stations_gims.json](national_stations_gims.json)에 기록했습니다. 17개 시도와 제주 관측소를 포함합니다. 공개 현황 선택 목록은 1,135개 ID이며 지도 원본 1,039개 중 1,038개가 이 목록과 일치합니다. 두 목록 차이는 미확인이고 지도 레이어 이름은 `표준화 테스트 국가관측망`이므로 이 목록은 검토용 inventory입니다. 모든 지점을 `verified=false`로 유지하고 예측·학습을 자동 활성화하지 않습니다. 지도 속성 `ELEV`를 관측 수위로 사용하지 않습니다.

[API 상세 목록](https://www.gims.go.kr/opnApiList.do)과 [공식 상세 JS](https://www.gims.go.kr/js/opnApiService.js)에서 확인한 제원 REST API는 `/api/data/groundwaterMonitoringNetworkService/getNationalGroundwater`이며 `GIMS_STATION_API_KEY`, `type=JSON`, `gennum`, `josacode=104`로 실제 이름·주소·원시자료명 응답을 받았습니다. 별도 키 추가 없이 등록한 키로 성공했습니다. 공식 문서 WFS `/api/wfs` 경로는 실제 요청에서 HTTP 404여서 좌표 확보에 사용하지 못했습니다.

일자료 `/api/data/observationStationService/getGroundwaterMonitoringNetwork`는 `GIMS_API_KEY`로 실제 `response.resultCode=Success`, `response.resultData` 구조를 확인했습니다. 중부 광주도척(601739), 남부 무안무안(11775), 제주조천(95537)을 공개 목록과 교차확인해 조회했습니다. 세 지점 모두 2026-07-01~31의 31행과 2026-10-07의 1행을 반환하여 총 96행을 확보했습니다. 이는 해당 지점·기간만 검증한 결과이며 모든 지점의 최신성·연속성을 입증하지 않습니다.

공식 현황 그래프는 수위 `el.m`, 심도 `m`로 표시하며 API 명세는 `elev`를 수위, `lev`를 `표고-수위`로 설명합니다. 다만 검토용 지도·API의 관측소별 기준면과 출처 정합을 자동 승인하지 않았고 현재 inventory의 단위·기준면은 `unverified`로 유지합니다. 실제 수위는 원본 단계로 보존하며 서울 `gl.-m` 모델 입력에 합치지 않습니다.

원본은 키를 제거한 뒤 `runtime/official/national/`에 저장했으며 요청 URL·인증키는 산출물에 포함하지 않습니다. 검증 결과와 원본 해시는 [national_source_probe.json](national_source_probe.json)에 있습니다. 관측소 좌표 정규화는 `parse_gims_station_layer()`가 수행하며 좌표계 불명·NaN·중복 ID를 격리합니다.

## 전국 ASOS 강수와 표시용 전국 경계

[전국 강수 자료](national_rainfall.json)는 실제 기상청 ASOS 일자료이며 단위는 mm입니다. 66개 지점에 대해 2026-07-01~31, 2026-09-07~10-07의 총 62일을 수집했습니다. 132개 기간 요청이 완료됐고, 4,092개 지점·날짜 중 유효 강수 1,444개, 원천 빈값 격리 2,648개입니다. 원천 빈값이 무강수인지 결측인지 자동 확정하지 않았으며 0으로 변환·보간하지 않습니다. 날짜별 지도에는 원천 숫자가 있는 지점만 강수 색상·높이를 표시하고 없는 지점은 자료 없음으로 구분해야 합니다. 수집 요청 완료와 모든 날짜의 값 확보는 다릅니다.

좌표는 [기상청 지점정보](https://data.kma.go.kr/tmeta/stn/selectStnList.do)에서 내려받은 메타데이터 CSV와 지점 ID·이름·운영 유효기간을 대조했습니다. 메타데이터 원본 SHA256은 `15cd579ee8d2078d7ecf4233b5df31217fcd3c55b818bf9ca5f6dfd8b41f0066`이며 원본과 66개 좌표 명세는 `runtime/official/national-rainfall/`에 보관합니다. 표시용 공유 자료의 `stations`에도 좌표·유효기간·원천 해시가 있습니다. 이 기상 지점 좌표를 지하수 관측소 위치로 대신 사용하지 않습니다.

수집 재현은 환경변수 `KMA_ASOS_SERVICE_KEY`가 설정된 서버에서 아래 명령으로 실행합니다. CLI는 `.env`를 읽거나 키를 출력하지 않습니다. 쉘에 키 값을 포함해 명령 이력을 남기지 말고 실행 환경에서 제공합니다. 기존 `collect_asos()`의 31일 구간 분할·페이지 완전성 검사·키 제거 원본 저장을 사용합니다. 지점 명세·기간·정책과 결과 해시가 일치하는 체크포인트만 재사용하고 실패 요청은 다음 실행 때 다시 처리합니다. 동시 요청은 최대 3개입니다. 이 명령은 수집 파일을 생성하며 공유 지도 자료나 모델을 자동 교체하지 않습니다.

```bash
python3 scripts/collect_national_rainfall.py --stations data/national_rainfall.json --period 2026-07-01 2026-07-31 --period 2026-09-07 2026-10-07 --output-dir runtime/official/national-rainfall --workers 3
python3 scripts/build_rainfall_network.py --root runtime/official/national-rainfall --stations data/national_rainfall.json --output data/national_rainfall.json
```

[Natural Earth 표시용 경계](korea_display_boundary.geojson)는 1:50m 국가 경계를 사용한 EPSG:4326 자료입니다. [출처·해시·라이선스 명세](korea_display_boundary_manifest.json)와 [Natural Earth 이용 조건](https://www.naturalearthdata.com/about/terms-of-use/)에 따라 Public domain 자료로 기록합니다. 이 경계는 전국 지도 배경 표시 전용이며 한국 공식 행정구역·법적 경계·기상 지점 연결·지하수 관측소 관할 판정에 사용하지 않습니다. 서울 기존 구 경계의 출처·라이선스와 별개입니다.

## 별도 AWS 분자료 snapshot

기상청 API허브 활용신청 후 `nph-aws2_min` 공식 API의 실제 2026-10-07 12:00 KST 응답을 확보했습니다. [national_aws_snapshot.json](national_aws_snapshot.json)은 **736개 지점의 단일 시각 분자료**이며 기존 ASOS 일강수 자료와 별도 계약입니다. 원본은 `runtime/official/apihub/11bc7afb91fb806b345cf79638535b1b477fa01ab7a5d72a080566d5d413fddd.txt`입니다.

원본 도움말은 `RN-15m`, `RN-60m`, `RN-12H`, `RN-DAY`가 각각 15분·60분·12시간·당일 누적 강수량(mm)이며 `-50 이하`가 관측 없음 또는 오류임을 명시합니다. 해당 값은 null로 보존하고 원천에서 실제 0인 값만 0으로 유지합니다. 특히 정오의 `RN-DAY`는 진행 중인 당일 누적량으로 완료된 ASOS 일강수와 합치거나 모델 입력에서 같은 의미로 취급하지 않습니다.

기상청 지점 메타데이터 CSV의 ID·운영 유효기간을 기준으로 정확히 한 행이 연결되는 지점만 좌표를 붙였습니다. 현재 736개 중 **626개 연결, 110개 미연결 또는 모호**이며 이 110개는 관측값은 보존하되 위치를 추정하지 않습니다. 분자료 원문은 지점 이름을 제공하지 않으므로 ID 외 이름의 독립 일치 검증을 주장하지 않습니다. 지하수 관측소와의 연결·모델 학습·화면 활성화는 이번 수입에 포함하지 않습니다.

실제 수집 재현은 환경변수 `KMA_APIHUB_KEY`를 설정한 실행 환경에서 수행합니다. 키·요청 URL은 출력하지 않고 원본 저장 전에 키를 제거합니다. 파서는 공식 열 순서, 요청 시각, 시작·끝 표식, 결측 도움말을 검증하며 중복 지점은 채택하지 않습니다. `--raw`를 지정하면 네트워크 없이 확보한 원본을 재검증합니다.

```bash
python3 scripts/collect_aws_snapshot.py --time 202610071200 --metadata /path/to/official-kma-stations.csv --raw-dir runtime/official/apihub --output data/national_aws_snapshot.json
```

## 지상·AWS 완료 일강수 자료

[지상·AWS 일강수](national_aws_daily.json)는 API허브 `sfc_aws_day.php`, `obs=rn_day`로 실제 확보한 **2026-10-07 완료일 723개 지점·723개 값**입니다. CP949 원본은 `runtime/official/apihub/aws_daily-018ca334804f555bac3bf0c8fc2d771c1ef950905c9926b8b8724f3207e9d3f4.txt`이고 SHA256은 파일명의 값입니다. 좌표·관측일·지점명·조회값을 같은 원본 응답에서 읽었으며 723개 모두 유효 좌표와 비음수 값을 갖습니다. 오류·중복·기간 밖 행 격리는 0개입니다.

[공식 PDF API 명세](https://apihub.kma.go.kr/getAttachFile.do?fileName=지상및AWS일통계자료조회_API명세서.pdf)는 ASOS와 AWS를 함께 조회하는 서비스라고 명시합니다. 따라서 공급자 구분은 `kma_ground_aws_daily`, ID는 `kma_ground_aws_daily:<번호>`이며 AWS 전용 지점만 있다는 뜻이 아닙니다. ASOS 과거 66개 지점 자료, 정오 AWS 분자료와 각각 별도의 snapshot으로 유지합니다.

단위는 두 공식 자료의 결합과 실제 값 대조로 확인했습니다. API PDF는 `rn_day=일강수량`, `VAL=obs로 지정한 기상요소의 값`을 명시하지만 VAL 단위 mm를 직접 쓰지는 않습니다. [같은 기상청 포털의 요소 표](https://data.kma.go.kr/climate/extremum/selectExtremumList.do)는 `일강수량(mm)`를 명시합니다. 추가로 2026-07-01을 실제 조회해 기존 ASOS 일자료와 공통 지점·날짜 **57쌍 전부 값이 정확히 일치**함을 확인했습니다. [교차검증 결과](aws_daily_unit_validation.json)에 값·원본 해시를 기록했고 snapshot의 `unit_evidence`에 이 근거와 API 단독 단위 표기 한계를 보존했습니다. 단위 변환은 하지 않았습니다.

파서는 공식 6개 열 헤더와 지점명까지 7개 필드, 날짜, CP949 인코딩, 완료일, 실좌표·유한 비음수 값을 검증합니다. 실제 0은 유지하고 음수·결측을 0으로 바꾸지 않습니다. 아래 명령은 환경변수 `KMA_APIHUB_KEY`만 사용하며 `--raw` 옵션으로 저장된 원본만 재검증할 수도 있습니다.

```bash
python3 scripts/collect_aws_daily.py --date 20261007 --raw-dir runtime/official/apihub --output data/national_aws_daily.json
```

## 전국 지하수 예측 준비도 소량 검증

[세 관측소 준비도 보고](national_training_readiness.json)는 실제 인증 API로 광주도척(601739), 무안무안(11775), 제주조천(95537)의 **2026-01-01~10-07 각 280일**을 확보한 결과입니다. 각 지점은 숫자·지점 ID·요청 날짜 범위 검증에서 유효 280일, 빠진 날짜·중복·잘못된 행 0개이며 연속 20일 입력 뒤 다음 날 정답을 만드는 수위 구간은 각 260개입니다. 141일 최소 길이를 수위만으로는 충족하지만 **현재 `training_ready=false`, `approved=false`**입니다. 원본 31일 분할 수집 10개씩은 `runtime/official/national/<지점>/2026-01-01_2026-10-07/`에 보존했습니다.

수위 단위 근거는 공식 GIMS 현황 그래프의 `수위(el.m)`, `심도(m)` 표기와 APIR10의 `elev=수위`, `lev=표고-수위` 설명입니다. 서울 원천의 `gl.-m`와 별개의 수위 기준으로 취급하며 자동 부호 변경·서울 입력 혼합을 하지 않습니다. 관측소별 수위 계약 및 수직 기준의 독립 근거는 승인 전 확인 사항입니다. 지도 메타데이터는 설치일(광주도척 2011-12-14, 무안무안 1996-09-19, 제주조천 2005-12-19)을 제공하지만 과거 이전·좌표 수정 이력을 입증하지 않으므로 `coordinate_history_verified=false`로 기록했습니다.

강수 매핑 후보는 실제 2026-10-07 지상·AWS API에 응답한 지점 중 조사 기간에 유효한 메타데이터가 정확히 한 행인 지점으로 한정했습니다. 가까운 후보는 광주도척→용인(549) 약 11.825km, 무안무안→무안(699) 약 3.206km, 제주조천→제주가시리(890) 약 4.110km입니다. 대안 후보와 기존 ASOS 연결 후보도 보고에 기록했습니다. 같은 ID의 유효 메타데이터가 복수인 경우 자동 선택하지 않았습니다. 거리만으로 매핑을 승인하지 않으며 자료 제공 기간·강수 결측·지형 대표성을 추가 검토해야 합니다.

보고의 고도 차이는 기상청 노장 고도와 수위 응답 `elev+lev` 중앙값의 차이입니다. 이 지하수 지점 고도는 공식 값의 합으로 유도한 **추천용 추정값**이며 독립 측량 고도를 확인한 결과가 아닙니다. 모델 입력이나 지하수 기준면 변환에 사용하지 않습니다. 특히 제주 후보의 높이 차이를 고려해 거리만으로 대표성을 단정하지 않습니다.

후속 지상·AWS 280일 응답 수집으로 강수 후보의 실제 날짜별 가용성을 추가 확인했습니다. 최신 연속 수위·강수 중첩은 광주도척→용인(549) 237일, 무안무안→무안(699) 41일, 제주조천→제주가시리(890) 225일입니다. 현재 전국 M0 기본 학습의 140일 길이 조건은 광주도척·제주조천 후보가 충족하고 무안무안 최신 구간은 미달합니다. 전체 응답 280일 확보와 각 관측소의 결측 없는 280일은 다르며, 상세 누락 날짜는 [강수 준비도 보고](national_rainfall_training_readiness.json)에 보존합니다. 검토된 강수 매핑, 수위 단위·기준면 계약, 좌표 이력 및 누수 없는 날짜 분리는 승인 전 조건이며 모델 학습·승격은 이 보고의 수집 단계에 포함하지 않습니다.

## 특보현황 원본의 빈 응답

공식 `wrn_now_data_new.php`에서 HTTP 200 응답을 실제 확보했지만 데이터 행은 0개입니다. 원본 `runtime/official/apihub/warning-795d653558e91c8f90137ebabcdfc18abf12c24cce9816f87edbc2944eecdfe5.txt`는 CP949 도움말·열 헤더를 포함하며 끝 표식은 없습니다. [상태 artifact](national_warning_status.json)는 `empty_response_unverified`, `no_warnings_verified=false`로 기록합니다. **HTTP 성공·빈 헤더를 ‘현재 특보 없음’이나 안전하다는 의미로 표시하지 않습니다.**

[공식 API 설명](https://apihub.kma.go.kr/apiList.do?seqApi=10&seqApiSub=288)은 `fe=f`가 발표시간 기준, `fe=e`가 발효시간 기준이며 `tm`이 KST 기준시각이라고 설명합니다. 출력 구역·발표/발효시각·특보종류/수준/명령 필드도 안내하지만 빈 응답의 의미와 완전성 판정은 확인하지 못했습니다. 현재 원본은 기준시각 파라미터를 생략한 현황 요청입니다. 과거 시점 조회나 발효시간 기준과 구분해야 합니다.

안전 수집 CLI와 파서는 인증 오류 HTML·열 구조 불일치를 차단하고 빈 응답 상태를 보존합니다. 실제 양성 행 구조가 확보되지 않아 지역명 공백을 임의로 쪼개 정규 특보 행으로 만들지 않으며 비어 있지 않은 미검증 응답도 `nonempty_response_schema_unverified`로 보존합니다. 특보 구역과 관측소의 매핑도 아직 구현·승인하지 않았습니다.

```bash
python3 scripts/collect_warning_snapshot.py --basis f --raw-dir runtime/official/apihub --output data/national_warning_status.json
```

수집은 환경변수 `KMA_APIHUB_KEY`만 사용하며 키·요청 URL을 출력하지 않습니다. `--raw` 옵션은 저장된 원본 재검증 전용입니다.

기상 관측소 좌표 메타데이터는 `kma_station_metadata.csv`(CP949, 14,928행)와 `kma_station_metadata_manifest.json`에 원본·해시·공식 다운로드 경로를 보존합니다. AWS 분자료 좌표 연결은 관측일에 유효한 동일 지점 번호 후보가 정확히 하나일 때만 수행하며, 중첩 이력이나 누락은 미연결로 남깁니다.

## 단기 강수 예보 격자 샘플

[예보 샘플](national_forecast_sample.json)은 실제 승인 후 확보한 단기예보 `getVilageFcst` 응답이며 관측값과 별도 `source_kind=forecast`입니다. 발표는 **2026-10-08 05:00 KST**, 격자는 **55/127**입니다. 격자의 지역명·관측소 매핑은 미확인으로 남기고 서울 또는 특정 관측소 예보라고 추정하지 않습니다. HTTP 200·결과코드 `00`·총 907개 원천 행·페이지 1개 완전성을 검증했습니다. 그중 75개 예보시각의 POP·PCP·PTY 225개를 추출했습니다.

[공식 안내](https://data.kma.go.kr/community/nuriLovePopup.do)는 POP 강수확률, PCP 1시간 강수량, PTY 강수형태를 설명하며 **연장기간에는 3시간 간격 자료와 PCP 정성 코드**를 제공한다고 명시합니다. 실제 원본 PCP에는 `강수없음`과 숫자 문자열 `0`이 함께 있습니다. 숫자 `0`을 자동 0mm로 해석하지 않고 `numeric_or_qualitative_code_unverified`와 원문을 보존합니다. PCP 범주는 하한·상한을 보존하며 중간값으로 바꾸지 않습니다. POP는 %, PTY는 공식 코드 원문으로 유지합니다. 75개 전체를 동일한 1시간 간격으로 설명하지 않습니다.

엄격 파서는 발표일·시각·격자, 예보 대상시각, 전체 페이지 및 행 수, 중복, 각 시각의 POP·PCP·PTY 존재를 검증합니다. 샘플 확보는 전국 격자 수집 또는 과거 당시 발표본 확보를 뜻하지 않으며, 사후 수집한 예보를 당시 운영 모델 입력으로 사용하지 않습니다. 지하수 모델·학습·승격에는 아직 연결하지 않았습니다.

```bash
python3 scripts/collect_forecast_sample.py --base-date 20261008 --base-time 0500 --nx 55 --ny 127 --raw-dir runtime/official/apihub --output data/national_forecast_sample.json
```

수집 키는 `KMA_APIHUB_KEY` 환경변수로만 읽으며 원본 저장 전 제거합니다. `--raw`를 페이지 수만큼 반복하면 저장된 JSON 원본을 네트워크 없이 재검증합니다.


### 전국 지상·AWS 일강수 이력 병합

`scripts/collect_aws_history.py`가 확보한 `runtime/official/aws-history/parsed/YYYY-MM-DD.json`을 `scripts/build_aws_rainfall_history.py`로 병합합니다. 캐시의 원천 SHA256을 확인하고 공식 원본을 다시 파싱하여 모든 정규화 필드가 일치하는 완결 응답 날짜만 포함합니다. 수집 중에는 확보된 날짜만 포함하며, 완료 후 같은 명령으로 다시 생성합니다.

```bash
python3 scripts/build_aws_rainfall_history.py --output data/national_aws_history.json.gz
```

공유 아티팩트는 `mtime=0` gzip이며 관측값과 `station_metadata_by_date`에 날짜별 원천 좌표·이름을 유지합니다. `stations`는 식별자 목록으로, 최신 좌표를 과거 날짜에 대입하지 않습니다. `provenance`에는 날짜별 원천/파싱 파일 해시·수집 시각·유효/격리 행수가 있습니다. 날짜 누락과 원천 격리값은 0으로 채우지 않으며, 공식 0은 그대로 유지합니다. 관측소 이름·좌표의 날짜별 변경 후보는 `quality.coordinate_or_name_variant_station_ids`에 기록합니다. 이 자료 확보는 지하수 매핑 승인이나 모델 학습 완료를 뜻하지 않습니다. 확보 범위와 행수는 아티팩트의 `available_dates`, `quality`를 기준으로 확인합니다.

실제 최종 병합 검증: **2026-01-01~2026-10-07 연속 280일, 201,206개 관측, 식별자 합집합 728개, 격리 0행**, gzip 5,178,070바이트입니다. 날짜별 좌표 또는 이름 변이가 확인된 식별자는 373·413·523·803·251이며, 각 날짜의 원천 메타데이터를 보존했습니다. 이 변경이 관측소 이동인지 명칭 정정인지는 별도 검증하지 않았습니다.


전국 수직 기준 추가 확인: 공식 CODIL 보관 국토해양부·K-water **2011년 지하수 관측연보 PDF 3쪽**은 지하수위를 해수면 기준 고도로 설명하고 수위 그래프 기본 단위를 1m로 명시합니다. [공식 연보](https://www.codil.or.kr/filebank/original/EC/OTKCEC200766/OTKCEC200766.pdf). 공식 GIMS 현황 화면의 제원 조회 `obsvSelectJewon.do`에서도 광주도척(601739) 표고 **112.25**, 제주조천(95537) **342.604**를 독립 확보하여 원천 `elev+lev` 중앙값과 일치를 확인했습니다. 현황 JavaScript의 표고 필드 연결과 API `elev=수위`, `lev=표고-수위`, 그래프 `el.m` 표기를 함께 근거로 삼습니다. 원본 해시·경로·확인 사실은 기존 [준비도 보고](national_training_readiness.json)에 보강했습니다. 다만 과거 연보와 현행 제원만으로 2026년 관측정 기준점 변경·표고 보정 이력까지 입증하지는 못하므로, 관측소 계약과 매핑의 미승인 상태를 유지합니다. 제원에 표시된 기상지점명 이천·성산과 코드의 현행 KMA 식별자 대응도 미확인으로 보존합니다.


### 전국 관제 모델용 명시적 실험 결합

`python3 scripts/build_national_experimental_join.py`는 확보된 GIMS 수위 원본 해시·지점/날짜·`elev+lev` 제원 정합과 검증된 기상청 일강수 이력을 확인하여 `data/national_experimental_joined.json`을 생성합니다. 3개 수위 관측소마다 공식 제원에 적힌 기상지점명 후보와 가까운 대안 후보를 각각 결합했습니다.

| 지하수 | 공식 제원명으로 선택한 KMA 지점 | 결합/최신 연속일 | 가까운 대안 | 결합/최신 연속일 |
|---|---|---|---|---|
| 광주도척 601739 | 이천 203 | 280 / 280 | 용인 549 | 237 / 237 |
| 무안무안 11775 | 목포 165 | 280 / 280 | 무안 699 | 269 / 41 |
| 제주조천 95537 | 성산 188 | 280 / 280 | 제주가시리 890 | 279 / 225 |

GIMS 제원의 기상 코드(244/236/184)는 현행 KMA 지점 ID라고 가정하지 않습니다. 공식 제원명과 실제 기상청 응답의 지점명을 대조하고 거리·표고 근거, 원천 해시 및 매핑 근거 버전을 명시했습니다. `source_contract_verified=true`는 원천 수위 m/elevation 및 일강수 mm와 날짜 품질의 확인이며, 대표성 검증이나 운영 승인을 뜻하지 않습니다. `mapping_status=experimental`, `operational_approved=false`를 별도로 유지합니다. 지점별 독립 학습에 전국 공통 측량 기준과 모든 과거 좌표 변경 이력의 완전성을 일괄 필수 조건으로 요구하지 않습니다. 운영 대표성·이력 검토와 실제 모델 평가는 별도 단계입니다.

이천203·목포165·성산188은 같은 ASOS 지점 ID의 공식 장마 통계 1973~2026년 각54건을 직접 연결했습니다. AWS 대안에는 동일 ID 장마 통계가 없으므로 장마 라벨은 null이며 광역 장마로 대체하지 않습니다. 장마 라벨은 평가 분류용으로만 사용하고 예측 당시 알 수 없던 종료일을 입력 변수로 사용하지 않습니다. 모든 결합 관측은 실제 최초 수집 시각을 보존하므로 역사적 실시간 예측·승격 성공으로 설명하지 않습니다. 과거 날짜로 available_at을 소급하지 않았습니다.


실측 일자료 자동 갱신은 `serving_app.national_observation_worker`가 담당합니다. `GROUNDWATCH_NATIONAL_OBSERVATION_COLLECTION_ENABLED=true`로 명시적으로 켠 경우에만 KST 11:30 이후 전날 자료를 조회합니다. 이미 등록된 observed 관측소 중 원천 계약이 확인되고 명시적 experimental/approved 매핑과 버전이 있는 지점에만 GIMS 일수위를 요청하며, 같은 날짜의 완료 지상·AWS 강수에서 지정 기상 ID를 결합합니다. 성공한 공급자 응답과 지점별 완료일·시도 시각은 실행 볼륨에 영속 저장하여 재시작 시 재사용합니다. 실패는 10분 뒤 재시도하고 기존 정상 관측은 유지합니다. 키 없음·같은 날 강수 없음·응답 품질 실패에서는 새 관측을 만들지 않습니다. 원본 해시와 실제 최초 수집 시각을 유지하며 등록·매핑 승인·학습을 자동 수행하지 않습니다. 기본 Compose는 이 설정을 true로 전달합니다. worker 모듈을 직접 실행할 때 환경변수를 생략하면 false입니다. 실제 수집의 운영 검증은 worker 기동 여부와 별도로 확인해야 합니다.
