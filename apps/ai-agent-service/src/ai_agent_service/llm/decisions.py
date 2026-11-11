"""Typed answers from OpenAI's Decisions API: the probability that a statement holds.

``POST /v1/decisions`` on ``gpt-6-luna`` reads shared input and answers up to 400 questions, each independently, and
writes no text. That is the soft guardrail's job in ``docs/design.md`` section 4.5, which is why the PolicyAgent asks it
rather than prompting a chat model for a verdict: the answer is a probability to threshold, not a word to parse.

What the guide (developers.openai.com/api/docs/guides/decisions) says about the shape of a request, and this module does:

- What all questions share goes in ``input``, questions stay out of the reusable prefix, and a prefix needs 1,024
  tokens to be cached. So the definitions go first, in a developer message that never changes (:func:`rules_message`),
  with an explicit breakpoint: it is reused across turns and calls whatever follows it.
- ``input_json`` is taken only in a user message, and a breakpoint only on a text part (:func:`evidence_message`).
- A question may be refused while the others are answered: its probability is None here.

The discipline of the chat path stays: one shared limiter, a slot reserved before the request goes out, a cooldown on
429, every figure in ``config/models.yaml``. The difference is failing fast: whatever calls this has a customer
waiting, so there is no retry, and an answer that is not here within the evaluator's ``timeout`` is
:class:`DecisionUnavailable`. The caller then decides by rule.

Nothing reaches this API that intake has not tokenised (section 4.1): no raw customer text.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Mapping, Sequence

import openai
from pydantic import BaseModel

from ..config.config_manager import PROVIDER_ENV_VAR, get_models_config, has_api_key, require_api_key
from . import evaluation_budget, spend_guard, token_ledger, tracing
from .factory import limiter_for

logger = logging.getLogger(__name__)

#: Marks where a reusable prefix ends.
BREAKPOINT = {"mode": "explicit"}


class Predicate(BaseModel):
    """The probability that a statement holds. The definitions are in the developer message, not here."""

    instructions: str
    #: The hash of the definitions it is read against: part of a run's manifest, which hashes the questions.
    rules_sha: str = ""


class Answer(BaseModel):
    """One question's answer. ``probability`` is None when the model declined to answer."""

    probability: float | None = None


class Decision(BaseModel):
    """Everything one request returned, with what it cost."""

    model: str
    answers: dict[str, Answer]
    input_tokens: int = 0
    cached_tokens: int = 0
    seconds: float


class DecisionUnavailable(RuntimeError):
    """No answer in time. The caller falls back to rules.

    ``code`` says why, for the trace and for ``flags``: ``NO_KEY``, ``THROTTLED`` (our own limiter had no slot),
    ``RATE_LIMITED`` (the API said 429), ``TIMEOUT``, ``NETWORK``, ``INVALID`` (an answer was missing), or the API's
    own error code.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


_client: openai.AsyncOpenAI | None = None


def _api() -> openai.AsyncOpenAI:
    """One client for the process, opened on first use. No retries underneath the limiter."""
    global _client
    if _client is None:
        _client = openai.AsyncOpenAI(api_key=require_api_key("openai"), max_retries=0)
    return _client


async def close() -> None:
    """Close the connection pool. For the API's shutdown."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None


def rules_message(rules: str) -> dict[str, Any]:
    """The definitions, first in every request, with a breakpoint: they never change."""
    return {"role": "developer", "content": [{"type": "input_text", "text": rules, "prompt_cache_breakpoint": BREAKPOINT}]}


def evidence_message(evidence: Mapping[str, Any], *, note: str, reusable: bool = False) -> dict[str, Any]:
    """JSON evidence with a line saying what it is; *reusable* evidence, which later requests repeat, ends a prefix."""
    text: dict[str, Any] = {"type": "input_text", "text": note}
    if reusable:
        text["prompt_cache_breakpoint"] = BREAKPOINT
    return {"role": "user", "content": [{"type": "input_json", "data": dict(evidence)}, text]}


