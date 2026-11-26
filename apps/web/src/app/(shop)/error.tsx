"use client";

import Link from "next/link";
import EmptyState from "@/components/shop/EmptyState";

export default function ShopError({ retry }: { retry: () => void }) {
  return (
    <EmptyState
      alert
      title="Trang đang gặp sự cố"
      line="Bạn có thể thử tải lại nội dung hoặc quay về cửa hàng."
      actions={<>
        <button className="s-btn" onClick={retry}>Thử lại</button>
        <Link className="s-btn s-btn-outline" href="/">Về cửa hàng</Link>
      </>}
    />
  );
}
