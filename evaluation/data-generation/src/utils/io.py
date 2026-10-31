import json
import sys
from pathlib import Path
from typing import Iterator, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


def load_model(path: Path, model: type[T]) -> T:
    return model.model_validate_json(path.read_text(encoding="utf-8-sig"))


def iter_models(paths, model: type[T]) -> Iterator[tuple[Path, T]]:
    """Yield ``(path, record)`` and skip files written by an older schema.

    Generated outputs from previous pipeline versions should not crash
    reporting stages; they are reported once on stderr so they can be regenerated.
    """
    for path in paths:
        try:
            yield path, load_model(path, model)
        except (ValidationError, ValueError) as exc:
            first_error = str(exc).splitlines()[0]
            print(f"[skip] {path.name}: not a valid {model.__name__} ({first_error})", file=sys.stderr)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
