"""Filesystem layout of the data-generation project.

Every stage imports paths from here instead of re-deriving them, so moving a
folder only requires one edit.
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
PROMPTS_DIR = ROOT / "src" / "prompts"

# Outputs
OUTPUT_DIR = ROOT / "output"
PLANS_DIR = OUTPUT_DIR / "plans"                      # deterministic call plans + labels (no LLM)
SCENARIOS_INTERNAL_DIR = OUTPUT_DIR / "scenarios_internal"  # full scenario incl. pipeline-only fields
SCENARIOS_DIR = OUTPUT_DIR / "scenarios"              # BTC scenario_format export
CONVERSATIONS_DIR = OUTPUT_DIR / "conversations"      # one reference transcript per call
JUDGMENTS_DIR = OUTPUT_DIR / "judgments"
SIMULATIONS_DIR = OUTPUT_DIR / "simulations"
AUDIO_DIR = OUTPUT_DIR / "audio"
REVIEW_DIR = OUTPUT_DIR / "review"
GOLDEN_DIR = OUTPUT_DIR / "golden"
REPORTS_DIR = OUTPUT_DIR / "reports"

VALIDATION_JSON = REPORTS_DIR / "validation.json"
MODEL_CALLS_LOG = REPORTS_DIR / "model_calls.jsonl"
CACHE_DIR = ROOT / ".cache" / "models"
