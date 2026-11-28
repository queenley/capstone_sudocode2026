"""Time the running tts-service: first audio and synthesis speed against playback (rtf < 1 keeps up)."""
import json
import time
import urllib.request

import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
URL = os.environ.get("TTS_URL", "http://127.0.0.1:8600")
SENTENCES = [
    "Dạ, em chào anh chị, em là trợ lý của cửa hàng Quivo.",
    "Máy lọc không khí AirPure Pro hiện còn hàng, giá bảy triệu sáu trăm chín mươi nghìn đồng.",
    "Anh chị muốn em đặt hàng giao về địa chỉ nào ạ?",
]
print(urllib.request.urlopen(URL + "/health/ready").read().decode())
for text in SENTENCES:
    request = urllib.request.Request(URL + "/v1/speak", data=json.dumps({"text": text}).encode(),
                                     headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    first = None
    size = 0
    with urllib.request.urlopen(request) as response:
        rate = int(response.headers["X-Sample-Rate"])
        while chunk := response.read1(65536):
            if first is None:
                first = time.perf_counter() - started
            size += len(chunk)
    total = time.perf_counter() - started
    audio = size / 2 / rate
    print(f"first_audio={first:.2f}s synth={total:.2f}s audio={audio:.2f}s rtf={total / audio:.2f}  {text[:40]}")
