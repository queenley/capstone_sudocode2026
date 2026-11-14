"""Đọc kịch bản thu âm đợt 1 (D01–D04) bằng giọng tổng hợp ElevenLabs.

Mỗi hội thoại ra ``audio/D0x.wav`` (mono 16 kHz 16-bit), ``audio/D0x.segments.json`` (mốc từng lượt) và một
``ground_truth.json`` theo định dạng BTC, nên chấm được ngay bằng ``run_eval.py --asr``.

Giọng tổng hợp không thay được bản thu thật gửi BTC: bộ này chỉ để thử pipeline ASR và tách lượt.
D02 của kịch bản đợt 1 (khách nữ miền Bắc) khác D02 trong ground truth của BTC (khách nam miền Nam);
``--check`` in các lượt khác nhau. File của BTC chỉ được đọc.

Từ gốc repo:

    pip install elevenlabs numpy
    python scripts/asr/elevenlabs_d01_d04.py --check           # so với BTC, đếm ký tự; không gọi API
    python scripts/asr/elevenlabs_d01_d04.py --list-voices     # giọng tiếng Việt trong Voice Library; không tốn credit
    python scripts/asr/elevenlabs_d01_d04.py --voice nu1=<id> --voice nu2=<id> --voice nu3=<id> --voice nam3=<id>
    python run_eval.py --asr data/dev/asr_elevenlabs --asr-transcribe --asr-turns

API key lấy từ ``ELEVENLABS_API_KEY`` (hỏi nếu chưa đặt; không in ra). Giọng nào không truyền ``--voice`` thì
script chọn giọng đầu tiên trong Voice Library khớp giới tính và vùng miền; nên nghe thử rồi tự chọn.
Mỗi lượt được cache theo (model, giọng, cài đặt, seed, văn bản), nên chạy lại không tốn thêm credit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import wave
from datetime import datetime, timezone
from getpass import getpass
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "dev" / "asr_elevenlabs"
BTC_GROUND_TRUTH = ROOT / "apps" / "ai-agent-service" / "data" / "btc" / "asr" / "ground_truth.json"  # chỉ đọc

RATE = 16000                 # bằng định dạng bộ ASR của repo
VOICE_SETTINGS = {"stability": 0.5, "similarity_boost": 0.75}   # eleven_v3 chỉ nhận stability 0.0 / 0.5 / 1.0

# Người đọc: mỗi người một giọng, giữ nguyên qua các hội thoại (Nữ 1 đọc cả D01 và D02).
READERS = {
    "nu1":  {"label": "Nữ 1", "gender": "female", "region": "bac"},
    "nu2":  {"label": "Nữ 2", "gender": "female", "region": "bac"},
    "nu3":  {"label": "Nữ 3", "gender": "female", "region": "nam"},
    "nam3": {"label": "Nam 3", "gender": "male",  "region": "trung"},
}

# Kịch bản đợt 1, giữ nguyên từng chữ. Speaker theo định dạng BTC: A = tư vấn viên, C = khách.
SCRIPT: dict[str, dict[str, Any]] = {
    "D01": {
        "note": "Khách do dự hỏi chồng", "agent": "nu2", "customer": "nu1",
        "turns": [
            ("A", "dạ shop bê tê xê xin nghe, em có thể giúp gì cho mình ạ"),
            ("C", "alo, chị muốn hỏi máy lọc không khí cho phòng ngủ, phòng chị khoảng hai mươi lăm mét vuông"),
            ("A", "dạ phòng hai mươi lăm mét thì bên em có hai mẫu phù hợp là e pia x và e pia y ạ, nhà mình có bé nhỏ không chị"),
            ("C", "có, nhà chị có bé hai tuổi, ngân sách tầm năm triệu thôi em"),
            ("A", "dạ vậy em gợi ý mẫu e pia y có khóa trẻ em, giá năm triệu hai trăm nghìn, đang có khuyến mãi tặng một màng lọc đến hết ngày hai mươi hai tháng mười ạ"),
            ("C", "hơi vượt ngân sách chị chút, còn mẫu x thì bao nhiêu"),
            ("A", "dạ mẫu x là bốn triệu tám trăm chín mươi nghìn, cũng được tặng màng lọc, nhưng không có khóa trẻ em chị ạ"),
            ("C", "ừ để chị hỏi ông xã rồi gọi lại em nhé"),
            ("A", "dạ vâng, em ghi nhận, mai hoặc ngày kia em gọi lại chị được không ạ"),
            ("C", "ừ chiều mai gọi chị, số này luôn nhé"),
        ],
    },
    "D02": {
        "note": "Khách gọi lại sau hai ngày (cùng khách với D01)", "agent": "nu3", "customer": "nu1",
        "turns": [
            ("C", "alo, hôm trước chị có gọi hỏi máy lọc không khí bên em đó"),
            ("A", "dạ em chào chị, hôm mười lăm bên em có tư vấn chị mẫu e pia y cho phòng ngủ hai mươi lăm mét, giá năm triệu hai trăm nghìn, chị đã trao đổi với anh nhà chưa ạ"),
            ("C", "rồi, ông xã chị đồng ý rồi, giá vẫn vậy đúng không em"),
            ("A", "dạ vẫn năm triệu hai trăm nghìn, còn tặng màng lọc, giao nội thành một đến hai ngày làm việc ạ"),
            ("C", "ừ lên đơn cho chị đi, giao về địa chỉ cũ, thanh toán khi nhận hàng"),
            ("A", "dạ em xác nhận lại, một máy e pia y, năm triệu hai trăm nghìn, giao về số mười hai ngõ ba mươi tám phố hoàng cầu quận đống đa, thanh toán cê ô đê, đúng không ạ"),
            ("C", "đúng rồi em"),
            ("A", "dạ mã đơn của chị là ô đê ba trăm mười hai nghìn bốn trăm năm mươi sáu, em cảm ơn chị ạ"),
        ],
    },
    "D03": {
        "note": "Khách so giá máy lọc nước", "agent": "nu2", "customer": "nam3",
        "turns": [
            ("C", "em ơi máy lọc nước ka rô phi chín lõi bên em giá bao nhiêu"),
            ("A", "dạ máy ka rô phi chín lõi bên em giá năm triệu chín trăm chín mươi nghìn, bảo hành ba mươi sáu tháng ạ"),
            ("C", "bên kia anh thấy bán có năm triệu bảy thôi, sao bên em đắt hơn"),
            ("A", "dạ bên em bảo hành ba năm thân máy, giao lắp tận nơi và đổi trả trong bảy ngày ạ, em không so được giá bên khác nhưng giá bên em là giá niêm yết chính hãng"),
            ("C", "thế lắp đặt có mất phí không"),
            ("A", "dạ đơn từ hai triệu được miễn phí vận chuyển, hàng cồng kềnh ngoài nội thành phụ thu ba mươi nghìn thôi ạ"),
            ("C", "để anh cân nhắc thêm rồi báo lại"),
            ("A", "dạ vâng, số của anh là không chín một bảy hai hai ba bốn năm sáu đúng không ạ, em lưu lại để gọi lại anh"),
            ("C", "đúng rồi"),
        ],
    },
    "D04": {
        "note": "Khách đã mua giày, gọi đổi size", "agent": "nu3", "customer": "nu2",
        "turns": [
            ("C", "alo, chị mới nhận giày hôm qua mà size bốn mươi hơi chật em ạ"),
            ("A", "dạ em chào chị, em thấy đơn ô đê năm trăm hai mươi mốt nghìn ba trăm ba mươi tám giày run lai hai pro size bốn mươi màu đen, chị muốn đổi lên size bốn mươi mốt ạ"),
            ("C", "ừ, đổi lên bốn mươi mốt, có mất phí gì không"),
            ("A", "dạ đổi size lần đầu bên em miễn phí hoàn toàn, shop chịu phí ship hai chiều ạ, em kiểm tra tồn kho size bốn mươi mốt màu đen chị chờ em chút"),
            ("C", "ừ"),
            ("A", "dạ còn hàng ạ, bên vận chuyển sẽ qua lấy đôi cũ trong một đến hai ngày làm việc và giao đôi mới, chị giữ nguyên hộp và tem giúp em nhé"),
            ("C", "ok em, cảm ơn em nhé"),
        ],
    },
}

REGION_WORDS = {
    "bac":   ("north", "hanoi", "ha noi", "hà nội", "miền bắc", "bắc"),
    "nam":   ("south", "saigon", "sài gòn", "ho chi minh", "hồ chí minh", "hcm", "miền nam"),
    "trung": ("central", "hue", "huế", "da nang", "đà nẵng", "nghệ", "miền trung", "trung"),
}


# --- Kịch bản và ground truth của BTC -------------------------------------------------------------------------

def characters() -> int:
    return sum(len(text) for d in SCRIPT.values() for _, text in d["turns"])


def load_btc() -> dict[str, Any]:
    return json.loads(BTC_GROUND_TRUTH.read_text(encoding="utf-8"))


def check(btc: dict[str, Any]) -> None:
    """In các lượt của kịch bản khác ground truth của BTC, và số ký tự sẽ tính credit."""
    references = {d["id"]: d for d in btc["dialogues"]}
    for key, dialogue in SCRIPT.items():
        reference = references.get(key)
        if reference is None:
            print(f"{key}: BTC không có hội thoại này, không có entity")
            continue
        different = [(i, text, ref["text"]) for i, ((_, text), ref)
                     in enumerate(zip(dialogue["turns"], reference["turns"]), 1) if text != ref["text"]]
        if len(dialogue["turns"]) != len(reference["turns"]):
            print(f"{key}: {len(dialogue['turns'])} lượt, BTC có {len(reference['turns'])}")
        print(f"{key}: {'trùng BTC' if not different else f'{len(different)} lượt khác BTC'}")
        for i, mine, theirs in different:
            print(f"   lượt {i}\n     kịch bản: {mine}\n     BTC:      {theirs}")
    turns = sum(len(d["turns"]) for d in SCRIPT.values())
    print(f"\n{turns} lượt, {characters()} ký tự (ước tính credit ElevenLabs).")


# --- ElevenLabs ----------------------------------------------------------------------------------------------

def client() -> Any:
    from elevenlabs.client import ElevenLabs

    api_key = os.environ.get("ELEVENLABS_API_KEY") or getpass("ELEVENLABS_API_KEY: ")
    return ElevenLabs(api_key=api_key)


def region_of(voice: Any) -> list[str]:
    text = " ".join(str(getattr(voice, field, "") or "") for field in
                    ("accent", "locale", "name", "description", "descriptive")).lower()
    return [region for region, words in REGION_WORDS.items() if any(word in text for word in words)]


def library(api: Any) -> list[Any]:
    """Giọng tiếng Việt trong Voice Library (không tốn credit)."""
    found = []
    for gender in ("female", "male"):
        found.extend(api.voices.get_shared(language="vi", gender=gender, page_size=100).voices)
    return found


def list_voices(api: Any) -> None:
    voices = library(api)
    print(f"{len(voices)} giọng tiếng Việt\n")
    for v in voices:
        print(f"{v.gender:6} {str(v.accent or '-'):14} {','.join(region_of(v)) or '?':10} {v.voice_id}  {v.name}")
        if v.description:
            print(f"{'':33}{v.description[:110]}")
        print(f"{'':33}preview: {v.preview_url}")


def choose_voices(api: Any, given: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """voice_id cho mỗi người đọc, và tên giọng để ghi vào manifest. Giọng từ Voice Library chưa có trong
    tài khoản thì được thêm vào (một số tài khoản phải thêm thì API mới dùng được)."""
    voices = dict(given)
    names: dict[str, str] = {}
    pool = library(api)
    by_id = {v.voice_id: v for v in pool}
    taken = set(voices.values())
    for reader, want in READERS.items():
        if voices.get(reader):
            continue
        matches = [v for v in pool if v.gender == want["gender"] and want["region"] in region_of(v)
                   and v.voice_id not in taken]
        if not matches:
            raise SystemExit(f"Không tìm được giọng {want['label']} ({want['gender']}, {want['region']}). "
                             f"Chạy --list-voices, nghe thử, rồi truyền --voice {reader}=<voice_id>.")
        voices[reader] = matches[0].voice_id
        taken.add(matches[0].voice_id)
    if len(set(voices.values())) != len(voices):
        raise SystemExit("Hai người đọc đang dùng cùng một giọng; máy sẽ không tách được lượt.")

    for reader, voice_id in list(voices.items()):
        v = by_id.get(voice_id)
        names[reader] = v.name if v else "giọng trong tài khoản"
        if v is not None and not v.is_added_by_user:
            added = api.voices.share(v.public_owner_id, v.voice_id,
                                     new_name=f"BTC {READERS[reader]['label']} - {v.name}"[:100])
            voices[reader] = added.voice_id
            print(f"Đã thêm {v.name} vào tài khoản cho {READERS[reader]['label']}: {added.voice_id}")
        print(f"{READERS[reader]['label']:6} -> {voices[reader]}  {names[reader]}")
    return voices, names


# --- Âm thanh --------------------------------------------------------------------------------------------------

def synthesize(api: Any, text: str, voice_id: str, args: argparse.Namespace, cache: Path) -> np.ndarray:
    """PCM của một lượt, float trong [-1, 1]. Đã có trong cache thì không gọi API."""
    key = json.dumps([args.model, args.language, args.normalization, VOICE_SETTINGS, args.seed, voice_id, text],
                     ensure_ascii=False)
    path = cache / f"{hashlib.sha256(key.encode('utf-8')).hexdigest()[:20]}.pcm"
    if not path.is_file():
        from elevenlabs import VoiceSettings
        from elevenlabs.core.api_error import ApiError

        options: dict[str, Any] = {"text": text, "model_id": args.model, "output_format": f"pcm_{RATE}",
                                   "voice_settings": VoiceSettings(**VOICE_SETTINGS), "seed": args.seed}
        if args.language:
            options["language_code"] = args.language
        if args.normalization:
            options["apply_text_normalization"] = args.normalization
        try:
            audio = b"".join(api.text_to_speech.convert(voice_id, **options))
        except ApiError as error:
            raise SystemExit(f"ElevenLabs từ chối ({error.status_code}): {error.body}. Nếu lỗi nói về language_code "
                             "hoặc apply_text_normalization, chạy lại với --language '' hoặc --normalization ''.")
        path.write_bytes(audio)
    return np.frombuffer(path.read_bytes(), dtype="<i2").astype(np.float32) / 32768


def trim(samples: np.ndarray, threshold: float = 0.02, pad_s: float = 0.05) -> np.ndarray:
    """Bỏ im lặng hai đầu, để khoảng nghỉ giữa hai lượt đúng bằng --gap."""
    loud = np.flatnonzero(np.abs(samples) > threshold)
    if loud.size == 0:
        return samples
    pad = int(pad_s * RATE)
    return samples[max(0, loud[0] - pad): loud[-1] + pad + 1]


def level(samples: np.ndarray, target_db: float = -20.0) -> np.ndarray:
    """Đưa các giọng về cùng độ to (RMS), không để đỉnh vượt 0.95."""
    rms = float(np.sqrt(np.mean(samples ** 2))) or 1e-9
    gain = min(10 ** (target_db / 20) / rms, 0.95 / (float(np.max(np.abs(samples))) or 1e-9))
    return samples * gain


def phone(samples: np.ndarray, seed: int) -> np.ndarray:
    """Băng thoại 300–3400 Hz và nhiễu nền nhẹ (-50 dBFS), cho giống thu qua điện thoại."""
    spectrum = np.fft.rfft(samples)
    frequencies = np.fft.rfftfreq(samples.size, 1 / RATE)
    spectrum[(frequencies < 300) | (frequencies > 3400)] = 0
    rng = np.random.default_rng(seed)
    return np.fft.irfft(spectrum, n=samples.size) + rng.normal(0, 10 ** (-50 / 20), samples.size)


def write_wav(path: Path, samples: np.ndarray) -> None:
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(pcm.tobytes())


# --- Tạo bộ dữ liệu --------------------------------------------------------------------------------------------

def build(api: Any, voices: dict[str, str], names: dict[str, str], btc: dict[str, Any],
          args: argparse.Namespace) -> None:
    out: Path = args.out
    audio_dir, cache = out / "audio", out / ".cache"
    audio_dir.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    references = {d["id"]: d for d in btc["dialogues"]}
    dialogues = []

    for key, dialogue in SCRIPT.items():
        silence = np.zeros(int(args.edge * RATE), np.float32)
        pieces, segments, turns = [silence], [], []
        clock = args.edge
        reference = references.get(key, {})
        borrowed = reference.get("turns", [])
        for idx, (speaker, text) in enumerate(dialogue["turns"], 1):
            reader = dialogue["agent"] if speaker == "A" else dialogue["customer"]
            samples = level(trim(synthesize(api, text, voices[reader], args, cache)))
            if idx > 1:
                pieces.append(np.zeros(int(args.gap * RATE), np.float32))
                clock += args.gap
            segments.append({"speaker": speaker, "start": round(clock, 2), "end": round(clock + samples.size / RATE, 2)})
            clock += samples.size / RATE
            pieces.append(samples)
            # Nhãn entity mượn của BTC theo số thứ tự lượt; lượt khác BTC (--check) cần người kiểm lại.
            entities = borrowed[idx - 1].get("entities", {}) if idx <= len(borrowed) else {}
            turns.append({"idx": idx, "speaker": speaker, "text": text, "entities": entities})
            print(f"{key} lượt {idx:2} {speaker} {READERS[reader]['label']:6} {samples.size / RATE:5.1f} s")
        pieces.append(silence)
        audio = np.concatenate(pieces)
        if args.phone:
            audio = phone(audio, args.seed)
        write_wav(audio_dir / f"{key}.wav", audio)
        (audio_dir / f"{key}.segments.json").write_text(
            json.dumps({"segments": segments}, ensure_ascii=False, indent=2), encoding="utf-8")
        agent, customer = READERS[dialogue["agent"]], READERS[dialogue["customer"]]
        dialogues.append({
            "id": key, "audio": f"audio/{key}.wav",
            "customer_region": customer["region"], "customer_gender": customer["gender"][0],
            "agent_region": agent["region"], "agent_gender": agent["gender"][0],
            "scenario_ref": reference.get("scenario_ref"), "noisy": args.phone, "note": dialogue["note"],
            "turns": turns, "full_text": " ".join(text for _, text in dialogue["turns"]),
            "entities": reference.get("entities", {}), "n_turns": len(turns),
        })
        print(f"-> {key}.wav {audio.size / RATE:.1f} s\n")

    ground_truth = {
        "description": "D01–D04 kịch bản thu âm đợt 1, đọc bằng giọng tổng hợp ElevenLabs (không phải bản thu thật). "
                       "Entity mượn từ ground truth BTC theo số thứ tự lượt.",
        "hypotheses_format": btc.get("hypotheses_format"),
        "normalization_rule": btc.get("normalization_rule"),
        "reference_date": btc.get("reference_date"),
        "dialogues": dialogues,
    }
    (out / "ground_truth.json").write_text(json.dumps(ground_truth, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps({
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model_id": args.model, "language_code": args.language, "text_normalization": args.normalization,
        "voice_settings": VOICE_SETTINGS, "seed": args.seed, "rate": RATE, "gap_s": args.gap, "edge_s": args.edge,
        "phone_effect": args.phone, "characters": characters(),
        "voices": {READERS[r]["label"]: {"voice_id": v, "name": names.get(r)} for r, v in voices.items()},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Đã ghi {out}")


def _voice(value: str) -> tuple[str, str]:
    reader, _, voice_id = value.partition("=")
    if reader not in READERS or not voice_id:
        raise argparse.ArgumentTypeError(f"dạng <người đọc>=<voice_id>, người đọc là {', '.join(READERS)}")
    return reader, voice_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="So kịch bản với ground truth BTC, đếm ký tự; không gọi API.")
    parser.add_argument("--list-voices", action="store_true", help="Liệt kê giọng tiếng Việt trong Voice Library.")
    parser.add_argument("--voice", type=_voice, action="append", default=[],
                        help="Giọng cho một người đọc, ví dụ nu1=<voice_id>. Lặp lại cho nu1, nu2, nu3, nam3.")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--model", default="eleven_v3", help="Có tiếng Việt: eleven_v3, eleven_flash_v2_5, eleven_turbo_v2_5.")
    parser.add_argument("--language", default="vi", help="language_code; '' nếu model không nhận.")
    parser.add_argument("--normalization", default="off",
                        help="apply_text_normalization: off để đọc đúng từng chữ (số đã viết bằng chữ); '' = mặc định API.")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--gap", type=float, default=1.0, help="Giây im lặng giữa hai lượt (hướng dẫn thu: khoảng 1 giây).")
    parser.add_argument("--edge", type=float, default=0.4, help="Giây im lặng đầu và cuối file.")
    parser.add_argument("--phone", action="store_true", help="Lọc băng thoại 300–3400 Hz và thêm nhiễu nhẹ.")
    args = parser.parse_args(argv)
    args.language = args.language or None
    args.normalization = args.normalization or None

    btc = load_btc()
    if args.check:
        check(btc)
        return 0
    api = client()
    if args.list_voices:
        list_voices(api)
        return 0
    print(f"{characters()} ký tự cần tạo (lượt đã có trong cache không tính).")
    voices, names = choose_voices(api, dict(args.voice))
    build(api, voices, names, btc, args)
    print("\nChấm ASR (local, không tốn phí):\n"
          f"  python run_eval.py --asr {args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out} "
          "--asr-transcribe --asr-turns")
    return 0


if __name__ == "__main__":
    sys.exit(main())
