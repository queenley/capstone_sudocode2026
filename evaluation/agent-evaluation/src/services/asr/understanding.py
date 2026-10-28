"""What the agent understands from what was heard: ai-agent-service's own pipeline, never one of the evaluator's.

On a real call a recognised line goes, in ``ai_agent_service``:

1. ``api/routes/voice.py``: ``lexicon.correct`` (mishearings of product names, "e pia" → AirPure);
2. ``pipeline/hot/nodes.perceive``: ``lexicon.correct`` again for an ``asr_transcript`` turn, ``intake.text.clean``
   (teencode, NFC), ``itn.normalise`` (spoken numbers and dates to written), ``pii.tokenise`` (phone, address);
3. after the call, ``MemoryAgent.extract``: one structured-output call of the ``agents.memory`` model of
   ``config/models.yaml`` over the transcript (its rules when no model or key: ``--understanding rules``).

:class:`AgentUnderstanding` runs exactly those functions on the heard lines and maps the slots the agent took from the
customer's words to BTC's entity keys (:data:`MEMORY_TO_BTC`). Keys the agent never reads from speech by design
(the price, a SKU or an order id come from its tools; a phone number is tokenised) are not counted against it;
the report lists them separately.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime
import unicodedata

#: The agent's slot (``components/memory/ontology.py``) → BTC's ``asr/ground_truth.json`` key.
MEMORY_TO_BTC = {"room_area_m2": "room_area_m2", "has_children": "has_children", "budget_vnd": "budget_vnd",
                 "competitor_price_vnd": "competitor_price_vnd", "payment": "payment", "blocker": "blocker",
                 "size": "size_new", "color": "color"}
#: The BTC keys the agent's pipeline can state from what a customer says.
UNDERSTOOD = frozenset(MEMORY_TO_BTC.values())


def plain(text: str) -> str:
    """Lowercase, no diacritics, single spaces: the agent writes "cần hỏi chồng", BTC labels "can hoi chong"."""
    folded = unicodedata.normalize("NFD", str(text).lower().replace("đ", "d"))
    return " ".join("".join(ch for ch in folded if unicodedata.category(ch) != "Mn").split())


class AgentUnderstanding:
    def __init__(self, *, use_model: bool = True, reference_date: str = "2026-10-15") -> None:
        from src.services.agent import launch

        launch.prepare()
        from ai_agent_service.agents.memory import MemoryAgent
        from ai_agent_service.components.intake import itn, lexicon, pii, text
        from ai_agent_service.config.config_manager import get_models_config
        from ai_agent_service.llm import token_ledger

        self.itn, self.lexicon, self.pii, self.text, self.ledger = itn, lexicon, pii, text, token_ledger
        self.memory = MemoryAgent(use_model=use_model)
        self.version = self.memory.version
        self.provider = get_models_config().agent_llm_config("memory").get("provider") if self.memory.llm else None
        self.on = reference_date
        self.now = datetime.combine(date.fromisoformat(reference_date), datetime.min.time())
        self._cache: dict[tuple, dict] = {}

    def perceive(self, heard: str, *, lexicon: bool) -> str:
        """``nodes.perceive`` on an ASR line: (lexicon), clean, ITN, tokenise."""
        raw = self.lexicon.correct(heard) if lexicon else heard
        cleaned, _ = self.text.clean(raw)
        written = self.itn.normalise(cleaned, self.now)
        return self.pii.tokenise(written, self.pii.Vault())

    def entities(self, lines: list[dict], *, lexicon: bool) -> dict:
        """BTC entities the agent takes from *lines* (``{speaker: A|C, text}``, what the recogniser heard)."""
        key = (lexicon, tuple((line["speaker"], line["text"]) for line in lines))
        if key not in self._cache:
            transcript = [{"turn": i, "speaker": "customer" if line["speaker"] == "C" else "agent",
                           "text": self.perceive(line["text"], lexicon=lexicon)}
                          for i, line in enumerate(lines, start=1) if line["text"].strip()]
            found = asyncio.run(self.memory.extract(transcript, [], on=self.on)) if transcript else []
            stated: dict = {}
            for candidate in sorted(found, key=lambda c: c.turn):
                name = MEMORY_TO_BTC.get(candidate.slot or "")
                if name and candidate.said_by == "customer":
                    stated[name] = plain(candidate.value) if name in ("blocker", "color") else candidate.value
            self._cache[key] = stated
        return self._cache[key]

    def usage(self) -> dict:
        """Tokens (and USD when ``models.yaml`` prices the provider) the memory model spent."""
        from src.services.agent import spend

        spent = self.ledger.snapshot().get("memory", {})
        if not self.provider:
            return {"model": None, "note": "rules: no model call"}
        return {"model": self.memory.model_name, **spend.usage(self.provider, spent.get("input") or 0, spent.get("output") or 0)}
