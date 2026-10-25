from pathlib import Path

EXCLUDED_MARKERS=("het-hieu-luc","noi-bo","noi-quy-nhan-vien","changelog")

def load_customer_policy(policy_dir: Path, max_chars_per_file: int = 8000) -> dict[str,str]:
    """Load customer-facing current policies; omit expired and internal-only notes."""
    documents={}
    for path in sorted(policy_dir.glob("*.md")):
        if any(marker in path.name.lower() for marker in EXCLUDED_MARKERS):
            continue
        documents[path.name]=path.read_text(encoding="utf-8")[:max_chars_per_file]
    return documents
