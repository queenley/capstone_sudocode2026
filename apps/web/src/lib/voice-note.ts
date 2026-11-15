// A voice message in the web chat, as on Zalo or Messenger: hold the microphone to record, let go to send.
//
// The browser records in its own format (MediaRecorder: webm/opus, or mp4 on Safari), then decodes the recording
// itself and resamples it to what the recogniser takes: 16-bit mono PCM at 16 kHz
// (POST /api/conversations/{id}/voice-message). No codec is needed on the server, and a minute fits under the
// web proxy's 2 MB.

export const VOICE_RATE = 16_000;
/** As on Zalo: a voice message is at most a minute. */
export const MAX_SECONDS = 60;
/** Shorter than this is a tap, not a message. */
export const MIN_SECONDS = 0.6;

export type VoiceNote = {
  /** The recording as recorded, to play back in the chat. */
  blob: Blob;
  pcm: Int16Array;
  seconds: number;
};

export function voiceSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof window.MediaRecorder !== "undefined" &&
    typeof window.OfflineAudioContext !== "undefined"
  );
}

export class VoiceRecorder {
  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private stopped = false;
  startedAt = 0;

  /** Ask for the microphone and start recording; must run inside the press (a user gesture). */
  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    if (this.stopped) {
      // Let go while the browser was still asking for the microphone.
      this.release();
      throw new DOMException("Released before recording started", "AbortError");
    }
    this.recorder = new MediaRecorder(this.stream);
    this.recorder.ondataavailable = (event) => {
      if (event.data.size) this.chunks.push(event.data);
    };
    this.recorder.start(250);
    this.startedAt = performance.now();
  }

  elapsed(): number {
    return this.startedAt ? (performance.now() - this.startedAt) / 1000 : 0;
  }

  /** Stop and hand back the recording, or null when there is none worth sending (a tap, silence). */
  async stop(): Promise<VoiceNote | null> {
    this.stopped = true;
    const recorder = this.recorder;
    if (!recorder || recorder.state === "inactive") {
      this.release();
      return null;
    }
    const done = new Promise<void>((resolve) => (recorder.onstop = () => resolve()));
    recorder.stop();
    await done;
    this.release();
    const blob = new Blob(this.chunks, { type: recorder.mimeType || "audio/webm" });
    const decoded = await toPcm(blob);
    if (!decoded || decoded.seconds < MIN_SECONDS || !decoded.voiced) return null;
    return { blob, pcm: decoded.pcm, seconds: decoded.seconds };
  }

  cancel(): void {
    this.stopped = true;
    try {
      if (this.recorder && this.recorder.state !== "inactive") this.recorder.stop();
    } catch {
      /* already stopped */
    }
    this.release();
  }

  private release(): void {
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
  }
}

/** The recording as 16 kHz mono 16-bit PCM, its length, and whether anyone spoke (the recogniser hears words in
 *  silence: one second of it came back as "đúng"). */
async function toPcm(blob: Blob): Promise<{ pcm: Int16Array; seconds: number; voiced: boolean } | null> {
  const context = new AudioContext();
  let buffer: AudioBuffer;
  try {
    buffer = await context.decodeAudioData(await blob.arrayBuffer());
  } catch {
    return null;
  } finally {
    void context.close();
  }
  const seconds = Math.min(buffer.duration, MAX_SECONDS);
  const length = Math.max(1, Math.ceil(seconds * VOICE_RATE));
  const offline = new OfflineAudioContext(1, length, VOICE_RATE);
  const source = offline.createBufferSource();
  source.buffer = buffer;
  source.connect(offline.destination);
  source.start();
  const samples = (await offline.startRendering()).getChannelData(0);

  // Voiced: some 30 ms frame loud enough to be speech, not the room.
  const frame = Math.round(VOICE_RATE * 0.03);
  let loudest = 0;
  for (let start = 0; start + frame <= samples.length; start += frame) {
    let sum = 0;
    for (let i = start; i < start + frame; i++) sum += samples[i] * samples[i];
    loudest = Math.max(loudest, Math.sqrt(sum / frame));
  }
  const pcm = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) pcm[i] = Math.max(-1, Math.min(1, samples[i])) * 0x7fff;
  return { pcm, seconds, voiced: loudest > 0.015 };
}

/** 0:07 */
export function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
