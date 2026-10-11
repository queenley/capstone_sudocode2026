from __future__ import annotations
import numpy as np
from scipy.signal import butter, sosfilt

NOISE_TYPES = ("street", "cafe", "wind", "weak_signal")

def _normalize(signal: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(signal))) if signal.size else 0.0
    return (signal / max(peak, 1e-9) * 0.95).astype(np.float32)

def _bandpass(signal: np.ndarray, sample_rate: int, low: float, high: float) -> np.ndarray:
    sos = butter(4, [low, min(high, sample_rate * .49)], btype="bandpass", fs=sample_rate, output="sos")
    return sosfilt(sos, signal).astype(np.float32)

def add_noise(audio: np.ndarray, sample_rate: int, noise_type: str | None, snr_db: int | None,
              seed: int, packet_drop_count: int = 2) -> np.ndarray:
    if noise_type is None:
        return _normalize(audio)
    if noise_type not in NOISE_TYPES:
        raise ValueError(f"Unknown noise type {noise_type}")
    rng = np.random.default_rng(seed)
    clean = audio.astype(np.float32).copy()
    if noise_type == "weak_signal":
        clean = _bandpass(clean, sample_rate, 300, 3400)
        for _ in range(packet_drop_count):
            length = int(rng.uniform(.08, .25) * sample_rate)
            if len(clean) > length:
                start = int(rng.integers(0, len(clean) - length))
                clean[start:start + length] = 0
    white = rng.normal(0, 1, len(clean)).astype(np.float32)
    if noise_type in ("street", "wind"):
        noise = sosfilt(butter(3, 450 if noise_type == "wind" else 900, btype="lowpass", fs=sample_rate, output="sos"), white)
        if noise_type == "street":
            for at in rng.integers(0, max(len(noise), 1), size=max(1, len(noise)//sample_rate//8)):
                width = min(int(.08*sample_rate), len(noise)-at)
                if width > 0: noise[at:at+width] += rng.normal(0, 2, width)
    elif noise_type == "cafe":
        noise = np.zeros_like(white)
        for f in (220, 370, 610, 950, 1400):
            phase = rng.uniform(0, 2*np.pi)
            envelope = .35 + .65 * np.sin(np.linspace(phase, phase+len(white)/sample_rate, len(white)))**2
            noise += (np.sin(2*np.pi*f*np.arange(len(white))/sample_rate) * envelope).astype(np.float32)
        noise += white * .15
    else:
        noise = white * .15
    signal_power = float(np.mean(clean**2)) + 1e-12
    noise_power = float(np.mean(noise**2)) + 1e-12
    target = 10 ** ((snr_db or 10) / 10)
    mixed = clean + noise * np.sqrt(signal_power / (target * noise_power))
    return _normalize(mixed)
