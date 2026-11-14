"""infra/improve/run.py: the weekly round without Airflow (EventBridge + Fargate on AWS), and the deploy files around it."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
VIETNAM = timezone(timedelta(hours=7))


def _runner():
    spec = importlib.util.spec_from_file_location("improve_run", ROOT / "infra/improve/run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Shell:
    """Records each command; answers weekly-status with the code given per week."""

    def __init__(self, status=None, fail=()):
        self.lines, self.status, self.fail = [], status or {}, fail

    def __call__(self, line):
        self.lines.append(line)
        week = line.split("--week ")[1].split(" ")[0] if "--week " in line else None
        if "weekly-status" in line:
            return self.status.get(week, 2)
        return 1 if any(word in line for word in self.fail) else 0


def test_the_week_is_viet_nams_monday_even_when_utc_is_still_sunday():
    run = _runner()
    # Monday 02:00 in Ho Chi Minh City is Sunday 19:00 UTC: the round is the new week's.
    assert run.iso_week(datetime(2026, 11, 15, 19, 0, tzinfo=timezone.utc)) == "2026-W47"


def test_learn_runs_the_dags_two_first_steps_for_this_week():
    run, shell = _runner(), Shell()
    assert run.learn(datetime(2026, 11, 16, 2, 0, tzinfo=VIETNAM), shell) == 0
    assert [line.split(" ")[3] for line in shell.lines] == ["gaps", "weekly-learn"]
    assert "--week 2026-W47" in shell.lines[1] and "{{" not in shell.lines[1]


def test_learn_stops_and_fails_when_restating_the_gaps_fails():
    run, shell = _runner(), Shell(fail=("gaps",))
    assert run.learn(datetime(2026, 11, 16, 2, 0, tzinfo=VIETNAM), shell) == 1
    assert len(shell.lines) == 1


def test_tick_measures_only_a_settled_week_and_also_looks_at_the_last_one():
    run = _runner()
    shell = Shell(status={"2026-W47": 1, "2026-W46": 0})   # this week waits for the admin; the last one is settled
    assert run.tick(datetime(2026, 11, 18, 8, 0, tzinfo=VIETNAM), shell) == 0
    measured = [line for line in shell.lines if "weekly-measure" in line]
    assert len(measured) == 1 and "--week 2026-W46" in measured[0]


def test_tick_skips_weeks_without_a_round_and_reports_a_failed_measure():
    run = _runner()
    assert run.tick(datetime(2026, 11, 18, tzinfo=VIETNAM), Shell()) == 0
    failing = Shell(status={"2026-W47": 0}, fail=("weekly-measure",))
    assert run.tick(datetime(2026, 11, 18, tzinfo=VIETNAM), failing) == 1


def _compose(path):
    return yaml.load((ROOT / path).read_text(encoding="utf-8"), Loader=_Tagged)


class _Tagged(yaml.SafeLoader):
    """Reads compose's !reset / !override tags as plain values."""


def _override(loader, node):
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    return loader.construct_sequence(node, deep=True)


_Tagged.add_constructor("!override", _override)
_Tagged.add_constructor("!reset", lambda loader, node: (
    {} if isinstance(node, yaml.MappingNode) else [] if isinstance(node, yaml.SequenceNode) else None))


@pytest.mark.parametrize("path", ["infra/compose/docker-compose.cloud.yml", "infra/compose/docker-compose.aws.yml"])
def test_the_gateway_behind_a_proxy_trusts_only_private_proxies_for_the_client_address(path):
    # Without it every customer shares the proxy's address and one 120/minute bucket (aws-plan.md 1.1).
    gateway = _compose(path)["services"]["api-gateway"]
    assert gateway["environment"]["FORWARDED_ALLOW_IPS"] == "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"


def test_uvicorn_takes_the_real_client_not_a_spoofed_forwarded_for():
    from uvicorn.middleware.proxy_headers import _TrustedHosts

    trusted = _TrustedHosts("10.0.0.0/8,172.16.0.0/12,192.168.0.0/16")
    # The ALB appends the address it saw to whatever the client sent.
    assert trusted.get_trusted_client_address("203.0.113.9, 198.51.100.7")[0] == "198.51.100.7"
    assert trusted.get_trusted_client_address("10.1.2.3, 198.51.100.7")[0] == "198.51.100.7"


def test_on_aws_nothing_is_built_and_the_agents_shared_files_are_on_efs():
    services = _compose("infra/compose/docker-compose.aws.yml")["services"]
    assert services["postgres"]["profiles"] and services["seed"]["profiles"]
    for name, service in services.items():
        if "image" in service and name != "redis":
            assert "build" in service and service["build"] is None, name   # !reset null
            assert "${IMAGE_TAG" in service["image"], name
    targets = {volume.rsplit(":", 1)[1] for volume in services["ai-agent-service"]["volumes"]}
    assert {"/app/agent/data/skills", "/app/agent/data/improvement", "/app/agent/data/kb"} <= targets
    assert {service["ports"][0] for service in services.values() if service.get("ports")} == {"8000:8000", "3000:3000"}


def test_knowledge_versions_survive_a_recreated_container():
    agent = _compose("docker-compose.yml")["services"]["ai-agent-service"]
    assert "agent-kb:/app/agent/data/kb" in agent["volumes"]


def test_the_improve_image_copies_what_the_round_reads():
    allowed = {line[1:] for line in (ROOT / "infra/improve/Dockerfile.dockerignore").read_text().splitlines()
               if line.startswith("!")}
    for path in allowed:
        assert (ROOT / path).exists(), path
    assert {"run_eval.py", "data/reflection", "data/gap-loop", "docs/evaluation", "config/prompts"} <= allowed
