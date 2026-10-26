"""Filesystem layout of the data-generation project.

Every stage imports paths from here instead of re-deriving them, so moving a
folder only requires one edit. Where each generated file goes inside
``output/`` is ``src/utils/dataset.py``'s job.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Inputs (read-only; never overwritten by the pipeline except the synthetic CRM)
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
CATALOG_DIR = DATA_DIR / "catalog"
POLICY_DIR = DATA_DIR / "policy"
SIMULATOR_DIR = DATA_DIR / "simulator"
PERSONAS_JSON = SIMULATOR_DIR / "personas.json"
PROMPTS_DIR = ROOT.parents[1] / "config" / "prompts" / "data-generation"  # the repository's prompt folder
#: The agent's copy of BTC's catalogue, kept equal to CATALOG_DIR (build_catalog --sync).
AGENT_CATALOG_DIR = ROOT.parents[1] / "apps" / "ai-agent-service" / "data" / "btc" / "catalog"

# Outputs (layout: src/utils/dataset.py)
OUTPUT_DIR = ROOT / "output"
PLAN_PREVIEW_DIR = OUTPUT_DIR / "plan_preview"        # --plan-only: the same layout, placeholder customer turns
AUDIO_DIR = OUTPUT_DIR / "audio"
ASR_TEST_DIR = OUTPUT_DIR / "asr_test"
RAG_DIR = OUTPUT_DIR / "rag"
REVIEW_DIR = OUTPUT_DIR / "review"
REPORTS_DIR = OUTPUT_DIR / "reports"

VALIDATION_JSON = REPORTS_DIR / "validation.json"
SIMULATION_REPLAYS = REPORTS_DIR / "simulation_replays.jsonl"
GOLDEN_MANIFEST = REVIEW_DIR / "golden_manifest.json"
MODEL_CALLS_LOG = REPORTS_DIR / "model_calls.jsonl"
CACHE_DIR = ROOT / ".cache" / "models"
