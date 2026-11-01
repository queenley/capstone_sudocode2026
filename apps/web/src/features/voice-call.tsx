"use client";
// A voice call to the shop's hotline, on the customer's current conversation.
//
// The call object (VoiceCall) is created by the page in the click that places
// the call; this component connects it and draws it: who is talking, what the
// assistant is doing, a microphone meter, the running transcript with each
// answer's time to first audio, and mute / hang up.
import { useEffect, useRef, useState } from "react";
import {
  CaptureProfile,
  CaptureSettings,
  VoiceCall,
  VoiceMessage,
} from "@/services/voice";

type Line = {
  id: string;
  who: "caller" | "agent" | "note";
  text: string;
  heard?: string;
  superseded?: boolean;
  ttfaMs?: number;
};
type Input = {
  level: number;
  speech_score: number;
  speech: number;
  turns: number;
};

const CAPTION: Record<string, string> = {
  connecting: "Đang kết nối…",
  loading: "Đang chuẩn bị đường dây…",
  listening: "Đang nghe",
  user: "Đang nghe bạn nói",
  thinking: "Đang suy nghĩ…",
  speaking: "Đang trả lời",
  ended: "Cuộc gọi đã kết thúc",
};

const CLOSE_REASON: Record<number, string> = {
  4404: "Phiên trò chuyện không hợp lệ. Hãy tạo phiên mới rồi gọi lại.",
  4409: "Phiên đang do nhân viên xử lý hoặc đã đóng.",
  1011: "Đường dây đang gặp sự cố. Vui lòng thử lại sau ít phút hoặc nhắn tin cho cửa hàng.",
  1006: "Cuộc gọi bị mất kết nối. Kiểm tra kết nối mạng rồi gọi lại, hoặc nhắn tin cho cửa hàng.",
};

