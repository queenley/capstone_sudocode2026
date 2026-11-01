from __future__ import annotations
import hashlib, os
from pathlib import Path
import re
import httpx, yaml
from dotenv import load_dotenv
import json
from src.utils.paths import CACHE_DIR, ENV_FILE

#: Speech already paid for, by its request (text, voice, model, settings): shared by every seed and run, so a turn
#: whose words did not change is never sent again. Noise is mixed after, so the cache holds the clean PCM.
TTS_CACHE_DIR = CACHE_DIR.parent / "tts"

#: CRM region -> ElevenLabs accent label of a Vietnamese voice; customer age band -> age labels, nearest first.
VOICE_ACCENTS = {"bac": "northern", "trung": "central", "nam": "southern", "default": "standard"}
VOICE_AGES = {"youth": ("young",), "adult": ("middle_aged", "middle-aged", "young"), "senior": ("old", "middle_aged", "middle-aged")}


class ElevenLabsClient:
    def __init__(self, voices_path: Path, output_dir: Path, char_budget: int):
        load_dotenv(ENV_FILE)
        self.api_key = os.getenv("ELEVENLABS_API_KEY")
        self.voices = yaml.safe_load(voices_path.read_text(encoding="utf-8"))["voices"]
        self.output_dir, self.char_budget, self.characters_sent = output_dir, char_budget, 0
        self.cache_hits = 0   # turns served from TTS_CACHE_DIR, not paid for
        self.unavailable: set[str] = set()   # configured voices this key cannot use (use_available_voices)
        self.free_voices: dict[str, list[str]] = {}   # premade voices by gender (use_free_voices_only)
        if not self.api_key:
            raise RuntimeError("ELEVENLABS_API_KEY is not set")

    def pick_voice(self, speaker_role: str, gender: str, region: str, age_band: str, customer_id: str) -> str:
        """A voice of *speaker_role* for this region, gender and age band, the same one for the same customer.

        Voices the key cannot use (:meth:`use_available_voices`) are skipped. When a group has none left, the
        nearest one that does is used: the region's other age bands, then the same gender in another region, then
        the role's default."""
        role_config = self.voices.get(speaker_role, {})

        def ids(node) -> list[str]:
            if isinstance(node, dict):
                return [voice for child in node.values() for voice in ids(child)]
            if isinstance(node, list):
                return [voice for child in node for voice in ids(child)]
            return [node] if isinstance(node, str) and node not in self.unavailable else []

        regional = role_config.get(region, {})
        by_gender = regional.get(gender, {}) if isinstance(regional, dict) else {}
        default = role_config.get("default", {})
        tiers = [
            by_gender.get(age_band, []) if isinstance(by_gender, dict) else by_gender,   # region, gender, age band
            by_gender,                                                                   # the region's other ages
            [g.get(gender, {}) for r, g in role_config.items() if r != "default" and isinstance(g, dict)],
            default.get(gender, []) if isinstance(default, dict) else default,
            self.free_voices.get(gender, []),          # --free-voices-only: the account's premade voices last
        ]
        candidates = next((found for tier in tiers if (found := ids(tier))), [])
        if not candidates:
            raise RuntimeError(f"No usable ElevenLabs voice for {speaker_role}/{gender}/{region}/{age_band}: "
                               "add voices this key can use to config/voices.yaml")
        index = int.from_bytes(hashlib.sha256(customer_id.encode()).digest()[:8], "big") % len(candidates)
        return candidates[index]

    def use_free_voices_only(self) -> list[str]:
        """Use only the voices a free plan may call through the API (the account's premade ones): every library voice
        is skipped, and each group without a configured premade voice falls back to the premade ones of its gender.
        Returns the premade voices. They are English voices: Vietnamese spoken with a foreign accent, no regional
        one, so this is a stopgap until the plan allows library voices."""
        premade = [v for v in self.account_voices() if v.get("category") == "premade"]
        free = {v["voice_id"] for v in premade}
        self.free_voices = {}
        for voice in premade:
            self.free_voices.setdefault((voice.get("labels") or {}).get("gender"), []).append(voice["voice_id"])
        configured = set(re.findall(r"[A-Za-z0-9]{20}", json.dumps(self.voices)))
        self.unavailable |= configured - free
        return sorted(free)

    def use_available_voices(self) -> list[str]:
        """Skip the configured voices this key cannot use, from now on; returns them."""
        self.unavailable = set(self.missing_voices())
        return sorted(self.unavailable)

    def account_voices(self) -> list[dict]:
        """The voices of this key's account (My Voices), with their labels (gender, age, accent, language)."""
        listing = httpx.get("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": self.api_key}, timeout=60)
        listing.raise_for_status()
        return listing.json().get("voices", [])

    def replace_missing_voices(self, path: Path) -> list[tuple[str, str, str]]:
        """Write *path* again with every voice this account lacks replaced by one of its Vietnamese voices of the same
        gender, the line's region accent and age band (VOICE_ACCENTS, VOICE_AGES), none already on that line, in turn
        so the replacements spread. The old file is kept as ``<name>.bak``. Returns ``(group, old, new)``."""
        account = self.account_voices()
        mine = [v for v in account if (v.get("labels") or {}).get("language") == "vi"]
        have = {v["voice_id"] for v in account}
        turn: dict[tuple, int] = {}

        def pick(gender: str, region: str, band: str | None, taken: set[str]) -> str | None:
            accent, ages = VOICE_ACCENTS.get(region), VOICE_AGES.get(band or "", ())
            def label(v, key):
                return (v.get("labels") or {}).get(key)
            tiers = [lambda v: label(v, "accent") == accent and (not ages or label(v, "age") in ages),
                     lambda v: label(v, "accent") == accent,
                     lambda v: label(v, "accent") == "standard" and (not ages or label(v, "age") in ages),
                     lambda v: not ages or label(v, "age") in ages,
                     lambda v: True]
            for rank, fits in enumerate(tiers):
                pool = sorted(v["voice_id"] for v in mine if label(v, "gender") == gender and fits(v)
                              and v["voice_id"] not in taken)
                if pool:
                    key = (gender, region, band, rank)
                    turn[key] = turn.get(key, -1) + 1
                    return pool[turn[key] % len(pool)]
            return None

        text = path.read_text(encoding="utf-8")
        out, stack, changes = [], [], []
        for line in text.splitlines(keepends=True):
            match = re.match(r"^(\s*)([A-Za-z_]+):\s*(\[.*\])?", line)
            if not match or line.lstrip().startswith("#"):
                out.append(line)
                continue
            indent, key, listed = len(match.group(1)), match.group(2), match.group(3)
            stack = [(i, k) for i, k in stack if i < indent] + [(indent, key)]
            if listed:
                path_keys = [k for _, k in stack][1:]           # drop "voices"
                role = path_keys[0]
                region = path_keys[1] if len(path_keys) > 2 else "default"
                gender = next((k for k in path_keys if k in ("female", "male")), None)
                band = path_keys[3] if role == "customer" and len(path_keys) > 3 else None
                ids = re.findall(r'"([A-Za-z0-9]{20})"', line)
                taken = {i for i in ids if i in have}
                for old in ids:
                    if old in have or gender is None:
                        continue
                    new = pick(gender, region, band, taken)
                    if new:
                        line = line.replace(f'"{old}"', f'"{new}"', 1)
                        taken.add(new)
                        changes.append(("/".join(path_keys), old, new))
            out.append(line)
        if changes:
            path.with_suffix(path.suffix + ".bak").write_text(text, encoding="utf-8")
            path.write_text("".join(out), encoding="utf-8")
            self.voices = yaml.safe_load(path.read_text(encoding="utf-8"))["voices"]
            self.unavailable = set(self.missing_voices())
        return changes

    def missing_voices(self) -> list[str]:
        """Configured voice IDs this API key cannot use (not added to the account's My Voices)."""
        def walk(node):
            if isinstance(node, dict):
                for value in node.values():
                    yield from walk(value)
            elif isinstance(node, list):
                yield from node
        configured = sorted(set(walk(self.voices)))
        # One request for the account's voices (My Voices). A restricted key may list them yet lack voices_read,
        # which the per-voice lookup needs: every voice then answered 401 and was taken for missing.
        listing = httpx.get("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": self.api_key}, timeout=60)
        if listing.is_success:
            mine = {voice["voice_id"] for voice in listing.json().get("voices", [])}
            return [voice_id for voice_id in configured if voice_id not in mine]
        missing = []
        for voice_id in configured:
            response = httpx.get(f"https://api.elevenlabs.io/v1/voices/{voice_id}",
                                 headers={"xi-api-key": self.api_key}, timeout=30)
            if response.status_code in (401, 403):   # a permission, not a voice, is missing: say so
                raise RuntimeError("This ElevenLabs key cannot read voices (enable Voices: read for it): "
                                   + response.text[:200])
            if response.is_error:
                missing.append(voice_id)
        return missing

    def synthesize_turn(self, text: str, voice_id: str, *, stability: float = .5,
                        similarity_boost: float = .75, style: float = .2, rate_hint: float = 1.0,
                        model_id: str = "eleven_v4", language_code: str | None = "vi") -> bytes:
        payload = {"text": text, "model_id": model_id,
                   "voice_settings": {"stability": stability, "similarity_boost": similarity_boost, "style": style,
                                       "speed": rate_hint, "use_speaker_boost": True}}
        if language_code:
            payload["language_code"] = language_code
        key = hashlib.sha256(json.dumps({"voice_id": voice_id, **payload}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        cached = TTS_CACHE_DIR / f"{key}.pcm"
        if cached.exists():
            self.cache_hits += 1
            return cached.read_bytes()
        if self.characters_sent + len(text) > self.char_budget:
            raise RuntimeError("ElevenLabs character budget exceeded")
        response = httpx.post(f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={"xi-api-key": self.api_key, "Accept": "audio/pcm;rate=16000", "Content-Type": "application/json"},
            params={"output_format": "pcm_16000"}, json=payload, timeout=90)
        if response.is_error:
            detail = response.text.strip() or "no response body"
            if response.status_code == 402 and "paid_plan_required" in detail:
                detail += (" -> this account's plan cannot use library voices through the API: upgrade the plan, use a "
                           "key of a paid account, or run with --free-voices-only (premade English voices)")
            raise RuntimeError(
                f"ElevenLabs TTS failed ({response.status_code}) for voice "
                f"{voice_id}: {detail}"
            )
        self.characters_sent += len(text)
        TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(response.content)
        return response.content
