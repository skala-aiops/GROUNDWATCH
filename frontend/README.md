# GroundWatch 프론트엔드

React·TypeScript 관제 화면입니다. 서비스 소개와 Docker 실행은 [루트 README](../README.md)를 따릅니다. API 필드와 날짜 의미는 [공통 계약](../docs/contracts.md)을 기준으로 합니다.

## 개발 실행

Node.js 22와 npm이 필요합니다. 아래 명령은 `frontend/`에서 실행합니다.

```bash
npm ci
npm run dev
```

개발 화면은 Vite가 출력하는 주소의 `/dashboard/`에서 확인합니다. `/api`·`/health`·`/metrics` 요청은 `vite.config.ts`에 따라 `http://localhost:8100`으로 전달하므로, 실제 자료 조회에는 루트 Docker 서비스가 실행 중이어야 합니다.

## 코드 배치

| 위치 | 역할 |
| --- | --- |
| `src/app/` | 화면 구성·전역 연결 |
| `src/components/atoms/` | shadcn/ui 기본 UI |
| `src/components/molecules/` | 상태 배지·패널 등 기본 UI 조합 |
| `src/components/organisms/` | 지도·차트·수위 비교·출처 표시 |
| `src/components/templates/` | 화면 공통 레이아웃 |
| `src/pages/` | 관제 화면의 데이터·업무 기능 연결 |
| `src/features/` | 모델 관리·계절별 평가 등 업무 기능 |
| `src/hooks/` | 공통 React 훅 |
| `src/api/` | HTTP 요청·응답 처리 |
| `src/store/` | 전역 상태 관리 |
| `src/types/`·`constants/`·`utils/` | 타입·상수·순수 함수 |
| `src/design-system/`·`styles/` | 테마·스타일 조합·화면 스타일 |
| `tests/unit/`·`integration/`·`e2e/`·`legacy/` | 단위·통합·브라우저·호환 화면 검증 |

Atomic Design에 따라 기본 UI·조합·화면 영역·레이아웃·페이지를 나눕니다. Tailwind 전역 토큰과 shadcn/ui Button·Input·NativeSelect·Badge·Card를 실제 화면에서 사용합니다. 업무별 기능은 `features/`에서 관리합니다.

## 컴포넌트 컨벤션

- React 함수 컴포넌트와 TypeScript를 사용합니다. 컴포넌트 이름과 직접 작성하는 파일은 `PascalCase`로 맞춥니다. shadcn/ui 기본 파일의 소문자 이름은 유지합니다.
- 버튼·입력·배지 같은 기본 UI는 atoms에서, 기본 UI의 조합은 molecules에서, 지도·수위 비교 같은 화면 영역은 organisms에서 관리하는 방향으로 정리합니다. 업무 로직은 `features/`에 둡니다.
- props 타입을 명시합니다. 서버 응답 타입과 화면 표시 타입이 다르면 변환 함수를 두고, 타입 단언으로 차이를 숨기지 않습니다.
- 조회·상태·변환 로직을 JSX 안에 길게 넣지 않습니다. 공통 훅·순수 함수로 분리하고, 재사용할 이유가 없는 작은 표현까지 컴포넌트로 나누지는 않습니다.
- 버튼은 동작을 설명하는 이름, 입력은 연결된 label을 제공합니다. 아이콘만 있는 버튼에는 `aria-label`을 넣습니다.
- 자료 없음·조회 중·요청 실패를 구분합니다. 준비되지 않은 모델이나 미확정 단위를 정상 예측처럼 표시하지 않습니다.

## 훅과 상태 컨벤션

