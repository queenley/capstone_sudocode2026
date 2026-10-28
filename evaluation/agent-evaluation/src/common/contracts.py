"""The evaluator's contracts (``contracts/``): its JSON schemas, and the organisers' files pinned by hash.

- :data:`checker` is ``contracts/check_contracts.py``: JSON-schema checks, and ``verify_sources()`` that refuses to go
  on when a file under ``contracts/sources/btc`` differs from ``sources.lock.json``.
- :func:`validate` checks one object against a definition of ``contracts.schema.json``.
- :func:`btc_module` loads the organisers' ``reference_eval.py`` after that check, to call its functions
  (``check_call``, ``wer_cer``, ``rag_eval``, ``p95``) instead of re-implementing them.
"""
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2] / "contracts"
spec = importlib.util.spec_from_file_location("evaluation_contract_checker", ROOT / "check_contracts.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def validate(definition, data):
    errors = checker.errors(f"contracts.schema.json#/$defs/{definition}", data)
    if errors:
        raise ValueError(f"{definition}: " + "; ".join(error.message for error in errors))


def btc_module():
    """The organisers' unmodified ``reference_eval.py``, loaded after its hash is verified."""
    checker.verify_sources()
    spec = importlib.util.spec_from_file_location("btc_reference_eval", ROOT / "sources/btc/eval/reference_eval.py")
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)
    return module
