/** What the assistant is doing during a turn, one line per tool call (ai_agent_service/runtime/steps.py).
 *
 *  Live (`done` false): every step, the running one with a spinner. Done: folded into one line ("Đã tra cứu 3 bước ·
 *  2,1 s") that opens on a click. The shop gets labels only; staff (`detail`) also see the tool and its time. */
"use client";

export type TurnStep = {
  id: number;
  label: string;
  status: "running" | "ok" | "error";
  /** Staff only: the server sends these to the call console, never to the shop. */
  tool?: string;
  ms?: number | null;
};

/** The same step arrives twice (running, then ok or error): keep the latest of each id, in order. */
export function mergeStep(steps: TurnStep[], step: TurnStep): TurnStep[] {
  const at = steps.findIndex((s) => s.id === step.id);
  if (at < 0) return [...steps, step];
  const next = steps.slice();
  next[at] = { ...next[at], ...step };
  return next;
}

function seconds(ms: number): string {
  return (ms / 1000).toLocaleString("vi-VN", { maximumFractionDigits: 1 }) + " s";
}

function StepLine({ step, detail }: { step: TurnStep; detail?: boolean }) {
  return (
    <li className={`steps-line steps-${step.status}`}>
      <span className="steps-mark" aria-hidden="true" />
      <span className="steps-label">
        {step.status === "error" ? `${step.label} (chưa tra được)` : step.label}
        {step.status === "running" && "…"}
      </span>
      {detail && step.tool && (
        <code className="steps-tool">
          {step.tool}
          {typeof step.ms === "number" ? ` · ${step.ms} ms` : ""}
        </code>
      )}
    </li>
  );
}

export default function StepTrail({
  steps,
  done,
  elapsedMs,
  detail = false,
}: {
  steps: TurnStep[];
  done: boolean;
  /** The whole turn, measured by the page: shown on the folded line. */
  elapsedMs?: number | null;
  detail?: boolean;
}) {
  if (!steps.length) return null;
  const failed = steps.filter((s) => s.status === "error").length;
  if (!done)
    return (
      <ol className="steps steps-live" aria-live="polite">
        {steps.map((step) => (
          <StepLine key={step.id} step={step} detail={detail} />
        ))}
      </ol>
    );
  const summary =
    `Đã tra cứu ${steps.length} bước` +
    (failed ? ` · ${failed} lỗi` : "") +
    (elapsedMs ? ` · ${seconds(elapsedMs)}` : "");
  return (
    <details className="steps steps-done">
      <summary>{summary}</summary>
      <ol>
        {steps.map((step) => (
          <StepLine key={step.id} step={step} detail={detail} />
        ))}
      </ol>
    </details>
  );
}
