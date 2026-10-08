import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { atom, useAtom } from "jotai";
import { viewAtom } from "./state";

// Open only from the guide button; do not interrupt page loads.
export const guideStepAtom = atom<number | null>(null);
const steps = [
  {
    view: "overview",
    target: ".provenance",
    title: "GroundWatch는 이렇게 사용합니다",
    body: "기본 화면에서 서울 25개 구별 대표 관측소의 수위·강수와 모델 품질을 확인합니다. 구 전체 평균이 아닙니다. 전국 추가 실측은 자료 범위에서 선택하며, 서울 과거 검증과 합성 시연은 조회 모드에서 구분합니다. 수위 예측은 싱크홀 확률이나 안전 등급이 아닙니다.",
  },
  {
    view: "overview",
    target: ".stats",
    title: "먼저 예측 준비와 날짜를 확인하세요",
    body: "전체 목록 중 모델 예측이 준비된 관측소 수를 확인하세요. 직전 관측값 기준(persistence)은 모델 준비 수에 포함하지 않습니다. 입력 기준일은 자료의 마지막 날짜이고, 예측 대상일은 예측값이 해당하는 다음 날입니다. 준비되지 않은 값은 —로 표시합니다.",
  },
  {
    view: "overview",
    target: ".map-panel",
    title: "관심 있는 관측소를 선택하세요",
    body: "서울 지도에서 구를 누르면 해당 구의 대표 관측소를 선택합니다. 전국 추가 자료에서는 관측소 이름 버튼이나 목록을 사용합니다. 전국 강수는 실제 관측값이며 0mm와 결측 지점은 기둥을 생략합니다. 선택한 기상지점과 지하수 관측소는 서로 다릅니다.",
  },
  {
    view: "detail",
    target: ".overview-grid > .panel:first-child",
    title: "실측 수위와 예측·비교값을 확인하세요",
    body: "관측소 상세에서 수위와 원천 단위·기준면·모델 준비 상태를 확인합니다. 전국 해발 수위는 지표 높이를 가정하지 않는 Three.js 수위 비교도로, 서울 GL 수위는 개념 단면으로 표시합니다. 실제 지층·관정 도면은 확보되지 않았습니다. 청록색은 입력 수위, 금색은 예측·당일 추정 또는 직전 관측값 기준 비교입니다. 화면의 날짜와 방법을 확인하세요. 단면은 이해를 돕는 개념도이며 실제 지질 구조가 아닙니다.",
  },
  {
    view: "detail",
    target: ".chart",
    title: "기간을 바꿔 변화 흐름을 살펴보세요",
    body: "최근 30·90·180일 수위와 강수량을 조회할 수 있습니다. 같은 날짜 저장 예측보다 입력이 높으면 빨강, 낮으면 파랑입니다. 이 색은 위험 등급이 아닙니다. 예측·추정값은 해당 날짜 정답 확보 전까지 평가하지 않습니다.",
  },
  {
    view: "operations",
    target: ".scenario",
    title: "운영 시연은 상황 선택부터 시작합니다",
    body: "전국 추가 실측 관측소에서는 실제 M0·M1 비교와 오차 감시 상태를 확인합니다. 합성 교체 시연은 자료 범위를 서울 25개 구별 대표 관측소로 선택한 뒤 모델 관리에서 실행합니다. 과거 시연과 현재 실측을 구분합니다.",
  },
  {
    view: "operations",
    target: ".pipeline",
    title: "실제 모델 처리 상태를 확인하세요",
    body: "자료 검증 → 오차 감시 → 감지 → 재학습 → 평가 → 교체 → 서빙 순서를 확인하세요. 요청 접수는 완료가 아닙니다. 후보가 기준에 미달하면 기존 모델을 유지하며, 평가에는 후속 정답이 필요합니다.",
  },
  {
    view: "overview",
    target: ".heading",
    title: "이제 관측소 조회부터 시작하세요",
    body: "일반 조회는 CSV 등록 없이 사용할 수 있습니다. 관측소 현황 → 상세가 기본 동선이고, 모델 관리·시연은 운영 확인용입니다. 우측 상단 사용 가이드로 필요할 때 안내를 열 수 있습니다.",
  },
] as const;
export default function ServiceGuide() {
  const [step, setStep] = useAtom(guideStepAtom);
  const [, setView] = useAtom(viewAtom);
  const title = useRef<HTMLHeadingElement>(null);
  const card = useRef<HTMLElement>(null);
  const [spot, setSpot] = useState({ x: 0, y: 0, width: 0, height: 0 });
  const [position, setPosition] = useState({
    left: 20,
    top: 20,
    side: "bottom",
  });
  useEffect(() => {
    if (step === null) return;
    setView(steps[step].view);
    let element: Element | null = null;
    let frame = 0;
    const measure = () => {
      const next = document.querySelector(steps[step].target);
      if (next !== element) {
        element = next;
        element?.scrollIntoView({ behavior: "instant", block: "center" });
      }
      const bounds = element?.getBoundingClientRect();
      if (!bounds || !card.current) return;
      const vw = window.innerWidth,
        vh = window.innerHeight;
      const x = Math.max(8, bounds.left - 8),
        y = Math.max(8, bounds.top - 8);
      const right = Math.min(vw - 8, bounds.right + 8),
        bottom = Math.min(vh - 8, bounds.bottom + 8);
      setSpot({
        x,
        y,
        width: Math.max(0, right - x),
        height: Math.max(0, bottom - y),
      });
      const w = card.current.offsetWidth,
        h = card.current.offsetHeight,
        gap = 18;
      const options = [
        {
          side: "right",
          left: right + gap,
          top: y,
          fits: vw - right >= w + gap + 16,
        },
        {
          side: "bottom",
          left: x,
          top: bottom + gap,
          fits: vh - bottom >= h + gap + 16,
        },
        { side: "top", left: x, top: y - h - gap, fits: y >= h + gap + 16 },
        { side: "left", left: x - w - gap, top: y, fits: x >= w + gap + 16 },
      ];
      const choice = options.find((o) => o.fits) ?? {
        side: "bottom",
        left: right - w,
        top: bottom - h,
      };
      setPosition({
        side: choice.side,
        left: Math.max(16, Math.min(vw - w - 16, choice.left)),
        top: Math.max(16, Math.min(vh - h - 16, choice.top)),
      });
    };
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measure);
    };
    const observer = new MutationObserver(schedule);
    observer.observe(document.getElementById("root")!, {
      childList: true,
      subtree: true,
    });
    const resize = new ResizeObserver(schedule);
    resize.observe(document.getElementById("root")!);
    if (card.current) resize.observe(card.current);
    schedule();
    title.current?.focus({ preventScroll: true });
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") setStep(null);
      if (e.key === "Tab" && card.current) {
        const buttons = Array.from(
          card.current.querySelectorAll<HTMLButtonElement>(
            "button:not(:disabled)",
          ),
        );
        const index = buttons.indexOf(
          document.activeElement as HTMLButtonElement,
        );
        e.preventDefault();
        buttons[
          (index + (e.shiftKey ? -1 : 1) + buttons.length) % buttons.length
        ]?.focus();
      }
    };
    document.addEventListener("keydown", key);
    window.addEventListener("resize", schedule);
    window.addEventListener("scroll", schedule, true);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      resize.disconnect();
      document.removeEventListener("keydown", key);
      window.removeEventListener("resize", schedule);
      window.removeEventListener("scroll", schedule, true);
    };
  }, [step, setView, setStep]);
  if (step === null) return null;
  const item = steps[step];
  return createPortal(
    <>
      <svg
        className="guide-shade"
        aria-hidden="true"
        width="100%"
        height="100%"
      >
        <defs>
          <mask id="guide-spotlight">
            <rect width="100%" height="100%" fill="white" />
            <rect
              {...{
                x: spot.x,
                y: spot.y,
                width: spot.width,
                height: spot.height,
              }}
              rx="10"
              fill="black"
            />
          </mask>
        </defs>
        <rect
          width="100%"
          height="100%"
          fill="rgba(2, 10, 12, .80)"
          mask="url(#guide-spotlight)"
        />
        <rect
          {...{ x: spot.x, y: spot.y, width: spot.width, height: spot.height }}
          rx="10"
          fill="none"
          stroke="#91ebcb"
          strokeWidth="2"
        />
      </svg>
      <section
        ref={card}
        className="service-guide"
        style={{ left: position.left, top: position.top }}
        data-side={position.side}
        role="dialog"
        aria-modal="true"
        aria-labelledby="guide-title"
        aria-describedby="guide-body"
      >
        <div className="guide-top">
          <span>
            서비스 사용 가이드 · {step + 1} / {steps.length}
          </span>
          <button onClick={() => setStep(null)} aria-label="사용 가이드 닫기">
            ×
          </button>
        </div>
        <h2 id="guide-title" ref={title} tabIndex={-1}>
          {item.title}
        </h2>
        <p id="guide-body">{item.body}</p>
        <div className="guide-progress" aria-hidden="true">
          {steps.map((_, i) => (
            <i key={i} className={i === step ? "active" : ""} />
          ))}
        </div>
        <div className="guide-actions">
          <button onClick={() => setStep(null)}>안내 건너뛰기</button>
          <div>
            <button disabled={step === 0} onClick={() => setStep(step - 1)}>
              이전
            </button>
            <button
              className="primary"
              onClick={() =>
                setStep(step === steps.length - 1 ? null : step + 1)
              }
            >
              {step === steps.length - 1 ? "사용 시작하기" : "다음"}
            </button>
          </div>
        </div>
      </section>
    </>,
    document.body,
  );
}
export function GuideButton() {
  const [, setStep] = useAtom(guideStepAtom);
  return (
    <button className="guide-trigger" onClick={() => setStep(0)}>
      사용 가이드
    </button>
  );
}
