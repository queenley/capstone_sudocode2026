"use client";
import Link from "next/link";
import React from "react";
import { categoryName } from "@/lib/catalog";
import { HOTLINE } from "@/lib/contact";
import { shopContext } from "@/lib/shop-context";
import { MAIN_ACTION } from "@/components/shop/Header";
import HeroChat from "@/components/shop/HeroChat";
import Icon from "@/components/ui/Icon";

/*
  type: product (a shop selling physical goods online; site-kind other)
  deal: hero product (a stand-in photograph), nav nav-split, close close-type, footer footer-columns,
        rhythm brand-band, buttons pill, mark: Quivo's own logo; palette white-navy-tab (a white ground
        and an orange action read as a retail shelf and its price tags); type Work Sans (the dealt
        Besley / Albert Sans set no Vietnamese)
  moments: photo-chapters in #gia-dung (three rooms' appliances shown in the space of one)
  screens: hero 1 · #hang 1 · #tro-ly 1 · #gia-dung 3 · #me-be 1 · #mua-hang 1 (the terms beside the questions; 2 on a tablet and a phone) · close 1
  Every photograph on this page is a licensed stand-in (public/assets/img/credits.json, /products: the shop's
  catalogue photos from data/seed/catalog), listed on /anh and in the footer's credits line.
*/

const IMG = "/assets/img";

/** The range: a category, the catalogue photo that shows it, and how its card reads. */
const RANGE: { slug: string; picture: string; alt: string }[] = [
  { slug: "gia-dung/may-loc-khong-khi", picture: "/products/SKU-AP-X.jpg", alt: "Máy lọc không khí trắng đặt cạnh sofa" },
  { slug: "gia-dung/may-loc-nuoc", picture: "/products/SKU-WF-RO9.jpg", alt: "Vòi máy lọc nước đang rót vào cốc thủy tinh" },
  { slug: "gia-dung/noi-chien", picture: "/products/SKU-AF-XM.jpg", alt: "Lò chiên không dầu đang nướng bánh" },
  { slug: "gia-dung/quat", picture: "/products/SKU-FAN-SEN.jpg", alt: "Quạt đứng giữa đồ đạc trong một nhà kho" },
  { slug: "thoi-trang/giay", picture: "/products/SKU-SN-RUN2.jpg", alt: "Đôi giày chạy bộ màu xám dây đỏ đặt trên hộp giày" },
  { slug: "thoi-trang/ao-khoac", picture: "/products/SKU-JK-WND.jpg", alt: "Người phụ nữ mặc áo khoác gió đứng trên boong tàu" },
  { slug: "me-be", picture: "/products/SKU-MB-STR1.jpg", alt: "Ba chiếc xe đẩy em bé dựng cạnh bức tường đá" },
  { slug: "gia-dung/combo", picture: "/products/SKU-BDL-AIR.jpg", alt: "Mặt trên của máy lọc không khí với bảng điều khiển cảm ứng" },
];

// From the store policy (chinh-sach), version 10/2026, and the catalogue.
const TERMS: { name: string; line: string; value: string }[] = [
  { name: "Giao hàng", line: "Nội thành Hà Nội, TP.HCM, Đà Nẵng 1–2 ngày làm việc; tỉnh khác 2–4 ngày.", value: "Miễn phí từ 2.000.000₫" },
  { name: "Thanh toán", line: "Trả khi nhận hàng cho đơn dưới 10.000.000₫, hoặc chuyển khoản VietQR.", value: "Phí thu hộ 0₫" },
  { name: "Đổi trả", line: "Gia dụng và đồ mẹ bé lỗi kỹ thuật từ nhà sản xuất được đổi mới trong 30 ngày.", value: "7 ngày" },
  { name: "Bảo hành", line: "Máy lọc nước RO 36 tháng, máy lọc không khí đến 24 tháng.", value: "Đến 36 tháng" },
];

