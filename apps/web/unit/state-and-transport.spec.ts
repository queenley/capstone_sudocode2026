import { test, expect } from "@playwright/test";
import { cart } from "../src/lib/cart";
import { api, streamTurn } from "../src/services/api";
import { forgetConversation, openSession } from "../src/lib/session";
import { VoiceCall } from "../src/services/voice";
import { NextRequest } from "next/server";
import { PATCH, POST } from "../src/app/backend/[...path]/route";

class MemoryStorage {
  data = new Map<string, string>();
  getItem(key: string) {
    return this.data.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.data.set(key, String(value));
  }
  removeItem(key: string) {
    this.data.delete(key);
  }
  clear() {
    this.data.clear();
  }
}
const nativeFetch = globalThis.fetch;
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

test.beforeEach(() => {
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: new MemoryStorage(),
  });
  Object.defineProperty(globalThis, "sessionStorage", {
    configurable: true,
    value: new MemoryStorage(),
  });
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: new EventTarget(),
  });
  globalThis.fetch = async () => {
    throw new Error("Unexpected network request in offline test");
  };
  cart.detach();
  forgetConversation();
});
test.afterEach(() => {
  cart.detach();
  globalThis.fetch = nativeFetch;
});

test("a delayed cart from the previous account cannot refill the signed-out cart", async () => {
  const request = deferred<Response>();
  globalThis.fetch = async () => request.promise;
  const loading = cart.attach("old-account");
  cart.detach();
  request.resolve(json({ items: [{ sku: "PRIVATE-OLD", qty: 1 }] }));
  await loading;
  expect(cart.lines()).toEqual([]);
});

test("a delayed old account cannot overwrite the new account cart", async () => {
  const old = deferred<Response>();
  globalThis.fetch = async (_url, options) =>
    (options?.headers as Record<string, string>).Authorization === "Bearer old"
      ? old.promise
      : json({ items: [{ sku: "NEW", qty: 2 }] });
  const first = cart.attach("old");
  cart.detach();
  await cart.attach("new");
  old.resolve(json({ items: [{ sku: "OLD", qty: 1 }] }));
  await first;
  expect(cart.lines()).toEqual([{ sku: "NEW", qty: 2 }]);
});

test("a merge response cannot overwrite an edit made while it was saving", async () => {
  const saved = deferred<Response>();
  const started = deferred<void>();
  globalThis.fetch = async (_url, options) => {
    if (options?.method === "PUT") {
      started.resolve();
      return saved.promise;
    }
    return json({ items: [{ sku: "SERVER", qty: 1 }] });
  };
  cart.add("LOCAL");
  const attaching = cart.attach("account");
  await started.promise;
  cart.set("SERVER", 3);
  saved.resolve(
    json({
      items: [
        { sku: "SERVER", qty: 1 },
        { sku: "LOCAL", qty: 1 },
      ],
    }),
  );
  await attaching;
  expect(cart.lines().find((line) => line.sku === "SERVER")?.qty).toBe(3);
});

test("a non-JSON unauthorized reply still exposes its status to the session handler", async () => {
  globalThis.fetch = async () => new Response("Unauthorized", { status: 401 });
  await expect(api("/api/customer/me")).rejects.toMatchObject({ status: 401 });
});

test("BFF forwards PATCH, authorization, query, text errors and retry headers", async () => {
  globalThis.fetch = async (url, options) => {
    expect(String(url)).toContain("/api/customer/me?fixture=1");
    expect(options?.method).toBe("PATCH");
    expect(new Headers(options?.headers).get("Authorization")).toBe(
      "Bearer fixture",
    );
    return new Response("Temporarily unavailable", {
      status: 503,
      headers: { "Retry-After": "10", "X-Request-ID": "fixture" },
    });
  };
  const response = await PATCH(
    new NextRequest("http://shop/backend/api/customer/me?fixture=1", {
      method: "PATCH",
      headers: { Authorization: "Bearer fixture" },
      body: "{}",
    }),
  );
  expect(response.status).toBe(503);
  expect(response.headers.get("Retry-After")).toBe("10");
  expect(await response.text()).toBe("Temporarily unavailable");
});

