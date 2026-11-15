"use client";
// The shop's policies as the assistant reads them (admin.css, "the policies"): the organisers' documents, section by
// section (read-only: data/btc/policy), each marked for who may hear it and when it is in force, and what reviewers
// added on top (the knowledge version in force). Search runs over every section's code, title and text.
import { useEffect, useMemo, useState } from "react";
import { api } from "@/services/api";

type Section = {
  id: string;
  title: string;
  text: string;
  restricted: boolean;
  valid_from: string | null;
  valid_to: string | null;
  changelog: string[];
  industry: string | null;
};
type Doc = { doc: string; title: string; sections: Section[]; internal: boolean; retired: boolean };
type Learned = { chunk_id: string; title?: string; text?: string; cites?: string[]; valid_from?: string; valid_to?: string; approved_by?: string };
type Policies = { documents: Doc[]; learned: { version: number; entries: Learned[] } };
type Filter = "all" | "public" | "internal" | "retired";

const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "Tất cả" },
  { id: "public", label: "Khách xem được" },
  { id: "internal", label: "Nội bộ" },
  { id: "retired", label: "Hết hiệu lực" },
];

/** A title as the files write it, without its markdown emphasis ("**HẾT HIỆU LỰC**"). */
const clean = (text: string) => text.replace(/\*\*/g, "").trim();

const plain = (text: string) => text.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/đ/g, "d").toLowerCase();

function fits(section: Section, filter: Filter) {
  if (filter === "public") return !section.restricted && !section.valid_to;
  if (filter === "internal") return section.restricted;
  if (filter === "retired") return !!section.valid_to;
  return true;
}

/** A section's markdown as the policy files write it: lines, "- " lists, **bold**; nothing else is interpreted. */
function Text({ text }: { text: string }) {
  return (
    <div className="ad-policy__text">
      {text.split("\n").map((line, index) => {
        const parts = line.replace(/^\s*[-*]\s+/, "").split(/(\*\*[^*]+\*\*)/g).map((part, j) =>
          part.startsWith("**") && part.endsWith("**") ? <b key={j}>{part.slice(2, -2)}</b> : <span key={j}>{part}</span>,
        );
        if (!line.trim()) return null;
        return /^\s*[-*]\s+/.test(line) ? <p key={index} className="is-item">{parts}</p> : <p key={index}>{parts}</p>;
      })}
    </div>
  );
}

