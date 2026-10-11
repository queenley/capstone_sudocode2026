"""Export each service's OpenAPI document to ``contracts/api/openapi/<service>.json``.

The apps are imported, not started: no database or model is needed. The gateway
only proxies, so its routing table (``apps/api-gateway/src/main.py``) together
with these files is the public API.

    python -m scripts.contracts.export_contracts
"""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/ai-agent-service/src"))
sys.path.insert(0, str(ROOT / "packages/backend-common"))

SERVICES = {
    "commerce-service": ROOT / "apps/commerce-service/src/main.py",
    "identity-service": ROOT / "apps/identity-service/src/main.py",
    "sales-service": ROOT / "apps/sales-service/src/main.py",
    "ai-agent-service": ROOT / "apps/ai-agent-service/src/ai_agent_service/main.py",
}


def load_app(name: str, path: Path):
    if name == "ai-agent-service":
        from ai_agent_service.main import app
        return app
    spec = importlib.util.spec_from_file_location(name.replace("-", "_") + "_main", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.app


def main() -> None:
    output = ROOT / "contracts/api/openapi"
    output.mkdir(parents=True, exist_ok=True)
    for name, path in SERVICES.items():
        target = output / f"{name}.json"
        target.write_text(json.dumps(load_app(name, path).openapi(), ensure_ascii=False, indent=2), encoding="utf-8")
        print("Exported", target.relative_to(ROOT))


if __name__ == "__main__":
    main()
