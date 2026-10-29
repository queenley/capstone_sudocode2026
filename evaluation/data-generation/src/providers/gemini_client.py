"""Gemini structured-output wrapper with persistent prompt cache and usage log."""
from __future__ import annotations

from src.utils.json_output import parse_output
from src.utils.quota import DailyLimitReached
import hashlib, json, os, time
import random
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TypeVar
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


def _gemini_compatible_schema(schema: type[BaseModel]) -> dict:
    """Remove JSON Schema features rejected by Gemini Developer API.

    Pydantic emits ``additionalProperties`` for strict and free-form dict
    fields. Gemini Enterprise accepts that keyword, but the Developer API does
    not. Keep the object types and all other constraints; Pydantic remains the
    authoritative validator after generation.
    """
    result = schema.model_json_schema()

    def strip_unsupported(value):
        if isinstance(value, dict):
            value.pop("additionalProperties", None)
            for child in value.values():
                strip_unsupported(child)
        elif isinstance(value, list):
            for child in value:
                strip_unsupported(child)

    strip_unsupported(result)
    return result

class GeminiClient:
    def __init__(self, model: str, cache_dir: Path, log_path: Path, retries: int = 3,
                 rpm_limit: int = 10, rpd_limit: int = 100,
                 retry_backoff_seconds: float = 2):
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not set; copy config/.env.example to .env and configure it")
        from google import genai
        self.client = genai.Client(api_key=key)
        self.model, self.cache_dir, self.log_path, self.retries = model, cache_dir, log_path, retries
        self.retry_backoff_seconds = max(0, retry_backoff_seconds)
        self.rpm_limit, self.rpd_limit = max(1, rpm_limit), max(1, rpd_limit)
        self._call_times: list[float] = []
        self._call_day = datetime.now(timezone.utc).date()
        self._calls_today = self._read_calls_today()
        cache_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, prompt: str, schema: type[T], *, temperature: float = 0.7,
                 max_output_tokens: int = 8192) -> T:
        from google.genai import types
        response_schema = _gemini_compatible_schema(schema)
        params = {"model": self.model, "temperature": temperature, "max_output_tokens": max_output_tokens,
                  "schema": response_schema}
        digest = hashlib.sha256((prompt + json.dumps(params, sort_keys=True)).encode()).hexdigest()
        cache_file = self.cache_dir / f"{digest}.json"
        if cache_file.exists():
            self._log({"model": self.model, "cache_hit": True, "elapsed_seconds": 0, "error": None})
            return schema.model_validate_json(cache_file.read_text(encoding="utf-8"))
        prior_error = ""
        for attempt in range(self.retries):
            utc_day=datetime.now(timezone.utc).date()
            if utc_day != self._call_day:
                self._call_day = utc_day
                self._calls_today = self._read_calls_today()
            now = time.monotonic()
            self._call_times = [stamp for stamp in self._call_times if now - stamp < 60]
            if self._calls_today >= self.rpd_limit:
                raise DailyLimitReached("Gemini", self.rpd_limit)
            if self._call_times and len(self._call_times) >= self.rpm_limit:
                time.sleep(max(0, 60 - (now - self._call_times[0])))
            elif self._call_times:
                time.sleep(max(0, 60 / self.rpm_limit - (now - self._call_times[-1])))
            self._call_times.append(time.monotonic())
            self._calls_today += 1
            started = time.monotonic()
            error = None
            response = None
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt + (f"\n\nPrevious output validation error: {prior_error}" if prior_error else ""),
                    config=types.GenerateContentConfig(temperature=temperature,
                        max_output_tokens=max_output_tokens, response_mime_type="application/json",
                        response_schema=response_schema),
                )
                parsed, repaired = response.parsed, False
                if isinstance(parsed, schema):
                    result = parsed
                elif isinstance(parsed, BaseModel):
                    result = schema.model_validate(parsed.model_dump())
                elif parsed is not None:
                    result = schema.model_validate(parsed)
                else:  # the SDK could not parse the text: repair it if the JSON is broken
                    result, repaired = parse_output(response.text or "", schema)
                cache_file.write_text(result.model_dump_json(indent=2), encoding="utf-8")
                self._log({"model": self.model, "cache_hit": False, "attempt": attempt + 1, "json_repaired": repaired,
                    "prompt_tokens": getattr(getattr(response, "usage_metadata", None), "prompt_token_count", None),
                    "output_tokens": getattr(getattr(response, "usage_metadata", None), "candidates_token_count", None),
                    "elapsed_seconds": round(time.monotonic() - started, 3), "error": None})
                return result
            except (ValidationError, ValueError) as exc:
                error = str(exc); prior_error = error
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                if attempt + 1 >= self.retries or not self._is_retryable(exc):
                    self._log({"model": self.model, "cache_hit": False, "attempt": attempt + 1,
                        "elapsed_seconds": round(time.monotonic() - started, 3), "error": error})
                    raise
                delay = self._retry_delay(exc, attempt)
                self._log({"model": self.model, "cache_hit": False, "attempt": attempt + 1,
                    "elapsed_seconds": round(time.monotonic() - started, 3), "error": error,
                    "retry_in_seconds": round(delay, 2)})
                time.sleep(delay)
                continue
            self._log({"model": self.model, "cache_hit": False, "attempt": attempt + 1,
                "elapsed_seconds": round(time.monotonic() - started, 3), "error": error})
        raise RuntimeError("Gemini output could not be validated after retries")

    @staticmethod
    def _is_retryable(error: Exception) -> bool:
        """Retry transient server/rate-limit failures, not invalid requests."""
        status = getattr(error, "code", None) or getattr(error, "status_code", None)
        if isinstance(status, int):
            return status in {408, 425, 429, 500, 502, 503, 504}
        return True

    def _retry_delay(self, error: Exception, attempt: int) -> float:
        """Exponential backoff with jitter, honoring Retry-After when present."""
        response = getattr(error, "response", None)
        headers = getattr(response, "headers", {}) or {}
        try:
            retry_after = float(headers.get("Retry-After", 0))
        except (TypeError, ValueError):
            retry_after = 0
        exponential = min(self.retry_backoff_seconds * (2 ** attempt), 60)
        return max(retry_after, exponential * random.uniform(0.8, 1.2))

    def _log(self, record: dict) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        record={"timestamp_utc":datetime.now(timezone.utc).isoformat(),"provider":"gemini",**record}
        with self.log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _read_calls_today(self) -> int:
        if not self.log_path.exists(): return 0
        count=0
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            try:
                record=json.loads(line)
                stamp=record.get("timestamp_utc","")
                # Count only this provider's real requests (older log lines have no provider field).
                if record.get("provider","gemini")!="gemini": continue
                if stamp[:10]==self._call_day.isoformat() and not record.get("cache_hit",False): count+=1
            except (ValueError, TypeError):
                continue
        return count
