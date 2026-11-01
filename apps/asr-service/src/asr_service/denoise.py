"""Optional RNNoise v0.2 waveform enhancement; off by default, no downloads at inference.

Native ABI via the pinned PyRNNoise wheel, without its file-I/O/resampling stack.
Frame alignment follows xiph/rnnoise v0.2 examples/rnnoise_demo.c (skip first hop).
Each utterance owns a fresh state, including each prefix decode of the offline WS service.
"""
from __future__ import annotations

import ctypes
from functools import lru_cache
import hashlib
from importlib.metadata import distribution, PackageNotFoundError
import platform

import numpy as np

VERSION = 'rnnoise-0.2-pyrnnoise-0.4.5-hop480-v1'
CHOICES = ('none', 'rnnoise')


@lru_cache(maxsize=1)
def library():
    try:
        package = distribution('pyrnnoise')
    except PackageNotFoundError as error:
        raise RuntimeError('RNNoise optional dependency missing; install requirements-denoise.txt') from error
    if package.version != '0.4.5':
        raise RuntimeError('RNNoise requires pinned pyrnnoise==0.4.5')
    filename = {'Darwin': 'librnnoise.dylib', 'Linux': 'librnnoise.so', 'Windows': 'rnnoise.dll'}.get(platform.system())
    if filename is None:
        raise RuntimeError('RNNoise unsupported platform')
    path = package.locate_file('pyrnnoise/' + filename)
    try:
        lib = ctypes.CDLL(str(path))
    except OSError as error:
        raise RuntimeError('RNNoise native library unavailable for this platform') from error
    pointer = ctypes.POINTER(ctypes.c_float)
    lib.rnnoise_create.argtypes, lib.rnnoise_create.restype = [ctypes.c_void_p], ctypes.c_void_p
    lib.rnnoise_destroy.argtypes, lib.rnnoise_destroy.restype = [ctypes.c_void_p], None
    lib.rnnoise_process_frame.argtypes = [ctypes.c_void_p, pointer, pointer]
    lib.rnnoise_process_frame.restype = ctypes.c_float
    lib.rnnoise_get_frame_size.argtypes, lib.rnnoise_get_frame_size.restype = [], ctypes.c_int
    if lib.rnnoise_get_frame_size() != 480:
        raise RuntimeError('Unexpected RNNoise frame size')
    return lib, hashlib.sha256(path.read_bytes()).hexdigest()


def validate(name: str) -> None:
    if name not in CHOICES:
        raise ValueError('denoiser must be none or rnnoise')


def metadata(name: str) -> dict:
    validate(name)
    if name == 'none':
        return {'name': 'none', 'version': 'identity-v1'}
    _, digest = library()
    return {'name': name, 'version': VERSION, 'library_sha256': digest, 'sample_rate': 48000,
            'frame_samples': 480, 'alignment': 'skip first 480 samples and flush one zero hop (upstream demo)',
            'state': 'fresh per utterance', 'implementation_sha256': hashlib.sha256(__import__('pathlib').Path(__file__).read_bytes()).hexdigest()}


def process(samples: np.ndarray, name: str = 'none') -> np.ndarray:
    validate(name)
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim != 1 or not samples.size or not np.isfinite(samples).all():
        raise ValueError('Denoiser requires finite nonempty mono 16kHz audio')
    if name == 'none':
        return samples
    import soxr
    lib, _ = library()
    signal = soxr.resample(samples, 16000, 48000, quality='HQ')
    # RNNoise uses float PCM on the int16 amplitude scale, not normalized float audio.
    padded = np.pad(np.clip(signal, -1, 1) * 32767, (0, (-len(signal)) % 480 + 480)).astype(np.float32)
    result = np.empty_like(padded)
    state = lib.rnnoise_create(None)
    if not state:
        raise RuntimeError('RNNoise state allocation failed')
    pointer = ctypes.POINTER(ctypes.c_float)
    try:
        for offset in range(0, len(padded), 480):
            frame = padded[offset:offset + 480]
            output = result[offset:offset + 480]
            lib.rnnoise_process_frame(state, output.ctypes.data_as(pointer), frame.ctypes.data_as(pointer))
    finally:
        lib.rnnoise_destroy(state)
    restored = soxr.resample(result[480:480 + len(signal)] / 32767, 48000, 16000, quality='HQ')
    restored = np.pad(restored, (0, max(0, len(samples) - len(restored))))[:len(samples)]
    if not np.isfinite(restored).all():
        raise RuntimeError('RNNoise produced nonfinite audio')
    return np.ascontiguousarray(np.clip(restored, -1, 1), dtype=np.float32)
