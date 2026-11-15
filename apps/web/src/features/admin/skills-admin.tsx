"use client";
// The advisor's skills (admin.css, "the skills"): how the shop does each task, as the assistant reads it. An admin
// reads the version in force, edits a skill, adds or removes one, and switches any version on; every change is a new
// version (the original, v0, never changes), served from the next turn. The API checks the role and the limits
// (api/routes/improvement.py, components/improvement/skill_versions.py).
import { useCallback, useEffect, useState } from "react";
import { api } from "@/services/api";

type Skill = { name: string; description: string; done_on: string[]; body: string; changed: boolean; new: boolean };
type Version = { version: number; active: boolean; saved_at: string | null; by: string; note: string; changed: string[] };
type Book = {
  active: number;
  version: number;
  skills: Skill[];
  versions: Version[];
  limits: { description: number; body: number };
};
type Draft = { name: string; description: string; done_on: string; body: string; isNew: boolean };

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" }) : "");
const who = (by: string) => by.replace(/^staff:/, "");

export default function SkillsAdmin({ token, onNotice }: { token: string; onNotice: (text: string) => void }) {
  const [book, setBook] = useState<Book | null>(null);
  const [viewing, setViewing] = useState<number | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    async (version: number | null = viewing) => {
      try {
        const query = version == null ? "" : `?version=${version}`;
        setBook(await api<Book>(`/api/developer/improvement/skills${query}`, token));
      } catch (e) {
        onNotice(e instanceof Error ? e.message : "Không tải được skills");
      }
    },
    [token, onNotice, viewing],
  );

  useEffect(() => {
    load();
  }, [load]);

  async function save(changes: Record<string, unknown>, activate: boolean, done: string) {
    setBusy(true);
    try {
      const result = await api<{ skills_version: number }>("/api/developer/improvement/skills", token, {
        changes,
        note,
        activate,
      });
      onNotice(`${done} Đã lưu thành v${result.skills_version}${activate ? ", trợ lý dùng từ lượt tiếp theo." : " (bản nháp, chưa bật)."}`);
      setDraft(null);
      setNote("");
      setViewing(null);
      await load(null);
    } catch (e) {
      onNotice(e instanceof Error ? e.message : "Không lưu được");
    } finally {
      setBusy(false);
    }
  }

  async function switchOn(version: number) {
    if (!window.confirm(`Bật skills v${version}? Trợ lý dùng bộ này từ lượt tiếp theo.`)) return;
    setBusy(true);
    try {
      await api(`/api/developer/improvement/skills/versions/${version}/activate`, token, { note });
      onNotice(`Đã bật skills v${version}.`);
      setViewing(null);
      await load(null);
    } catch (e) {
      onNotice(e instanceof Error ? e.message : "Không bật được");
    } finally {
      setBusy(false);
    }
  }

  if (book === null) return <p className="sl-muted" role="status">Đang tải…</p>;
  const editable = book.version === book.active;
  const limits = book.limits;

  function submit(activate: boolean) {
    if (!draft) return;
    const name = draft.name.trim();
    const skill = {
      description: draft.description.trim(),
      body: draft.body.trim(),
      done_on: draft.done_on.split(",").map((t) => t.trim()).filter(Boolean),
    };
    save({ [name]: skill }, activate, draft.isNew ? `Đã thêm skill ${name}.` : `Đã sửa skill ${name}.`);
  }

  return (
    <div className="ad-stack ad-skills">
      <section className="sl-panel ad-skills__head">
        <div>
          <h2>Skills của trợ lý</h2>
          <p className="ad-lead">
            Cách cửa hàng làm từng việc (đặt đơn, đổi đơn, tư vấn…), trợ lý đọc mỗi lượt. Mỗi lần lưu là một version mới; bản
            gốc v0 không bao giờ bị sửa, nên luôn quay lại được.
          </p>
        </div>
        <div className="ad-skills__version">
          <span className="ad-skills__live">Đang dùng: v{book.active}</span>
          <label>
            Xem version
            <select value={book.version} onChange={(e) => { setViewing(Number(e.target.value)); setDraft(null); }}>
              {book.versions.map((v) => (
                <option key={v.version} value={v.version}>
                  v{v.version}{v.active ? " (đang dùng)" : ""}
                </option>
              ))}
            </select>
          </label>
          {!editable && (
            <button className="sl-btn" disabled={busy} onClick={() => switchOn(book.version)}>Bật v{book.version}</button>
          )}
        </div>
      </section>

      {!editable && <p className="sl-alert ad-ok" role="status">Đang xem v{book.version}, chưa phải bản trợ lý dùng. Chỉ sửa được bản đang dùng.</p>}

      <div className="ad-skills__grid">
        <div className="ad-skills__list">
          {editable && !draft && (
            <button className="ad-btn-quiet ad-skills__add" onClick={() => setDraft({ name: "", description: "", done_on: "", body: "", isNew: true })}>
              + Thêm skill
            </button>
          )}
          {draft?.isNew && <SkillForm draft={draft} setDraft={setDraft} note={note} setNote={setNote} limits={limits} busy={busy} onSave={submit} />}
          {book.skills.map((skill) => {
            const editing = draft && !draft.isNew && draft.name === skill.name;
            const expanded = open === skill.name;
            return (
              <article key={skill.name} className={"ad-skill" + (editing ? " is-editing" : "")}>
                {editing ? (
                  <SkillForm draft={draft!} setDraft={setDraft} note={note} setNote={setNote} limits={limits} busy={busy} onSave={submit} />
                ) : (
                  <>
                    <header>
                      <div>
                        <strong>{skill.name}</strong>
                        {skill.new ? <span className="ad-tag is-new">Mới</span> : skill.changed ? <span className="ad-tag">Đã sửa so với gốc</span> : null}
                      </div>
                      {editable && (
                        <div className="ad-skill__actions">
                          <button className="ad-btn-quiet" onClick={() => setDraft({ name: skill.name, description: skill.description, done_on: skill.done_on.join(", "), body: skill.body, isNew: false })}>
                            Sửa
                          </button>
                          <button
                            className="ad-btn-danger"
                            disabled={busy || book.skills.length < 2}
                            onClick={() => {
                              if (window.confirm(`Bỏ skill ${skill.name}? Lưu thành version mới; quay lại version cũ là có lại.`))
                                save({ [skill.name]: null }, true, `Đã bỏ skill ${skill.name}.`);
                            }}
                          >
                            Bỏ
                          </button>
                        </div>
                      )}
                    </header>
                    <p className="ad-skill__desc">{skill.description}</p>
                    {skill.done_on.length > 0 && (
                      <p className="ad-skill__done">
                        Xong khi gọi: {skill.done_on.map((tool) => <code key={tool}>{tool}</code>)}
                      </p>
                    )}
                    <pre className={"ad-skill__body" + (expanded ? " is-open" : "")}>{skill.body}</pre>
                    {/* A body of a few short lines shows whole; a longer one folds to five lines. */}
                    {(skill.body.length > 320 || skill.body.split("\n").length > 4) && (
                      <button className="link-button" onClick={() => setOpen(expanded ? null : skill.name)} aria-expanded={expanded}>
                        {expanded ? "Thu gọn" : `Xem toàn bộ (${skill.body.split("\n").length} dòng)`}
                      </button>
                    )}
                  </>
                )}
              </article>
            );
          })}
        </div>

        <aside className="sl-panel ad-skills__versions" aria-label="Các version">
          <h3>Các version</h3>
          <ol>
            {book.versions.map((v) => (
              <li key={v.version} className={v.active ? "is-active" : ""}>
                <div>
                  <strong>v{v.version}</strong>
                  {v.active && <span className="ad-tag is-live">Đang dùng</span>}
                </div>
                <small>
                  {v.version === 0 ? "Bản gốc" : [who(v.by), when(v.saved_at)].filter(Boolean).join(" · ")}
                </small>
                {v.changed.length > 0 && <small>Đổi: {v.changed.join(", ")}</small>}
                {v.note && <small className="ad-skills__note">“{v.note}”</small>}
                <div className="ad-skill__actions">
                  <button className="ad-btn-quiet" onClick={() => { setViewing(v.version); setDraft(null); }}>Xem</button>
                  {!v.active && (
                    <button className="ad-btn-quiet" disabled={busy} onClick={() => switchOn(v.version)}>Bật</button>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </aside>
      </div>
    </div>
  );
}

function SkillForm({
  draft,
  setDraft,
  note,
  setNote,
  limits,
  busy,
  onSave,
}: {
  draft: Draft;
  setDraft: (d: Draft | null) => void;
  note: string;
  setNote: (n: string) => void;
  limits: { description: number; body: number };
  busy: boolean;
  onSave: (activate: boolean) => void;
}) {
  const set = (change: Partial<Draft>) => setDraft({ ...draft, ...change });
  const valid = /^[a-z][a-z0-9-]{1,47}$/.test(draft.name.trim()) && draft.description.trim() && draft.body.trim() &&
    draft.description.length <= limits.description && draft.body.length <= limits.body;
  return (
    <form className="ad-form ad-skill-form" onSubmit={(e) => { e.preventDefault(); onSave(true); }}>
      <h3>{draft.isNew ? "Thêm skill" : `Sửa skill ${draft.name}`}</h3>
      {draft.isNew && (
        <label>
          Tên <small>chữ thường, số, gạch ngang: warranty-claim</small>
          <input required value={draft.name} onChange={(e) => set({ name: e.target.value })} pattern="[a-z][a-z0-9-]{1,47}" />
        </label>
      )}
      <label>
        Mô tả <small>{draft.description.length}/{limits.description} · trợ lý đọc dòng này để biết khi nào dùng skill</small>
        <textarea rows={2} required value={draft.description} maxLength={limits.description} onChange={(e) => set({ description: e.target.value })} />
      </label>
      <label>
        Nội dung <small>{draft.body.length}/{limits.body} · mỗi dòng một chỉ dẫn, bắt đầu bằng “- ”</small>
        <textarea className="ad-skill-form__body" rows={14} required value={draft.body} maxLength={limits.body} onChange={(e) => set({ body: e.target.value })} />
      </label>
      <label>
        Xong khi gọi tool <small>tùy chọn, cách nhau bằng dấu phẩy: order_create</small>
        <input value={draft.done_on} onChange={(e) => set({ done_on: e.target.value })} />
      </label>
      <label>
        Ghi chú cho version này <small>tùy chọn</small>
        <input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} placeholder="Vì sao sửa" />
      </label>
      <div className="ad-skill__actions">
        <button className="sl-btn" type="submit" disabled={busy || !valid}>Lưu và áp dụng ngay</button>
        <button className="ad-btn-quiet" type="button" disabled={busy || !valid} onClick={() => onSave(false)}>Lưu bản nháp</button>
        <button className="ad-btn-quiet" type="button" onClick={() => setDraft(null)}>Hủy</button>
      </div>
    </form>
  );
}
