"use client";

import Link from "next/link";

export default function ShopError({ retry }: { retry: () => void }) {
  return (
    <div className="s-wrap s-page s-empty-state" role="alert">
      <h1 className="s-page-title">Trang đang gặp sự cố</h1>
      <p>Bạn có thể thử tải lại nội dung hoặc quay về cửa hàng.</p>
      <div className="s-center">
        <button className="s-btn" onClick={retry}>Thử lại</button>
        <Link className="s-btn s-btn-outline" href="/">Về cửa hàng</Link>
      </div>
    </div>
  );
}
