"use client";
import { useEffect, useRef, useState } from "react";
import { shopContext } from "@/lib/shop-context";

// The home hero's small conversation: a customer asks, the assistant types and answers word by word, the next
// customer asks, and so on round the list. Every answer says only what the page already says (the store policy
// in TERMS on the home page, the AirPure Pro card in #tro-ly). It is a picture of the chat, not the chat: the whole
// card is one button that opens the real one. It pauses off screen and in a hidden tab; under reduced motion it
// shows the first two exchanges, still.
const SCRIPT: { q: string; a: string }[] = [
  {
    q: "Phòng 25m² nhà có bé nhỏ thì chọn máy lọc nào em?",
    a: "Dạ, AirPure Pro có khóa trẻ em, lọc HEPA H13 và hợp phòng đến 45m², kho còn hàng ạ.",
  },
  {
    q: "Đơn 2 triệu có được miễn phí giao không?",
    a: "Dạ có ạ, đơn từ 2.000.000₫ được giao miễn phí, nội thành 1–2 ngày làm việc.",
  },
  {
    q: "Máy lọc nước RO bảo hành bao lâu?",
    a: "Dạ máy lọc nước RO được bảo hành 36 tháng ạ.",
  },
  {
    q: "Mình trả tiền khi nhận hàng được không?",
    a: "Dạ được ạ, với đơn dưới 10.000.000₫. Mình cũng có thể chuyển khoản VietQR.",
  },
];
const KEEP = 4; // messages on the card at once: two exchanges

type Line = { id: number; who: "me" | "bot"; text: string; words?: number };

export default function HeroChat() {
  const [lines, setLines] = useState<Line[]>([]);
  const [typing, setTyping] = useState(false);
  const card = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const still =
      matchMedia("(prefers-reduced-motion: reduce)").matches ||
      document.documentElement.dataset.motion === "off";
    if (still) {
      setLines(
        SCRIPT.slice(0, 2).flatMap((s, i) => [
          { id: i * 2, who: "me" as const, text: s.q },
          { id: i * 2 + 1, who: "bot" as const, text: s.a },
        ]),
      );
      return;
    }
    let gone = false;
    let seen = true;
    const observer = new IntersectionObserver(([entry]) => {
      seen = entry.isIntersecting;
    });
    if (card.current) observer.observe(card.current);
    // waits ms of time the card is on screen in a visible tab
    const wait = (ms: number) =>
      new Promise<void>((done) => {
        let left = ms;
        const tick = () => {
          if (gone) return;
          if (seen && !document.hidden) left -= 100;
          if (left <= 0) done();
          else setTimeout(tick, 100);
        };
        setTimeout(tick, 100);
      });
    const push = (line: Line) => setLines((all) => [...all, line].slice(-KEEP));
    (async () => {
      let id = 0;
      await wait(900); // after the hero's own entrance
      for (let turn = 0; !gone; turn = (turn + 1) % SCRIPT.length) {
        const { q, a } = SCRIPT[turn];
        push({ id: id++, who: "me", text: q });
        await wait(700);
        setTyping(true);
        await wait(1100);
        if (gone) return;
        setTyping(false);
        const bot = id++;
        const words = a.split(" ");
        push({ id: bot, who: "bot", text: a, words: 0 });
        for (let n = 1; n <= words.length && !gone; n++) {
          await wait(60);
          setLines((all) =>
            all.map((l) => (l.id === bot ? { ...l, words: n } : l)),
          );
        }
        await wait(2800);
      }
    })();
    return () => {
      gone = true;
      observer.disconnect();
    };
  }, []);

  return (
    // The wrapper lifts on hover; the card inside settles with the hero's entrance (data-enter-media).
    <div ref={card} className="s-hero-chat-wrap">
      <div className="ui ui-panel ui-chat s-hero-chat" data-enter-media>
        <div className="ui-head" aria-hidden="true">
          <span className="ui-agent" />
          <div className="ui-title">Trợ lý Quivo</div>
          <span className="ui-chat__online">Trực tuyến</span>
          <span className="ui-spacer" />
        </div>
        <div className="ui-chat__body" aria-hidden="true">
          {lines.map((line) =>
            line.who === "me" ? (
              <div
                key={line.id}
                className="ui-msg ui-msg--me s-hero-msg s-hero-msg--me"
              >
                <span className="ui-msg__text">{line.text}</span>
              </div>
            ) : (
              <div key={line.id} className="ui-msg ui-msg--bot s-hero-msg">
                <span className="ui-agent ui-msg__av" />
                <span className="ui-msg__col">
                  <span className="ui-chat__answer">
                    {line.words === undefined
                      ? line.text
                      : line.text.split(" ").slice(0, line.words).join(" ")}
                  </span>
                </span>
              </div>
            ),
          )}
          {typing && (
            <div className="ui-msg ui-msg--bot s-hero-msg">
              <span className="ui-agent ui-msg__av" />
              <span className="s-hero-dots">
                <i />
                <i />
                <i />
              </span>
            </div>
          )}
        </div>
        <div className="ui-chat__input" aria-hidden="true">
          <span className="ui-chat__ph">Hỏi trợ lý ngay…</span>
          <span className="ui-chat__send">
            <svg viewBox="0 0 16 16" width="14" height="14">
              <path
                d="M8 13V3.5M3.8 7.5 8 3.3l4.2 4.2"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.7"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </span>
        </div>
        <button
          className="s-chat-preview-open"
          type="button"
          onClick={() => shopContext.openChat()}
          aria-label="Chat với trợ lý AI: hỏi giá, tồn kho, giao hàng và bảo hành"
        />
      </div>
    </div>
  );
}
