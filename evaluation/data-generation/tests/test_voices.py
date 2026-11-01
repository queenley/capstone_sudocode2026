"""Configured voices the ElevenLabs key cannot use are skipped; the nearest group that has one speaks instead."""
import pytest

from src.providers.elevenlabs_client import ElevenLabsClient


@pytest.fixture
def tts(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test")
    voices = tmp_path / "voices.yaml"
    voices.write_text("""voices:
  customer:
    bac:
      female: {adult: [gone1, keep1], senior: [gone2]}
    nam:
      female: {adult: [south1]}
    default:
      female: [fallback1]
""", encoding="utf-8")
    client = ElevenLabsClient(voices, tmp_path, 100)
    client.unavailable = {"gone1", "gone2"}
    return client


def test_an_unavailable_voice_is_never_picked(tts):
    assert {tts.pick_voice("customer", "female", "bac", "adult", f"C{i}") for i in range(20)} == {"keep1"}


def test_an_empty_group_falls_back_to_the_regions_other_ages_then_other_regions(tts):
    assert tts.pick_voice("customer", "female", "bac", "senior", "C1") == "keep1"
    tts.unavailable.add("keep1")
    assert tts.pick_voice("customer", "female", "bac", "senior", "C1") == "south1"
    tts.unavailable.add("south1")
    assert tts.pick_voice("customer", "female", "bac", "senior", "C1") == "fallback1"
    tts.unavailable.add("fallback1")
    with pytest.raises(RuntimeError):
        tts.pick_voice("customer", "female", "bac", "senior", "C1")


def test_a_missing_voice_is_replaced_by_one_of_the_same_gender_accent_and_age(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test")
    path = tmp_path / "voices.yaml"
    path.write_text('voices:\n  customer:\n    nam:\n      female:\n'
                    '        senior: ["goneAAAAAAAAAAAAAAAA", "keepAAAAAAAAAAAAAAAA"]  # names\n', encoding="utf-8")
    account = [{"voice_id": "keepAAAAAAAAAAAAAAAA", "labels": {"gender": "female", "accent": "southern", "age": "old", "language": "vi"}},
               {"voice_id": "northOldFAAAAAAAAAAA", "labels": {"gender": "female", "accent": "northern", "age": "old", "language": "vi"}},
               {"voice_id": "southOldMAAAAAAAAAAA", "labels": {"gender": "male", "accent": "southern", "age": "old", "language": "vi"}},
               {"voice_id": "southOldFAAAAAAAAAAA", "labels": {"gender": "female", "accent": "southern", "age": "old", "language": "vi"}},
               {"voice_id": "englishFAAAAAAAAAAAA", "labels": {"gender": "female", "accent": "american", "age": "old", "language": "en"}}]
    tts = ElevenLabsClient(path, tmp_path, 100)
    monkeypatch.setattr(tts, "account_voices", lambda: account)
    monkeypatch.setattr(tts, "missing_voices", lambda: [])
    changes = tts.replace_missing_voices(path)
    assert changes == [("customer/nam/female/senior", "goneAAAAAAAAAAAAAAAA", "southOldFAAAAAAAAAAA")]
    assert path.read_text(encoding="utf-8").endswith('["southOldFAAAAAAAAAAA", "keepAAAAAAAAAAAAAAAA"]  # names\n')
    assert (tmp_path / "voices.yaml.bak").read_text(encoding="utf-8").count("goneAAAA") == 1