async def evaluate(
    caller: str,
    messages: Sequence[Mapping[str, Any]],
    questions: Mapping[str, Predicate],
    *,
    timeout: float | None = None,
    wait: bool = False,
) -> Decision:
    """Ask the model routed to *caller* under ``evaluators``, which also fixes the timeout and tags the ledger.

    Raises :class:`DecisionUnavailable` instead of retrying. ``wait`` lets a check running beside the reply wait for a
    slot of the limiter; a check that holds a reply is refused one instead.
    """
    spend_guard.check()
    config = get_models_config().evaluator_config(caller)
    if timeout is not None:
        config = {**config, "timeout": timeout}
    provider = config["provider"]
    if not has_api_key(provider):
        raise DecisionUnavailable("NO_KEY", f"{PROVIDER_ENV_VAR.get(provider, provider)} is not set")
    limiter = limiter_for(provider, config["rate_limits"], config["model"])
    if not await limiter.aacquire(blocking=wait):
        raise DecisionUnavailable("THROTTLED", "no slot in the local rate limit")

    names = list(questions)
    body = {
        "model": config["model"],
        "input": list(messages),
        "questions": [{"type": "predicate", "name": name, "instructions": questions[name].instructions} for name in names],
    }
    rates = config["rate_limits"]
    price = rates["input_token_price_per_million"] / 1_000_000
    # A token is at least one UTF-8 byte, so the bytes sent bound the tokens; a failed request keeps the reservation.
    reservation = evaluation_budget.reserve(f"{caller}:{config['model']}",
                                            max(1, len(json.dumps(body, ensure_ascii=False).encode())) * price * 1.25)
    started = time.perf_counter()
    try:
        response = await _api().decisions.create(**body, timeout=config["timeout"])
    except openai.APITimeoutError as error:
        limiter.record_failure()
        raise DecisionUnavailable("TIMEOUT", f"no answer within {config['timeout']}s") from error
    except openai.RateLimitError as error:
        limiter.record_rate_limited(_retry_after(error))
        raise DecisionUnavailable("RATE_LIMITED", "the API refused the call for quota") from error
    except openai.APIConnectionError as error:
        limiter.record_failure()
        raise DecisionUnavailable("NETWORK", type(error).__name__) from error
    except openai.APIStatusError as error:
        limiter.record_failure()
        raise DecisionUnavailable(str(error.code or error.status_code), error.message) from error
    seconds = time.perf_counter() - started

    usage = response.usage
    details = usage.input_tokens_details
    cached, written = int(details.cached_tokens or 0), int(details.cache_write_tokens or 0)
    limiter.record_request(usage.input_tokens, usage.output_tokens)
    token_ledger.record(f"{caller}:{config['model']}", usage.input_tokens, usage.output_tokens, cached)
    # Langfuse prices it by its own definition of the model, cached input at its cached rate: the real spend.
    tracing.record_generation(f"decisions:{caller}", LANGFUSE_MODEL.get(config["model"], config["model"]), {
        "input": max(0, usage.input_tokens - cached - written), "input_cached_tokens": cached,
        "input_cache_creation": written, "output": usage.output_tokens}, {"questions": names})
    # Reads cost a tenth of the input rate and writes 1.25 times; both are within input_tokens. Output is not charged.
    evaluation_budget.settle(reservation, (usage.input_tokens - cached - written + cached * 0.1 + written * 1.25) * price)

    answers = {answer.name: answer for answer in response.answers}
    if set(names) - set(answers):
        raise DecisionUnavailable("INVALID", f"no answer for {sorted(set(names) - set(answers))}")
    return Decision(
        model=response.model,
        answers={name: Answer(probability=getattr(answers[name], "probability", None)) for name in names},
        input_tokens=usage.input_tokens,
        cached_tokens=cached,
        seconds=seconds,
    )


#: Langfuse's own name for a Decisions model, the one its price table matches.
LANGFUSE_MODEL = {"gpt-6-luna": "global.openai.gpt-6-luna"}


def _retry_after(error: openai.APIStatusError) -> float | None:
    try:
        return float(error.response.headers.get("retry-after", ""))
    except ValueError:
        return None