export default function PoliciesAdmin({ token, onNotice }: { token: string; onNotice: (text: string) => void }) {
  const [data, setData] = useState<Policies | null>(null);
  const [doc, setDoc] = useState<string>("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");

  useEffect(() => {
    api<Policies>("/api/developer/policies", token)
      .then(setData)
      .catch((e) => onNotice(e instanceof Error ? e.message : "Không tải được chính sách"));
  }, [token, onNotice]);

  const words = plain(query).split(/\s+/).filter(Boolean);
  const shown = useMemo(() => {
    if (!data) return [];
    return data.documents
      .filter((d) => !doc || d.doc === doc)
      .map((d) => ({
        ...d,
        sections: d.sections.filter((s) => fits(s, filter) && words.every((w) => plain(`${s.id} ${s.title} ${s.text}`).includes(w))),
      }))
      .filter((d) => d.sections.length > 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- words come from query
  }, [data, doc, filter, query]);

  if (data === null) return <p className="sl-muted" role="status">Đang tải…</p>;
  const total = shown.reduce((n, d) => n + d.sections.length, 0);

  return (
    <div className="ad-policies">
      <aside className="sl-panel ad-policies__docs" aria-label="Tài liệu">
        <h2>Tài liệu</h2>
        <p className="ad-lead">Bộ chính sách của BTC (chỉ đọc). Trợ lý chỉ nói với khách các mục không phải nội bộ và còn hiệu lực.</p>
        <ul>
          <li>
            <button className={!doc ? "is-on" : ""} onClick={() => setDoc("")}>
              <span>Tất cả tài liệu</span>
              <small>{data.documents.reduce((n, d) => n + d.sections.length, 0)} mục</small>
            </button>
          </li>
          {data.documents.map((d) => (
            <li key={d.doc}>
              <button className={doc === d.doc ? "is-on" : ""} onClick={() => setDoc(d.doc)}>
                <span>{clean(d.title)}</span>
                <small>
                  {d.sections.length} mục
                  {d.internal ? " · nội bộ" : ""}
                  {d.retired ? " · hết hiệu lực" : ""}
                </small>
              </button>
            </li>
          ))}
          <li>
            <button className={doc === "__learned" ? "is-on" : ""} onClick={() => setDoc("__learned")}>
              <span>Kiến thức bổ sung đã duyệt</span>
              <small>v{data.learned.version} · {data.learned.entries.length} mục</small>
            </button>
          </li>
        </ul>
      </aside>

      <section className="ad-policies__main">
        <div className="sl-panel ad-policies__tools">
          <input
            type="search"
            aria-label="Tìm trong chính sách"
            placeholder="Tìm mã (DT-03), tiêu đề hoặc nội dung: đổi size, COD, bảo hành…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="ad-policies__filters" role="group" aria-label="Lọc">
            {FILTERS.map((f) => (
              <button key={f.id} className={"ad-chip" + (filter === f.id ? " is-on" : "")} aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}>
                {f.label}
              </button>
            ))}
          </div>
          {doc !== "__learned" && <span className="sl-muted">{total} mục</span>}
        </div>

        {doc === "__learned" ? (
          <section className="sl-panel ad-policy-doc">
            <h2>Kiến thức bổ sung đã duyệt</h2>
            <p className="ad-lead">
              Câu trả lời người duyệt thêm từ Gap Loop (knowledge v{data.learned.version}). FAQ theo đợt nằm ở tab Kiến thức.
            </p>
            {data.learned.entries.length === 0 ? (
              <p className="sl-muted">Chưa có mục nào: trợ lý chỉ dùng bộ chính sách của BTC.</p>
            ) : (
              data.learned.entries.map((entry) => (
                <article key={entry.chunk_id} className="ad-policy">
                  <header>
                    <code>{entry.chunk_id}</code>
                    <strong>{entry.title || "Bổ sung"}</strong>
                  </header>
                  {entry.text && <Text text={entry.text} />}
                  <p className="ad-policy__meta">
                    {entry.cites?.length ? `Dựa trên: ${entry.cites.join(", ")}` : ""}
                    {entry.approved_by ? ` · duyệt bởi ${entry.approved_by}` : ""}
                  </p>
                </article>
              ))
            )}
          </section>
        ) : shown.length === 0 ? (
          <p className="sl-muted">Không có mục nào khớp.</p>
        ) : (
          shown.map((d) => (
            <section key={d.doc} className="sl-panel ad-policy-doc">
              <header className="ad-policy-doc__head">
                <h2>{clean(d.title)}</h2>
                <code>{d.doc}</code>
              </header>
              {d.sections.map((s) => (
                <article key={s.id} id={s.id} className={"ad-policy" + (s.restricted ? " is-internal" : "") + (s.valid_to ? " is-retired" : "")}>
                  <header>
                    <code>{s.id}</code>
                    <strong>{clean(s.title)}</strong>
                    {s.restricted && <span className="ad-tag">Nội bộ, không nói với khách</span>}
                    {s.valid_to && <span className="ad-tag is-old">Hết hiệu lực từ {s.valid_to}</span>}
                  </header>
                  <Text text={s.text} />
                  {(s.valid_from || s.changelog.length > 0 || s.industry) && (
                    <p className="ad-policy__meta">
                      {s.valid_from ? `Hiệu lực từ ${s.valid_from}` : ""}
                      {s.changelog.length ? `${s.valid_from ? " · " : ""}Thay đổi: ${s.changelog.join(", ")}` : ""}
                      {s.industry ? ` · Ngành: ${s.industry}` : ""}
                    </p>
                  )}
                </article>
              ))}
            </section>
          ))
        )}
      </section>
    </div>
  );
}
