// The caller's side of a voice call: microphone up, spoken answers down.
//
// Ported from the reference agent's frontend (services/voice.js). Everything
// that decides anything runs on the server (ai-agent-service api/routes/voice.py):
// when the caller has finished, what they said, the answer, and whether speech
// over the answer is an interruption. This file captures, plays, and reports
// back what only the browser knows: when playback started (TTFA as the caller
// experiences it) and how much of an interrupted answer was heard.
//
// Lessons kept from the reference:
// - ONE AudioContext for the microphone and the answers, so the browser's echo
//   canceller removes the answer from the microphone. With two contexts the
//   assistant hears itself as the customer.
// - Create the context inside the click that places the call (prepare());
//   Safari starts a context created later suspended, and the answer is silent.
// - The page owns the call object, not the component that draws it: React
//   StrictMode mounts components twice in development.
// - Pausing an answer cannot suspend the context (that stops the microphone);
//   the queued pieces are stopped and their position kept instead.
//
// Protocol: first text frame {token, sample_rate}; then binary Float32 PCM at
// the context's rate. Down: JSON {type: state|status|input|transcript|reply|
// audio|audio_end|pause|resume|stop|truncated|metrics|ignored|error}.

export type VoiceMessage = { type: string; [key: string]: unknown };

type Piece = {
  seq: number;
  buffer: AudioBuffer;
  start: number;
  duration: number;
  source: AudioBufferSourceNode | null;
};
type Playing = {
  turn: string;
  items: Piece[];
  queueEnd: number;
  started: boolean;
  stopped: boolean;
  pausedAt: number | null;
  lastSeq: number | null;
};

