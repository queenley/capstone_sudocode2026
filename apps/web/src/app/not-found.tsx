import Link from "next/link";
import { Logo } from "@/components/brand/Logo";

export default function NotFound() {
  return (
    <main className="route-fallback">
      <Logo height={36} />
      <p className="eyebrow">404 · KHÔNG TÌM THẤY TRANG</p>
      <h1>Trang này chưa có ở Quivo</h1>
      <p>Đường dẫn có thể đã thay đổi. Bạn có thể về cửa hàng hoặc xem lại giỏ hàng.</p>
      <div className="buttonrow">
        <Link href="/">Về cửa hàng</Link>
        <Link href="/gio-hang">Xem giỏ hàng</Link>
      </div>
    </main>
  );
}
