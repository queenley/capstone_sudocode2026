"use client";
import { useEffect, useState } from "react";
import { api } from "@/services/api";

type Context = {
  identity_confirmed: boolean;
  memory_status: string | null;
  facts: {
    slot: string;
    value: unknown;
    status: string;
    created_at: string;
    source: { call_id?: string; channel?: string };
  }[];
  episodes: {
    call_id: string;
    started_at: string;
    channel: string;
    summary: string;
    outcome: string;
  }[];
  orders: {
    order_id: string;
    sku: string;
    qty: number;
    status: string;
    source: string;
  }[];
};

export default function CallContext({
  callId,
  token,
}: {
  callId: number;
  token: string;
}) {
  const [context, setContext] = useState<Context | null>(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setContext(null);
    setError("");
    api<Context>(
      `/api/agent/calls/${callId}/context`,
      token,
      undefined,
      undefined,
      { signal: controller.signal },
    )
      .then((value) => {
        if (!controller.signal.aborted) setContext(value);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [callId, token, reload]);
  return (
    <section>
      <h3>Bộ nhớ và đơn của trợ lý</h3>
      <button onClick={() => setReload((value) => value + 1)}>
        Tải lại bộ nhớ
      </button>
      {error ? (
        <p role="alert">{error}</p>
      ) : !context ? (
        <p>Đang tải…</p>
      ) : (
        <>
          {!context.identity_confirmed && (
            <p>Chưa xác minh danh tính để tải hồ sơ khách.</p>
          )}
          <p>
            Trạng thái ghi nhớ: {context.memory_status || "Chưa có kết quả"}
          </p>
          {context.facts.map((fact, index) => (
            <div key={`${fact.slot}-${index}`}>
              <strong>{fact.slot}</strong>:{" "}
              {typeof fact.value === "string"
                ? fact.value
                : JSON.stringify(fact.value)}
              <small>
                {" "}
                · {fact.status} · {fact.created_at} · cuộc{" "}
                {fact.source?.call_id || "—"}
              </small>
            </div>
          ))}
          {context.episodes.map((episode) => (
            <p key={episode.call_id}>
              {episode.started_at} · {episode.channel}: {episode.summary} (
              {episode.outcome})
            </p>
          ))}
          {context.orders.map((order) => (
            <p key={order.order_id}>
              Đơn {order.order_id} · {order.sku} × {order.qty} · {order.status}
            </p>
          ))}
          {!context.facts.length &&
            !context.episodes.length &&
            !context.orders.length && <p>Chưa có dữ liệu được ghi nhận.</p>}
        </>
      )}
    </section>
  );
}
