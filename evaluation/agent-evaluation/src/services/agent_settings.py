"""Ask the agent's own interpreter about the agent, and log a finished run to Langfuse.

Both run a child process in ``apps/ai-agent-service``'s venv (``AGENT_PYTHON``), from ``evaluation/agent-evaluation``:

- :func:`product_settings`: the advisor's provider, model and parameters as the agent reads them
  (``config/models.yaml``, or ``--advisor``), and the extractor's (``--extractor``, else OpenAI ``gpt-4.1-mini``);
- :func:`log_spend`: ``src.services.agent.langfuse_log`` sends the run's tokens, cost and scores to Langfuse.
"""
import json
import os
from pathlib import Path
import subprocess

from src.services.agent.launch import EVALUATION, SERVICE, python as agent_python

PRODUCT = SERVICE
PYTHON = agent_python()
DEFAULT_EXTRACTOR = "openai:gpt-4.1-mini"
#: What the agent's interpreter reports about the agent it would run.
QUERY = """
import json, os
from src.services.agent.bridge import parameters
from ai_agent_service.config.config_manager import get_models_config, has_api_key
m = get_models_config()
def pick(spec, fallback):
    provider, _, model = (spec or fallback).partition(":")
    if not has_api_key(provider):
        raise SystemExit(f"No API key for provider {provider!r} (model {model!r}); set it in .env")
    return provider, model
a = m.agent("advisor")
provider, model = pick(os.environ.get("EVAL_ADVISOR"), a.provider + ":" + a.model)
default = os.environ.get("EVAL_EXTRACTOR") or ("openai:gpt-4.1-mini" if has_api_key("openai") else provider + ":" + model)
xp, xm = pick(default, default)
print(json.dumps({"provider": provider, "model": model, "parameters": parameters(provider, model),
                  "extractor": m.llm_config(xp, xm, agent="extractor")}))
"""


def product_settings(advisor=None, extractor=None):
    env = {**os.environ, "PYTHONUTF8": "1"}
    for key, value in (("EVAL_ADVISOR", advisor), ("EVAL_EXTRACTOR", extractor)):
        if value:
            env[key] = value
    result = subprocess.run([str(PYTHON), "-B", "-c", QUERY], cwd=EVALUATION, capture_output=True, text=True,
                            encoding="utf-8", timeout=120, env=env)
    if result.returncode:
        raise RuntimeError("The agent's settings could not be read: " + (result.stderr.strip().splitlines() or ["?"])[-1])
    return json.loads(result.stdout.strip().splitlines()[-1])


def git_state():
    def git(*args):
        return subprocess.run(["git", *args], cwd=PRODUCT, capture_output=True, text=True).stdout.strip()
    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}


def log_spend(run, *, force=False):
    """Log *run*'s spend and scores to Langfuse (``src/services/agent/langfuse_log.py``), with the
    agent's interpreter, which has Langfuse. Never fails the evaluation."""
    command = [str(PYTHON), "-B", "-m", "src.services.agent.langfuse_log", str(Path(run).resolve())] + (["--force"] if force else [])
    try:
        result = subprocess.run(command, cwd=EVALUATION, capture_output=True, text=True, encoding="utf-8",
                                timeout=300, env={**os.environ, "PYTHONUTF8": "1"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"Langfuse logging failed: {type(exc).__name__}: {exc}"
    lines = (result.stdout or "").strip().splitlines()
    if result.returncode or not lines:
        return "Langfuse logging failed: " + ((result.stderr or "").strip().splitlines() or ["no output"])[-1]
    return lines[-1]
