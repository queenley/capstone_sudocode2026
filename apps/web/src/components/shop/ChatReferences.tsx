"use client";
// The manufacturer's pages under an assistant message (docs/plan/002, section 12). The server sends them with the
// turn (TurnResult.references): links a person approved with the knowledge entry that answered, on a manufacturer's
// domain the shop allows. The model never writes them. They open on the manufacturer's site, in a new tab.
import type { TurnResult } from "@/services/api";

export type Reference = NonNullable<TurnResult["references"]>[number];

export default function ChatReferences({ references }: { references: Reference[] }) {
  if (!references.length) return null;
  return (
    <div className="s-msg-refs" aria-label="Nguồn từ nhà sản xuất">
      {references.map((ref) => (
        <a key={ref.url} className="s-msg-ref" href={ref.url} target="_blank" rel="noopener noreferrer nofollow">
          <span>Xem hướng dẫn của hãng</span>
          <small>{ref.domain} ↗</small>
        </a>
      ))}
    </div>
  );
}
