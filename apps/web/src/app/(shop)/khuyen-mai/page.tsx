"use client";
import { useEffect, useState } from "react";
import ProductListing from "@/components/product/ProductListing";
import { discountPercent, fetchProducts, ShopProduct } from "@/lib/catalog";

export default function PromotionsPage() {
  const [products, setProducts] = useState<ShopProduct[] | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setError("");
    setProducts(null);
    fetchProducts()
      .then((all) => { if (active) setProducts(all.filter((p) => discountPercent(p.price, p.listPrice) > 0)); })
      .catch((e) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [attempt]);

  return (
    <div className="s-wrap s-page">
      <h1 className="s-page-title">Khuyến mãi đang diễn ra</h1>
      <p className="s-lead">
        Giá dưới đây đã gồm ưu đãi áp dụng cho mọi khách. Ưu đãi riêng (theo khu vực, đổi máy cũ, khách quen) được trợ lý
        hoặc nhân viên báo khi tư vấn.
      </p>
      <ProductListing products={products} error={error} onRetry={() => setAttempt((value) => value + 1)} empty="Hiện chưa có sản phẩm giảm giá." />
    </div>
  );
}