test("BFF rejects oversized and cancelled uploads before calling upstream", async () => {
  const oversized = await POST(
    new NextRequest("http://shop/backend/api/customer/me", {
      method: "POST",
      body: "x".repeat(2 * 1024 * 1024 + 1),
    }),
  );
  expect(oversized.status).toBe(413);
  const controller = new AbortController();
  controller.abort();
  const cancelled = await POST(
    new NextRequest("http://shop/backend/api/customer/me", {
      method: "POST",
      body: "{}",
      signal: controller.signal,
    }),
  );
  expect(cancelled.status).toBe(499);
});

test("a failed cart attach can be retried with the same account", async () => {
  globalThis.fetch = async () => json({ detail: "temporary" }, 503);
  await cart.attach("account");
  globalThis.fetch = async () =>
    json({ items: [{ sku: "RECOVERED", qty: 1 }] });
  await cart.attach("account");
  expect(cart.lines()).toEqual([{ sku: "RECOVERED", qty: 1 }]);
});

test("a temporary failure resuming chat does not silently create a new conversation", async () => {
  sessionStorage.setItem(
    "conversation",
    JSON.stringify({ conversation_id: "saved", conversation_token: "secret" }),
  );
  sessionStorage.setItem("conversation-customer", "");
  let created = 0;
  globalThis.fetch = async (_url, options) => {
    if (options?.method === "POST") created++;
    return json({ detail: "unavailable" }, 503);
  };
  await expect(openSession()).rejects.toMatchObject({ status: 503 });
  expect(created).toBe(0);
});

test("SSE accepts CRLF, split Unicode, a final event and cancels its reader", async () => {
  const bytes = new TextEncoder().encode(
    'event: delta\r\ndata: {"text":"Chào chị"}\r\n\r\nevent: done\r\ndata: {"reply":"Chào chị"}\r\n\r\n',
  );
  let cancelled = false;
  let body: Record<string, unknown> = {};
  globalThis.fetch = async (_url, options) => {
    body = JSON.parse(String(options?.body));
    return new Response(
      new ReadableStream({
        start(controller) {
          for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
        },
        cancel() {
          cancelled = true;
        },
      }),
    );
  };
  const chunks: string[] = [];
  const reply = await streamTurn(
    { conversation_id: "saved", conversation_token: "secret" },
    "Xin chào",
    "",
    (text) => chunks.push(text),
    null,
    { turnId: "stable-turn" },
  );
  expect(reply.reply).toBe("Chào chị");
  expect(chunks).toEqual(["Chào chị"]);
  expect(body.turn_id).toBe("stable-turn");
  expect(cancelled).toBe(true);
});

test("a truncated stream is reported, preserving the text already delivered", async () => {
  globalThis.fetch = async () =>
    new Response('event: delta\ndata: {"text":"Một phần"}\n\n');
  let displayed = "";
  await expect(
    streamTurn(
      { conversation_id: "saved", conversation_token: "secret" },
      "Chào",
      "",
      (text) => {
        displayed = text;
      },
    ),
  ).rejects.toThrow("gián đoạn");
  expect(displayed).toBe("Một phần");
});

function voiceFixture(getUserMedia: () => Promise<MediaStream>) {
  let closed = 0,
    disconnected = 0,
    socketsClosed = 0;
  class Node {
    port = { onmessage: null, close() {} };
    gain = { value: 0 };
    onended: (() => void) | null = null;
    start() {}
    stop() {}
    connect(destination: unknown) {
      return destination;
    }
    disconnect() {
      disconnected++;
    }
  }
  class Context {
    state = "running";
    sampleRate = 48000;
    destination = {};
    currentTime = 0;
    decodeAudioData() {
      return Promise.resolve({ duration: 1 });
    }
    createBufferSource() {
      return new Node();
    }
    audioWorklet = { addModule: async () => {} };
    resume() {
      return Promise.resolve();
    }
    close() {
      closed++;
      this.state = "closed";
      return Promise.resolve();
    }
    createAnalyser() {
      return new Node();
    }
    createGain() {
      return new Node();
    }
    createMediaStreamSource() {
      return new Node();
    }
  }
  const sent: Record<string, unknown>[] = [];
  const sockets: { onmessage?: (event: { data: string }) => void }[] = [];
  class Socket {
    static OPEN = 1;
    readyState = 1;
    bufferedAmount = 0;
    onmessage?: (event: { data: string }) => void;
    constructor() {
      sockets.push(this);
    }
    close() {
      socketsClosed++;
    }
    send(value: string) {
      sent.push(JSON.parse(value));
    }
  }
  Object.assign(window, {
    AudioContext: Context,
    location: { protocol: "http:", hostname: "127.0.0.1" },
  });
  Object.defineProperty(globalThis, "AudioWorkletNode", {
    configurable: true,
    value: Node,
  });
  Object.defineProperty(globalThis, "WebSocket", {
    configurable: true,
    value: Socket,
  });
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: { mediaDevices: { getUserMedia } },
  });
  return {
    sockets,
    sent,
    counts: () => ({ closed, disconnected, socketsClosed }),
  };
}

