"""OpenAI structured-output wrapper with persistent prompt cache and usage log."""
from __future__ import annotations

from src.utils.json_output import parse_output
from src.utils.quota import DailyLimitReached

import hashlib
import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar

from dotenv import load_dotenv
from src.utils.paths import ENV_FILE
from openai import BadRequestError
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class OpenAIClient:
    def __init__(self, model: str, cache_dir: Path, log_path: Path, retries: int = 3,
                 rpm_limit: int = 10, rpd_limit: int = 100,
                 retry_backoff_seconds: float = 2):
        load_dotenv(ENV_FILE)
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set; configure it in evaluation/data-generation/.env")
        from openai import OpenAI

        self.client = OpenAI(api_key=key)
        self.model, self.cache_dir, self.log_path, self.retries = model, cache_dir, log_path, retries
        self.retry_backoff_seconds = max(0, retry_backoff_seconds)
        self.rpm_limit, self.rpd_limit = max(1, rpm_limit), max(1, rpd_limit)
        self._call_times: list[float] = []
        self._call_day = datetime.now(timezone.utc).date()
        self._calls_today = self._read_calls_today()
        #: Schemas the API refused in strict mode (a free-form object such as a tool's args): sent non-strict.
        self._not_strict: set[str] = set()
        cache_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, prompt: str, schema: type[T], *, temperature: float = 0.7,
                 max_output_tokens: int = 8192) -> T:
        response_schema = schema.model_json_schema()
        params = {"model": self.model, "temperature": temperature,
                  "max_output_tokens": max_output_tokens,
              "schema": response_schema, "strict": False}
        digest = hashlib.sha256((prompt + json.dumps(params, sort_keys=True)).encode()).hexdigest()
        cache_file = self.cache_dir / f"{digest}.json"
        if cache_file.exists():
            self._log({"provider": "openai", "model": self.model, "cache_hit": True,
                       "elapsed_seconds": 0, "error": None})
            return schema.model_validate_json(cache_file.read_text(encoding="utf-8"))

        # The cache key above names the schema, not how it is enforced: strict mode allows no answer the schema
        # does not, so answers cached before it stay valid.
        prior_error = ""
        for attempt in range(self.retries):
            self._wait_for_rate_limit()
            started = time.monotonic()
            strict = self._strict_schema(schema)
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt +
                               (f"\n\nPrevious output validation error: {prior_error}" if prior_error else "")}],
                    response_format={"type": "json_schema", "json_schema": {
                        "name": schema.__name__, "strict": strict is not None, "schema": strict or response_schema}},
                    temperature=temperature,
                    max_tokens=max_output_tokens,
                    # One key per stage: requests that share the fixed prefix (instructions, policies) go to the
                    # same cache, which bills those tokens at the cached rate. The answer does not depend on it.
                    prompt_cache_key=f"datagen-{schema.__name__}",
                )
                result, repaired = parse_output(response.choices[0].message.content or "", schema)
                cache_file.write_text(result.model_dump_json(indent=2), encoding="utf-8")
                usage = response.usage
                details = getattr(usage, "prompt_tokens_details", None)
                self._log({"provider": "openai", "model": self.model, "cache_hit": False,
                           "attempt": attempt + 1, "json_repaired": repaired,
                           "prompt_tokens": getattr(usage, "prompt_tokens", None),
                           "cached_tokens": getattr(details, "cached_tokens", None),
                           "output_tokens": getattr(usage, "completion_tokens", None),
                           "elapsed_seconds": round(time.monotonic() - started, 3), "error": None})
                return result
            except BadRequestError as exc:
                if strict is None:
                    raise
                # The API's strict mode takes a subset of JSON Schema: this schema goes non-strict from now on.
                self._not_strict.add(schema.__name__)
                self._log_failure(attempt, started, f"strict schema refused, sent non-strict: {exc}")
            except (ValidationError, ValueError) as exc:
                prior_error = str(exc)
                if attempt + 1 >= self.retries:
                    self._log_failure(attempt, started, prior_error)
                    raise RuntimeError("OpenAI output could not be validated after retries") from exc
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                if attempt + 1 >= self.retries:
                    self._log_failure(attempt, started, error)
                    raise
                delay = self.retry_backoff_seconds * (2 ** attempt) * random.uniform(0.8, 1.2)
                self._log_failure(attempt, started, error, delay)
                time.sleep(delay)
        raise RuntimeError("OpenAI output could not be validated after retries")

    def _strict_schema(self, schema: type[BaseModel]) -> dict | None:
        """*schema* for Structured Outputs' strict mode, in which the API makes the model answer in exactly that
        shape (non-strict, gpt-4o-mini wrote ``{"asr_transcript": ...}`` for a string and keys where none belong).
        None when the SDK cannot convert it or the API refused it before."""
        if schema.__name__ in self._not_strict:
            return None
        try:
            from openai.lib._pydantic import to_strict_json_schema   # the SDK's own converter (a private module)
            converted = to_strict_json_schema(schema)
        except Exception:   # an SDK without it, or a type it cannot express
            self._not_strict.add(schema.__name__)
            return None
        _shape_only(converted)   # the shape is enforced; value limits stay with Pydantic
        return converted

    def _wait_for_rate_limit(self) -> None:
        utc_day = datetime.now(timezone.utc).date()
        if utc_day != self._call_day:
            self._call_day, self._calls_today = utc_day, self._read_calls_today()
        if self._calls_today >= self.rpd_limit:
            raise DailyLimitReached("OpenAI", self.rpd_limit)
        now = time.monotonic()
        self._call_times = [stamp for stamp in self._call_times if now - stamp < 60]
        if self._call_times:
            time.sleep(max(0, 60 / self.rpm_limit - (now - self._call_times[-1])))
        self._call_times.append(time.monotonic())
        self._calls_today += 1

    def _log_failure(self, attempt: int, started: float, error: str, retry_in_seconds: float | None = None) -> None:
        record = {"provider": "openai", "model": self.model, "cache_hit": False,
                  "attempt": attempt + 1, "elapsed_seconds": round(time.monotonic() - started, 3),
                  "error": error}
        if retry_in_seconds is not None:
            record["retry_in_seconds"] = round(retry_in_seconds, 2)
        self._log(record)

    def _log(self, record: dict) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), **record}
        with self.log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _read_calls_today(self) -> int:
        if not self.log_path.exists():
            return 0
        count = 0
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
                if record.get("provider") == "openai" and record.get("timestamp_utc", "")[:10] == self._call_day.isoformat() and not record.get("cache_hit", False):
                    count += 1
            except (ValueError, TypeError):
                continue
        return count


#: Keywords left out of the strict schema: value limits the API's strict mode may refuse. The schema still sets
#: the shape (types, required keys, enums), and Pydantic checks the limits on the answer, as before.
VALUE_LIMITS = frozenset({"default", "minLength", "maxLength", "minItems", "maxItems", "pattern", "format",
                          "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"})


def _shape_only(node: object) -> None:
    """Remove VALUE_LIMITS from a JSON schema in place. The keys of "properties" and "$defs" are names, not
    keywords (a field may be called "format"): only the schemas under them are walked."""
    if isinstance(node, dict):
        for key in VALUE_LIMITS:
            node.pop(key, None)
        for key, value in node.items():
            if key in ("properties", "$defs") and isinstance(value, dict):
                for child in value.values():
                    _shape_only(child)
            else:
                _shape_only(value)
    elif isinstance(node, list):
        for value in node:
            _shape_only(value)
