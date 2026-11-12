"""How the shop does a task, in the prompt only while the task is on. ``docs/design.md`` section 4.4.

The model reads the catalogue (name and description) and calls ``load_skill``
when it needs one: nothing here guesses what the customer wants. A skill grants
nothing: permissions, consent and prices stay with the tools and their guards.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

from ...config.config_manager import kb_dir, load_prompt_yaml

ACTIVE = "active.json"


def versions_dir() -> Path:
    """Where Reflection's published versions live, beside the knowledge base's."""
    return kb_dir().parent / "skills"


def active_version(folder: Path) -> int:
    forced = os.environ.get("EVAL_SKILLS_VERSION", "").strip()
    if forced:
        return int(forced)
    path = folder / ACTIVE
    return int(json.loads(path.read_text(encoding="utf-8"))["version"]) if path.is_file() else 0


def read_book(folder: Path | None = None) -> dict[str, Any]:
    """The skills in force: version 0 is the file in the prompts, a later one what Reflection published."""
    where = folder or versions_dir()
    version = active_version(where)
    if version == 0:
        return load_prompt_yaml("advisor/skills.yaml")
    return yaml.safe_load((where / f"v{version}.yaml").read_text(encoding="utf-8"))


SKILLS: Mapping[str, Mapping[str, Any]] = read_book()


def learned_cites(book: Mapping[str, Mapping[str, Any]], original: Mapping[str, Mapping[str, Any]]) -> tuple[str, ...]:
    """The rule codes cited by the lines of *book* that *original* does not have: what Reflection's lessons rest on.

    The advisor may state a policy only from the passages of the turn (its rule 3), and a customer's worry does not
    retrieve the rule a lesson applies to it: on 2026-11-11 a lesson citing BH-05 was followed only where the passage
    happened to be there. So the rules a published lesson cites come along with every turn's passages
    (``pipeline/hot/nodes.py``). With the original skills there are none."""
    codes: list[str] = []
    for name, skill in book.items():
        before = set(str((original.get(name) or {}).get("body") or "").splitlines())
        for line in str(skill.get("body") or "").splitlines():
            if line not in before:
                codes += re.findall(r"\b[A-Z]{2,3}-\d{2}\b", line)
    return tuple(dict.fromkeys(codes))


#: Empty for the original agent.
LEARNED_CITES: tuple[str, ...] = learned_cites(SKILLS, load_prompt_yaml("advisor/skills.yaml"))
#: Past this many, the oldest leaves the prompt; the model can load it again.
MAX_LOADED = 3


def on_demand() -> bool:
    """Every body stays in the prompt unless ``ADVISOR_SKILLS=1``: a load costs a model round and a prompt longer by
    these bodies costs next to nothing once cached (2026-11-07, four scenarios: 28% more model calls when loading)."""
    return os.environ.get("ADVISOR_SKILLS", "0").strip().lower() not in ("0", "false", "no", "off", "")


def catalogue(loaded: Iterable[str] = ()) -> str:
    have = set(loaded)
    lines = "\n".join(f"- {name}: " + ("đã nạp, không gọi lại." if name in have else skill["description"])
                      for name, skill in SKILLS.items())
    return ("Quy trình của shop. Trước khi làm một việc dưới đây, gọi load_skill(name) trước rồi làm theo, có thể gọi "
            f"cùng lúc với tool tra cứu; không hỏi khách, không nói tên quy trình cho khách:\n{lines}")


def section(loaded: Iterable[str], *, offered: bool) -> str:
    """What the prompt says of skills: the catalogue, and the body of each one loaded."""
    if not offered:
        return ""
    if not on_demand():
        return "## Cách làm\n" + "\n\n".join(f"### {name}: {skill['description']}\n{skill['body']}"
                                              for name, skill in SKILLS.items())
    bodies = [f"Cách làm ({name}):\n{SKILLS[name]['body']}" for name in loaded if name in SKILLS]
    return "\n".join([catalogue(loaded), *bodies])


def load(loaded: list[str], name: str) -> dict[str, Any]:
    """The tool's result; *loaded* is this turn's list, read again by the next model call."""
    if name not in SKILLS:
        return {"ok": False, "error": {"code": "UNKNOWN_SKILL", "retryable": False,
                                       "message": f"Chỉ có: {', '.join(SKILLS)}."}}
    if name not in loaded:
        loaded.append(name)
        del loaded[:-MAX_LOADED]
    return {"ok": True, "data": {"loaded": name, "note": "Cách làm đã có trong hướng dẫn, làm tiếp theo đó."}}


def after_turn(loaded: Sequence[str], results: Iterable[Mapping[str, Any]]) -> list[str]:
    """What stays for the next turn: a skill whose task succeeded leaves."""
    done = {str(r.get("name") or "").replace(".", "_") for r in results if (r.get("result") or {}).get("ok")}
    return [name for name in loaded if name in SKILLS and not done & set(SKILLS[name].get("done_on") or [])]