export default function VoiceCallPanel({
  call,
  conversationId,
  token,
  onClose,
}: {
  call: VoiceCall;
  conversationId: string;
  token: string;
  onClose: () => void;
}) {
  const [state, setState] = useState("connecting");
  const [lines, setLines] = useState<Line[]>([]);
  const [error, setError] = useState("");
  const [muted, setMuted] = useState(false);
  const [paused, setPaused] = useState(false);
  const [input, setInput] = useState<Input | null>(null);
  const [mic, setMic] = useState<{ id: string; label: string } | null>(null);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [capture, setCapture] = useState<CaptureSettings>(() =>
    call.captureSettings(),
  );
  const [changingCapture, setChangingCapture] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const startedAt = useRef<number | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const panel = dialog.current!;
    panel.showModal();
    return () => panel.close();
  }, []);

  useEffect(() => {
    call
      .connect(conversationId, token, (m: VoiceMessage) => {
        switch (m.type) {
          case "state":
            setMic((current) => current || call.microphone());
            setState(String(m.state));
            if (m.state === "listening" && startedAt.current == null)
              startedAt.current = Date.now();
            break;
          case "pause":
            setPaused(true);
            break;
          case "resume":
          case "stop":
            setPaused(false);
            break;
          case "input":
            setInput(m as unknown as Input);
            break;
          case "capture_settings":
            setCapture(m as unknown as CaptureSettings);
            break;
          case "transcript":
            setLines((all) => [
              ...all,
              { id: `${m.turn}-caller`, who: "caller", text: String(m.text) },
            ]);
            break;
          case "reply":
            if (m.waiting)
              setLines((all) => [
                ...all,
                {
                  id: `${m.turn}-wait`,
                  who: "note",
                  text: "Nhân viên tư vấn đang nhận cuộc gọi.",
                },
              ]);
            else if (m.text)
              setLines((all) => [
                ...all,
                {
                  id: `${m.turn}-agent`,
                  who: "agent",
                  text: String(m.text),
                  superseded: Boolean(m.superseded),
                },
              ]);
            break;
          case "truncated":
            setLines((all) =>
              all.map((l) =>
                l.id === `${m.turn}-agent`
                  ? { ...l, heard: String(m.heard) }
                  : l,
              ),
            );
            break;
          case "metrics":
            if (typeof m.ttfa_ms === "number")
              setLines((all) =>
                all.map((l) =>
                  l.id === `${m.turn}-agent`
                    ? { ...l, ttfaMs: Number(m.ttfa_ms) }
                    : l,
                ),
              );
            break;
          case "error":
            setError(String(m.text));
            break;
          case "closed":
            setState("ended");
            if (typeof m.code === "number" && CLOSE_REASON[m.code])
              setError((e) => e || CLOSE_REASON[m.code as number]);
            break;
        }
      })
      .catch((err: unknown) => {
        call.stop();
        const name = err instanceof DOMException ? err.name : "";
        setError(
          name === "NotAllowedError"
            ? "Trình duyệt chưa cho phép dùng micro. Hãy cho phép rồi gọi lại."
            : err instanceof Error
              ? err.message
              : String(err),
        );
        setState("ended");
      });
  }, [call, conversationId, token]);

  useEffect(() => {
    if (mic)
      call
        .microphones()
        .then(setDevices)
        .catch(() => setDevices([]));
  }, [mic, call]);

  useEffect(() => {
    const timer = setInterval(() => {
      if (startedAt.current != null && state !== "ended")
        setSeconds(Math.floor((Date.now() - startedAt.current) / 1000));
    }, 500);
    return () => clearInterval(timer);
  }, [state]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "nearest" });
  }, [lines]);

  const live = state !== "ended";
  const micLevel = useLevel(live ? call.micAnalyser : null);
  const agentLevel = useLevel(live ? call.agentAnalyser : null);
  const callerTalking = state === "user" || paused;
  const level = callerTalking
    ? micLevel
    : state === "speaking"
      ? agentLevel
      : 0;
  const hint = !input
    ? null
    : input.level < 0.002
      ? "Gần như không có âm thanh tới đường dây. Kiểm tra micro có bị tắt không."
      : input.speech_score < 0.5 && input.speech === 0
        ? "Có âm thanh nhưng chưa giống giọng nói. Hãy nói gần micro hơn."
        : null;

  return (
    <dialog ref={dialog} className="voice-dialog" aria-label="Cuộc gọi thoại" onCancel={(event) => {
      event.preventDefault();
      call.hangUp();
      onClose();
    }}>
      <section className="modal call-panel">
        <header className="call-top">
          <div className={"call-avatar " + (live ? "live" : "")}>☏</div>
          <div>
            <p className="eyebrow">HOTLINE CỬA HÀNG</p>
            <h2>Tư vấn qua cuộc gọi</h2>
            <span className="call-clock">
              {!live
                ? `Đã kết thúc · ${clock(seconds)}`
                : startedAt.current == null
                  ? "Đang gọi…"
                  : clock(seconds)}
            </span>
          </div>
        </header>

        <div
          className={"call-bars " + (callerTalking ? "caller" : "agent")}
          aria-hidden="true"
        >
          {Array.from({ length: 9 }, (_, i) => (
            <span
              key={i}
              style={{
                height: `${Math.min(100, 12 + level * (2600 - Math.abs(4 - i) * 380))}%`,
              }}
              className={state === "thinking" ? "pulse" : ""}
            />
          ))}
        </div>
        <p className="call-caption" aria-live="polite">
          {live
            ? paused
              ? CAPTION.user
              : CAPTION[state] || CAPTION.listening
            : CAPTION.ended}
        </p>

        {live && (
          <div className="call-mic">
            <div className="meter">
              <i style={{ width: `${Math.min(100, micLevel * 600)}%` }} />
            </div>
            <div className="call-mic-row">
              <label>
                Chế độ micro
                <select
                  aria-label="Chế độ micro"
                  value={capture.profile}
                  disabled={changingCapture}
                  onChange={async (event) => {
                    setChangingCapture(true);
                    setError("");
                    try {
                      await call.setCaptureProfile(
                        event.target.value as CaptureProfile,
                      );
                    } catch (error) {
                      setError(
                        error instanceof Error
                          ? error.message
                          : "Không đổi được chế độ micro.",
                      );
                    } finally {
                      setChangingCapture(false);
                    }
                  }}
                >
                  <option value="standard">Lọc ồn tiêu chuẩn</option>
                  <option value="barge-in">
                    Ưu tiên nghe khi loa đang phát
                  </option>
                </select>
              </label>
              <span>{mic ? mic.label : "Đang mở micro…"}</span>
              {devices.length > 1 && (
                <select
                  aria-label="Micro"
                  value={mic?.id || ""}
                  onChange={async (e) => {
                    await call.useMicrophone(e.target.value);
                    setMic(call.microphone());
                  }}
                >
                  {devices.map((d) => (
                    <option key={d.deviceId} value={d.deviceId}>
                      {d.label || "Micro"}
                    </option>
                  ))}
                </select>
              )}
            </div>
            {hint && <p className="hint">{hint}</p>}
            <p className="hint">
              Chế độ ưu tiên giữ khử tiếng vọng và tắt lọc ồn tự động nếu trình
              duyệt hỗ trợ. Hãy dùng khi loa làm giọng bạn bị nhỏ đi.
            </p>
          </div>
        )}

        {error && (
          <div className="alert" role="alert">
            {error}
          </div>
        )}

        <div className="call-transcript">
          {lines.length === 0 && (
            <p className="empty">Nội dung cuộc gọi sẽ hiện ở đây.</p>
          )}
          {lines.map((line) =>
            line.who === "note" ? (
              <p className="call-note" key={line.id}>
                {line.text}
              </p>
            ) : (
              <div
                key={line.id}
                className={
                  "message " + (line.who === "caller" ? "outgoing" : "incoming")
                }
              >
                <small>{line.who === "caller" ? "BẠN" : "TRỢ LÝ AI"}</small>
                <p className={line.superseded ? "faded" : ""}>
                  {line.heard != null ? line.heard : line.text}
                  {line.heard != null && line.text.startsWith(line.heard) && (
                    <span className="faded">
                      {line.text.slice(line.heard.length)}
                    </span>
                  )}
                </p>
                {(line.ttfaMs != null ||
                  line.heard != null ||
                  line.superseded) && (
                  <small className="call-meta">
                    {line.superseded
                      ? "Không đọc: bạn đã hỏi điều khác."
                      : line.heard != null
                        ? "Bạn đã ngắt lời; chỉ giữ phần đã nghe."
                        : `Âm thanh đầu sau ${(line.ttfaMs! / 1000).toFixed(1)} s`}
                  </small>
                )}
              </div>
            ),
          )}
          <div ref={bottom} />
        </div>

        <footer className="call-controls">
          {live ? (
            <>
              <button
                className="secondary"
                aria-pressed={muted}
                onClick={() => {
                  call.setMuted(!muted);
                  setMuted(!muted);
                }}
              >
                {muted ? "Bật micro" : "Tắt micro"}
              </button>
              <button
                className="hangup"
                onClick={() => {
                  call.hangUp();
                  setState("ended");
                }}
              >
                Gác máy
              </button>
            </>
          ) : (
            <button onClick={onClose}>Đóng</button>
          )}
        </footer>
      </section>
    </dialog>
  );
}

function useLevel(analyser: AnalyserNode | null): number {
  const [level, setLevel] = useState(0);
  useEffect(() => {
    if (!analyser) {
      setLevel(0);
      return undefined;
    }
    const data = new Float32Array(analyser.fftSize);
    let frame = 0;
    let last = 0;
    const tick = (time: number) => {
      if (time - last > 60) {
        analyser.getFloatTimeDomainData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
        setLevel(Math.sqrt(sum / data.length));
        last = time;
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [analyser]);
  return level;
}

function clock(total: number) {
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}
