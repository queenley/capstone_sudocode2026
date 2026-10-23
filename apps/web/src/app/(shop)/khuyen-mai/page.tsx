"use client";
import { useEffect, useState } from "react";
import ProductListing from "@/components/product/ProductListing";
import { discountPercent, fetchProducts, ShopProduct } from "@/lib/catalog";

export default function PromotionsPage() {
  const [products, setProducts] = useState<ShopProduct[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchProducts()
      .then((all) => setProducts(all.filter((p) => discountPercent(p.price, p.listPrice) > 0)))
      .catch((e) => setError(e.message));
  }, []);

  return (
    <div className="s-wrap s-page">
      <h1 className="s-page-title">Khuyến mãi đang diễn ra</h1>
      <p className="s-lead">
        Giá dưới đây đã gồm ưu đãi áp dụng cho mọi khách. Ưu đãi riêng (theo khu vực, đổi máy cũ, khách quen) được trợ lý
        hoặc nhân viên báo khi tư vấn.
      </p>
      {error && <div className="s-alert">Không tải được: {error}</div>}
      <ProductListing products={products} empty="Hiện chưa có sản phẩm giảm giá." />
    </div>
  );
}
