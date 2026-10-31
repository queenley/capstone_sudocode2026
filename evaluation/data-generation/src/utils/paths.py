"""Filesystem layout of the data-generation project.

Every stage imports paths from here instead of re-deriving them, so moving a
folder only requires one edit. Where each generated file goes inside
``output/`` is ``src/utils/dataset.py``'s job.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Inputs (read-only; never overwritten by the pipeline except the synthetic CRM)
CONFIG_DIR = ROOT / "config"
#: The organisers' pack: the one copy there is, the agent's (``apps/ai-agent-service/data/btc``). ``BTC_DATA_DIR``
#: points elsewhere, as it does for the agent. The synthetic CRM this project generates is written into its catalogue.
DATA_DIR = Path(os.environ.get("BTC_DATA_DIR") or ROOT.parents[1] / "apps" / "ai-agent-service" / "data" / "btc").resolve()
CATALOG_DIR = DATA_DIR / "catalog"
POLICY_DIR = DATA_DIR / "policy"
SIMULATOR_DIR = DATA_DIR / "simulator"
PERSONAS_JSON = SIMULATOR_DIR / "personas.json"
PROMPTS_DIR = ROOT.parents[1] / "config" / "prompts" / "data-generation"  # the repository's prompt folder
SAMPLE_DIR = DATA_DIR / "test_set" / "public_sample"   # the seven scenarios BTC ships

# Outputs (layout: src/utils/dataset.py)
OUTPUT_DIR = ROOT / "output"
PLAN_PREVIEW_DIR = OUTPUT_DIR / "plan_preview"        # --plan-only: the same layout, placeholder customer turns
AUDIO_DIR = OUTPUT_DIR / "audio"
ASR_REFERENCE_DIR = OUTPUT_DIR / "asr_reference"   # spoken form of each customer turn + ground_truth.json of the audio
ASR_TEST_DIR = OUTPUT_DIR / "asr_test"
RAG_DIR = OUTPUT_DIR / "rag"
REVIEW_DIR = OUTPUT_DIR / "review"
REPORTS_DIR = OUTPUT_DIR / "reports"

VALIDATION_JSON = REPORTS_DIR / "validation.json"
SIMULATION_REPLAYS = REPORTS_DIR / "simulation_replays.jsonl"
GOLDEN_MANIFEST = REVIEW_DIR / "golden_manifest.json"
MODEL_CALLS_LOG = REPORTS_DIR / "model_calls.jsonl"
CACHE_DIR = ROOT / ".cache" / "models"
