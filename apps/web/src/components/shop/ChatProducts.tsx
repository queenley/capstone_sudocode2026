"use client";
// The products an assistant message names, as small cards under it: the
// picture, then the name, the price and a link to the product page. A product
// with one variant in stock can go to the cart from here. Links are paths on
// this site ("/san-pham/<ref>"), so they hold on any domain.
import Link from "next/link";
import { useEffect, useState } from "react";
import ProductArt from "@/components/product/ProductArt";
import { discountPercent, money, ShopProduct } from "@/lib/catalog";
import { cart } from "@/lib/cart";
import { catalogOnce, newMentions } from "@/lib/mentions";

/** *onShow* runs once the cards appear, after the catalogue arrives: the chat scrolls to keep them in view.
 *  *earlier*: the assistant's messages above this one. A product already shown under one of them gets no second
 *  card: its card is up there, and the same card under every reply that names it again only fills the chat. */
export default function ChatProducts({
  text,
  earlier = [],
  onShow,
}: {
  text: string;
  earlier?: string[];
  onShow?: () => void;
}) {
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

  const named = newMentions(text, earlier, products);
  useEffect(() => {
    if (named.length) onShow?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [named.length]);
  if (!named.length) return null;
  return (
    <div className="s-msg-products" aria-label="Sản phẩm được nhắc tới">
      {named.map((product) => (
        <ChatProduct key={product.ref} product={product} />
      ))}
    </div>
  );
}

function ChatProduct({ product }: { product: ShopProduct }) {
  const [added, setAdded] = useState(0);
  const off = discountPercent(product.price, product.listPrice);
  const single = product.variants.length === 1 && product.available > 0 ? product.variants[0] : null;
  return (
    <div className="s-msg-product">
      <Link href={`/san-pham/${encodeURIComponent(product.ref)}`} className="s-msg-product-main">
        <ProductArt category={product.category} brand={product.brand} size="thumb" image={product.image} alt={product.name} />
        <span className="s-msg-product-name">{product.name}</span>
        <span className="s-msg-product-price">
          {product.variants.length > 1 && <small>Từ </small>}
          {money(product.price)}
          {off > 0 && <s>{money(product.listPrice)}</s>}
        </span>
        {!single && <span className="s-msg-product-link">{product.available > 0 ? "Chọn phân loại →" : "Hết hàng · xem →"}</span>}
      </Link>
      {single &&
        (added > 0 ? (
          <p className="s-msg-product-done" role="status">
            <Link className="s-msg-product-link" href="/gio-hang">
              Đã thêm {added} · Xem giỏ →
            </Link>
          </p>
        ) : (
          <button
            className="s-btn s-btn-ghost s-msg-product-add"
            aria-label={`Thêm ${product.name} vào giỏ`}
            onClick={() => {
              cart.add(single.sku_code);
              setAdded((value) => value + 1);
            }}
          >
            Thêm vào giỏ
          </button>
        ))}
    </div>
  );
}
