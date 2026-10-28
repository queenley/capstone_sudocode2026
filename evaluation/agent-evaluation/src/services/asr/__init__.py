"""ASR evaluation: data-generation makes the ground truth, the agent's own pipeline hears and understands the audio.

    data-generation                                  agent-evaluation
    ───────────────                                  ────────────────
    text → spoken form (LLM) → TTS reads it          asr-build: pin ground_truth.json + audio + hashes (dataset.py)
    entities of that text, BTC keys + entity_schema  asr: engine hears (engines.py; dialogues: diarization.py)
    asr_reference/ (turns), asr_test/ (dialogues)         → agent's lexicon, intake, MemoryAgent (understanding.py)
                                                          → BTC wer_cer: WER/CER/entities/diarization (evaluate.py)
"""
from src.services.asr.dataset import DEFAULT_SET, build_set, check_set, restore_audio

__all__ = ["DEFAULT_SET", "build_set", "check_set", "restore_audio"]
