"use client";
// The admin's review of the weekly improvement round: each change Reflection proposed, its evidence, the decision;
// then the round's measurement (R0 against the candidate) and the switch. docs/plan/001, part C.
// Every decision and switch is checked again by the API (admin only, under the signed-in account).
import { useCallback, useEffect, useState } from "react";
import { api } from "@/services/api";

type Proposal = {
  id: string;
  kind: string;
  decision: "approved" | "rejected" | null;
  reviewer: string | null;
  note: string | null;
  body: {
    situation?: string;
    failure_code?: string;
    why?: string;
    flags?: string[];
    policy?: string[];
    counts?: Record<string, number>;
    approval?: { approve: boolean; reason: string } | null;
    evidence?: { scenario_id: string; call: string }[];
    entry?: { text?: string; find?: string; cites?: string[]; when?: string; where?: string };
  };
};
type Comparison = {
  metrics: Record<string, { before: string; after: string }>;
  fixed: unknown[];
  broken: unknown[];
  unstable: unknown[];
  harm: { scenario_id: string; call: string; code: string }[];
  calls: number;
};
type Round = {
  name: string;
  week: string;
  status: string;
  base_skills_version: number;
  candidate_skills_version: number | null;
  proposals?: Proposal[] | number;
  pending?: number;
  detail: { comparison?: Record<string, Comparison>; error?: string; expired?: string; refused?: unknown[] };
};

export const ROUND_STATUS: Record<string, string> = {
  learning: "Đang học",
  no_change: "Không có đề xuất",
  waiting_review: "Chờ admin duyệt",
  expired: "Hết hạn, không áp dụng",
  rejected: "Không đề xuất nào được duyệt",
  measuring: "Đang đo version ứng viên",
  measured: "Đã đo, chờ bật",
  harm: "Phép đo thấy vi phạm mới",
  active: "Đã bật",
  failed: "Lỗi",
};

