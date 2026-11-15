"""An admin reads and changes the advisor's skills in /admin (skill_versions.edit, the /improvement/skills routes)."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ai_agent_service.api.routes import improvement as routes
from ai_agent_service.components.context import skills as skill_book
from ai_agent_service.components.improvement import review, skill_versions


@pytest.fixture()
def folder(tmp_path, monkeypatch):
    where = tmp_path / "skills"
    monkeypatch.setattr(skill_book, "versions_dir", lambda: where)
    monkeypatch.setattr(review, "log_path", lambda: tmp_path / "improvement-log.jsonl")
    monkeypatch.setattr(routes, "staff", lambda request, roles: "admin")
    monkeypatch.delenv("EVAL_SKILLS_VERSION", raising=False)
    yield where
    skill_book.reload()  # the module's skills as the original again, for the tests after this one


def _request(actor="u-1"):
    return SimpleNamespace(state=SimpleNamespace(actor_id=actor))


def test_an_edit_is_a_new_version_and_the_original_never_changes(folder):
    original = skill_versions.read_version(0)
    name = next(iter(original))
    changed = {**original[name], "body": original[name]["body"] + "\n- Một dòng admin thêm."}
    first = skill_versions.edit({name: changed}, reviewer="staff:u-1", note="thêm dòng")
    assert first == 1 and skill_versions.active(folder) == 1
    assert skill_versions.read_version(1)[name]["body"].endswith("Một dòng admin thêm.")
    assert skill_versions.read_version(0) == original
    added = skill_versions.edit({"warranty-claim": {"description": "Khách báo lỗi trong bảo hành.",
                                                    "body": "- Hỏi mã đơn trước.", "done_on": ["order_status"]}},
                                reviewer="staff:u-1", activate=False)
    assert added == 2 and skill_versions.active(folder) == 1  # a candidate: v1 still served
    listed = {v["version"]: v for v in skill_versions.versions(folder)}
    assert listed[1]["active"] and listed[1]["changed"] == [name] and listed[1]["by"] == "staff:u-1"
    assert listed[2]["changed"] == ["warranty-claim"] and not listed[2]["active"]
    removed = skill_versions.edit({name: None}, reviewer="staff:u-1")
    assert name not in skill_versions.read_version(removed)


def test_an_edit_is_refused_when_it_would_break_the_prompt(folder):
    name = next(iter(skill_versions.read_version(0)))
    with pytest.raises(ValueError, match="mô tả"):
        skill_versions.edit({name: {"description": "x" * 300, "body": "b"}}, reviewer="staff:u-1")
    with pytest.raises(ValueError, match="Tên skill"):
        skill_versions.edit({"Bad Name": {"description": "d", "body": "b"}}, reviewer="staff:u-1")
    with pytest.raises(ValueError, match="tool"):
        skill_versions.edit({name: {"description": "d", "body": "b", "done_on": ["drop table"]}}, reviewer="staff:u-1")
    with pytest.raises(ValueError):
        skill_versions.edit({name: {"description": "d", "body": "b"}}, reviewer=" ")
    assert skill_versions.active(folder) == 0


@pytest.mark.asyncio
async def test_the_admin_routes_serve_the_change_from_the_next_turn(folder):
    name = next(iter(skill_versions.read_version(0)))
    shown = await routes.skills(_request(), version=None)
    assert shown["active"] == 0 and {s["name"] for s in shown["skills"]} == set(skill_versions.read_version(0))
    edit = routes.SkillEdit(changes={name: routes.SkillIn(description="Mô tả mới.", body="- Làm thế này.")})
    result = await routes.edit_skills(edit, _request())
    assert result == {"skills_version": 1, "active": True}
    assert skill_book.SKILLS[name]["description"] == "Mô tả mới."  # read again in the process
    shown = await routes.skills(_request(), version=None)
    assert next(s for s in shown["skills"] if s["name"] == name)["changed"]
    back = await routes.activate_skills(0, routes.Activation(note="thử lại"), _request())
    assert back["previous"] == 1 and skill_book.SKILLS == skill_versions.read_version(0)
    with pytest.raises(HTTPException) as refused:
        await routes.activate_skills(9, routes.Activation(), _request())
    assert refused.value.status_code == 422


@pytest.mark.asyncio
async def test_the_policies_page_lists_every_section_and_marks_who_may_hear_it(monkeypatch):
    monkeypatch.setattr(routes, "staff", lambda request, roles: "admin")
    found = await routes.policies(_request())
    docs = {d["doc"]: d for d in found["documents"]}
    assert sum(len(d["sections"]) for d in docs.values()) >= 90
    assert docs["noi-quy-nhan-vien.md"]["internal"] and not docs["chinh-sach-bao-hanh.md"]["internal"]
    assert docs["chinh-sach-doi-tra-v2026-06-HET-HIEU-LUC.md"]["retired"]
    assert all(s["id"] and s["text"] for d in docs.values() for s in d["sections"])
    assert "version" in found["learned"]
