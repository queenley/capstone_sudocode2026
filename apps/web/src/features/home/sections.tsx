"use client";
import Link from "next/link";
import React from "react";
import { categoryName } from "@/lib/catalog";
import { shopContext } from "@/lib/shop-context";
import { MAIN_ACTION } from "@/components/shop/Header";
import HeroChat from "@/components/shop/HeroChat";
import Icon from "@/components/ui/Icon";
import { ASSIST, IMG, QUESTIONS, RANGE, TERMS } from "./content";

// The home page's sections, in page order (app/(shop)/page.tsx). Each is one screen at 1440x900.

const arrow = (
  <svg className="m-arrow" viewBox="0 0 12 12" aria-hidden="true"><path className="m-arrow__stem" d="M1 6h8" /><path className="m-arrow__head" d="M4.5 2.5 8 6l-3.5 3.5" /></svg>
);

/** The photograph is the ground, a gradient over its left for the words (shop.css, "the home hero"),
    and the assistant's small conversation on the right (HeroChat: one button that opens the chat). */
export function HomeHero() {
  return (
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
  );
}

function Tile({ slug, picture, alt }: { slug: string; picture: string; alt: string }) {
  return (
    <Link className="tile span-3 m-zoom" href={`/danh-muc/${slug}`}>
      <div className="tile__media"><img src={picture} alt={alt} width={900} height={600} decoding="async" /></div>
      <div className="tile__head"><h3>{categoryName(slug)}</h3></div>
    </Link>
  );
}

export function RangeSection() {
  return (
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
  );
}

/** A picture of a conversation, and one button over it that opens the real chat. */
function ChatPreview() {
  return (
    <div className="ui ui-panel ui-chat s-chat-preview" data-ui="chat">
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
  );
}

export function AssistantSection() {
  return (
    <section className="section" id="tro-ly" aria-labelledby="tro-ly-h">
      <div className="wrap">
        <div className="section-head">
          <h2 id="tro-ly-h">Trợ lý trả lời bằng dữ liệu của cửa hàng</h2>
        </div>
        <div className="grid fill s-tro-ly">
          <div className="split-col span-5">
            <p className="t-lead">Bạn hỏi bằng lời của mình. Trợ lý tra catalogue, kho và khuyến mãi rồi mới trả lời, và nói rõ khi chưa chắc.</p>
            {/* Each row's icon in a tinted round tile (shop.css, "rows with icons"). */}
            <ul className="rows s-rows-icons">
              {ASSIST.map((row) => (
                <li key={row.name}><span className="s-row-icon"><Icon name={row.icon} size={20} /></span><span className="rows__name">{row.name}</span><p>{row.line}</p></li>
              ))}
            </ul>
          </div>
          <div className="frame span-6 q-col-7 s-tro-ly__frame"><ChatPreview /></div>
        </div>
      </div>
    </section>
  );
}

/** The two smaller departments on the brand band: a photograph each, linked to its listing. */
export function FamilySection() {
  return (
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
  );
}

export function TermsSection() {
  return (
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
  );
}
