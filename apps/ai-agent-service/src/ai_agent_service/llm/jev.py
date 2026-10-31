"""Typed decisions from an evaluation model: Jev, through Vercel AI Gateway.

Jev (``typesafe-ai/jev``) reads a piece of state and answers typed questions
about it. It never writes text. A question is one of three kinds:

- :class:`Choice` picks one of several named options and gives the
  probability of each;
- :class:`Score` places the state on an ordered scale of two to ten rungs;
- :class:`Boolean` gives the probability that a statement is true.

Several questions go in one request and are answered independently, so
adding a question never moves the answer to another. That is the soft
guardrail's job in ``docs/design.md`` section 4.5 exactly, which is why the
PolicyAgent asks Jev rather than prompting a chat model for a verdict: the
answer is a probability to threshold, not a word to parse.

The call is ``POST <base_url>/evaluate`` with the gateway key, as documented
at https://vercel.com/docs/ai-gateway/modalities/evaluation, or TypeSafe's
own API, ``POST https://api.typesafe.ai/v1/systemone`` with
``TYPESAFE_API_KEY`` (https://api.typesafe.ai/docs), chosen by the provider's
``api`` in ``config/models.yaml``. The two differ only in names, translated
here: a yes/no question is ``noul`` there and its answer's probability is
``noul``; usage is ``input_tokens``; an error is ``{"detail": ...}``. There is no
LangChain integration for evaluation models, so this module is the whole
client. What it keeps from the chat path is the discipline that path learned
the hard way: one shared limiter per provider, a slot reserved before the
request goes out, a cooldown when the gateway says 429, and every figure in
``config/models.yaml``.

What it does differently is fail fast. Everything that calls this sits on the
hot path with a customer waiting, so there is no retry and no queueing
behind the limiter: an answer that is not here within the evaluator's
``timeout`` is :class:`JevUnavailable`, and the caller decides by rule
instead. A late answer is worth less than a rule-based one.

Not done yet, and needed before an evaluation run can rely on it:

- a cache keyed on (model, state, questions), in the store of Appendix D, so
  ``eval replay`` makes no call;
- a Langfuse span per call. This runs outside LangChain, so the handler
  passed in a run's config never sees it.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Literal, Mapping, Sequence, Union

import httpx
from pydantic import BaseModel, Field

from ..config.config_manager import PROVIDER_ENV_VAR, get_models_config, has_api_key, require_api_key
from . import token_ledger, evaluation_budget
from .factory import limiter_for

logger = logging.getLogger(__name__)


# ── questions ─────────────────────────────────────────────────────────────


class Choice(BaseModel):
    """Pick one option. ``criteria`` maps each option's name to what it means."""

    type: Literal["choice"] = "choice"
    instructions: str
    criteria: dict[str, str] = Field(min_length=2, max_length=255)


class Score(BaseModel):
    """Place the state on a scale. ``criteria`` runs from lowest to highest."""

    type: Literal["score"] = "score"
    instructions: str
    criteria: list[str] = Field(min_length=2, max_length=10)


class Boolean(BaseModel):
    """The probability that a statement holds.

    ``criteria``, when given, says what counts as true and what as false.
    """

    type: Literal["boolean"] = "boolean"
    instructions: str
    criteria: dict[Literal["true", "false"], str] | None = None


Question = Union[Choice, Score, Boolean]

#: What ``state`` may be: text, one JSON object, or a JSON array read as a
#: single state rather than a batch. At most 32k tokens.
State = Union[str, Mapping[str, Any], Sequence[Any]]


# ── answers ───────────────────────────────────────────────────────────────


class Answer(BaseModel):
    """One question's answer. Which fields are set depends on ``type``.

    Probabilities are rounded to two decimals, so a distribution may sum to
    0.99. ``confidence`` summarises how concentrated a choice or score
    distribution is, from 0 to 1; booleans have none.
    """

    type: Literal["choice", "score", "boolean"]
    choice: str | None = None
    score: float | None = None
    probability: float | None = None
    probabilities: dict[str, float] = Field(default_factory=dict)
    confidence: float | None = None


class Decision(BaseModel):
    """Everything one request returned, with what it cost."""

    model: str
    answers: dict[str, Answer]
    input_tokens: int = 0
    seconds: float


class JevUnavailable(RuntimeError):
    """No answer in time. The caller falls back to rules.

    ``code`` says why, for the trace and for ``flags``: ``NO_KEY``,
    ``THROTTLED`` (our own limiter had no slot), ``RATE_LIMITED`` (the gateway
    said 429), ``TIMEOUT``, ``NETWORK``, ``INVALID`` (an answer was missing),
    or the gateway's own error type, such as
    ``customer_verification_required``.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


# ── the call ──────────────────────────────────────────────────────────────

_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    """One connection pool for the process, opened on first use."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient()
    return _client


