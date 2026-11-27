"""An improved agent kept by code (components/improvement/builds.py): learned changes merged onto today's skills,
not a learning round's snapshot. No model call."""
import json

import pytest
import yaml

from ai_agent_service.components.improvement import builds

TODAY = {
    "place-order": {"description": "Dùng khi khách muốn mua.", "body": "- Khách đã nói đặt thì tạo đơn, chưa chọn thì COD."},
    "objection-handling": {"description": "Dùng khi khách lo lắng.", "body": "Trấn an khách bằng thông tin tool."},
}
#: What the round held on the day it learned: an old place-order line, plus the one change it approved.
SNAPSHOT = {
    "place-order": {"description": "Dùng khi khách muốn mua.", "body": "- Chưa biết thanh toán thì hỏi khách trước."},
    "objection-handling": {"description": "Dùng khi khách lo lắng. Cả khi khách lo máy hỏng sau bảo hành.",
                           "body": "Trấn an khách bằng thông tin tool. Giới thiệu gói bảo hành mở rộng (BH-05)."},
}
PATCH = {"skill": "objection-handling", "part": "body", "find": "", "text": "Giới thiệu gói bảo hành mở rộng.",
         "cites": ["BH-05"]}


@pytest.fixture
def where(tmp_path, monkeypatch):
    monkeypatch.setenv("IMPROVEMENT_DIR", str(tmp_path / "improvement"))
    base = tmp_path / "skills.yaml"
    base.write_text(yaml.safe_dump(TODAY, allow_unicode=True), encoding="utf-8")
    round_dir = tmp_path / "runs" / "reflect-x"
    (round_dir / "improvement").mkdir(parents=True)
    (round_dir / "improvement" / "improvement-log.jsonl").write_text(
        json.dumps({"action": "publish_skills", "version": 1, "reviewer": "approval-agent", "patches": [PATCH]}) + "\n",
        encoding="utf-8")
    (round_dir / "learned" / "skills").mkdir(parents=True)
    (round_dir / "learned" / "skills" / "v1.yaml").write_text(yaml.safe_dump(SNAPSHOT, allow_unicode=True), encoding="utf-8")
    kb_round = tmp_path / "runs" / "gap-x"
    (kb_round / "learned" / "kb").mkdir(parents=True)
    (kb_round / "learned" / "kb" / "v5.jsonl").write_text(json.dumps(
        {"chunk_id": "FAQ-GAP-1", "doc": "faq", "title": "Lắp đặt", "text": "Shop có thợ lắp.", "source": "faq"},
        ensure_ascii=False) + "\n", encoding="utf-8")
    return {"tmp": tmp_path, "base": base, "round": round_dir, "kb_round": kb_round, "agents": tmp_path / "agents",
            "kb": tmp_path / "kb", "skills": tmp_path / "skills"}


def _build(where, name="improved-1"):
    return builds.build(name, kb_version=5, kb_round=where["kb_round"], skills_rounds=[where["round"]],
                        reviewer="tester", folder=where["agents"], base_path=where["base"])


def test_a_build_merges_the_approved_change_onto_today_not_the_snapshot(where):
    manifest = _build(where)
    book = yaml.safe_load((where["agents"] / "improved-1" / builds.SKILLS_FILE).read_text(encoding="utf-8"))
    assert book["place-order"] == TODAY["place-order"]  # the snapshot's old line does not come back
    assert book["objection-handling"]["body"].endswith("Giới thiệu gói bảo hành mở rộng (BH-05).")
    assert "Cả khi khách lo máy hỏng sau bảo hành." in book["objection-handling"]["description"]
    assert manifest["skills"]["patches"][0]["round"] == "reflect-x"
    assert manifest["knowledge"]["entries"] == ["FAQ-GAP-1"]


def test_a_change_that_no_longer_applies_stops_the_build(where):
    log = where["round"] / "improvement" / "improvement-log.jsonl"
    gone = {**PATCH, "find": "Câu không còn trong skill."}
    log.write_text(json.dumps({"action": "publish_skills", "version": 1, "reviewer": "a", "patches": [gone]}) + "\n",
                   encoding="utf-8")
    with pytest.raises(ValueError, match="no longer apply"):
        _build(where)
    assert not (where["agents"] / "improved-1").exists()


def test_a_build_is_never_rewritten(where):
    _build(where)
    with pytest.raises(FileExistsError):
        _build(where)


def test_install_switches_nothing_on_and_reuses_a_version_with_the_same_content(where):
    _build(where)
    first = builds.install("improved-1", folder=where["agents"], kb_folder=where["kb"], skills_folder=where["skills"],
                           base_path=where["base"])
    assert first == {"kb_version": 1, "skills_version": 1}
    assert not (where["skills"] / "active.json").exists()
    again = builds.install("improved-1", folder=where["agents"], kb_folder=where["kb"], skills_folder=where["skills"],
                           base_path=where["base"])
    assert again == first and sorted(p.name for p in where["skills"].iterdir()) == ["v1.yaml"]
    assert builds.run_args(first) == ["--profile", "combined", "--kb-version", "1", "--skills-version", "1"]


def test_a_build_on_other_skills_than_today_must_be_built_again(where):
    _build(where)
    where["base"].write_text(yaml.safe_dump({**TODAY, "place-order": {"description": "x", "body": "- y"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="build it again"):
        builds.install("improved-1", folder=where["agents"], kb_folder=where["kb"], skills_folder=where["skills"],
                       base_path=where["base"])


def test_run_args_name_only_what_the_build_has():
    assert builds.run_args({"kb_version": 5, "skills_version": 0}) == ["--profile", "gaploop", "--kb-version", "5"]
    assert builds.run_args({"kb_version": 0, "skills_version": 2}) == ["--profile", "reflection", "--skills-version", "2"]


def test_install_finds_the_committed_knowledge_version_it_was_built_from(where):
    where["kb"].mkdir()
    committed = where["kb"] / "v5.jsonl"
    committed.write_bytes((where["kb_round"] / "learned" / "kb" / "v5.jsonl").read_bytes())
    _build(where)
    installed = builds.install("improved-1", folder=where["agents"], kb_folder=where["kb"],
                               skills_folder=where["skills"], base_path=where["base"])
    assert installed["kb_version"] == 5 and sorted(p.name for p in where["kb"].iterdir()) == ["v5.jsonl"]
