from pathlib import Path

from dotenv import load_dotenv

# The repository's root .env, as run_eval.py reads it: the improvement loop runs beside the evaluation, on its keys.
load_dotenv(Path(__file__).resolve().parents[6] / ".env", override=False)

from ...llm import tracing  # noqa: E402  (the environment first)
from .cli import main  # noqa: E402

try:
    code = main()
finally:
    tracing.flush()  # the loop's model calls reach Langfuse before the process ends
raise SystemExit(code)
