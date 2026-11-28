// The evaluation history as the API returns it (GET /api/developer/evaluations), and what each number means.
// Numbers of two runs compare only on the same cohort (scenario files) and extractor.

export type Run = {
  run_id: string;
  purpose: string;
  week: string;
  started_at: string;
  cohort_sha256: string | null;
  n_scenarios: number | null;
  extractor_version: string | null;
  advisor_model: string | null;
  profile: string;
  skills_version: number | null;
  kb_version: number | null;
  metrics: Record<string, Record<string, number>>;
};
export type Round = { name: string; week: string; status: string; candidate_skills_version: number | null };
export type Scenario = {
  config: string;
  scenario_id: string;
  passed: boolean;
  failures: { call: string | null; reasons: string[]; hard_case: string | null }[];
  calls: number;
  turns: number;
  tool_calls: number;
  tool_errors: number;
  ttft_p95_ms: number | null;
};

export const PURPOSE: Record<string, string> = {
  weekly_frozen: "Hằng tuần, version đang chạy (R0)",
  weekly_candidate: "Hằng tuần, version ứng viên (R1)",
  dev_full: "Toàn bộ data/dev",
  adhoc: "Chạy tay",
};
export const SERIES = [
  { config: "full", label: "Có bộ nhớ (full)", color: "var(--ad-series-1)" },
  { config: "baseline_no_memory", label: "Không bộ nhớ (baseline)", color: "var(--ad-series-2)" },
];

export type Unit = "pct" | "ms" | "count" | "tokens" | "usd" | "ratio";
export type Metric = { id: string; title: string; better: "cao" | "thấp"; unit: Unit; config?: string };

export const RATES: Metric[] = [
  { id: "TSR", title: "Task Success Rate (TSR)", better: "cao", unit: "pct" },
  { id: "CCR", title: "Context Carryover Rate (CCR)", better: "cao", unit: "pct" },
  { id: "RQR", title: "Repeat-Question Rate (RQR)", better: "thấp", unit: "pct" },
  { id: "HR", title: "Hallucination Rate (HR, giá & KM)", better: "thấp", unit: "pct" },
];

/** Performance, on the full configuration (pipeline/eval/history.py, _performance). */
export const PERFORMANCE: Metric[] = [
  { id: "ttft_p50_ms", title: "TTFT p50", better: "thấp", unit: "ms" },
  { id: "ttft_p95_ms", title: "TTFT p95", better: "thấp", unit: "ms" },
  { id: "total_p50_ms", title: "Thời gian trả lời p50", better: "thấp", unit: "ms" },
  { id: "total_p95_ms", title: "Thời gian trả lời p95", better: "thấp", unit: "ms" },
  { id: "call_brief_p95_ms", title: "Call brief p95", better: "thấp", unit: "ms" },
  { id: "tokens_per_turn", title: "Token mỗi lượt", better: "thấp", unit: "tokens" },
  { id: "tokens_per_turn_with_after_call", title: "Token mỗi lượt, kể cả after_call", better: "thấp", unit: "tokens" },
  { id: "cached_share", title: "Tỷ lệ token cache", better: "cao", unit: "pct" },
  { id: "cost_per_turn_usd", title: "Chi phí mỗi lượt", better: "thấp", unit: "usd" },
  { id: "cost_per_turn_with_after_call_usd", title: "Chi phí mỗi lượt, kể cả after_call", better: "thấp", unit: "usd" },
];

/** Quality counts and the report's other figures (history.py, _quality and _problems). */
export const QUALITY: Metric[] = [
  { id: "TSR_hard_cases", title: "TSR ca khó", better: "cao", unit: "pct" },
  { id: "calls_to_close", title: "Số cuộc gọi để chốt", better: "thấp", unit: "ratio" },
  { id: "avg_turns_per_call", title: "Lượt mỗi cuộc gọi", better: "thấp", unit: "ratio" },
  { id: "guardrail_violations", title: "Vi phạm guardrail", better: "thấp", unit: "count" },
  { id: "guardrail_over_escalation", title: "· chuyển người thừa", better: "thấp", unit: "count" },
  { id: "guardrail_claims_human", title: "· tự nhận là người", better: "thấp", unit: "count" },
  { id: "guardrail_pii_in_memory_or_text", title: "· lộ dữ liệu cá nhân", better: "thấp", unit: "count" },
  { id: "guardrail_forbidden_pattern", title: "· câu bị cấm", better: "thấp", unit: "count" },
  { id: "failed_turns", title: "Lượt lỗi", better: "thấp", unit: "count" },
  { id: "after_call_failed", title: "after_call thất bại", better: "thấp", unit: "count" },
  { id: "safe_lines", title: "Câu trả lời dự phòng", better: "thấp", unit: "count" },
  { id: "policy_skipped", title: "PolicyAgent bỏ qua", better: "thấp", unit: "count" },
  { id: "unlabelled_turns", title: "Lượt chưa gán nhãn", better: "thấp", unit: "count" },
  { id: "schema_errors", title: "Lỗi schema", better: "thấp", unit: "count" },
  { id: "scenarios_stopped", title: "Kịch bản dừng giữa chừng", better: "thấp", unit: "count" },
];

export const cohortKey = (r: Run) => `${r.cohort_sha256 || "?"}|${r.extractor_version || "?"}`;

const num = (v: number, digits = 1) => v.toLocaleString("vi-VN", { maximumFractionDigits: digits });

export function format(value: number | undefined | null, unit: Unit): string {
  if (value == null || Number.isNaN(value)) return "chưa đo";
  switch (unit) {
    case "pct":
      return `${num(value)}%`;
    case "ms":
      return value >= 1000 ? `${num(value / 1000, 2)} s` : `${Math.round(value)} ms`;
    case "tokens":
      return num(Math.round(value), 0);
    case "usd":
      return `$${value.toFixed(5)}`;
    case "ratio":
      return num(value, 2);
    default:
      return num(value, 0);
  }
}

export const pct = (v: number | undefined) => format(v, "pct");

/** B against A: "better", "worse" or "same", read with the metric's direction. */
export function verdict(metric: Metric, a: number | undefined, b: number | undefined): "better" | "worse" | "same" | null {
  if (a == null || b == null) return null;
  if (Math.abs(b - a) < 1e-9) return "same";
  return (b > a) === (metric.better === "cao") ? "better" : "worse";
}

export function delta(metric: Metric, a: number | undefined, b: number | undefined): string {
  if (a == null || b == null) return "—";
  const d = b - a;
  const sign = d > 0 ? "+" : d < 0 ? "−" : "±";
  const size = Math.abs(d);
  if (metric.unit === "pct") return `${sign}${num(size)} điểm`;
  return `${sign}${format(size, metric.unit)}`;
}

export const value = (run: Run | undefined, metric: Metric, config = metric.config || "full") => run?.metrics?.[config]?.[metric.id];
