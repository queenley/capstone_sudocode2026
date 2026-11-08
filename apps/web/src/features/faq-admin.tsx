"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/services/api";

type Effective = {
  valid_from: string | null;
  valid_to: string | null;
  applies_to: string[];
};
type Entry = {
  chunk_id: string;
  title: string;
  text: string;
  status: "draft" | "live";
  valid_from: string | null;
  valid_to: string | null;
  campaign: string | null;
  applies_to: string[];
  cites: string[];
  approved_by: string | null;
  effective: Effective;
  in_force: boolean;
  editable: boolean;
};
type Promotion = { code: string; name: string; start: string; end: string };
type Listing = { day: string; entries: Entry[]; promotions: Promotion[] };
type Form = {
  id: string | null;
  title: string;
  text: string;
  campaign: string;
  appliesTo: string;
  cites: string;
  validFrom: string;
  validTo: string;
  approved: boolean;
};

const EMPTY: Form = {
  id: null,
  title: "",
  text: "",
  campaign: "",
  appliesTo: "",
  cites: "",
  validFrom: "",
  validTo: "",
  approved: false,
};
const words = (value: string) =>
  value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

function payload(form: Form, status: "draft" | "live", approved: boolean) {
  return {
    title: form.title,
    text: form.text,
    campaign: form.campaign || null,
    applies_to: words(form.appliesTo),
    cites: words(form.cites),
    valid_from: form.validFrom || null,
    valid_to: form.validTo || null,
    status,
    approved,
  };
}

function state(entry: Entry) {
  if (entry.status === "draft") return "Nháp";
  return entry.in_force ? "Đang áp dụng" : "Đã bật, ngoài thời gian đợt";
}

function period(entry: Entry) {
  const { valid_from: from, valid_to: to } = entry.effective;
  if (!from && !to) return "Không giới hạn";
  return `${from ?? "…"} đến ${to ?? "…"}`;
}

