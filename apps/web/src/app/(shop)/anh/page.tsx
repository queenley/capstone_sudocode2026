"use client";
import React, { useEffect, useState } from "react";
import { fetchProducts, ShopProduct } from "@/lib/catalog";

// Who made the photographs the shop shows and under which licence: the footer's one credits line opens
// this list (CC BY and CC BY-SA ask for the credit; taste-skill puts it here, never under a picture).
// The home page's photographs are listed by taste-skill's photos.mjs in public/assets/img/credits.json;
// the products' come with the catalogue (data/seed/catalog/product_images.json, image_credit).

/** The home page's photographs, by their photos.mjs id. */
const HOME = ["f107853503", "f128819374", "f136522144", "f121715176", "f131628124", "f184936789"];

type Found = { id: string; alt: string; by: string; licence: string; licenceUrl: string; page: string; source: string };

export default function CreditsPage() {
  const [home, setHome] = useState<Found[]>([]);
  const [products, setProducts] = useState<ShopProduct[] | null>(null);

  useEffect(() => {
    fetch("/assets/img/credits.json")
      .then((response) => response.json())
      .then((data: { photos: Found[] }) => setHome(data.photos.filter((photo) => HOME.includes(photo.id))))
      .catch(() => setHome([]));
    fetchProducts().then(setProducts).catch(() => setProducts([]));
  }, []);

  const credited = (products || []).filter((product) => product.image && product.imageCredit);

  return (
    <div className="s-wrap s-section">
      <h1>Nguồn ảnh</h1>
      <p className="s-muted">Ảnh trên trang minh họa loại hàng, không phải ảnh của đúng mẫu đang bán. Mỗi ảnh dùng theo giấy phép ghi bên cạnh.</p>
      <h2>Trang chủ</h2>
      <ul className="s-credits">
        {home.map((photo) => (
          <li key={photo.id}>
            <a href={photo.page} target="_blank" rel="noreferrer">{photo.alt}</a>, {photo.by},{" "}
            <a href={photo.licenceUrl} target="_blank" rel="noreferrer">{photo.licence}</a>, qua {photo.source}
          </li>
        ))}
      </ul>
      <h2>Sản phẩm</h2>
      {products === null ? <p role="status">Đang tải…</p> : (
        <ul className="s-credits">
          {credited.map((product) => {
            const credit = product.imageCredit!;
            return (
              <li key={product.ref}>
                {product.name}: <a href={credit.source_url} target="_blank" rel="noreferrer">{credit.title || "ảnh"}</a>, {credit.author},{" "}
                <a href={credit.license_url} target="_blank" rel="noreferrer">{credit.license}</a>, qua {credit.provider}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