test("a microphone granted after hangup is stopped and cannot open a socket", async () => {
  const granted = deferred<MediaStream>();
  const requested = deferred<void>();
  const fixture = voiceFixture(() => {
    requested.resolve();
    return granted.promise;
  });
  let tracksStopped = 0;
  const call = new VoiceCall().prepare();
  const connecting = call.connect("conversation", "token", () => {});
  await requested.promise;
  call.stop();
  granted.resolve({
    getTracks: () => [
      {
        stop: () => {
          tracksStopped++;
        },
      },
    ],
  } as unknown as MediaStream);
  await connecting;
  call.stop();
  expect(tracksStopped).toBe(1);
  expect(fixture.counts().closed).toBe(1);
  expect(fixture.sockets).toHaveLength(0);
});

test("permission failure releases the audio context", async () => {
  const fixture = voiceFixture(async () => {
    throw new DOMException("denied", "NotAllowedError");
  });
  await expect(
    new VoiceCall().prepare().connect("conversation", "token", () => {}),
  ).rejects.toThrow("denied");
  expect(fixture.counts().closed).toBe(1);
});

test("malformed voice frames stop capture and close the socket", async () => {
  let tracksStopped = 0;
  const fixture = voiceFixture(
    async () =>
      ({
        getTracks: () => [
          {
            stop: () => {
              tracksStopped++;
            },
          },
        ],
      }) as unknown as MediaStream,
  );
  const messages: string[] = [];
  const call = new VoiceCall().prepare();
  await call.connect("conversation", "token", (message) =>
    messages.push(message.type),
  );
  fixture.sockets[0].onmessage?.({ data: "not JSON" });
  call.stop();
  expect(messages).toContain("error");
  expect(tracksStopped).toBe(1);
  expect(fixture.counts().socketsClosed).toBe(1);
  expect(fixture.counts().disconnected).toBeGreaterThan(0);
});

test("changing noise profile uses constraints on the same track, retaining AEC", async () => {
  let opened = 0;
  let settings: Record<string, unknown> = {
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
  };
  const track = {
    stop() {},
    getSettings: () => settings,
    applyConstraints: async (next: Record<string, unknown>) => {
      settings = next;
    },
  };
  const fixture = voiceFixture(async () => {
    opened++;
    return {
      getTracks: () => [track],
      getAudioTracks: () => [track],
    } as unknown as MediaStream;
  });
  const call = new VoiceCall().prepare();
  await call.connect("fixture", "token", () => {});
  await call.setCaptureProfile("barge-in");
  expect(opened).toBe(1);
  expect(call.captureSettings()).toMatchObject({
    profile: "barge-in",
    echoCancellation: true,
    noiseSuppression: false,
    autoGainControl: false,
  });
  expect(fixture.sent.at(-1)).toMatchObject({
    type: "capture_settings",
    profile: "barge-in",
  });
  call.stop();
});

test("playback evidence is emitted only when audio starts, and hangup cancels pending evidence", async () => {
  const fixture = voiceFixture(
    async () => ({ getTracks: () => [] }) as unknown as MediaStream,
  );
  const call = new VoiceCall().prepare();
  await call.connect("fixture", "token", () => {});
  fixture.sockets[0].onmessage?.({
    data: JSON.stringify({ type: "audio", turn: "t1", seq: 0, data: "AA==" }),
  });
  await expect
    .poll(
      () =>
        fixture.sent.filter((message) => message.type === "playback_started")
          .length,
    )
    .toBe(1);
  fixture.sockets[0].onmessage?.({
    data: JSON.stringify({ type: "audio", turn: "t1", seq: 1, data: "AA==" }),
  });
  await Promise.resolve();
  call.stop();
  expect(
    fixture.sent.filter((message) => message.type === "playback_chunk"),
  ).toHaveLength(0);
});