export default function ImprovementAdmin({ token, onNotice }: { token: string; onNotice: (text: string) => void }) {
  const [rounds, setRounds] = useState<Round[] | null>(null);
  const [skillsVersion, setSkillsVersion] = useState<number | null>(null);
  const [open, setOpen] = useState<Round | null>(null);

  const load = useCallback(async () => {
    try {
      const found = await api<{ rounds: Round[]; skills_version: number }>("/api/developer/improvement/rounds", token);
      setRounds(found.rounds);
      setSkillsVersion(found.skills_version);
    } catch (e) {
      setRounds([]);
      onNotice(e instanceof Error ? e.message : "Không tải được vòng cải tiến");
    }
  }, [token, onNotice]);

  const openRound = useCallback(
    async (name: string) => {
      try {
        setOpen(await api<Round>(`/api/developer/improvement/rounds/${encodeURIComponent(name)}`, token));
      } catch (e) {
        onNotice(e instanceof Error ? e.message : "Không mở được vòng");
      }
    },
    [token, onNotice],
  );

  useEffect(() => {
    load();
  }, [load]);

  if (rounds === null) return <p className="sl-muted" role="status">Đang tải…</p>;
  return (
    <div className="ad-stack">
      <section className="sl-panel" aria-label="Các vòng cải tiến">
        <header>
          <strong>Vòng hằng tuần</strong>
          <span className="sl-muted">Skills đang chạy: v{skillsVersion ?? "?"}</span>
        </header>
        {rounds.length === 0 ? (
          <p className="sl-muted">
            Chưa có vòng nào. Airflow chạy vòng mỗi thứ Hai (DAG <code>improvement_weekly</code>), hoặc chạy tay{" "}
            <code>improve weekly-learn</code>.
          </p>
        ) : (
          <table className="sl-table">
            <thead>
              <tr>
                <th>Tuần</th>
                <th>Trạng thái</th>
                <th>Đề xuất</th>
                <th>Skills</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rounds.map((r) => (
                <tr key={r.name}>
                  <td>{r.week}</td>
                  <td>
                    <span className="sl-badge">{ROUND_STATUS[r.status] || r.status}</span>
                  </td>
                  <td>
                    {Number(r.proposals) || 0}
                    {r.pending ? ` (${r.pending} chờ duyệt)` : ""}
                  </td>
                  <td>
                    v{r.base_skills_version}
                    {r.candidate_skills_version != null ? ` → v${r.candidate_skills_version}` : ""}
                  </td>
                  <td>
                    <button className="sl-btn sl-btn-small" onClick={() => openRound(r.name)}>
                      Mở {r.week}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      {open && (
        <RoundDetail
          token={token}
          round={open}
          onNotice={onNotice}
          onChange={async () => {
            await openRound(open.name);
            await load();
          }}
        />
      )}
      <Rollback token={token} current={skillsVersion} onNotice={onNotice} onDone={load} />
    </div>
  );
}

function RoundDetail({
  token,
  round,
  onNotice,
  onChange,
}: {
  token: string;
  round: Round;
  onNotice: (text: string) => void;
  onChange: () => Promise<void>;
}) {
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const proposals = Array.isArray(round.proposals) ? round.proposals : [];
  const reviewing = round.status === "waiting_review";

  async function run(fn: () => Promise<string>) {
    setBusy(true);
    try {
      onNotice(await fn());
      await onChange();
    } catch (e) {
      onNotice(e instanceof Error ? e.message : "Thao tác không thành công");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="sl-panel" aria-label={`Vòng ${round.week}`}>
      <header>
        <strong>
          Vòng {round.week} · {ROUND_STATUS[round.status] || round.status}
        </strong>
        <span className="sl-muted">học từ skills v{round.base_skills_version}</span>
      </header>
      {round.detail?.error && <div className="sl-alert">{round.detail.error}</div>}
      {round.detail?.expired && <p className="sl-muted">{round.detail.expired}</p>}
      {proposals.length === 0 && <p className="sl-muted">Vòng này không có đề xuất.</p>}
      {proposals.map((p) => (
        <article className="ad-proposal" key={p.id} aria-label={`Đề xuất ${p.id}`}>
          <div className="ad-proposal-head">
            <strong>{p.body.entry?.where || p.kind}</strong>
            <span className="sl-badge">
              {p.decision === "approved" ? "Đã duyệt" : p.decision === "rejected" ? "Đã từ chối" : "Chờ duyệt"}
            </span>
          </div>
          <p className="sl-muted">
            Tình huống: {p.body.situation || "?"} · lỗi {p.body.failure_code || "?"}
          </p>
          <dl className="ad-facts">
            <dt>Câu mới</dt>
            <dd>{p.body.entry?.text}</dd>
            <dt>Thay cho</dt>
            <dd>{p.body.entry?.find || "(thêm vào cuối skill)"}</dd>
            {p.body.entry?.when && (
              <>
                <dt>Áp dụng khi</dt>
                <dd>{p.body.entry.when}</dd>
              </>
            )}
            <dt>Dựa trên luật</dt>
            <dd>{(p.body.entry?.cites || []).join(", ") || "không"}</dd>
            <dt>Vì sao</dt>
            <dd>{p.body.why || "?"}</dd>
            <dt>Cổng kiểm</dt>
            <dd>
              {(p.body.flags || []).length ? `Cờ: ${p.body.flags!.join(", ")}` : "Không có cờ"}
              {(p.body.policy || []).length ? ` · PolicyAgent: ${p.body.policy!.join("; ")}` : " · PolicyAgent: qua"}
            </dd>
            {p.body.approval && (
              <>
                <dt>ApprovalAgent</dt>
                <dd>
                  {p.body.approval.approve ? "đồng ý" : "từ chối"}: {p.body.approval.reason}
                </dd>
              </>
            )}
            <dt>Bằng chứng</dt>
            <dd>{(p.body.evidence || []).map((e) => `${e.scenario_id}/${e.call}`).join(", ") || "không"}</dd>
          </dl>
          {p.decision ? (
            <p className="sl-muted">
              {p.reviewer}: {p.note || "không ghi chú"}
            </p>
          ) : (
            reviewing && (
              <>
                <label>
                  Ghi chú (bắt buộc khi từ chối)
                  <textarea
                    rows={2}
                    value={notes[p.id] || ""}
                    onChange={(e) => setNotes((old) => ({ ...old, [p.id]: e.target.value }))}
                  />
                </label>
                <div className="sl-actions">
                  <button
                    className="sl-btn sl-btn-small"
                    disabled={busy}
                    onClick={() =>
                      run(async () => {
                        await api(`/api/developer/improvement/proposals/${encodeURIComponent(p.id)}/review`, token, {
                          decision: "approved",
                          note: notes[p.id] || "",
                        });
                        return `Đã duyệt ${p.id}.`;
                      })
                    }
                  >
                    Duyệt {p.id}
                  </button>
                  <button
                    className="sl-btn sl-btn-small sl-danger"
                    disabled={busy || (notes[p.id] || "").trim().length < 3}
                    onClick={() =>
                      run(async () => {
                        await api(`/api/developer/improvement/proposals/${encodeURIComponent(p.id)}/review`, token, {
                          decision: "rejected",
                          note: notes[p.id] || "",
                        });
                        return `Đã từ chối ${p.id}.`;
                      })
                    }
                  >
                    Từ chối {p.id}
                  </button>
                </div>
              </>
            )
          )}
        </article>
      ))}
      {round.detail?.comparison && <Measurement comparison={round.detail.comparison} />}
      {round.status === "measured" && round.candidate_skills_version != null && (
        <div className="ad-switch">
          <label>
            <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
            Tôi đã xem phép đo trước/sau và muốn bật skills v{round.candidate_skills_version}
          </label>
          <button
            className="sl-btn"
            disabled={busy || !confirmed}
            onClick={() =>
              run(async () => {
                await api(`/api/developer/improvement/rounds/${encodeURIComponent(round.name)}/activate`, token, {});
                return `Đã bật skills v${round.candidate_skills_version}. Khởi động lại ai-agent-service để agent đọc version mới.`;
              })
            }
          >
            Bật skills v{round.candidate_skills_version}
          </button>
        </div>
      )}
      {round.status === "harm" && (
        <div className="sl-alert">Phép đo thấy vi phạm mới so với trước: version ứng viên không được bật.</div>
      )}
    </section>
  );
}

function Measurement({ comparison }: { comparison: Record<string, Comparison> }) {
  return (
    <div className="ad-measure">
      <h3>Đo trên bộ frozen: trước (R0) và với version ứng viên (R1)</h3>
      {Object.entries(comparison).map(([set, c]) => (
        <div key={set}>
          <table className="sl-table" aria-label={`Phép đo ${set}`}>
            <caption>
              Bộ {set}: {c.calls} cuộc so từng cuộc · sửa được {c.fixed.length} · làm hỏng {c.broken.length} · dao động{" "}
              {c.unstable.length} · vi phạm mới {c.harm.length}
            </caption>
            <thead>
              <tr>
                <th>Chỉ số</th>
                <th>Trước</th>
                <th>Sau</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(c.metrics).map(([name, cells]) => (
                <tr key={name}>
                  <td>{name}</td>
                  <td>{cells.before}</td>
                  <td>{cells.after}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

function Rollback({
  token,
  current,
  onNotice,
  onDone,
}: {
  token: string;
  current: number | null;
  onNotice: (text: string) => void;
  onDone: () => Promise<void>;
}) {
  const [to, setTo] = useState(0);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <form
      className="sl-panel"
      aria-label="Quay lui skills"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
          await api("/api/developer/improvement/skills/rollback", token, { to, reason });
          onNotice(`Đã quay về skills v${to}. Khởi động lại ai-agent-service để áp dụng.`);
          setReason("");
          await onDone();
        } catch (error) {
          onNotice(error instanceof Error ? error.message : "Không quay lui được");
        } finally {
          setBusy(false);
        }
      }}
    >
      <header>
        <strong>Quay lui skills</strong>
        <span className="sl-muted">đang chạy v{current ?? "?"}</span>
      </header>
      <label>
        Về version
        <input type="number" min={0} value={to} onChange={(e) => setTo(Number(e.target.value))} required />
      </label>
      <label>
        Lý do
        <input value={reason} minLength={3} onChange={(e) => setReason(e.target.value)} required />
      </label>
      <button className="sl-btn sl-btn-small sl-danger" disabled={busy} type="submit">
        Quay lui
      </button>
    </form>
  );
}
