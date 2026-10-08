import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { atom, useAtom } from "jotai";
import { viewAtom } from "./state";

// Memory only: a new Provider/page load always starts at the first step.
export const guideStepAtom = atom<number | null>(0);
const steps = [
  {
    view: "overview",
    target: ".provenance",
    title: "GroundWatch는 이렇게 사용합니다",
    body: "기본 화면은 서울시 지하수와 기상청 강수를 실제 API로 받아 표시합니다. 관측일과 수집 시각을 구분해 확인하세요. 실제 자료로 학습한 별도 모델의 다음 날 예측을 표시합니다. 드리프트 시연은 조회 모드의 ‘과제 시연 예측’에서 확인할 수 있으며, 현장 안전 등급을 제공하지 않습니다.",
  },
  {
    view: "overview",
    target: ".stats",
    title: "먼저 관측 확보와 날짜를 확인하세요",
    body: "API 관측 확보 수는 예측 모델 준비 수와 다릅니다. 입력 기준일은 공급자가 제공한 관측 날짜입니다. 오늘 수집했더라도 오늘 관측이라는 뜻은 아닙니다. 예측 조건을 충족하지 않은 값은 —로 표시합니다.",
  },
  {
    view: "overview",
    target: ".map-panel",
    title: "관심 있는 관측소를 선택하세요",
    body: "서울 지도에서 구를 누르거나 아래 관측소 표에서 검색해 선택하세요. 오른쪽 카드에 선택한 관측소의 예측값과 모델 상태가 표시됩니다. 지도는 구 선택용이며 실제 관측소 위치나 구 전체 평균을 나타내지 않습니다.",
  },
  {
    view: "detail",
    target: ".overview-grid > .panel:first-child",
    title: "입력 수위와 다음 날 예측을 비교하세요",
    body: "실제 API 관측 모드에서는 원값과 날짜별 차트를 확인합니다. API 수위의 기준을 대조하기 전에는 지표 기준 단면으로 표시하지 않습니다. 시연 모드의 단면은 이해를 돕는 개념도이며 실제 지질 구조가 아닙니다.",
  },
  {
    view: "detail",
    target: ".chart",
    title: "기간을 바꿔 변화 흐름을 살펴보세요",
    body: "최근 30·90·180일 수위와 강수량을 조회할 수 있습니다. 같은 날짜 저장 예측보다 입력이 높으면 빨강, 낮으면 파랑입니다. 이 색은 위험 등급이 아닙니다. 다음 날 예측은 정답 확보 전까지 평가하지 않습니다.",
  },
  {
    view: "operations",
    target: ".scenario",
    title: "운영 시연은 상황 선택부터 시작합니다",
    body: "‘과제 시연 예측’ 모드에서 기본 상황 또는 드리프트 시연을 선택하고 준비를 기다린 뒤 자료를 진행합니다. ‘실제 API 관측·예측’ 모드에서는 실제 자료의 학습·평가·예측과 드리프트 감지·자동 재학습 상태를 확인합니다. 새 정답이 확보되어야 운영 단계가 진행됩니다. 안내를 따라가는 것만으로 시연이나 학습을 실행하지는 않습니다.",
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
    body: "일반 조회는 CSV 등록 없이 사용할 수 있습니다. 관측소 현황 → 상세가 기본 동선이고, 모델 관리·시연은 운영 확인용입니다. 우측 상단 사용 가이드로 언제든 다시 볼 수 있습니다. 새로고침하면 안내가 처음부터 다시 표시됩니다.",
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