- 훅 이름은 `use`로 시작하고 파일 이름을 일치시킵니다. 조건문·반복문 안에서 훅을 호출하지 않습니다.
- effect가 참조하는 값을 의존성 배열에 포함하고 타이머·이벤트·요청은 cleanup에서 해제합니다.
- 폴링 조회는 `useResource`를 사용합니다. 경로가 없으면 요청하지 않고, 경로 변경·unmount 시 이전 요청을 취소하며 이전 응답으로 현재 화면을 덮어쓰지 않습니다.
- 조회 훅에 학습·교체·삭제 같은 변경 요청을 넣지 않습니다. 변경 요청은 사용자 동작에서 명시적으로 실행합니다.
- `store/`는 전역 상태를 관리하는 폴더이며, 현재 상태 관리 라이브러리는 Jotai입니다. 여러 화면이 공유하는 선택 상태는 이곳의 atom으로 관리하고, 해당 컴포넌트만 쓰는 상태는 `useState`에 둡니다. 서버 조회 결과를 전역 상태에 불필요하게 복제하지 않습니다.

## API·타입·유틸리티 컨벤션

- 업무 API 요청은 `api/client.ts`의 `request`·`post`를 사용합니다. 지도 정적 파일 로딩 등 일반 자원 조회와 구분합니다.
- 공통 헤더와 HTTP 오류는 인터셉터에서 처리합니다. 화면은 `ApiError`와 조회 상태에 따라 사용자 메시지를 표시합니다.
- `/api/v1`·`/api/v2`를 구분하고 서버의 `snake_case` 필드를 임의로 변경하지 않습니다. FormData의 multipart boundary는 브라우저가 설정하도록 합니다.
- 학습·승격 등 변경 요청을 자동 재시도하지 않습니다. ready 503을 로그인 오류로 취급하지 않습니다.
- 공통 타입은 `types/`, 고정 상태명은 `constants/`, React에 의존하지 않는 계산·변환 함수는 `utils/`에 둡니다. `any` 사용을 늘리지 않고 응답별 타입을 좁힙니다.

## 스타일 컨벤션

- 공통 색상·간격·모서리·포커스 표현은 `design-system/`에서 관리하는 방향으로 통일합니다. 화면별 CSS는 배치와 시각화에 필요한 규칙을 둡니다.
- shadcn/ui 기본 컴포넌트를 프로젝트 테마에 맞춰 사용하고, 클래스 조합은 `cn`으로 처리합니다. 동일한 버튼·입력 스타일을 화면마다 복사하지 않습니다.
- 3D 화면에는 2D 대체 화면을 제공하고, 작은 화면과 동작 줄이기 설정을 함께 확인합니다.

## 검증

`frontend/`에서 실행합니다. 브라우저 E2E는 Chrome을 사용합니다.

```bash
npm ci
npm run test:unit
npm run test:integration
npm run test:legacy
npm run test:e2e
npm run build
```

전체 테스트는 `npm run test:all`, Vitest 전체는 `npm test`입니다. Chrome이 없으면 설치하거나 Playwright 설정의 channel을 변경하고 `npx playwright install chromium`으로 테스트 브라우저를 준비합니다.

| 경로 | 검증 대상 |
| --- | --- |
| `tests/unit/api/` | 인터셉터·요청 경로·관측소 상태 표시 |
| `tests/unit/utils/` | 자료 범위·오차 비교·날짜 공백·포맷 |
| `tests/unit/components/` | 강수·후보 평가·수위 기준면 렌더링 |
| `tests/integration/` | 조회 훅의 취소·폴링·오류 복구, 지도·manifest 계약 |
| `tests/e2e/` | 모의 API를 사용하는 실제 Chrome 화면 시나리오 |
| `tests/legacy/` | 유지 중인 `/legacy/` 화면의 상태·시연 제어 |

E2E는 테스트용 응답으로 화면 동작을 확인합니다. 실제 API 연결이나 모델 정확도를 입증하는 테스트와 구분합니다. 실제 서비스의 읽기 검증은 저장소 루트에서 `node frontend/tests/live/verify.mjs http://localhost:8100`으로 실행합니다. 실행 중인 서비스와 Chrome이 필요하며 원본 모델을 교체하는 요청은 보내지 않습니다. 캡처와 결과는 날짜별 evidence에 저장됩니다.

실행 결과와 실제 서비스 확인은 [실행 증거](../evidence/README.md)를 따릅니다.
