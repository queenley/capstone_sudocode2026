"use client";
// Each scenario of one run (GET /api/developer/evaluations/{run_id}/scenarios): passed or not, the organisers'
// reasons, and what it took. Failed first; a filter shows only the failed ones.
import { useEffect, useState } from "react";
import { api } from "@/services/api";
import { format, Run, Scenario } from "./model";

export default function Scenarios({ points, token }: { points: Run[]; token: string }) {
  const [runId, setRunId] = useState(points[points.length - 1]?.run_id || "");
  const [config, setConfig] = useState("full");
  const [onlyFailed, setOnlyFailed] = useState(false);
  const [rows, setRows] = useState<Scenario[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!runId) return;
    let gone = false;
    setRows(null);
    setError("");
    api<{ scenarios: Scenario[] }>(`/api/developer/evaluations/${encodeURIComponent(runId)}/scenarios`, token)
      .then((found) => !gone && setRows(Array.isArray(found?.scenarios) ? found.scenarios : []))
      .catch((e) => !gone && (setRows([]), setError(e instanceof Error ? e.message : "Không tải được kịch bản")));
    return () => {
      gone = true;
    };
  }, [runId, token]);

  const ofConfig = (rows || []).filter((r) => r.config === config);
  const shown = onlyFailed ? ofConfig.filter((r) => !r.passed) : ofConfig;
  const passed = ofConfig.filter((r) => r.passed).length;

  return (
    <div className="ad-stack">
      <div className="ad-filters" role="group" aria-label="Lọc kịch bản">
        <label>
          Run
          <select value={runId} onChange={(e) => setRunId(e.target.value)}>
            {[...points].reverse().map((p) => (
              <option key={p.run_id} value={p.run_id}>
                {p.week} · {p.run_id}
              </option>
            ))}
          </select>
        </label>
        <label>
          Cấu hình
          <select value={config} onChange={(e) => setConfig(e.target.value)}>
            <option value="full">Có bộ nhớ (full)</option>
            <option value="baseline_no_memory">Không bộ nhớ (baseline)</option>
          </select>
        </label>
        <label className="ad-check">
          <input type="checkbox" checked={onlyFailed} onChange={(e) => setOnlyFailed(e.target.checked)} /> Chỉ kịch bản trượt
        </label>
      </div>
      {error && <p className="sl-alert">{error}</p>}
      {rows === null ? (
        <p className="sl-muted" role="status">Đang tải…</p>
      ) : ofConfig.length === 0 ? (
        <p className="sl-muted">Run này chưa có dữ liệu từng kịch bản: ingest lại để xem.</p>
      ) : (
        <>
          <p role="status">
            <strong>{passed}/{ofConfig.length}</strong> kịch bản đạt TSR · {ofConfig.length - passed} trượt
          </p>
          <div className="ad-scroll">
            <table className="sl-table" aria-label="Kết quả từng kịch bản">
              <thead>
                <tr>
                  <th scope="col">Kịch bản</th>
                  <th scope="col">Kết quả</th>
                  <th scope="col">Vì sao trượt</th>
                  <th scope="col">Cuộc gọi · lượt</th>
                  <th scope="col">Tool (lỗi)</th>
                  <th scope="col">TTFT p95</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.scenario_id}>
                    <td>
                      <code>{r.scenario_id}</code>
                    </td>
                    <td>
                      <span className={`sl-badge ${r.passed ? "ad-badge-pass" : "ad-badge-fail"}`}>{r.passed ? "Đạt" : "Trượt"}</span>
                    </td>
                    <td>
                      {r.failures.length === 0 ? (
                        <span className="sl-muted">—</span>
                      ) : (
                        <ul className="ad-reasons">
                          {r.failures.flatMap((f) =>
                            f.reasons.map((reason, k) => (
                              <li key={`${f.call}-${k}`}>
                                {f.call && <code>{f.call}</code>} {reason}
                              </li>
                            )),
                          )}
                        </ul>
                      )}
                    </td>
                    <td>
                      {r.calls} · {r.turns}
                    </td>
                    <td className={r.tool_errors > 0 ? "ad-bad" : undefined}>
                      {r.tool_calls} ({r.tool_errors})
                    </td>
                    <td>{format(r.ttft_p95_ms, "ms")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
