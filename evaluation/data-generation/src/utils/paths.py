"""Filesystem layout of the data-generation project.

Every stage imports paths from here instead of re-deriving them, so moving a
folder only requires one edit. Where each generated file goes inside the
output folder is ``src/utils/dataset.py``'s job.

The output folder is a seed of the repository's data, ``data/seed-<name>/`` at the
repository root: ``DATAGEN_SEED`` names it (default ``dev``), ``run_all --seed``
sets it for every stage, and ``DATAGEN_OUTPUT`` replaces the whole path.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ROOT.parents[1]

#: API keys (OPENAI_API_KEY, GEMINI_API_KEY, ELEVENLABS_API_KEY): every provider client reads this one file.
ENV_FILE = ROOT / ".env"

# Inputs (read-only; never overwritten by the pipeline except the synthetic CRM)
CONFIG_DIR = ROOT / "config"
#: The organisers' pack: the one copy there is, the agent's (``apps/ai-agent-service/data/btc``). ``BTC_DATA_DIR``
#: points elsewhere, as it does for the agent. The synthetic CRM this project generates is written into its catalogue.
DATA_DIR = Path(os.environ.get("BTC_DATA_DIR") or REPO_ROOT / "apps" / "ai-agent-service" / "data" / "btc").resolve()
CATALOG_DIR = DATA_DIR / "catalog"
POLICY_DIR = DATA_DIR / "policy"
SIMULATOR_DIR = DATA_DIR / "simulator"
PERSONAS_JSON = SIMULATOR_DIR / "personas.json"
PROMPTS_DIR = REPO_ROOT / "config" / "prompts" / "data-generation"  # the repository's prompt folder
SAMPLE_DIR = DATA_DIR / "test_set" / "public_sample"   # the seven scenarios BTC ships

#: Every key a scenario may carry (src/schemas/keys.py checks each scenario against it).
KEYS_FILE = REPO_ROOT / "contracts" / "scenario" / "scenario-keys.yaml"

# Outputs (layout: src/utils/dataset.py)
SEED_ENV = "DATAGEN_SEED"
SEED = os.environ.get(SEED_ENV) or "dev"
OUTPUT_DIR = Path(os.environ.get("DATAGEN_OUTPUT") or REPO_ROOT / "data" / f"seed-{SEED}").resolve()
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
