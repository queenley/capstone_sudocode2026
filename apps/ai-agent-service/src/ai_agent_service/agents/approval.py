"""ApprovalAgent: accepts or refuses a Reflection change in the reviewer's place, against the lesson we accept.

We write the learning set, so we know, per situation, the lesson we accept (``expected.yaml`` beside the set's
``learn/`` and ``frozen/``: one ``accept`` text per situation). This agent reads only the accepted lesson of the
situations the change's evidence calls are in (each scenario's ``metadata/<id>.json``), the change, the rules it cites
and what the PolicyAgent found, and answers once: the same lesson, in other words or not, is accepted; a different one
is refused.

It never writes a change, so no agent both writes and approves (``components/improvement/review.py``). Without an
expectation for the evidence it is not asked, and the change waits for a person. Its answers go through the answer
store, so a round run again is decided the same way.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from ..components.improvement import answers
from ..config.config_manager import load_prompt
from .base import model_for

logger = logging.getLogger(__name__)

class Approval(BaseModel):
    approve: bool = Field(description="True when the change teaches the accepted lesson, in its words or others.")
    reason: str = Field(description="One sentence, written into the review file: why it was accepted or refused.")


def expectations(scenarios: Path, scenario_ids: Iterable[str]) -> dict[str, Any]:
    """The accepted lessons of the situations *scenario_ids* are in: ``expected.yaml`` of their set, by situation.

    *scenarios* is the set's ``learn/scenarios`` folder; the situation of each scenario is its metadata's. Empty when
    the set states no expectation."""
    path = scenarios.parent.parent / "expected.yaml"
    if not path.is_file():
        return {}
    expected = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    situations = set()
    for sid in scenario_ids:
        meta = scenarios.parent / "metadata" / f"{sid}.json"
        if meta.is_file():
            situations.add(json.loads(meta.read_text(encoding="utf-8")).get("situation"))
    return {name: expected[name] for name in sorted(s for s in situations if s) if name in expected}


class ApprovalAgent:
    """One structured answer per change; the model is ``agents.approval`` in ``config/models.yaml``."""

    def __init__(self, *, llm: BaseChatModel | None = None) -> None:
        self.name = "approval"
        self._llm = llm

    @property
    def llm(self) -> BaseChatModel | None:
        if self._llm is None:
            self._llm = model_for(self.name)
        return self._llm

    async def decide(self, proposal: Mapping[str, Any], expected: Mapping[str, Any], *,
                     cited_rules: Mapping[str, str]) -> Approval | None:
        """Approve or refuse *proposal* against *expected*; None without a model, an expectation, or an answer."""
        if not expected or self.llm is None:
            return None
        entry = proposal.get("entry") or {}
        change = {"where": entry.get("where"), "replaces": entry.get("find") or "(added at the end)",
                  "description_adds": entry.get("when") or "(nothing)",
                  "text": entry.get("text"), "cites": entry.get("cites") or [], "why": proposal.get("why"),
                  "screen_flags": [f for f in proposal.get("flags") or [] if not str(f).startswith("policy:")],
                  "policy_agent": list(proposal.get("policy") or []) or ["passed"]}
        request = "\n\n".join([load_prompt("approval_decide.md"),
                               "ACCEPTED:\n" + yaml.safe_dump(dict(expected), allow_unicode=True, sort_keys=False),
                               "CITED RULES:\n" + ("\n".join(f"[{c}] {t}" for c, t in cited_rules.items()) or "(none)"),
                               "CHANGE:\n" + json.dumps(change, ensure_ascii=False, indent=1)])

        async def ask() -> dict[str, Any] | None:
            try:
                return (await self.llm.with_structured_output(Approval).ainvoke(request)).model_dump()
            except Exception as error:  # noqa: BLE001 - no answer leaves the change to a person
                logger.warning("Approval failed: %s", type(error).__name__)
                return None

        found = await answers.remember("approval.decide", answers.model_label(self.llm), request, ask)
        return Approval.model_validate(found) if found else None