const QUESTIONS: { q: string; a: string }[] = [
  { q: "Trợ lý AI lấy giá ở đâu?", a: "Từ hệ thống bán hàng của Quivo, cùng nguồn với trang sản phẩm. Giá và tồn kho được xác nhận lại khi bạn đặt hàng." },
  { q: "Khi nào trợ lý chuyển tôi cho nhân viên?", a: "Khi bạn yêu cầu, hoặc khi trợ lý không chắc câu trả lời. Nhân viên nhận cuộc trò chuyện kèm những gì bạn đã nói." },
  { q: "Trợ lý có nhớ tôi ở lần sau không?", a: "Có, sau khi bạn xác minh số điện thoại: lần sau trợ lý nhớ nhu cầu và đơn hàng cũ. Bạn có thể yêu cầu xóa những gì trợ lý nhớ." },
  { q: "Tôi có gọi điện cho Quivo được không?", a: `Có. Gọi hotline ${HOTLINE}, hoặc bấm Gọi thoại trong khung chat để gọi qua web, không tốn cước.` },
];

const arrow = (
  <svg className="m-arrow" viewBox="0 0 12 12" aria-hidden="true"><path className="m-arrow__stem" d="M1 6h8" /><path className="m-arrow__head" d="M4.5 2.5 8 6l-3.5 3.5" /></svg>
);

function Tile({ slug, picture, alt }: { slug: string; picture: string; alt: string }) {
  return (
    <Link className="tile span-3 m-zoom" href={`/danh-muc/${slug}`}>
      <div className="tile__media"><img src={picture} alt={alt} width={900} height={600} decoding="async" /></div>
      <div className="tile__head"><h3>{categoryName(slug)}</h3></div>
    </Link>
  );
}