/** The gateway's WebSocket origin: NEXT_PUBLIC_VOICE_URL, else the page host on port 8000. */
export function voiceOrigin(): string {
  const configured = (process.env.NEXT_PUBLIC_VOICE_URL || "").replace(/\/$/, "");
  if (configured) return configured.replace(/^http/, "ws");
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.hostname}:8000`;
}

export class VoiceCall {
  micAnalyser: AnalyserNode | null = null;
  agentAnalyser: AnalyserNode | null = null;
  private on: (message: VoiceMessage) => void = () => {};
  private ws: WebSocket | null = null;
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private capture: AudioWorkletNode | null = null;
  private playing: Playing | null = null;
  private decodeChain: Promise<void> = Promise.resolve();
  private cancelled = new Set<string>();
  private started = false;
  private closed = false;
  // Audio goes up only once the server has loaded its models: sound sent
  // earlier would queue and arrive late, all at once.
  private ready = false;

  /** Call inside the click that places the call, before anything is awaited. */
  prepare(): this {
    const Context =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    this.ctx = new Context();
    void this.ctx.resume();
    this.agentAnalyser = this.ctx.createAnalyser();
    this.agentAnalyser.fftSize = 2048;
    this.agentAnalyser.connect(this.ctx.destination);
    return this;
  }

  /** Idempotent: a second call only replaces the listener. */
  async connect(conversationId: string, token: string, on: (message: VoiceMessage) => void) {
    this.on = on;
    if (this.started || this.closed) return;
    this.started = true;
    if (!this.ctx) this.prepare();
    const ctx = this.ctx!;
    await ctx.audioWorklet.addModule("/capture.js");
    if (this.closed) return;
    this.capture = new AudioWorkletNode(ctx, "capture");
    this.micAnalyser = ctx.createAnalyser();
    this.micAnalyser.fftSize = 2048;
    // The worklet runs only when the graph pulls it; a silent path to the
    // speakers does that without playing the microphone back.
    const mute = ctx.createGain();
    mute.gain.value = 0;
    this.capture.connect(mute).connect(ctx.destination);
    await this.useMicrophone(null);
    if (this.closed) return;

    this.ws = new WebSocket(`${voiceOrigin()}/api/conversations/${conversationId}/voice`);
    this.ws.binaryType = "arraybuffer";
    this.ws.onopen = () => this.send({ token, sample_rate: ctx.sampleRate });
    this.ws.onmessage = (event) => this.handle(JSON.parse(String(event.data)));
    this.ws.onclose = (event) => {
      this.stop();
      this.on({ type: "closed", code: event.code });
    };
    this.capture.port.onmessage = (event: MessageEvent<Float32Array>) => {
      if (this.ready && this.ws?.readyState === WebSocket.OPEN) this.ws.send(event.data.buffer);
    };
  }

  /** The system default input when deviceId is null, else the one chosen. */
  async useMicrophone(deviceId: string | null) {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
      },
    });
    if (this.closed || !this.ctx) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    this.source?.disconnect();
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = stream;
    this.source = this.ctx.createMediaStreamSource(stream);
    this.source.connect(this.micAnalyser!);
    this.source.connect(this.capture!);
  }

  microphone(): { id: string; label: string } | null {
    const track = this.stream?.getAudioTracks()[0];
    return track ? { id: track.getSettings().deviceId || "", label: track.label || "Micro" } : null;
  }

  async microphones(): Promise<MediaDeviceInfo[]> {
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter((d) => d.kind === "audioinput" && d.deviceId !== "default");
  }

  setMuted(muted: boolean) {
    this.stream?.getAudioTracks().forEach((track) => {
      track.enabled = !muted;
    });
  }

  hangUp() {
    this.send({ type: "hangup" });
    const ws = this.ws;
    setTimeout(() => ws?.close(), 300);
    this.stop();
  }

  stop() {
    if (this.closed) return;
    this.closed = true;
    this.stopPlayback();
    this.stream?.getTracks().forEach((track) => track.stop());
    if (this.ctx && this.ctx.state !== "closed") void this.ctx.close();
  }

  private send(payload: Record<string, unknown>) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(payload));
  }

  private handle(message: VoiceMessage) {
    switch (message.type) {
      case "audio":
        this.decodeChain = this.decodeChain.then(() => this.enqueue(message)).catch(() => {});
        return;
      case "audio_end":
        this.decodeChain = this.decodeChain.then(() => this.finish(message));
        return;
      case "status":
        this.ready = true;
        break;
      case "pause":
        this.pause(String(message.turn));
        break;
      case "resume":
        this.resume(String(message.turn));
        break;
      case "stop":
        this.interrupt(String(message.turn));
        break;
    }
    this.on(message);
  }

  // ── playback ──────────────────────────────────────────────────────────

  private async enqueue(m: VoiceMessage) {
    const turn = String(m.turn);
    if (!this.ctx || this.closed || this.cancelled.has(turn)) return;
    const bytes = Uint8Array.from(atob(String(m.data)), (c) => c.charCodeAt(0));
    const buffer = await this.ctx.decodeAudioData(bytes.buffer);
    if (this.closed || this.cancelled.has(turn)) return;
    if (!this.playing || this.playing.turn !== turn) {
      this.stopPlayback();
      this.playing = { turn, items: [], queueEnd: this.ctx.currentTime, started: false, stopped: false, pausedAt: null, lastSeq: null };
    }
    const playing = this.playing;
    const at = playing.pausedAt != null ? playing.queueEnd : Math.max(this.ctx.currentTime + 0.02, playing.queueEnd);
    const item: Piece = { seq: Number(m.seq), buffer, start: at, duration: buffer.duration, source: null };
    playing.items.push(item);
    playing.queueEnd = at + buffer.duration;
    // While paused the piece waits in the queue; resume schedules it.
    if (playing.pausedAt == null) this.schedule(playing, item, at, 0);
    if (!playing.started && playing.pausedAt == null) {
      playing.started = true;
      const delay = Math.max(0, (at - this.ctx.currentTime) * 1000);
      setTimeout(() => this.send({ type: "playback_started", turn }), delay);
    }
  }

  private schedule(playing: Playing, item: Piece, when: number, offset: number) {
    const source = this.ctx!.createBufferSource();
    source.buffer = item.buffer;
    source.connect(this.agentAnalyser!);
    source.start(when, offset);
    item.source = source;
    source.onended = () => {
      if (this.playing === playing && !playing.stopped && playing.pausedAt == null && playing.lastSeq === item.seq && item.source === source) {
        this.send({ type: "playback_ended", turn: playing.turn });
      }
    };
  }

  // The last piece is known only once synthesis is over; if playback has
  // already run past it, report the end now.
  private finish(m: VoiceMessage) {
    const turn = String(m.turn);
    if (!this.playing || this.playing.turn !== turn || !this.ctx) return;
    this.playing.lastSeq = Number(m.last_seq);
    const item = this.playing.items.find((it) => it.seq === Number(m.last_seq));
    if (item && this.playing.pausedAt == null && this.ctx.currentTime >= item.start + item.duration) {
      this.send({ type: "playback_ended", turn });
    }
  }

  private pause(turn: string) {
    const playing = this.playing;
    if (!playing || playing.turn !== turn || playing.pausedAt != null || !this.ctx) return;
    playing.pausedAt = this.ctx.currentTime;
    for (const item of playing.items) this.silence(item);
  }

  private resume(turn: string) {
    const playing = this.playing;
    if (!playing || playing.turn !== turn || playing.pausedAt == null || !this.ctx) return;
    const pausedAt = playing.pausedAt;
    const now = this.ctx.currentTime + 0.02;
    const shift = now - pausedAt;
    playing.pausedAt = null;
    for (const item of playing.items) {
      if (item.start + item.duration <= pausedAt) continue;
      const offset = Math.max(0, pausedAt - item.start);
      const when = item.start >= pausedAt ? item.start + shift : now;
      item.start += shift;
      this.schedule(playing, item, when, offset);
    }
    playing.queueEnd += shift;
    if (!playing.started) {
      playing.started = true;
      this.send({ type: "playback_started", turn });
    }
  }

  private interrupt(turn: string) {
    this.cancelled.add(turn);
    const playing = this.playing;
    if (!playing || playing.turn !== turn || !this.ctx) return;
    // Paused, the answer stands where the caller cut in.
    const now = playing.pausedAt ?? this.ctx.currentTime;
    const items = playing.items;
    const current =
      items.find((it) => now >= it.start && now < it.start + it.duration) ||
      items.find((it) => now < it.start) ||
      items[items.length - 1];
    const played = current ? Math.max(0, (now - current.start) * 1000) : 0;
    this.stopPlayback();
    this.send({
      type: "playback_stopped",
      turn,
      seq: current ? current.seq : 0,
      played_ms: played,
      duration_ms: current ? current.duration * 1000 : 1,
    });
  }

  private silence(item: Piece) {
    try {
      item.source?.stop();
    } catch {
      // Not started yet, or already ended.
    }
    item.source = null;
  }

  private stopPlayback() {
    if (!this.playing) return;
    this.playing.stopped = true;
    for (const item of this.playing.items) this.silence(item);
    this.playing = null;
  }
}