async def close() -> None:
    """Close the connection pool. For the API's shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def evaluate(
    caller: str,
    state: State,
    questions: Mapping[str, Question],
    *,
    timeout: float | None = None,
) -> Decision:
    """Ask the evaluation model routed to *caller* in ``config/models.yaml``.

    *caller* names a block under ``evaluators``, which fixes the model and the
    timeout, and tags the tokens in the ledger. Raises
    :class:`JevUnavailable` instead of waiting or retrying.

    ``timeout`` replaces the configured one for this call. The hot path never
    passes it; a measurement does, to see how long an answer really takes.
    """
    config = get_models_config().evaluator_config(caller)
    if timeout is not None:
        config = {**config, "timeout": timeout}
    provider = config["provider"]
    if not has_api_key(provider):
        raise JevUnavailable("NO_KEY", f"{PROVIDER_ENV_VAR.get(provider, provider)} is not set")
    typesafe = config.get("api") == "typesafe"

    limiter = limiter_for(provider, config["rate_limits"], config["model"])
    if not await limiter.aacquire(blocking=False):
        raise JevUnavailable("THROTTLED", "no slot in the local rate limit")

    body: dict[str, Any] = {
        "model": config["model"],
        "state": state,
        "questions": {
            name: _question(question, typesafe)
            for name, question in questions.items()
        },
    }
    if config["zero_data_retention"] and not typesafe:
        body["providerOptions"] = {"gateway": {"zeroDataRetention": True}}

    started = time.perf_counter()
    price = config["rate_limits"]["input_token_price_per_million"] / 1_000_000
    # Jev accepts at most 32k input tokens; failed requests keep the reservation.
    reservation = evaluation_budget.reserve(f"{caller}:{config['model']}", 32_000 * price)
    try:
        response = await _http().post(
            config["url"],
            json=body,
            headers={"Authorization": f"Bearer {require_api_key(provider)}"},
            timeout=config["timeout"],
        )
    except httpx.TimeoutException as error:
        limiter.record_failure()
        raise JevUnavailable("TIMEOUT", f"no answer within {config['timeout']}s") from error
    except httpx.HTTPError as error:
        limiter.record_failure()
        raise JevUnavailable("NETWORK", type(error).__name__) from error
    seconds = time.perf_counter() - started

    if response.status_code == 429:
        limiter.record_rate_limited(_retry_after(response))
        raise JevUnavailable("RATE_LIMITED", "the gateway refused the call for quota")
    if response.status_code >= 400:
        limiter.record_failure()
        code, message = _error_of(response)
        raise JevUnavailable(code, message)

    payload = response.json()
    usage = payload.get("usage") or {}
    input_tokens = int(usage.get("inputTokens") or usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("outputTokens") or usage.get("output_tokens") or 0)
    limiter.record_request(input_tokens, output_tokens)
    token_ledger.record(f"{caller}:{config['model']}", input_tokens, output_tokens)
    if "inputTokens" in usage or "input_tokens" in usage:
        evaluation_budget.settle(reservation, input_tokens * price)

    confidence = ((payload.get("providerMetadata") or {}).get("typesafe") or {}).get(
        "confidence"
    ) or {}
    raw = payload.get("answers") or {}
    missing = set(questions) - set(raw)
    if missing:
        raise JevUnavailable("INVALID", f"no answer for {sorted(missing)}")

    return Decision(
        model=str(payload.get("model") or config["model"]),
        # The answer carries its own confidence; the gateway's metadata is
        # the fallback for when it does not.
        answers={
            name: Answer(**{"confidence": confidence.get(name), **_answer(raw[name])})
            for name in questions
        },
        input_tokens=input_tokens,
        seconds=seconds,
    )


def _question(question: Question, typesafe: bool) -> dict[str, Any]:
    """*question* as the API takes it: TypeSafe calls a yes/no question ``noul``."""
    dumped = question.model_dump(exclude_none=True)
    if typesafe and dumped["type"] == "boolean":
        dumped["type"] = "noul"
    return dumped


def _answer(raw: Mapping[str, Any]) -> dict[str, Any]:
    """An answer in the gateway's names: TypeSafe's ``noul`` is a boolean's probability.

    Fields :class:`Answer` does not keep (a score's ``legend``) are dropped.
    """
    if raw.get("type") == "noul":
        return {"type": "boolean", "probability": raw.get("noul")}
    return {key: value for key, value in raw.items() if key in Answer.model_fields}


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers.get("retry-after", ""))
    except ValueError:
        return None


def _error_of(response: httpx.Response) -> tuple[str, str]:
    """The API's error type and message, or the status when it gave none."""
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    error = payload.get("error") if isinstance(payload, dict) else None
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, dict):  # TypeSafe: {"detail": {"error_type", "message"}}
        error = {"type": detail.get("error_type"), "message": detail.get("message")}
    elif isinstance(detail, list) and detail:  # TypeSafe's validation errors
        first = detail[0] if isinstance(detail[0], dict) else {}
        error = {"type": "validation_error",
                 "message": f"{'.'.join(map(str, first.get('loc') or []))}: {first.get('msg')}"}
    if isinstance(error, dict):
        return (
            str(error.get("type") or error.get("code") or f"HTTP_{response.status_code}"),
            str(error.get("message") or response.reason_phrase),
        )
    return f"HTTP_{response.status_code}", str(error or response.reason_phrase)
