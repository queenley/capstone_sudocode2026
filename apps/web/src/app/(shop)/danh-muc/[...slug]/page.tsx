"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import ProductListing from "@/components/product/ProductListing";
import { categoryName, DEPARTMENTS, fetchProducts, ShopProduct } from "@/lib/catalog";

export default function CategoryPage() {
  const params = useParams<{ slug: string[] }>();
  const slug = (params.slug || []).map(decodeURIComponent).join("/");
  const department = DEPARTMENTS.find((d) => slug === d.slug || slug.startsWith(d.slug + "/"));
  const [products, setProducts] = useState<ShopProduct[] | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setError("");
    setProducts(null);
    fetchProducts({ category: slug })
      .then((products) => { if (active) setProducts(products); })
      .catch((e) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [slug, attempt]);

  return (
    <div className="s-wrap s-page">
      <nav className="s-crumbs" aria-label="Đường dẫn">
        <Link href="/">Trang chủ</Link>
        {department && department.slug !== slug && (
          <>
            <span>/</span>
            <Link href={`/danh-muc/${department.slug}`}>{categoryName(department.slug)}</Link>
          </>
        )}
        <span>/</span>
        <span>{categoryName(slug)}</span>
      </nav>
      <h1 className="s-page-title">{categoryName(slug)}</h1>
      {department && department.children.length > 0 && (
        <div className="s-subcats">
          {department.children.map((child) => (
            <Link key={child} href={`/danh-muc/${child}`} className={`s-pill ${child === slug ? "active" : ""}`}>
              {categoryName(child)}
            </Link>
          ))}
        </div>
      )}
      <ProductListing products={products} error={error} onRetry={() => setAttempt((value) => value + 1)} empty="Danh mục này chưa có sản phẩm." />
    </div>
  );
}