export default function FaqAdmin({
  token,
  refresh = 0,
}: {
  token: string;
  /** Changes when something else added an entry. */
  refresh?: number;
}) {
  const [listing, setListing] = useState<Listing | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const load = useCallback(
    async (signal?: AbortSignal) => {
      setListing(
        await api<Listing>("/api/developer/faq", token, undefined, undefined, {
          signal,
        }),
      );
    },
    [token],
  );
  useEffect(() => {
    const controller = new AbortController();
    setListing(null);
    setForm(null);
    setMessage("");
    if (token)
      load(controller.signal).catch((e) => {
        if (!controller.signal.aborted) setMessage(e.message);
      });
    return () => controller.abort();
  }, [token, load]);

  useEffect(() => {
    if (token && refresh) load().catch((e) => setMessage(e.message));
  }, [token, refresh, load]);

  async function run(work: () => Promise<void>, done: string) {
    if (busy) return;
    setBusy(true);
    setMessage("");
    try {
      await work();
      await load();
      setMessage(done);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Không lưu được FAQ");
    } finally {
      setBusy(false);
    }
  }
  function save(status: "draft" | "live") {
    if (!form) return;
    const path = form.id
      ? `/api/developer/faq/${form.id}`
      : "/api/developer/faq";
    run(
      async () => {
        await api(
          path,
          token,
          payload(form, status, form.approved),
          form.id ? "PUT" : "POST",
        );
        setForm(null);
      },
      status === "live" ? "Đã bật FAQ." : "Đã lưu nháp.",
    );
  }
  function switchOff(entry: Entry) {
    run(async () => {
      await api(
        `/api/developer/faq/${entry.chunk_id}`,
        token,
        payload(toForm(entry), "draft", false),
        "PUT",
      );
    }, "Đã tắt FAQ, mục quay về nháp.");
  }
  function remove(entry: Entry) {
    if (!window.confirm(`Xóa FAQ "${entry.title}"?`)) return;
    run(async () => {
      await api(
        `/api/developer/faq/${entry.chunk_id}`,
        token,
        undefined,
        "DELETE",
      );
      if (form?.id === entry.chunk_id) setForm(null);
    }, "Đã xóa FAQ.");
  }
  const set = (change: Partial<Form>) =>
    setForm((value) => (value ? { ...value, ...change } : value));

  return (
    <section className="panel" aria-label="FAQ theo đợt">
      <div className="panel-title">
        <h2>FAQ theo đợt</h2>
        <button disabled={busy || !token} onClick={() => setForm(EMPTY)}>
          Thêm FAQ
        </button>
      </div>
      <p>
        Agent chỉ đọc mục đã bật và đang trong thời gian đợt. Giá, mã khuyến mãi
        và tồn kho luôn lấy từ tool, nên không ghi trong câu trả lời.
        {listing && ` Ngày nghiệp vụ: ${listing.day}.`}
      </p>
      {message && <p role="status">{message}</p>}
      {listing && !listing.entries.length && <p>Chưa có mục FAQ nào.</p>}
      {listing?.entries.map((entry) => (
        <article className="faq-entry" key={entry.chunk_id}>
          <strong>{entry.title}</strong>
          <p>{entry.text}</p>
          <small className="hint">
            {state(entry)} · {period(entry)}
            {entry.campaign && ` · Đợt: ${entry.campaign}`}
            {entry.effective.applies_to.length > 0 &&
              ` · Áp dụng: ${entry.effective.applies_to.join(", ")}`}
            {entry.cites.length > 0 && ` · Nguồn: ${entry.cites.join(", ")}`}
            {entry.approved_by && ` · Duyệt bởi: ${entry.approved_by}`}
          </small>
          {entry.editable ? (
            <div className="faq-actions">
              <button
                disabled={busy}
                onClick={() => setForm(toForm(entry))}
                aria-label={`Sửa ${entry.title}`}
              >
                Sửa
              </button>
              {entry.status === "live" && (
                <button
                  disabled={busy}
                  onClick={() => switchOff(entry)}
                  aria-label={`Tắt ${entry.title}`}
                >
                  Tắt
                </button>
              )}
              <button
                disabled={busy}
                onClick={() => remove(entry)}
                aria-label={`Xóa ${entry.title}`}
              >
                Xóa
              </button>
            </div>
          ) : (
            <small className="hint"> · Thuộc bản phát hành, chỉ xem.</small>
          )}
        </article>
      ))}
      {form && (
        <form
          aria-label={form.id ? "Sửa FAQ" : "Thêm FAQ"}
          onSubmit={(event) => {
            event.preventDefault();
            save("draft");
          }}
        >
          <h3>{form.id ? "Sửa FAQ" : "Thêm FAQ"}</h3>
          <label>
            Câu hỏi
            <input
              required
              minLength={3}
              maxLength={300}
              value={form.title}
              disabled={busy}
              onChange={(e) => set({ title: e.target.value })}
            />
          </label>
          <label>
            Câu trả lời
            <textarea
              required
              minLength={3}
              maxLength={2000}
              rows={4}
              value={form.text}
              disabled={busy}
              onChange={(e) => set({ text: e.target.value })}
            />
          </label>
          <label>
            Đợt (mã khuyến mãi hoặc tên đợt)
            <input
              list="faq-promotions"
              maxLength={80}
              value={form.campaign}
              disabled={busy}
              onChange={(e) => set({ campaign: e.target.value })}
            />
          </label>
          <datalist id="faq-promotions">
            {listing?.promotions.map((promotion) => (
              <option key={promotion.code} value={promotion.code}>
                {promotion.name} ({promotion.start} đến {promotion.end})
              </option>
            ))}
          </datalist>
          <label>
            Áp dụng cho, cách nhau bằng dấu phẩy
            <input
              value={form.appliesTo}
              disabled={busy}
              placeholder="SKU-AP-X, category:gia-dung, *"
              onChange={(e) => set({ appliesTo: e.target.value })}
            />
          </label>
          <label>
            Nguồn, cách nhau bằng dấu phẩy
            <input
              value={form.cites}
              disabled={busy}
              placeholder="KM-03, DT-01"
              onChange={(e) => set({ cites: e.target.value })}
            />
          </label>
          <label>
            Từ ngày
            <input
              type="date"
              value={form.validFrom}
              disabled={busy}
              onChange={(e) => set({ validFrom: e.target.value })}
            />
          </label>
          <label>
            Đến ngày
            <input
              type="date"
              value={form.validTo}
              disabled={busy}
              onChange={(e) => set({ validTo: e.target.value })}
            />
          </label>
          <small className="hint">
            Đợt là mã khuyến mãi thì để trống ngày để lấy theo khuyến mãi. Đợt
            tự đặt tên phải có ngày kết thúc.
          </small>
          <label className="faq-approve">
            <input
              type="checkbox"
              checked={form.approved}
              disabled={busy}
              onChange={(e) => set({ approved: e.target.checked })}
            />
            Tôi đã đối chiếu nguồn và duyệt câu trả lời này
          </label>
          <div className="faq-actions">
            <button disabled={busy} type="submit">
              Lưu nháp
            </button>
            <button
              disabled={busy || !form.approved}
              type="button"
              onClick={() => save("live")}
            >
              Duyệt và bật
            </button>
            <button disabled={busy} type="button" onClick={() => setForm(null)}>
              Hủy
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

function toForm(entry: Entry): Form {
  return {
    id: entry.chunk_id,
    title: entry.title,
    text: entry.text,
    campaign: entry.campaign ?? "",
    appliesTo: entry.applies_to.join(", "),
    cites: entry.cites.join(", "),
    validFrom: entry.valid_from ?? "",
    validTo: entry.valid_to ?? "",
    approved: false,
  };
}
