"use client";
// The products an assistant message names, as small cards under it: the
// picture, then the name, the price and a link to the product page. Links
// are paths on this site ("/san-pham/<ref>"), so they hold on any domain.
import Link from "next/link";
import { useEffect, useState } from "react";
import ProductArt from "@/components/product/ProductArt";
import { discountPercent, money, ShopProduct } from "@/lib/catalog";
import { catalogOnce, productMentions } from "@/lib/mentions";

/** *onShow* runs once the cards appear, after the catalogue arrives: the chat scrolls to keep them in view. */
export default function ChatProducts({ text, onShow }: { text: string; onShow?: () => void }) {
  const [products, setProducts] = useState<ShopProduct[]>([]);
  useEffect(() => {
    let live = true;
    catalogOnce()
      .then((all) => live && setProducts(all))
      .catch(() => undefined); // no cards is fine: the text still says it
    return () => {
      live = false;
    };
  }, []);

  const named = productMentions(text, products);
  useEffect(() => {
    if (named.length) onShow?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [named.length]);
  if (!named.length) return null;
  return (
    <div className="s-msg-products" aria-label="Sản phẩm được nhắc tới">
      {named.map((product) => {
        const off = discountPercent(product.price, product.listPrice);
        return (
          <Link key={product.ref} href={`/san-pham/${encodeURIComponent(product.ref)}`} className="s-msg-product">
            <ProductArt category={product.category} brand={product.brand} size="thumb" />
            <span className="s-msg-product-name">{product.name}</span>
            <span className="s-msg-product-price">
              {product.variants.length > 1 && <small>Từ </small>}
              {money(product.price)}
              {off > 0 && <s>{money(product.listPrice)}</s>}
            </span>
            <span className="s-msg-product-link">{product.available > 0 ? "Xem sản phẩm →" : "Hết hàng · xem →"}</span>
          </Link>
        );
      })}
    </div>
  );
}
