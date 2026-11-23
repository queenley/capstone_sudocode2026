"""Render manifests only. This command never applies resources or deploys a site.

    python scripts/deployment/render_deployment.py --environment staging --registry <registry> --tag <tag>
    python scripts/deployment/render_deployment.py --environment aws-production --registry <ecr> --tag <sha> \
        --terraform-output overlay.json      # terraform -chdir=infra/terraform/aws-eks output -json overlay

Every ``telesales-<image>:dev`` becomes ``<registry>/telesales-<image>:<tag>``. An overlay's ``__PLACEHOLDERS__``
(production, aws-production) are filled from Terraform's ``overlay`` output, whose keys are the placeholders'
names in lower case (``jobs_queue_url`` fills ``__JOBS_QUEUE_URL__``), and from ``--set NAME=value``; a manifest
with a placeholder left is refused, not written. aws-production also renders overlays/aws-cluster (Karpenter's
cluster-scoped objects, which must carry no namespace) into the same file.
"""

import argparse
import json
import re
import subprocess
from pathlib import Path

ENVIRONMENTS = {
    "staging": ["staging"],
    "production": ["production"],
    "aws-production": ["aws-production", "aws-cluster"],
}
PLACEHOLDER = re.compile(r"__([A-Z][A-Z0-9_]*)__")
# The cluster's name is the Terraform prefix (aws-eks/versions.tf: name-environment).
DERIVED = {"CLUSTER": lambda values: values.get("CLUSTER") or "telesales-production"}


def values_from(path: Path | None, pairs: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    if path is not None:
        found = json.loads(path.read_text(encoding="utf-8-sig"))  # Windows PowerShell 5.1 writes a BOM
        found = found.get("value", found) if isinstance(found, dict) else found  # `output -json` with or without the name
        values.update({str(key).upper(): str(value) for key, value in found.items()})
    for pair in pairs:
        name, _, value = pair.partition("=")
        if not name or not _:
            raise SystemExit(f"--set wants NAME=value, not {pair!r}")
        values[name.strip().upper()] = value
    for name, derive in DERIVED.items():
        values.setdefault(name, derive(values))
    return values


def fill(content: str, values: dict[str, str]) -> str:
    missing = sorted({name for name in PLACEHOLDER.findall(content) if name not in values})
    if missing:
        raise SystemExit("No value for " + ", ".join(f"__{name}__" for name in missing)
                         + ": give --terraform-output or --set NAME=value.")
    for name, value in values.items():
        if not re.fullmatch(r"[A-Za-z0-9./:_@+=,!-]*", value):  # ! is in the secret ARNs RDS manages
            raise SystemExit(f"{name} contains characters a manifest value should not: {value!r}")
    return PLACEHOLDER.sub(lambda match: values[match.group(1)], content)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", choices=sorted(ENVIRONMENTS), required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--terraform-output", type=Path, help="terraform output -json overlay, saved to a file")
    parser.add_argument("--set", action="append", default=[], metavar="NAME=value", help="a placeholder's value")
    parser.add_argument("--output", type=Path, default=Path("reports/generated/deployment.yaml"))
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9./:_-]+", args.registry) or not re.fullmatch(r"[a-zA-Z0-9_.-]+", args.tag):
        raise SystemExit("Registry or tag contains invalid characters")
    root = Path(__file__).resolve().parents[2]
    parts = [
        subprocess.run(["kubectl", "kustomize", str(root / "infra/kubernetes/overlays" / overlay)],
                       capture_output=True, text=True, check=True).stdout
        for overlay in ENVIRONMENTS[args.environment]
    ]
    content = "---\n".join(part if part.endswith("\n") else part + "\n" for part in parts)
    content = re.sub(r"image: telesales-([a-z0-9-]+):dev\b", rf"image: {args.registry}/telesales-\1:{args.tag}", content)
    content = fill(content, values_from(args.terraform_output, args.set))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8")
    print("Rendered", args.output)