export default function HomePage() {
  return (
    <>
      {/* The photograph is the ground, a gradient over its left for the words (shop.css, "the home hero"),
          and the assistant's small conversation on the right (HeroChat: one button that opens the chat). */}
      <section className="hero s-hero" data-enter aria-labelledby="hero-h">
        <img
          className="hero__bg"
          src={`${IMG}/photo-f107853503.webp`}
          srcSet={`${IMG}/photo-f107853503-960.webp 960w, ${IMG}/photo-f107853503-1280.webp 1280w, ${IMG}/photo-f107853503.webp 1920w`}
          sizes="100vw" width={1920} height={1444}
          alt="Máy lọc không khí bọc vải xám đặt sát tường trong một căn phòng sáng"
          style={{ "--ly-pos": "50% 62%" } as React.CSSProperties}
          fetchPriority="high" decoding="async" data-source="stand-in" data-subject="air purifier"
        />
        <div className="s-hero__shade" aria-hidden="true" />
        <div className="wrap">
          <div className="s-hero__grid">
            <div className="s-hero__copy">
              <h1 id="hero-h">Gia dụng, thời trang và đồ mẹ bé</h1>
              <p className="hero__lead">Trợ lý AI báo giá, tồn kho và khuyến mãi lấy thẳng từ cửa hàng, cả đêm. Giao miễn phí cho đơn từ 2.000.000₫.</p>
              <div className="btn-row">
                <button className="btn btn--primary" type="button" onClick={() => shopContext.openChat()}>{MAIN_ACTION}{arrow}</button>
                <Link className="btn btn--secondary" href="/danh-muc/gia-dung/may-loc-khong-khi">Xem máy lọc không khí</Link>
              </div>
            </div>
            <HeroChat />
          </div>
        </div>
      </section>

      <section className="section" id="hang" aria-labelledby="hang-h">
        <div className="wrap">
          <div className="section-head section-head--split">
            <div>
              <h2 id="hang-h">Hàng đang bán. <span className="muted">Giá và tồn kho theo kho của cửa hàng.</span></h2>
            </div>
            <Link className="link" href="/khuyen-mai">Xem hàng đang giảm giá</Link>
          </div>
          <div className="grid">{RANGE.map((item) => <Tile key={item.slug} {...item} />)}</div>
        </div>
      </section>

      <section className="section" id="tro-ly" aria-labelledby="tro-ly-h">
        <div className="wrap">
          <div className="section-head">
            <h2 id="tro-ly-h">Trợ lý trả lời bằng dữ liệu của cửa hàng</h2>
          </div>
          <div className="grid fill">
            <div className="split-col span-5">
              <p className="t-lead">Bạn hỏi bằng lời của mình. Trợ lý tra catalogue, kho và khuyến mãi rồi mới trả lời, và nói rõ khi chưa chắc.</p>
              {/* Each row's icon in a tinted round tile (shop.css, "rows with icons"). */}
              <ul className="rows s-rows-icons">
                <li><span className="s-row-icon"><Icon name="sparkles" size={20} /></span><span className="rows__name">Tư vấn theo nhu cầu</span><p>Diện tích phòng, tuổi của bé, cỡ giày: trợ lý hỏi lại cho đủ rồi mới gợi ý.</p></li>
                <li><span className="s-row-icon"><Icon name="cart" size={20} /></span><span className="rows__name">Đặt hàng trong khung chat</span><p>Thêm vào giỏ, xác minh số điện thoại và đặt mà không rời trang.</p></li>
                <li><span className="s-row-icon"><Icon name="headset" size={20} /></span><span className="rows__name">Chuyển cho nhân viên</span><p>Khi bạn muốn nói với người thật, nhân viên nhận cả cuộc trò chuyện.</p></li>
              </ul>
            </div>
            <div className="frame frame--fill span-6 q-col-7">
                  <div className="ui ui-panel ui-chat s-chat-preview" data-ui="chat">
                    {/* A picture of a conversation, and one button over it that opens the real chat. */}
                    <button className="s-chat-preview-open" type="button" onClick={() => shopContext.openChat()}
                      aria-label="Ví dụ: khách hỏi máy lọc cho phòng 25 mét vuông có bé nhỏ, trợ lý gợi ý AirPure Pro. Bấm để chat với trợ lý" />
                    <div className="ui-head" aria-hidden="true">
                      <span className="ui-agent" aria-hidden="true"></span>
                      <div className="ui-title">Trợ lý Quivo</div>
                      <span className="ui-chat__online">Trực tuyến</span>
                      <span className="ui-spacer"></span>
                    </div>
                    <div className="ui-chat__body" aria-hidden="true">
                      <div className="ui-msg ui-msg--me"><span className="ui-msg__text">Phòng 25m², nhà có bé nhỏ thì nên chọn máy lọc nào?</span></div>
                      <div className="ui-msg ui-msg--bot">
                        <span className="ui-agent ui-msg__av" aria-hidden="true"></span>
                        <span className="ui-msg__col">
                          <span className="ui-chat__answer">Dạ, AirPure Pro có <b>khóa trẻ em</b>, lọc HEPA H13 và hợp với phòng đến 45m². Giá niêm yết 7.990.000₫, kho còn hàng ạ.</span>
                          <span className="ui-chat__srcs">
                            <span className="ui-chat__src"><svg className="ui-icon" viewBox="0 0 16 16"><path d="M4 2.5h5l3 3v8H4z" /><path d="M9 2.5v3h3" /></svg>Máy lọc không khí AirPure Pro</span>
                          </span>
                        </span>
                      </div>
                      <div className="ui-msg ui-msg--me"><span className="ui-msg__text">Thêm vào giỏ giúp mình nhé.</span></div>
                    </div>
                    <div className="ui-chat__input" aria-hidden="true">
                      <span className="ui-chat__ph">Nhập tin nhắn</span>
                      <span className="ui-chat__send" aria-hidden="true"><svg viewBox="0 0 16 16" width="14" height="14"><path d="M8 13V3.5M3.8 7.5 8 3.3l4.2 4.2" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg></span>
                    </div>
                  </div>
            </div>
          </div>
        </div>
      </section>


      <section className="section" id="gia-dung" data-moment="photo-chapters" aria-labelledby="gia-dung-h">
        <div className="wrap mo-ph">
          <div className="mo-ph__head">
            <h2 id="gia-dung-h">Gia dụng cho không khí, nước và bếp</h2>
            <p>Máy và cả bộ lọc, lõi lọc thay thế, bán cùng một chỗ.</p>
          </div>
          <ol className="mo-ph__list">
            <li className="mo-ph__ch">
              <figure className="mo-ph__pic"><img src={`${IMG}/photo-f128819374.webp`} srcSet={`${IMG}/photo-f128819374-960.webp 960w, ${IMG}/photo-f128819374.webp 1280w`} sizes="(max-width: 639px) 240vw, 1280px" alt="Cánh quạt bên trong một máy lọc không khí màu trắng" width={1280} height={853} loading="lazy" decoding="async" /></figure>
              <h3>Máy lọc không khí</h3>
              <p>Từ phòng ngủ đến phòng khách 45m², lọc HEPA, bảo hành đến 24 tháng. Màng lọc thay thế có sẵn.</p>
            </li>
            <li className="mo-ph__ch">
              <figure className="mo-ph__pic"><img src={`${IMG}/photo-f136522144.webp`} srcSet={`${IMG}/photo-f136522144-960.webp 960w, ${IMG}/photo-f136522144.webp 1280w`} sizes="(max-width: 639px) 240vw, 1280px" alt="Hai vòi nước nóng và lạnh của một máy lọc nước" width={1280} height={853} loading="lazy" decoding="async" /></figure>
              <h3>Máy lọc nước</h3>
              <p>Máy lọc RO 9 và 10 lõi, bảo hành 36 tháng. Lõi lọc thay định kỳ đặt được ngay trong khung chat.</p>
            </li>
            <li className="mo-ph__ch">
              <figure className="mo-ph__pic"><img src={`${IMG}/photo-f121715176-1440.webp`} srcSet={`${IMG}/photo-f121715176-960.webp 960w, ${IMG}/photo-f121715176-1440.webp 1440w`} sizes="(max-width: 639px) 240vw, 1280px" alt="Ba củ khoai tây nướng trong rổ của nồi chiên không dầu" width={1440} height={1374} loading="lazy" decoding="async" /></figure>
              <h3>Nồi chiên không dầu</h3>
              <p>Loại 4 lít cho hai người và 6,2 lít cho cả nhà, bảo hành 12 tháng.</p>
            </li>
          </ol>
        </div>
      </section>

      <section className="section ground-brand" id="me-be" aria-labelledby="me-be-h">
        <div className="wrap">
          <div className="section-head">
            <h2 id="me-be-h">Đồ cho bé và giày cho cả nhà</h2>
          </div>
          <div className="grid fill">
            <Link className="tile span-6 m-zoom" href="/danh-muc/me-be">
              <div className="tile__media"><img src={`${IMG}/photo-f131628124.webp`} srcSet={`${IMG}/photo-f131628124-500.webp 500w, ${IMG}/photo-f131628124-960.webp 960w, ${IMG}/photo-f131628124.webp 1280w`} sizes="(max-width: 1023px) 100vw, 628px" alt="Một người đẩy xe nôi trên con phố vắng lúc chiều" width={1280} height={854} loading="lazy" decoding="async" /></div>
              <div className="tile__head"><h3>Xe đẩy, máy hút sữa, bình sữa và ghế ô tô</h3></div>
              <p>Joie, Combi, Spectra, Medela, Pigeon, Chicco. Lỗi kỹ thuật được đổi mới trong 30 ngày.</p>
            </Link>
            <Link className="tile span-6 m-zoom" href="/danh-muc/thoi-trang">
              <div className="tile__media"><img src={`${IMG}/photo-f184936789.webp`} srcSet={`${IMG}/photo-f184936789-500.webp 500w, ${IMG}/photo-f184936789-960.webp 960w, ${IMG}/photo-f184936789.webp 1280w`} sizes="(max-width: 1023px) 100vw, 628px" alt="Đôi giày vải trắng buộc dây đặt trên nền đá" width={1280} height={960} loading="lazy" decoding="async" /></div>
              <div className="tile__head"><h3>Giày chạy bộ, giày đi phố và áo khoác</h3></div>
              <p>Chưa chắc cỡ thì hỏi trợ lý trước khi đặt. Đổi trả trong 7 ngày.</p>
            </Link>
          </div>
        </div>
      </section>

      <section className="section" id="mua-hang" aria-labelledby="mua-hang-h">
        <div className="wrap">
          <div className="section-head section-head--split">
            <div><h2 id="mua-hang-h">Giao hàng, đổi trả và câu hỏi về Quivo</h2></div>
            <Link className="link" href="/chinh-sach">Đọc chính sách đầy đủ</Link>
          </div>
          <div className="grid grid--top">
            <ul className="rows rows--spec span-6">
              {TERMS.map((term) => (
                <li key={term.name}><span className="rows__name">{term.name}</span><p>{term.line}</p><span className="rows__value">{term.value}</span></li>
              ))}
            </ul>
            <div className="faq span-6 q-col-7">
            {QUESTIONS.map((item) => (
              <div className="faq__item" key={item.q}><h3>{item.q}</h3><p>{item.a}</p></div>
            ))}
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
