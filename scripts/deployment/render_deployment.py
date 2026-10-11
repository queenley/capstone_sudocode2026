"""Render manifests only. This command never applies resources or deploys a site."""

import argparse
import re
import subprocess
from pathlib import Path

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--environment", choices=["staging", "production"], required=True
    )
    parser.add_argument("--registry", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument(
        "--output", type=Path, default=Path("reports/generated/deployment.yaml")
    )
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9./:_-]+", args.registry) or not re.fullmatch(
        r"[a-zA-Z0-9_.-]+", args.tag
    ):
        raise SystemExit("Registry or tag contains invalid characters")
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            "kubectl",
            "kustomize",
            str(root / "infra/kubernetes/overlays" / args.environment),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    content = result.stdout.replace(
        "image: telesales-backend-common:dev", f"image: {args.registry}/telesales-backend-common:{args.tag}"
    ).replace(
        "image: telesales-web:dev", f"image: {args.registry}/telesales-web:{args.tag}"
    ).replace(
        "image: telesales-commerce:dev", f"image: {args.registry}/telesales-commerce:{args.tag}"
    ).replace(
        "image: telesales-gateway:dev", f"image: {args.registry}/telesales-gateway:{args.tag}"
    ).replace(
        "image: telesales-identity:dev", f"image: {args.registry}/telesales-identity:{args.tag}"
    ).replace(
        "image: telesales-sales:dev", f"image: {args.registry}/telesales-sales:{args.tag}"
    ).replace(
        "image: telesales-ai-agent:dev", f"image: {args.registry}/telesales-ai-agent:{args.tag}"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8")
    print("Rendered", args.output)
