"""Revision r4 of data/dev's labels: the fixes of the 08/11/2026 audit and after, every change recorded.

Run from the repository root:  python evaluation/datasets/ground-truth-review/build_dev_r4.py

It starts from the labels at SOURCE_REF (git), builds under data/.build/dev and replaces the label folders of data/dev
(scenarios, metadata, asr_reference, tools, call_brief, handoff_brief), conversion-report.json and DISPUTES.md. Audio,
conversations, judgments and the rest of data/dev are not touched. Then rebuild trace_log/ and the oracle reports with
build_ground_truth --root ../../data/dev (from evaluation/data-generation).

Two kinds of change, kept apart in the report (SKILL.md of this folder):
- decision "revise", reviewer set: a group whose proposal the reviewer accepted as written (groups 1, 2, 3, 4 for
  SCN-ADV-0028, 5, 8, 9, 10, and the format fixes of 11);
- proposed_by "claude": a change the reviewer asked Claude to propose after reading the sentences (ADV-0023, the
  hotline calls of group 7, the field/blocker/date fixes of 11 that need meaning, 12). Pending (reviewer null) until
  CLAUDE_PROPOSALS_REVIEWED is set; then decision "revise" with the reviewer, and proposed_by kept as provenance.
official_gt_approved stays false: nothing here makes the set golden.
"""
from __future__ import annotations

import argparse
import importlib.util
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import sys
import unicodedata
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
#: The last commit of data/dev before this revision: the labels it starts from.
SOURCE_REF = "46b2f2ff"
DEST = ROOT / "data" / "dev"
SRC = DEST  # set by main() to the labels at SOURCE_REF
BUILD = ROOT / "data" / ".build"
#: The folders a revision rewrites. Audio, conversations, judgments and the rest of a dataset stay as they are.
LABEL_FOLDERS = ("scenarios", "metadata", "asr_reference", "tools", "call_brief", "handoff_brief")


def source_tree(name: str, ref: str) -> Path:
    """The dataset's label folders as they were at commit *ref* (before any revision), unpacked under data/.build."""
    dest = BUILD / f"source-{name}"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    archive = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", ref,
                              *[f"data/{name}/{folder}" for folder in LABEL_FOLDERS]], capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(dest)
    return dest / "data" / name


def install(out: Path, dest: Path) -> None:
    """Replace the label folders of *dest* (data/dev, data/test) with the built ones; nothing else is touched.

    Except the spoken forms of calls whose audio was made again after a label revision (synthesize_scenario_audio
    --changed-only): such an asr_reference/<call>.json in *dest* covers other words than the built one (another
    source_sha256), so it stays, and asr_reference/ground_truth.json is then rewritten from the clips on disk, taking
    each clip's entities from those call files (src/asr/reference.write_ground_truth).
    """
    # Scenarios added to the dataset after its source revision (add_scenarios.py) are not in the build: their label
    # files stay as they are.
    built_ids = {f.stem for f in (out / "scenarios").glob("*.json")}
    added_ids = {f.stem for f in (dest / "scenarios").glob("*.json")} - built_ids
    added: dict[Path, bytes] = {}
    for folder in LABEL_FOLDERS:
        for path in (dest / folder).rglob("*") if (dest / folder).exists() else ():
            if path.is_file() and any(i in path.relative_to(dest).as_posix() for i in added_ids):
                added[path.relative_to(dest)] = path.read_bytes()
    respoken: dict[Path, bytes] = {}
    for kept in (dest / "asr_reference").glob("scenarios_*/call_*.json"):
        built = out / "asr_reference" / kept.relative_to(dest / "asr_reference")
        sha = json.loads(kept.read_text(encoding="utf-8")).get("source_sha256")
        if sha and (not built.exists() or json.loads(built.read_text(encoding="utf-8")).get("source_sha256") != sha):
            respoken[kept.relative_to(dest)] = kept.read_bytes()
    for folder in LABEL_FOLDERS:
        if (dest / folder).exists():
            shutil.rmtree(dest / folder)
        shutil.copytree(out / folder, dest / folder)
    for relative, data in [*added.items(), *respoken.items()]:
        (dest / relative).parent.mkdir(parents=True, exist_ok=True)
        (dest / relative).write_bytes(data)
    if respoken:
        datagen = ROOT / "evaluation" / "data-generation"
        python = datagen / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run([str(python), "-m", "src.pipeline.synthesize_scenario_audio", "--ground-truth-only"], cwd=datagen,
                       env={**os.environ, "DATAGEN_SEED": dest.name, "PYTHONIOENCODING": "utf-8"}, check=True)
        print(f"kept {len(respoken)} re-spoken asr_reference calls; ground_truth.json rewritten from the clips")
    for name in ("conversion-report.json", "DISPUTES.md"):
        if (out / name).exists():
            shutil.copyfile(out / name, dest / name)
    if added_ids:
        print(f"kept the labels of {len(added_ids)} scenarios added after the source revision: {sorted(added_ids)}")
    print(f"installed into {dest} ({', '.join(LABEL_FOLDERS)}, conversion-report.json, DISPUTES.md)")
OUT = BUILD / "dev"
BTC = ROOT / "apps" / "ai-agent-service" / "data" / "btc"
REVIEWER = "dngan0365"
DAY = "2026-11-08"
AUDIT = "Bản tổng hợp nhãn cần sửa của data/dev, 08/11/2026"
HAND_WRITTEN = ("DISPUTES.md",)
#: The reviewer's notes live in git beside this script (data/dev-r*/ is not in git); a build copies them in.
NOTES = Path(__file__).resolve().parent / "notes" / "dev"
#: The reviewer read the table "Đã sửa, chờ duyệt (đề xuất của Claude)" of DISPUTES.md and accepted every row of it
#: (ADV-0023, the 7 hotline calls of group 7, the blocker/promo_expiry/phone/money/restock_date labels of 11, the
#: source tags of 12). None: those changes stay "pending".
CLAUDE_PROPOSALS_REVIEWED: str | None = "2026-11-08"

changes: list[dict] = []
disputed: dict[str, str] = {}


def status(approved: bool) -> dict:
    """Who decided a change: the reviewer on the audit's proposal, or Claude's proposal, pending or reviewed."""
    if approved:
        return {"reviewer": REVIEWER, "proposed_by": None, "decision": "revise"}
    if CLAUDE_PROPOSALS_REVIEWED:
        return {"reviewer": REVIEWER, "proposed_by": "claude", "decision": "revise",
                "reviewed_on": CLAUDE_PROPOSALS_REVIEWED}
    return {"reviewer": None, "proposed_by": "claude", "decision": "pending"}


def record(sid, call, field, source, proposed, evidence, group, approved):
    changes.append({"scenario_id": sid, "call": call, "field": field, "source": source, "proposed": proposed,
                    "evidence": evidence, "group": group, **status(approved)})


def plain(text: str) -> str:
    """The scenario's ASR style: lower case, no diacritics, no punctuation."""
    text = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn").lower()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text)).strip()


def ref(item: str) -> tuple[str, str]:
    """'GEN-0019/c2' -> ('SCN-GEN-0019', 'call_2')."""
    sid, call = item.split("/")
    return "SCN-" + sid, "call_" + call.lstrip("c")


def calls(text: str) -> list[tuple[str, str]]:
    return [ref(item.strip()) for item in text.replace("\n", " ").split(",") if item.strip()]


# ── Group 1 and the chat calls of group 7: the customer reads their number in the chat, as in SAMPLE-04 ──────────
G1 = calls("ADV-0049/c1, GEN-0011/c1, GEN-0027/c1, GEN-0030/c1, GEN-0030/c2, GEN-0043/c1, GEN-0046/c2, GEN-0064/c2, "
           "GEN-0077/c1, GEN-0080/c1, GEN-0093/c1, GEN-0096/c2, GEN-0111/c1, GEN-0114/c2, GEN-0127/c1, GEN-0130/c1, "
           "GEN-0143/c1, GEN-0146/c1, GEN-0161/c1, GEN-0164/c1, GEN-0177/c1, GEN-0180/c1, GEN-0196/c1, GEN-0211/c1, "
           "GEN-0227/c1, GEN-0230/c1, GEN-0243/c1, GEN-0061/c1, GEN-0193/c1")
G1_ANON = calls("ADV-0050/c1, ADV-0093/c1, ADV-0145/c1")
G7_HOTLINE = calls("ADV-0146/c2, GEN-0037/c2, GEN-0158/c2, GEN-0171/c2, GEN-0187/c2, GEN-0221/c2, GEN-0237/c2")

G2 = calls("""ADV-0016/c1, ADV-0048/c1, ADV-0062/c1, ADV-0062/c2, ADV-0064/c1, ADV-0064/c2, ADV-0068/c1, ADV-0068/c2,
ADV-0075/c1, ADV-0075/c2, ADV-0076/c1, ADV-0081/c1, ADV-0081/c2, ADV-0083/c1, ADV-0083/c2, ADV-0085/c1, ADV-0085/c2,
ADV-0087/c1, ADV-0087/c2, ADV-0088/c1, ADV-0088/c2, ADV-0089/c1, ADV-0090/c1, ADV-0097/c2, ADV-0099/c1, ADV-0099/c2,
GEN-0019/c1, GEN-0019/c2, GEN-0035/c1, GEN-0059/c1, GEN-0061/c1, GEN-0063/c1, GEN-0064/c1, GEN-0064/c2, GEN-0064/c3,
GEN-0066/c1, GEN-0066/c2, GEN-0067/c1, GEN-0067/c2, GEN-0068/c1, GEN-0070/c1, GEN-0070/c2, GEN-0070/c3, GEN-0071/c1,
GEN-0072/c1, GEN-0072/c2, GEN-0076/c1, GEN-0076/c2, GEN-0076/c3, GEN-0079/c1, GEN-0084/c1, GEN-0084/c2, GEN-0085/c1,
GEN-0085/c2, GEN-0136/c1, GEN-0136/c2, GEN-0139/c1, GEN-0139/c2, GEN-0141/c1, GEN-0142/c1, GEN-0142/c2, GEN-0142/c3,
GEN-0143/c1, GEN-0143/c2, GEN-0144/c1, GEN-0145/c1, GEN-0149/c2, GEN-0150/c1, GEN-0150/c2, GEN-0151/c1, GEN-0152/c1,
GEN-0152/c2, GEN-0154/c1, GEN-0154/c2, GEN-0156/c1, GEN-0156/c2, GEN-0157/c1, GEN-0157/c2, GEN-0158/c2, GEN-0159/c1,
GEN-0159/c2, GEN-0160/c1, GEN-0160/c2, GEN-0160/c3, GEN-0161/c1, GEN-0161/c2, GEN-0169/c1, GEN-0201/c1, GEN-0214/c1,
GEN-0214/c2, GEN-0214/c3, GEN-0219/c1, GEN-0219/c2, GEN-0224/c1, GEN-0224/c2, GEN-0225/c1, GEN-0226/c1, GEN-0226/c3,
GEN-0227/c1, GEN-0227/c2, GEN-0228/c1, GEN-0230/c1, GEN-0230/c2, GEN-0230/c3, GEN-0232/c1, GEN-0232/c2, GEN-0233/c1,
GEN-0234/c1, GEN-0234/c2, GEN-0235/c1, GEN-0236/c1, GEN-0236/c2, GEN-0237/c1, GEN-0239/c1, GEN-0239/c2""")

G3 = calls("GEN-0017/c2, GEN-0067/c2, GEN-0083/c2, GEN-0099/c2, GEN-0117/c2, GEN-0149/c2, GEN-0167/c2, GEN-0183/c2, "
           "GEN-0199/c2, GEN-0233/c2, GEN-0249/c2")
COD_WORDS = re.compile(r"COD|tiền mặt|trả tiền khi nhận", re.IGNORECASE)

G5 = {ref(k): v for k, v in {
    "ADV-0010/c2": ["room_area_m2"], "ADV-0102/c2": ["room_area_m2"], "ADV-0137/c2": ["room_area_m2"],
    "GEN-0001/c2": ["room_area_m2"], "GEN-0016/c2": ["room_area_m2"], "GEN-0020/c3": ["blocker", "room_area_m2"],
    "GEN-0036/c3": ["blocker"], "GEN-0048/c2": ["room_area_m2"], "GEN-0070/c3": ["blocker"],
    "GEN-0082/c2": ["room_area_m2"], "GEN-0086/c3": ["blocker"], "GEN-0116/c2": ["room_area_m2"],
    "GEN-0120/c3": ["blocker"], "GEN-0136/c3": ["blocker"], "GEN-0148/c2": ["room_area_m2"],
    "GEN-0170/c3": ["blocker"], "GEN-0182/c2": ["room_area_m2"], "GEN-0186/c3": ["blocker"],
    "GEN-0216/c2": ["room_area_m2"], "GEN-0220/c3": ["blocker"], "GEN-0236/c3": ["blocker"],
    "GEN-0248/c2": ["room_area_m2"]}.items()}

#: Group 8: (old label, the number the customer said).
G8 = {ref(k): v for k, v in {
    "ADV-0003/c1": (2500000, 2000000), "ADV-0030/c1": (8500000, 8000000), "ADV-0035/c1": (2500000, 2000000),
    "ADV-0079/c1": (7500000, 7000000), "GEN-0057/c1": (8500000, 8000000), "GEN-0083/c2": (8500000, 8000000),
    "GEN-0117/c1": (8500000, 8000000), "GEN-0117/c2": (8500000, 8000000), "GEN-0234/c1": (5500000, 5000000),
    "GEN-0247/c1": (6500000, 6000000)}.items()}

G9 = calls("""ADV-0007/c1, ADV-0014/c1, ADV-0017/c1, ADV-0017/c3, ADV-0018/c1, ADV-0018/c2, ADV-0021/c2, ADV-0027/c1,
ADV-0027/c2, ADV-0035/c1, ADV-0035/c2, ADV-0044/c1, ADV-0044/c2, ADV-0052/c1, ADV-0053/c1, ADV-0053/c2, ADV-0063/c2,
ADV-0065/c2, ADV-0066/c2, ADV-0071/c1, ADV-0073/c2, ADV-0078/c1, ADV-0078/c3, ADV-0079/c1, ADV-0079/c2, ADV-0087/c2,
ADV-0089/c1, ADV-0090/c1, ADV-0090/c2, ADV-0097/c2, ADV-0099/c1, ADV-0099/c2, ADV-0110/c1, ADV-0116/c1, ADV-0116/c2,
ADV-0139/c1, ADV-0139/c2, ADV-0141/c1, ADV-0142/c1, GEN-0004/c2, GEN-0005/c2, GEN-0009/c1, GEN-0009/c2, GEN-0012/c1,
GEN-0015/c2, GEN-0018/c1, GEN-0018/c2, GEN-0025/c1, GEN-0025/c2, GEN-0027/c1, GEN-0027/c2, GEN-0028/c1, GEN-0031/c2,
GEN-0036/c1, GEN-0036/c2, GEN-0038/c1, GEN-0038/c2, GEN-0039/c2, GEN-0044/c1, GEN-0045/c1, GEN-0050/c1, GEN-0050/c2,
GEN-0054/c1, GEN-0054/c2, GEN-0057/c2, GEN-0061/c1, GEN-0061/c2, GEN-0062/c1, GEN-0066/c1, GEN-0070/c1, GEN-0070/c2,
GEN-0071/c1, GEN-0072/c1, GEN-0072/c2, GEN-0079/c1, GEN-0084/c1, GEN-0084/c2, GEN-0088/c1, GEN-0088/c2, GEN-0093/c2,
GEN-0094/c1, GEN-0099/c2, GEN-0102/c2, GEN-0103/c1, GEN-0103/c2, GEN-0106/c1, GEN-0106/c2, GEN-0111/c2, GEN-0117/c2,
GEN-0118/c1, GEN-0118/c2, GEN-0120/c2, GEN-0125/c1, GEN-0125/c2, GEN-0128/c1, GEN-0138/c2, GEN-0144/c1, GEN-0150/c1,
GEN-0150/c2, GEN-0152/c1, GEN-0152/c2, GEN-0156/c2, GEN-0161/c1, GEN-0161/c2, GEN-0162/c1, GEN-0165/c2, GEN-0170/c1,
GEN-0170/c2, GEN-0178/c1, GEN-0179/c1, GEN-0184/c1, GEN-0184/c2, GEN-0187/c1, GEN-0188/c1, GEN-0188/c2, GEN-0194/c1,
GEN-0198/c1, GEN-0206/c1, GEN-0206/c2, GEN-0212/c1, GEN-0218/c1, GEN-0218/c2, GEN-0222/c1, GEN-0222/c2, GEN-0232/c1,
GEN-0244/c1, GEN-0247/c2, GEN-0249/c2, GEN-0250/c1, GEN-0250/c2""")
#: Promotions that are neither a discount nor a gift (promotions.json "type").
NOT_A_PROMOTION = {"freeship", "freecod"}

# ── Group 11, ASR entity labels (asr_reference) ──────────────────────────────────────────────────────────────
COLOR = {"đen": "den", "xám": "xam", "xanh navy": "navy", "màu này": None}
SIZE_WORDS = {"bốn mươi mốt": 41, "bốn mươi hai": 42, "lờ": "L", "ê xi el": "XL", "x l": "XL"}
#: Sizes said in a question about a product, not in an exchange: size_new (the size wanted), as the audit proposes.
SIZE_OLD_NOT_EXCHANGE = {"SCN-ADV-0096-call_1-t4", "SCN-ADV-0112-call_1-t1", "SCN-ADV-0131-call_2-t2",
                         "SCN-ADV-0132-call_1-t1", "SCN-GEN-0059-call_1-t1", "SCN-GEN-0124-call_2-t2",
                         "SCN-GEN-0160-call_1-t1", "SCN-GEN-0166-call_2-t1", "SCN-GEN-0226-call_1-t1"}
RESTOCK_CALLBACK = {"SCN-GEN-0049-call_2-t8"}  # "hẹn cho chị gọi lại vào ngày hai mươi mốt": a callback, not a restock
RETURN_NOT_DELIVERY = {"SCN-GEN-0063-call_2-t1", "SCN-GEN-0229-call_2-t1"}  # "đổi trả trong mười bốn ngày"
#: Money said in a sentence, filed under another field: (id, field) -> new field, or None when no field fits.
MONEY = {
    ("SCN-ADV-0024-call_1-t2", "competitor_price_vnd"): "price_vnd",  # "hình như em nói giá là ..."
    ("SCN-ADV-0030-call_1-t4", "competitor_price_vnd"): "price_vnd",  # "chị thấy giá ... có đúng không"
    ("SCN-ADV-0068-call_1-t2", "competitor_price_vnd"): None,         # "giá em báo": already price_vnd
    ("SCN-ADV-0075-call_1-t2", "budget_vnd"): "price_vnd",            # "giá là ... đúng không em"
    ("SCN-ADV-0094-call_1-t2", "competitor_price_vnd"): "price_vnd",  # the shop's own page
    ("SCN-ADV-0107-call_2-t5", "competitor_price_vnd"): None,         # an order total; no total field in the schema
    ("SCN-ADV-0012-call_2-t3", "price_vnd"): None,                    # "tổng tiền": a total, not a unit price
    ("SCN-GEN-0030-call_2-t2", "competitor_price_vnd"): "price_vnd",  # "hôm trước em báo giá là ..."
    ("SCN-GEN-0030-call_3-t2", "budget_vnd"): "price_vnd",            # "giá là ... đúng không"
    ("SCN-GEN-0049-call_1-t3", "competitor_price_vnd"): "price_vnd",  # "cái máy này giá ..."
    ("SCN-GEN-0066-call_1-t2", "budget_vnd"): "price_vnd",
    ("SCN-GEN-0082-call_1-t2", "competitor_price_vnd"): None,         # "đợt trước chị mua là ...": a past purchase
    ("SCN-GEN-0105-call_2-t5", "budget_vnd"): "price_vnd",            # "đồng ý với giá ... hôm trước"
    ("SCN-GEN-0114-call_2-t2", "competitor_price_vnd"): "price_vnd",  # the shop's fanpage
    ("SCN-GEN-0160-call_2-t2", "competitor_price_vnd"): "price_vnd",  # "giá vẫn là ..."
    ("SCN-GEN-0176-call_2-t3", "competitor_price_vnd"): "price_vnd",
    ("SCN-GEN-0180-call_2-t2", "competitor_price_vnd"): "price_vnd",  # "giá hôm trước em báo"
    ("SCN-GEN-0214-call_3-t3", "competitor_price_vnd"): "price_vnd",
    ("SCN-GEN-0218-call_1-t2", "competitor_price_vnd"): "price_vnd",  # "nghe nói xe này giá ... đúng không em"
    ("SCN-GEN-0232-call_1-t2", "budget_vnd"): "price_vnd",
    ("SCN-GEN-0246-call_2-t2", "competitor_price_vnd"): "price_vnd",  # the shop's fanpage
}
#: Blocker labels read one by one (92 had no cue word of their kind): the new label, None when the line states none.
_DROP = None
BLOCKER = {
    # A callback time, a budget, a return or size request, instalments, a policy doubt: no reason not to buy.
    **{k: _DROP for k in """SCN-ADV-0007-call_1-t4 SCN-ADV-0043-call_1-t5 SCN-ADV-0047-call_1-t5 SCN-ADV-0072-call_1-t3
    SCN-ADV-0097-call_2-t4 SCN-ADV-0110-call_1-t4 SCN-ADV-0113-call_1-t3 SCN-ADV-0138-call_1-t3 SCN-ADV-0138-call_1-t4
    SCN-ADV-0138-call_1-t5 SCN-ADV-0138-call_1-t6 SCN-ADV-0141-call_2-t4 SCN-ADV-0152-call_1-t4 SCN-ADV-0152-call_1-t5
    SCN-GEN-0013-call_2-t3 SCN-GEN-0022-call_1-t4 SCN-GEN-0033-call_1-t4 SCN-GEN-0040-call_2-t1 SCN-GEN-0044-call_1-t4
    SCN-GEN-0072-call_2-t4 SCN-GEN-0078-call_1-t4 SCN-GEN-0105-call_1-t4 SCN-GEN-0112-call_2-t4 SCN-GEN-0141-call_2-t2
    SCN-GEN-0163-call_2-t3 SCN-GEN-0163-call_2-t4 SCN-GEN-0172-call_1-t5 SCN-GEN-0179-call_2-t4 SCN-GEN-0187-call_1-t3
    SCN-GEN-0188-call_2-t3 SCN-ADV-0022-call_1-t3 SCN-ADV-0054-call_1-t4 SCN-GEN-0070-call_1-t4 SCN-GEN-0079-call_1-t4
    SCN-GEN-0084-call_1-t3 SCN-GEN-0136-call_1-t4 SCN-GEN-0162-call_1-t4 SCN-GEN-0249-call_1-t5 SCN-ADV-0082-call_1-t6
    SCN-ADV-0112-call_2-t1 SCN-ADV-0116-call_2-t5 SCN-GEN-0062-call_2-t3 SCN-GEN-0062-call_2-t4 SCN-GEN-0094-call_2-t4
    SCN-GEN-0094-call_2-t5 SCN-GEN-0144-call_2-t3 SCN-GEN-0144-call_2-t4 SCN-GEN-0194-call_2-t4 SCN-GEN-0228-call_2-t3
    SCN-ADV-0030-call_1-t4 SCN-GEN-0023-call_2-t2 SCN-GEN-0080-call_2-t1 SCN-GEN-0130-call_1-t2 SCN-GEN-0246-call_2-t2
    SCN-ADV-0081-call_1-t3 SCN-ADV-0095-call_1-t4 SCN-ADV-0107-call_2-t5""".split()},
    # The reason said is another kind.
    "SCN-GEN-0073-call_1-t5": "so sanh gia",        # "giá bên mình cao hơn chỗ khác anh cần hỏi thêm"
    "SCN-GEN-0075-call_2-t4": "so sanh gia",        # "đã tham khảo vài nơi rồi, nên ... không mua nữa"
    "SCN-ADV-0022-call_2-t3": "can suy nghi them",  # "đang phân vân không biết có nên mua ngay không"
    "SCN-ADV-0084-call_2-t4": "can suy nghi them",  # "đang phân vân giữa cái này và cái khác"
}

# ── Groups 14-16: Claude's proposals of 2026-11-09 (a check of the labels against the customer's words) ─────────
#: The reviewer accepted groups 11b and 14-18 on this day (decision "revise", proposed_by kept). None: pending.
NEW_PROPOSALS_REVIEWED: str | None = "2026-11-09"
NEW_SOURCE = "Kiểm mâu thuẫn nhãn với lời khách, 09/11/2026"


def status_new() -> dict:
    if NEW_PROPOSALS_REVIEWED:
        return {"reviewer": REVIEWER, "proposed_by": "claude", "decision": "revise", "reviewed_on": NEW_PROPOSALS_REVIEWED}
    return {"reviewer": None, "proposed_by": "claude", "decision": "pending"}


def vnd_words(value: int) -> str:
    """6000000 -> "6 triệu", 5500000 -> "5 triệu rưỡi", 6200000 -> "6 triệu 2", 500000 -> "500 nghìn"."""
    millions, rest = divmod(int(value), 1_000_000)
    if not millions:
        return f"{rest // 1000} nghìn"
    if not rest:
        return f"{millions} triệu"
    if rest == 500_000:
        return f"{millions} triệu rưỡi"
    return f"{millions} triệu {rest // 100_000}" if rest % 100_000 == 0 else f"{millions} triệu {rest // 1000} nghìn"


def stated_line(honorific: str, facts: dict, slots: list[str]) -> str:
    """One sentence in which the customer says the labelled facts they never said."""
    parts = []
    if "room_area_m2" in slots:
        parts.append(f"phòng {honorific} khoảng {facts['room_area_m2']} mét vuông")
    if "child_age_months" in slots:
        parts.append(f"bé nhà {honorific} được {facts['child_age_months']} tháng")
    elif "has_children" in slots:
        parts.append(f"nhà {honorific} {'có' if facts['has_children'] else 'không có'} trẻ nhỏ")
    if "budget_vnd" in slots:
        parts.append(f"ngân sách của {honorific} tầm {vnd_words(facts['budget_vnd'])}")
    line = ", ".join(parts)
    return line[0].upper() + line[1:] + "."



# ── Groups 19-22: a check of the agent's expected actions against the customer's words, 2026-11-09 ─────────────
#: Groups 19-24, 31: the reviewer (dngan0365) accepted them all on this date. None: not decided.
ACTION_PROPOSALS_REVIEWED: str | None = "2026-11-09"
ACTION_SOURCE = "Kiểm hành động kỳ vọng của agent với lời khách và mock BTC, 09/11/2026"


def status_action() -> dict:
    if ACTION_PROPOSALS_REVIEWED:
        return {"reviewer": REVIEWER, "proposed_by": "claude", "decision": "revise", "reviewed_on": ACTION_PROPOSALS_REVIEWED}
    return {"reviewer": None, "proposed_by": "claude", "decision": "pending"}


SELF = re.compile(r"\b(anh|chị|cô|chú|bác)\b", re.IGNORECASE)


def speaker_pronoun(scenario: dict, c: dict) -> str:
    """How the person on this call calls themselves: the commonest of anh/chị/cô/chú/bác in their words, leaving out
    "cô Loan" style mentions of the scenario's customer (a shared phone: someone else may be calling)."""
    name = scenario.get("customer_name") or ""
    counts: dict[str, int] = {}
    for turn in c.get("customer_turns") or []:
        for m in SELF.finditer(turn):
            if name and turn[m.end():].lstrip().startswith(name):
                continue
            word = m.group(1).lower()
            counts[word] = counts.get(word, 0) + 1
    if not counts:
        return scenario["honorific"]
    best = max(counts.values())
    # a tie keeps the scenario's own (a customer's words may slip, as SCN-ADV-0117)
    return scenario["honorific"] if counts.get(scenario["honorific"]) == best else max(counts, key=counts.get)


def call_day(scenario: dict, name: str) -> str:
    day = None
    for n in sorted(scenario["calls"]):
        c = scenario["calls"][n]
        if c.get("call_date"):
            day = date.fromisoformat(c["call_date"])
        elif day is not None and c.get("days_later") is not None:
            day += timedelta(days=int(c["days_later"]))
        else:
            day = day or date(2026, 10, 15)
        if n == name:
            return day.isoformat()
    raise KeyError(name)


#: Group 19: the customer sets a callback time, the label asks for no tool. (call, hour of the next day)
G19 = {ref("GEN-0184/c2"): 19}
#: Group 20: the last words put the order off ("Để chị bàn với gia đình rồi chốt đơn cho em."), as ADV-0028 in group 4.
G20 = calls("ADV-0123/c1")
#: Group 21: the person on a shared phone orders the product of the label, not the other person's.
G21 = {
    ref("GEN-0197/c2"): [("hôm qua có gọi hỏi máy lọc nước", "hôm qua cô Loan có gọi hỏi máy lọc nước"),
                         ("Bây giờ chị muốn mua máy lọc nước RO Karofi 9 lõi rồi.", "Bây giờ chị muốn mua máy lọc không khí AirPure Mini."),
                         ("Đúng rồi cháu, lên đơn giúp cô nhé.", "Đúng rồi em, lên đơn giúp chị nhé.")],
    ("test", ref("GEN-0015/c2")): [("Chị quyết định mua máy lọc nước RO Karofi 9 lõi mà cô Loan đã hỏi.",
                                    "Chị quyết định mua máy lọc không khí AirPure Mini cho phòng của chị."),
                                   ("Đúng rồi em, lên đơn giúp cô nhé.", "Đúng rồi em, lên đơn giúp chị nhé.")],
}
#: Group 23: the customer of the label ("anh") calls himself "chị" in two lines; the generator slipped (as group 10).
G23 = {ref("ADV-0117/c1"): [("chị đợi đến lúc đó", "anh đợi đến lúc đó"), ("nói chị nghe đi, chị đợi", "nói anh nghe đi, anh đợi")]}
#: Group 22: a callback asked for on a day off (LN-02: 26/10, 01/01). args_match pinned the asked time, so an agent
#: that proposes the next working slot itself (LN-01) fails; ground_truth_facts.callback_at and must_say_any keep the
#: moved time, which both ways reach.
#: Group 31: has_children labelled but never said (found once auto_verify.py matched values, not any mention):
#: the customer now says it, in the first turn, as group 14.
G31 = {ref("GEN-0066/c1"): "has_children", ref("GEN-0181/c1"): "has_children"}
#: Group 24: the oracle's schedule.callback result for 22:00 on 11/11 (LN-02 hours).
G24 = calls("ADV-0154/c1")
G22 = calls("ADV-0151/c1, GEN-0022/c1, GEN-0056/c1, GEN-0102/c1, GEN-0138/c1, GEN-0172/c1, GEN-0206/c1")


def apply_actions(scenarios: dict, out_dir: Path, add, which: str) -> None:
    """Groups 19-22 on one revision ("dev" or "test"); add(sid, call, field, source, proposed, evidence, group)."""
    mock = None
    for key, swaps in G21.items():
        if isinstance(key[0], str) and key[0] == "test":
            if which != "test":
                continue
            key = key[1]
        elif which == "test":
            continue
        sid, name = key
        c = scenarios[sid]["calls"][name]
        for i, turn in enumerate(c["customer_turns"]):
            new = turn
            for old, repl in swaps:
                new = new.replace(old, repl)
            if new != turn:
                c["customer_turns"][i] = new
                if c.get("customer_turns_asr"):
                    c["customer_turns_asr"][i] = plain(new)
                add(sid, name, f"customer_turns[{i}]", turn, new, f"{ACTION_SOURCE}, nhóm 21: hai người chung SĐT; người gọi "
                    f"cuộc này đặt {c['success_if']['args_match']['sku']} theo nhãn, nhưng lời thoại lại là món người kia hỏi.", 21)
    for (sid, name), swaps in (G23.items() if which == "dev" else []):
        c = scenarios[sid]["calls"][name]
        for i, turn in enumerate(c["customer_turns"]):
            new = turn
            for old, repl in swaps:
                new = new.replace(old, repl)
            if new != turn:
                c["customer_turns"][i] = new
                if c.get("customer_turns_asr"):
                    c["customer_turns_asr"][i] = plain(new)
                add(sid, name, f"customer_turns[{i}]", turn, new, f"{ACTION_SOURCE}, nhóm 23: nhãn và CRM là \"anh\" "
                    "(như các lượt khác của khách), hai lượt tự xưng \"chị\".", 23)
    for sid, name in G22:
        if sid not in scenarios or (which == "test" and sid != "SCN-GEN-0022"):
            continue
        si = scenarios[sid]["calls"][name]["success_if"]
        am = si.get("args_match") or {}
        if "callback_at" in am:
            add(sid, name, "success_if.args_match.callback_at", am.pop("callback_at"), "<bỏ>", f"{ACTION_SOURCE}, nhóm 22: giờ khách "
                "hẹn rơi vào ngày nghỉ (LN-02). Gửi giờ khách hẹn để tool dời, hay tự đề xuất khung gần nhất (LN-01), đều đúng; "
                "ground_truth_facts.callback_at và must_say_any vẫn kiểm giờ sau khi dời.", 22)
            if not am:
                si.pop("args_match", None)
    for sid, name in (G20 if which == "dev" else []):
        c = scenarios[sid]["calls"][name]
        new = {"tool_called": None, "must_not_call_tools": ["order.create"]}
        add(sid, name, "success_if", c["success_if"], new, f"{ACTION_SOURCE}, nhóm 20: câu cuối \"{c['customer_turns'][-1]}\" là "
            "hoãn, khách chưa đặt hôm nay (như ADV-0028 ở nhóm 4); bỏ cả must_say_any về gọi xác nhận đơn.", 20)
        add(sid, name, "expected_outcome", c["expected_outcome"], "hen_goi_lai", "Cùng lý do.", 20)
        c["success_if"], c["expected_outcome"] = new, "hen_goi_lai"
        for key in ("facts_established", "memory_expectation", "ground_truth_facts"):
            if "order_id" in (c.get(key) or {}):
                add(sid, name, f"{key}.order_id", c[key].pop("order_id"), "<bỏ>", "Không có đơn được tạo.", 20)
        tools = out_dir / "tools" / f"scenarios_{sid}" / f"{name}.json"
        planned = json.loads(tools.read_text(encoding="utf-8"))
        kept = [t for t in planned if t.get("name") != "order.create"]
        tools.write_text(json.dumps(kept, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        add(sid, name, "tools (oracle)", [t["name"] for t in planned], [t["name"] for t in kept], "Không tạo đơn.", 20)
    for (sid, name), slot in (G31.items() if which == "dev" else []):
        s, c = scenarios[sid], scenarios[sid]["calls"][name]
        line = stated_line(speaker_pronoun(s, c), c["facts_established"], [slot])
        old = c["customer_turns"][0]
        c["customer_turns"][0] = f"{old.rstrip()} {line}"
        if c.get("customer_turns_asr"):
            c["customer_turns_asr"][0] = f"{c['customer_turns_asr'][0].rstrip()} {plain(line)}"
        add(sid, name, "customer_turns[0]", old, c["customer_turns"][0], f"{ACTION_SOURCE}, nhóm 31: facts_established có "
            f"{slot}={c['facts_established'][slot]} nhưng khách không nói ở cuộc nào; thêm lời khách (như nhóm 14).", 31)
    for sid, name in (G24 if which == "dev" else []):
        tools = out_dir / "tools" / f"scenarios_{sid}" / f"{name}.json"
        planned = json.loads(tools.read_text(encoding="utf-8"))
        for t in planned:
            if t["name"] == "schedule.callback" and t["result"].get("moved_from"):
                old = dict(t["result"])
                t["result"].update(callback_at=t["args"]["callback_at"], moved_from=None)
                add(sid, name, "tools (oracle).schedule.callback.result", old, dict(t["result"]), f"{ACTION_SOURCE}, nhóm 24: "
                    "LN-02 mở tổng đài 07:00–23:00 ngày 11/11; tool schedule_callback của agent (mcp/servers/crm.py, "
                    "clock.SPECIAL_HOURS) giữ 22:00, chỉ mock thô của BTC dời về 08:00. Kết quả trong đáp án lấy theo tool "
                    "agent thật dùng, khớp ground_truth_facts.callback_at và must_say_any.", 24)
        tools.write_text(json.dumps(planned, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for (sid, name), hour in (G19.items() if which == "dev" else []):
        if mock is None:
            spec = importlib.util.spec_from_file_location("btc_mock_tools", BTC / "eval" / "mock_tools.py")
            mock = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mock)
        s = scenarios[sid]
        c = s["calls"][name]
        at = (date.fromisoformat(call_day(s, name)) + timedelta(days=1)).isoformat() + f"T{hour:02d}:00"
        result = mock.schedule_callback(s["customer_phone"], at, "khách hẹn gọi lại khi có hàng")
        old = dict(c["success_if"])
        c["success_if"] = {"tool_called": "schedule.callback", "args_match": {"callback_at": at},
                           **{k: v for k, v in old.items() if k not in ("tool_called", "args_match")}}
        add(sid, name, "success_if", old, c["success_if"], f"{ACTION_SOURCE}, nhóm 19: khách nói \"{c['customer_turns'][-1]}\"; "
            "playbook: xác nhận thời điểm gọi lại và ghi lịch bằng schedule.callback.", 19)
        c.setdefault("ground_truth_facts", {})["callback_at"] = result["callback_at"]
        add(sid, name, "ground_truth_facts.callback_at", None, result["callback_at"], "Kết quả schedule.callback của mock BTC.", 19)
        tools = out_dir / "tools" / f"scenarios_{sid}" / f"{name}.json"
        planned = json.loads(tools.read_text(encoding="utf-8")) if tools.exists() else []
        planned.append({"name": "schedule.callback", "args": {"customer_phone": s["customer_phone"], "callback_at": at,
                                                             "note": "khách hẹn gọi lại khi có hàng"}, "result": result})
        tools.parent.mkdir(parents=True, exist_ok=True)
        tools.write_text(json.dumps(planned, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        add(sid, name, "tools (oracle)", None, "schedule.callback", "Agent lý tưởng ghi lịch gọi lại.", 19)


def add_stated_facts(scenarios: dict, g14: dict, add) -> None:
    """Group 14: facts_established holds a fact the customer says in no call and no seed history; a later call may
    forbid asking it (RQR) or require it (CCR). The customer now says it, in the first turn (as groups 1 and 3 add
    the customer's words). add(sid, call, field, source, proposed, evidence)."""
    for item, slots in g14.items():
        sid, name = ref(item)
        s = scenarios[sid]
        c = s["calls"][name]
        slots = slots.split()
        line = stated_line(speaker_pronoun(s, c), c["facts_established"], slots)
        old = c["customer_turns"][0]
        c["customer_turns"][0] = f"{old.rstrip()} {line}"
        if c.get("customer_turns_asr"):
            c["customer_turns_asr"][0] = f"{c['customer_turns_asr'][0].rstrip()} {plain(line)}"
        labelled = ", ".join(f"{k}={c['facts_established'][k]}" for k in slots)
        add(sid, name, "customer_turns[0]", old, c["customer_turns"][0],
            f"{NEW_SOURCE}, nhóm 14: facts_established có {labelled} "
            "nhưng khách không nói ở cuộc nào và seed_history không có; thêm lời khách nói đúng giá trị đó.")


#: Group 14 for dev-r4, read by hand.
G14 = {
    "ADV-0010/c1": "room_area_m2",
    "ADV-0012/c1": "room_area_m2 has_children budget_vnd",
    "ADV-0013/c1": "budget_vnd",
    "ADV-0014/c1": "room_area_m2",
    "ADV-0017/c1": "child_age_months budget_vnd",
    "ADV-0020/c1": "room_area_m2 has_children budget_vnd",
    "ADV-0021/c1": "budget_vnd",
    "ADV-0026/c1": "room_area_m2 has_children budget_vnd",
    "ADV-0027/c1": "budget_vnd",
    "ADV-0028/c1": "budget_vnd",
    "ADV-0031/c1": "budget_vnd",
    "ADV-0034/c2": "child_age_months",
    "ADV-0037/c1": "budget_vnd",
    "ADV-0044/c1": "child_age_months budget_vnd",
    "ADV-0044/c2": "budget_vnd",
    "ADV-0045/c1": "budget_vnd",
    "ADV-0046/c1": "room_area_m2 has_children budget_vnd",
    "ADV-0052/c1": "child_age_months",
    "ADV-0053/c1": "child_age_months budget_vnd",
    "ADV-0054/c1": "room_area_m2 has_children budget_vnd",
    "ADV-0057/c1": "budget_vnd",
    "ADV-0060/c1": "budget_vnd",
    "ADV-0062/c2": "child_age_months",
    "ADV-0063/c2": "child_age_months",
    "ADV-0064/c1": "budget_vnd",
    "ADV-0066/c1": "budget_vnd",
    "ADV-0071/c1": "child_age_months",
    "ADV-0073/c1": "room_area_m2 has_children budget_vnd",
    "ADV-0074/c1": "budget_vnd",
    "ADV-0075/c1": "budget_vnd",
    "ADV-0081/c1": "child_age_months budget_vnd",
    "ADV-0082/c1": "budget_vnd",
    "ADV-0083/c2": "budget_vnd",
    "ADV-0088/c1": "budget_vnd",
    "ADV-0089/c1": "child_age_months",
    "ADV-0090/c1": "child_age_months budget_vnd",
    "ADV-0090/c2": "budget_vnd",
    "ADV-0097/c2": "child_age_months",
    "ADV-0099/c1": "child_age_months",
    "ADV-0100/c1": "room_area_m2 has_children budget_vnd",
    "ADV-0101/c1": "room_area_m2 has_children",
    "ADV-0107/c1": "room_area_m2 has_children budget_vnd",
    "ADV-0108/c1": "budget_vnd",
    "ADV-0115/c1": "child_age_months budget_vnd",
    "ADV-0116/c1": "budget_vnd",
    "ADV-0117/c1": "budget_vnd",
    "ADV-0118/c1": "has_children",
    "ADV-0121/c1": "room_area_m2 has_children budget_vnd",
    "ADV-0126/c1": "budget_vnd",
    "ADV-0127/c1": "budget_vnd",
    "ADV-0134/c1": "budget_vnd",
    "ADV-0137/c1": "budget_vnd",
    "ADV-0140/c1": "budget_vnd",
    "ADV-0141/c1": "child_age_months",
    "ADV-0142/c1": "child_age_months",
    "ADV-0146/c1": "budget_vnd",
    "ADV-0147/c1": "budget_vnd",
    "ADV-0149/c1": "room_area_m2 has_children budget_vnd",
    "ADV-0150/c1": "budget_vnd",
    "GEN-0001/c1": "has_children",
    "GEN-0004/c2": "room_area_m2",
    "GEN-0009/c1": "child_age_months",
    "GEN-0010/c1": "room_area_m2 has_children budget_vnd",
    "GEN-0012/c1": "child_age_months budget_vnd",
    "GEN-0015/c2": "room_area_m2",
    "GEN-0016/c1": "has_children budget_vnd",
    "GEN-0018/c1": "child_age_months budget_vnd",
    "GEN-0029/c1": "room_area_m2 has_children budget_vnd",
    "GEN-0036/c1": "budget_vnd",
    "GEN-0044/c1": "child_age_months",
    "GEN-0048/c1": "has_children",
    "GEN-0049/c1": "budget_vnd",
    "GEN-0053/c1": "has_children budget_vnd",
    "GEN-0057/c1": "has_children",
    "GEN-0063/c1": "child_age_months",
    "GEN-0065/c2": "room_area_m2 budget_vnd",
    "GEN-0066/c1": "room_area_m2 budget_vnd",
    "GEN-0068/c1": "budget_vnd",
    "GEN-0070/c1": "child_age_months",
    "GEN-0071/c1": "child_age_months budget_vnd",
    "GEN-0075/c1": "budget_vnd",
    "GEN-0078/c1": "child_age_months",
    "GEN-0079/c1": "child_age_months",
    "GEN-0082/c1": "has_children budget_vnd",
    "GEN-0083/c1": "budget_vnd",
    "GEN-0086/c2": "budget_vnd",
    "GEN-0089/c1": "room_area_m2 has_children",
    "GEN-0091/c1": "budget_vnd",
    "GEN-0094/c1": "child_age_months",
    "GEN-0097/c2": "room_area_m2",
    "GEN-0098/c1": "child_age_months budget_vnd",
    "GEN-0106/c1": "child_age_months budget_vnd",
    "GEN-0107/c1": "budget_vnd",
    "GEN-0110/c1": "room_area_m2 has_children budget_vnd",
    "GEN-0111/c1": "budget_vnd",
    "GEN-0115/c1": "budget_vnd",
    "GEN-0115/c2": "room_area_m2 budget_vnd",
    "GEN-0118/c1": "child_age_months",
    "GEN-0125/c1": "child_age_months",
    "GEN-0129/c1": "budget_vnd",
    "GEN-0133/c1": "budget_vnd",
    "GEN-0139/c1": "room_area_m2",
    "GEN-0145/c1": "has_children",
    "GEN-0147/c2": "room_area_m2",
    "GEN-0150/c1": "budget_vnd",
    "GEN-0153/c1": "budget_vnd",
    "GEN-0155/c1": "budget_vnd",
    "GEN-0155/c2": "budget_vnd",
    "GEN-0157/c1": "has_children",
    "GEN-0162/c1": "child_age_months",
    "GEN-0163/c1": "has_children",
    "GEN-0170/c1": "child_age_months",
    "GEN-0173/c1": "budget_vnd",
    "GEN-0178/c1": "budget_vnd",
    "GEN-0179/c1": "child_age_months",
    "GEN-0182/c1": "has_children",
    "GEN-0186/c2": "budget_vnd",
    "GEN-0187/c1": "child_age_months",
    "GEN-0188/c1": "child_age_months budget_vnd",
    "GEN-0189/c1": "budget_vnd",
    "GEN-0191/c1": "budget_vnd",
    "GEN-0197/c1": "budget_vnd",
    "GEN-0197/c2": "room_area_m2 budget_vnd",
    "GEN-0198/c1": "child_age_months budget_vnd",
    "GEN-0207/c1": "budget_vnd",
    "GEN-0209/c1": "budget_vnd",
    "GEN-0210/c1": "has_children",
    "GEN-0212/c1": "budget_vnd",
    "GEN-0215/c2": "room_area_m2",
    "GEN-0216/c1": "has_children budget_vnd",
    "GEN-0217/c1": "budget_vnd",
    "GEN-0217/c2": "budget_vnd",
    "GEN-0218/c1": "child_age_months",
    "GEN-0223/c1": "budget_vnd",
    "GEN-0225/c1": "child_age_months budget_vnd",
    "GEN-0227/c1": "budget_vnd",
    "GEN-0228/c1": "child_age_months",
    "GEN-0232/c1": "child_age_months budget_vnd",
    "GEN-0236/c1": "budget_vnd",
    "GEN-0237/c1": "budget_vnd",
    "GEN-0239/c1": "room_area_m2",
    "GEN-0241/c1": "budget_vnd",
    "GEN-0247/c2": "room_area_m2",
    "GEN-0248/c1": "has_children budget_vnd",
}

#: Group 17: the anonymous chat (fb.anon, no phone said) cannot be joined to the later hotline call from a number the
#: CRM does not know, so the later call keeps only what the customer says again in it. The reviewer's rule: had the
#: customer given a phone number, the agent would have to save them and keep the context.
G17 = {  # (scenario, call): (must_carry_over, must_not_ask) kept
    ref("ADV-0050/c2"): (["size", "product_advised", "variant_sku"], ["size", "color", "product_advised", "variant_sku"]),
    ref("ADV-0093/c2"): ([], []),
    ref("ADV-0145/c2"): (["blocker"], []),
}
#: Group 18: owned_sku from the CRM history is context only; this call buys a filter for the AirPure Pro the customer
#: names, while the history holds a Lock&Lock air fryer. Carrying owned_sku would require the unrelated item.
G18 = calls("ADV-0045/c1")


def apply_anon_and_owned(scenarios: dict, g17: dict, g18, add) -> None:
    for (sid, name), (carry, nask) in g17.items():
        if sid not in scenarios:
            continue
        c = scenarios[sid]["calls"][name]
        for key, kept in (("must_carry_over", carry), ("must_not_ask", nask)):
            before = list(c.get(key) or [])
            after = [x for x in before if x in kept]
            if after != before:
                if after:
                    c[key] = after
                else:
                    c.pop(key, None)
                add(sid, name, key, before, after or "<bỏ>", f"{NEW_SOURCE}, nhóm 17: call_1 chat ẩn danh (fb.anon), "
                    "khách không đọc SĐT nên không nối được với cuộc hotline này; chỉ giữ slot khách nói lại trong cuộc.", 17)
    for sid, name in g18:
        c = scenarios[sid]["calls"][name]
        before = list(c.get("must_carry_over") or [])
        if "owned_sku" in before:
            c["must_carry_over"] = [x for x in before if x != "owned_sku"]
            add(sid, name, "must_carry_over", before, c["must_carry_over"], f"{NEW_SOURCE}, nhóm 18: seed_history chỉ là "
                "thông tin tham khảo; cuộc này mua màng lọc cho AirPure Pro khách nêu, còn lịch sử là nồi chiên Lock&Lock.", 18)

#: Group 16: freeship labelled true with no delivery area known (NAM-SHIP0 needs a southern address).
G16 = calls("ADV-0065/c2, GEN-0111/c2")

#: Group 11b: blocker labels whose line has the cue word of their kind, read one by one. None: the line states no
#: reason not to buy (the schema: null when the line gives no reason), or the reason is already settled.
BLOCKER_CUE = {
    "SCN-GEN-0025-call_2-t5": None,              # "hôm nay anh sẽ không quyết định mua": no reason given
    "SCN-GEN-0053-call_2-t5": None,              # "nếu em không giảm thêm thì chắc chị không mua đâu": no reason of a kind
    "SCN-GEN-0078-call_2-t4": None,              # asks to be transferred
    "SCN-GEN-0225-call_2-t4": None,              # "có thể tìm sản phẩm khác phù hợp hơn": another product, not price
    "SCN-GEN-0245-call_2-t4": None,              # "em kiểm tra giúp chị, chị sẽ gọi lại sau": no reason
    "SCN-GEN-0142-call_3-t3": None,              # "đã bàn với gia đình rồi nên giờ chị muốn lên đơn": settled
    "SCN-GEN-0156-call_2-t2": None,              # "đã hỏi vợ và quyết định mua rồi": settled
    "SCN-ADV-0118-call_1-t6": None,              # "còn chờ lương nhưng chị muốn chốt đơn ngay": buys now
    "SCN-GEN-0023-call_2-t3": "vuot ngan sach",  # "không thấy thuyết phục lắm với giá này": the price, nothing compared
    "SCN-GEN-0053-call_2-t1": "vuot ngan sach",  # "giá bên em vẫn cao lắm"
    "SCN-GEN-0075-call_2-t3": "vuot ngan sach",  # "giá cũng cao, có cách nào tiết kiệm hơn"
    "SCN-GEN-0173-call_2-t4": "vuot ngan sach",  # "anh cần giá tốt hơn để chốt đơn"
}

#: Group 11c (raised by the reviewer, 09/11/2026): "vuot ngan sach" on a line that only states the budget ("ngân sách
#: của chị chỉ khoảng bốn triệu thôi"). The schema: null when the line gives no reason. Kept: SCN-ADV-0110-call_2-t4
#: ("ngân sách eo hẹp quá nên cần trả góp"), a reason.
BLOCKER_BUDGET_ONLY = """SCN-ADV-0012-call_2-t4 SCN-ADV-0025-call_1-t4 SCN-ADV-0038-call_1-t3 SCN-ADV-0073-call_2-t4
SCN-ADV-0107-call_2-t4 SCN-ADV-0109-call_1-t4 SCN-ADV-0142-call_1-t4 SCN-GEN-0072-call_1-t3 SCN-GEN-0088-call_1-t4
SCN-GEN-0099-call_2-t5 SCN-GEN-0103-call_1-t5 SCN-GEN-0125-call_1-t4 SCN-GEN-0137-call_1-t4 SCN-GEN-0222-call_1-t4
SCN-GEN-0228-call_1-t3""".split()
#: Group 25 (raised by the reviewer, 09/11/2026): "Chị có một bé lớn" with has_children false (no small child): the
#: line says so plainly, the label stays.
G25 = {ref("GEN-0099/c1"): ("Chị có một bé lớn, mà ngân sách", "Nhà chị không có trẻ nhỏ, bé nhà chị lớn rồi, mà ngân sách")}
REVIEWER_RAISED = "Người duyệt nêu và yêu cầu sửa ngày 09/11/2026"

#: Group 26 (the reviewer's decision, 09/11/2026): "Nhà anh có một phòng ngủ của con" with has_children false; the
#: reviewer chose to change the label (the customer has a child), not the words.
G26 = calls("ADV-0031/c1, ADV-0126/c1")


def apply_g26(scenarios: dict, add) -> None:
    """add(sid, call, field, source, proposed, evidence) records a change the reviewer decided."""
    for sid, name in G26:
        if sid not in scenarios:
            continue
        c = scenarios[sid]["calls"][name]
        for key in ("facts_established", "memory_expectation"):
            if (c.get(key) or {}).get("has_children") is False:
                c[key]["has_children"] = True
                add(sid, name, f"{key}.has_children", False, True, f"{REVIEWER_RAISED}, nhóm 26: khách nói \"Nhà anh có một "
                    "phòng ngủ của con\"; người duyệt chọn đổi nhãn (khách có con) thay vì sửa lời.")


#: Groups 27-30: a second check of every call (09/11/2026), the reviewer asked for these fixes.
SECOND_CHECK = "Lần kiểm thứ hai (người kiểm khác) báo, người duyệt yêu cầu sửa ngày 09/11/2026"
#: Group 27: args_match.payment the customer never says; the customer now says it, before the last turn.
G27 = {"dev": {ref("ADV-0053/c2"): "bank", ref("GEN-0001/c1"): "COD", ref("GEN-0216/c1"): "bank", ref("GEN-0248/c1"): "COD"},
       "test": {}}
#: Group 28: room_area_m2 the customer never says (the returning customers moved house; the CRM's 20 m² is from the
#: expired history), while call_2 forbids asking it: the customer now says the room of the new home.
G28 = {"dev": calls("GEN-0016/c1, GEN-0048/c1, GEN-0082/c1, GEN-0148/c1, GEN-0182/c1, GEN-0216/c1, GEN-0248/c1, "
                    "ADV-0023/c1, ADV-0118/c1"),
       "test": calls("GEN-0048/c1, ADV-0023/c1")}
#: Group 29: two people on one phone. call_2's caller is the other person: facts they do not say are not theirs.
G29 = {"dev": {ref(k): v.split() for k, v in {
    "GEN-0004/c2": "has_children budget_vnd", "GEN-0015/c2": "has_children budget_vnd", "GEN-0047/c2": "budget_vnd",
    "GEN-0065/c2": "has_children", "GEN-0081/c2": "usage_need budget_vnd", "GEN-0097/c2": "has_children budget_vnd",
    "GEN-0105/c2": "budget_vnd", "GEN-0115/c2": "has_children", "GEN-0131/c2": "budget_vnd",
    "GEN-0147/c2": "has_children", "GEN-0155/c2": "usage_need", "GEN-0165/c2": "budget_vnd",
    "GEN-0181/c2": "usage_need budget_vnd", "GEN-0197/c2": "has_children", "GEN-0205/c2": "usage_need",
    "GEN-0215/c2": "has_children budget_vnd", "GEN-0231/c2": "budget_vnd", "GEN-0247/c2": "has_children"}.items()},
       "test": {ref(k): v.split() for k, v in {
    "GEN-0004/c2": "has_children budget_vnd", "GEN-0005/c2": "budget_vnd", "GEN-0031/c2": "budget_vnd",
    "GEN-0047/c2": "budget_vnd"}.items()}}
#: Group 30: who says what on a shared phone. Loan is "cô" in the CRM (C034), Dung "chị" (C035).
LOAN_SELF = re.compile(r"\b([Cc])hị\b(?! Dung)")
G30_LINES = {"dev": {
    ref("GEN-0081/c2"): [("hôm trước em tư vấn cho chị Dung về máy lọc nước RO Karofi 9 lõi", "hôm trước cô có hỏi em về máy lọc nước RO Karofi 9 lõi")],
    ref("GEN-0131/c2"): [("Hôm qua em đã tư vấn cho chị Dung về máy lọc nước RO đúng không?", "Hôm qua cô có hỏi em về máy lọc nước RO đúng không?")],
    ref("GEN-0097/c2"): [("hôm trước có tư vấn cho cô Loan", "hôm trước em có tư vấn cho cô Loan")]}, "test": {}}
G30_LOAN = {"dev": calls("GEN-0005/c2, GEN-0055/c2, GEN-0081/c2, GEN-0131/c2, GEN-0181/c2"), "test": []}


def apply_second_check(scenarios: dict, which: str, add) -> None:
    """Groups 27-30; add(sid, call, field, source, proposed, evidence, group)."""
    def say(c, index, line):
        old = c["customer_turns"][index]
        c["customer_turns"][index] = f"{old.rstrip()} {line}"
        if c.get("customer_turns_asr"):
            c["customer_turns_asr"][index] = f"{c['customer_turns_asr'][index].rstrip()} {plain(line)}"
        return old
    for (sid, name), pay in G27[which].items():
        s, c = scenarios[sid], scenarios[sid]["calls"][name]
        who = speaker_pronoun(s, c)
        line = f"{who.capitalize()} thanh toán chuyển khoản ngân hàng nhé." if pay == "bank" else \
            f"{who.capitalize()} trả tiền mặt khi nhận hàng nhé."
        i = len(c["customer_turns"]) - 2
        old = say(c, i, line)
        add(sid, name, f"customer_turns[{i}]", old, c["customer_turns"][i], f"{SECOND_CHECK}, nhóm 27: args_match.payment={pay} "
            "nhưng khách không nói cách thanh toán; agent hỏi lại thì không có câu trả lời (TSR).", 27)
    for sid, name in G28[which]:
        s, c = scenarios[sid], scenarios[sid]["calls"][name]
        area = c["facts_established"]["room_area_m2"]
        line = f"Phòng mới của {speaker_pronoun(s, c)} khoảng {area} mét vuông."
        old = say(c, 0, line)
        add(sid, name, "customer_turns[0]", old, c["customer_turns"][0], f"{SECOND_CHECK}, nhóm 28: room_area_m2={area} nhưng khách "
            "không nói (khách đã chuyển nhà, lịch sử CRM 20 m² đã quá hạn); call_2 cấm hỏi diện tích (RQR).", 28)
    for (sid, name), slots in G29[which].items():
        c = scenarios[sid]["calls"][name]
        for key in ("facts_established", "memory_expectation"):
            for slot in slots:
                if slot in (c.get(key) or {}):
                    add(sid, name, f"{key}.{slot}", c[key].pop(slot), "<bỏ>", f"{SECOND_CHECK}, nhóm 29: hai người chung SĐT; "
                        "người gọi cuộc này không nói điều đó, fact là của người kia.", 29)
    for (sid, name), swaps in G30_LINES[which].items():
        c = scenarios[sid]["calls"][name]
        for i, turn in enumerate(c["customer_turns"]):
            new = turn
            for old, repl in swaps:
                new = new.replace(old, repl)
            if new != turn:
                c["customer_turns"][i] = new
                if c.get("customer_turns_asr"):
                    c["customer_turns_asr"][i] = plain(new)
                add(sid, name, f"customer_turns[{i}]", turn, new, f"{SECOND_CHECK}, nhóm 30: câu mở đầu lẫn vai giữa hai người chung SĐT.", 30)
    for sid, name in G30_LOAN[which]:
        c = scenarios[sid]["calls"][name]
        for i, turn in enumerate(c["customer_turns"]):
            new = LOAN_SELF.sub(lambda m: "Cô" if m.group(1) == "C" else "cô", turn)
            if new != turn:
                c["customer_turns"][i] = new
                if c.get("customer_turns_asr"):
                    c["customer_turns_asr"][i] = plain(new)
                add(sid, name, f"customer_turns[{i}]", turn, new, f"{SECOND_CHECK}, nhóm 30: người gọi là cô Loan (CRM C034, "
                    "\"cô\"), lời lại tự xưng \"chị\".", 30)


# ── Group 10: what the customer calls themselves, to match the label "anh" ──────────────────────────────────────
G10 = {"SCN-ADV-0021": "co", "SCN-ADV-0082": "co", "SCN-ADV-0116": "co", "SCN-ADV-0034": "chi"}


def as_anh(text: str, speaker: str) -> str:
    if speaker == "chi":
        return re.sub(r"\bChị\b", "Anh", re.sub(r"\bchị\b", "anh", text))
    for old, new in (("cho cháu 13 tháng tuổi", "cho bé nhà anh 13 tháng tuổi"), ("con cháu", "người nhà"),
                     ("cháu ơi", "em ơi")):
        text = text.replace(old, new)
    for old, new in (("Cháu", "Em"), ("cháu", "em"), ("Cô", "Anh"), ("cô", "anh")):
        text = re.sub(rf"\b{old}\b", new, text)
    return text


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="accepted for old commands; every run rebuilds")
    parser.parse_args()
    global SRC
    SRC = source_tree("dev", SOURCE_REF)
    kept: dict[str, str] = {}
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "scenarios").mkdir(parents=True)
    shutil.copytree(SRC / "metadata", OUT / "metadata")
    shutil.copytree(SRC / "asr_reference", OUT / "asr_reference")
    # What the ideal agent does and says (build_ground_truth builds the oracle trace from these).
    for folder in ("tools", "call_brief", "handoff_brief"):
        shutil.copytree(SRC / folder, OUT / folder)
    for name, text in kept.items():
        (OUT / name).write_text(text, encoding="utf-8")
    for name in HAND_WRITTEN:  # the notes in git win over a kept copy; byte for byte
        if (NOTES / name).exists():
            shutil.copyfile(NOTES / name, OUT / name)
    scenarios = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((SRC / "scenarios").glob("*.json"))}
    source_sha = {p.name: sha(p) for p in sorted((SRC / "scenarios").glob("*.json"))}

    def call(sid, name):
        return scenarios[sid]["calls"][name]

    # Group 1 (+ chat calls of 7).
    for sid, name in G1:
        s, c = scenarios[sid], call(sid, name)
        assert c.get("channel") in ("chat_fanpage", "zalo_oa"), (sid, name, c.get("channel"))
        line = f"Số {s['honorific']} là {s['customer_phone']}."
        turns = c["customer_turns"]
        old = turns[-1]
        turns[-1] = f"{old.rstrip()} {line}"
        record(sid, name, "customer_turns[-1]", old, turns[-1], f"{AUDIT} nhóm 1: kênh {c['channel']} mã "
               f"{c.get('channel_identity')} không có trong CRM, khách không đọc SĐT; SAMPLE-04: khách đọc số trong chat.", 1, True)
        if c.get("customer_turns_asr"):
            asr_old = c["customer_turns_asr"][-1]
            c["customer_turns_asr"][-1] = f"{asr_old.rstrip()} {plain(line)}"
            record(sid, name, "customer_turns_asr[-1]", asr_old, c["customer_turns_asr"][-1], "Cùng lời thêm ở trên.", 1, True)
        if (c.get("facts_established") or {}).get("phone_provided") is not True:
            record(sid, name, "facts_established.phone_provided", (c.get("facts_established") or {}).get("phone_provided"),
                   True, "Khách đọc SĐT ở lượt vừa thêm.", 1, True)
            c.setdefault("facts_established", {})["phone_provided"] = True
    for sid, name in G1_ANON:
        disputed[f"{sid}/{name}"] = ("Nhóm 1: khách ẩn danh có chủ đích, giữ lời thoại; must_carry_over của cuộc sau "
                                     "chưa rà (agent không thể biết khách).")

    # Group 7, hotline calls: the customer never says their own number.
    for sid, name in G7_HOTLINE:
        c = call(sid, name)
        for key in ("facts_established", "memory_expectation"):
            if (c.get(key) or {}).get("phone_provided") is not None:
                record(sid, name, f"{key}.phone_provided", c[key]["phone_provided"], "<bỏ>",
                       "Nhóm 7: hotline, không lượt nào khách đọc SĐT của mình (SAMPLE-04 ghi phone_provided bằng số "
                       "khách đọc). must_not_ask của cuộc sau giữ nguyên: hệ thống đã biết số gọi tới.", 7, False)
                del c[key]["phone_provided"]
                if not c[key]:
                    del c[key]  # BTC's samples leave an empty section out (scenario-keys.yaml rules.values)

    # Group 2.
    for sid, name in G2:
        c = call(sid, name)
        before = list(c["must_carry_over"])
        c["must_carry_over"] = [s for s in before if s != "owned_sku"]
        record(sid, name, "must_carry_over", before, c["must_carry_over"], f"{AUDIT} nhóm 2: cuộc gọi về sản phẩm khác "
               "món đã mua; không mẫu BTC nào đòi nhớ owned_sku; PB-01 chỉ nhắc thông tin liên quan.", 2, True)

    # Group 3.
    for sid, name in G3:
        s, c = scenarios[sid], call(sid, name)
        turns = c["customer_turns"]
        index = max(i for i, t in enumerate(turns) if COD_WORDS.search(t))
        line = f"Vậy {s['honorific']} chuyển khoản nhé."
        turns.insert(index + 1, line)
        record(sid, name, f"customer_turns[{index + 1}]", "<không có>", line, f"{AUDIT} nhóm 3: cod_allowed false, nhãn "
               f"payment bank và order.create, nhưng khách chỉ đòi COD (\"{turns[index]}\"); thêm lời đồng ý chuyển khoản "
               "(VC-03, QT-01).", 3, True)
        assert not c.get("customer_turns_asr"), (sid, name)

    # Group 4.
    for (sid, name), approved, why in [
        (ref("ADV-0028/c1"), True, "nhóm 4: câu cuối \"Chị cần suy nghĩ thêm một chút trước khi chốt đơn.\""),
        (ref("ADV-0023/c1"), False, "nhóm 4 (đề xuất của Claude): câu cuối \"Chị chờ cuối tháng này nhận lương rồi "
         "thanh toán qua ngân hàng nhé.\", blocker \"chờ cuối tháng nhận lương\": khách chưa đặt hôm nay."),
    ]:
        c = call(sid, name)
        new = {"tool_called": None, "must_not_call_tools": ["order.create"],
               **{k: v for k, v in c["success_if"].items() if k in ("forbidden_claims", "must_say_any", "max_agent_questions")}}
        record(sid, name, "success_if", c["success_if"], new, AUDIT + " " + why, 4, approved)
        record(sid, name, "expected_outcome", c["expected_outcome"], "hen_goi_lai", "Cùng lý do.", 4, approved)
        c["success_if"], c["expected_outcome"] = new, "hen_goi_lai"
        for key in ("facts_established", "memory_expectation", "ground_truth_facts"):
            if "order_id" in (c.get(key) or {}):
                record(sid, name, f"{key}.order_id", c[key].pop("order_id"), "<bỏ>", "Không có đơn được tạo.", 4, approved)
        tools = OUT / "tools" / f"scenarios_{sid}" / f"{name}.json"
        if tools.exists():
            planned = json.loads(tools.read_text(encoding="utf-8"))
            kept_calls = [t for t in planned if t.get("name") != "order.create"]
            if kept_calls != planned:
                tools.write_text(json.dumps(kept_calls, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                record(sid, name, "tools (oracle)", [t["name"] for t in planned], [t["name"] for t in kept_calls],
                       "Agent lý tưởng không tạo đơn khi khách chưa quyết.", 4, approved)

    # Group 5.
    for (sid, name), slots in G5.items():
        c = call(sid, name)
        before = list(c["must_carry_over"])
        c["must_carry_over"] = [s for s in before if s not in slots]
        record(sid, name, "must_carry_over", before, c["must_carry_over"], f"{AUDIT} nhóm 5: cuộc "
               f"{c['success_if'].get('tool_called')} không cần {', '.join(slots)}; vẫn giữ ở must_not_ask nếu có.", 5, True)

    # Group 8.
    for (sid, name), (old, new) in G8.items():
        c = call(sid, name)
        said = next(t for t in c["customer_turns"] if "triệu" in t)
        for key in ("facts_established", "memory_expectation"):
            if (c.get(key) or {}).get("budget_vnd") == old:
                c[key]["budget_vnd"] = new
                record(sid, name, f"{key}.budget_vnd", old, new, f"{AUDIT} nhóm 8: khách nói \"{said}\".", 8, True)
    disputed["SCN-GEN-0083/call_1"] = ("budget_vnd 8.500.000 ở facts_established/memory_expectation nhưng khách không nói "
                                       "ngân sách trong call_1; chưa sửa vì cuộc sau có thể dựa vào nó.")

    # Group 9.
    promotions = json.loads((BTC / "catalog" / "promotions.json").read_text(encoding="utf-8"))
    kinds = {p["promo_code"]: p["type"] for p in promotions.get("promotions", promotions)}
    for sid, name in G9:
        g = call(sid, name)["ground_truth_facts"]
        active = [k[6:-7] for k, v in g.items() if k.startswith("promo_") and k.endswith("_active") and k != "promo_active" and v is True]
        assert g.get("promo_active") is True and active and all(kinds[a] in NOT_A_PROMOTION for a in active), (sid, name, active)
        g["promo_active"] = False
        record(sid, name, "ground_truth_facts.promo_active", True, False, f"{AUDIT} nhóm 9: chương trình đang chạy chỉ là "
               f"{', '.join(f'{a} ({kinds[a]})' for a in active)}; quy ước promo_active = giảm giá hoặc quà tặng, "
               "freeship có khóa freeship riêng.", 9, True)

    # Group 10.
    for sid, who in G10.items():
        for name, c in scenarios[sid]["calls"].items():
            for i, old in enumerate(list(c["customer_turns"])):
                new = as_anh(old, who)
                if new != old:
                    c["customer_turns"][i] = new
                    record(sid, name, f"customer_turns[{i}]", old, new, f"{AUDIT} nhóm 10: nhãn và CRM là \"anh\" "
                           f"({scenarios[sid]['customer_name']}), khách tự xưng khác.", 10, True)
                    if c.get("customer_turns_asr"):
                        c["customer_turns_asr"][i] = plain(new)
                        record(sid, name, f"customer_turns_asr[{i}]", "<theo lời cũ>", plain(new), "Sinh lại từ lời mới.", 10, True)
            for key in ("facts_established", "memory_expectation"):
                if (c.get(key) or {}).get("blocker") == "cần hỏi con cháu":
                    c[key]["blocker"] = "cần hỏi người nhà"
                    record(sid, name, f"{key}.blocker", "cần hỏi con cháu", "cần hỏi người nhà",
                           "Nhóm 10: lời khách đổi \"con cháu\" thành \"người nhà\".", 10, True)

    # Group 12: where each scenario's customer comes from (metadata only).
    btc_phones = {c.get("phone") for c in json.loads((BTC / "catalog" / "crm_seed.json").read_text(encoding="utf-8"))["customers"]}
    for path in sorted((OUT / "metadata").glob("*.json")):
        meta = json.loads(path.read_text(encoding="utf-8"))
        phone = scenarios[path.stem]["customer_phone"]
        # A tag, not a key: the generator's Scenario model forbids keys it does not know.
        meta["tags"] = sorted({*meta.get("tags", []), "source:btc" if phone in btc_phones else "source:team"})
        path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    record("*", "*", "metadata.tags", None, "source:btc | source:team", f"{AUDIT} nhóm 12: khách có trong crm_seed.json "
           "của BTC là source:btc, còn lại (crm_seed_synthetic.json của đội) là source:team; để báo cáo tách hai phần.",
           12, False)

    def add_action(sid, name, field, source, proposed, evidence, group):
        changes.append({"scenario_id": sid, "call": name, "field": field, "source": source, "proposed": proposed,
                        "evidence": evidence, "group": group, **status_action()})

    apply_actions(scenarios, OUT, add_action, "dev")
    apply_g26(scenarios, lambda sid, name, field, source, proposed, evidence: record(sid, name, field, source, proposed,
                                                                                     evidence, 26, True))
    for (sid, name), (old_text, new_text) in G25.items():
        c = call(sid, name)
        i = next(k for k, turn in enumerate(c["customer_turns"]) if old_text in turn)
        old = c["customer_turns"][i]
        c["customer_turns"][i] = old.replace(old_text, new_text)
        if c.get("customer_turns_asr"):
            c["customer_turns_asr"][i] = plain(c["customer_turns"][i])
        record(sid, name, f"customer_turns[{i}]", old, c["customer_turns"][i], f"{REVIEWER_RAISED}, nhóm 25: has_children: false "
               "(nhà không có trẻ nhỏ) nhưng câu \"có một bé lớn\" dễ đọc thành có trẻ; nói rõ, nhãn giữ nguyên.", 25, True)

    def add_new(sid, name, field, source, proposed, evidence, group=14):
        changes.append({"scenario_id": sid, "call": name, "field": field, "source": source, "proposed": proposed,
                        "evidence": evidence, "group": group, **status_new()})

    add_stated_facts(scenarios, G14, add_new)
    apply_second_check(scenarios, "dev", lambda sid, name, field, source, proposed, evidence, group:
                       record(sid, name, field, source, proposed, evidence, group, True))
    apply_anon_and_owned(scenarios, G17, G18, add_new)
    for sid, name in G16:
        g = call(sid, name)["ground_truth_facts"]
        add_new(sid, name, "ground_truth_facts.freeship", g.pop("freeship"), "<bỏ>", f"{NEW_SOURCE}, nhóm 16: sản phẩm "
                "dưới 2.000.000đ chỉ được miễn phí ship nhờ NAM-SHIP0 (miền Nam), nhưng khách không nói nơi giao và CRM "
                "không có địa chỉ; không biết được freeship hay không.", 16)

    for sid, s in scenarios.items():
        (OUT / "scenarios" / f"{sid}.json").write_text(json.dumps(s, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    asr_changes = relabel_asr()

    report = {"revision": "dev-r4", "source": "dev (seed-dev-r3)", "built_by": "evaluation/datasets/ground-truth-review/build_dev_r4.py",
              "official_gt_approved": False,
              "reviewer": {"name": REVIEWER, "date": DAY, "scope": "Chấp nhận đề xuất của bản tổng hợp cho nhóm 1 (thêm SĐT), "
                           "2, 3 (thêm lời đồng ý chuyển khoản), 4 (SCN-ADV-0028), 5, 8, 9 (promo_active = giảm giá hoặc "
                           "quà), 10 và phần định dạng của 11. "
                           + (f"Ngày {CLAUDE_PROPOSALS_REVIEWED}, chấp nhận cả các đề xuất của Claude (proposed_by: "
                              "claude): ADV-0023, 7 cuộc hotline nhóm 7, nhãn blocker/promo_expiry/phone/tiền/"
                              "restock_date của nhóm 11, tag nguồn nhóm 12."
                              if CLAUDE_PROPOSALS_REVIEWED else "Các mục còn lại do Claude đề xuất, chờ duyệt.")},
              "source_scenario_sha256": source_sha, "changes": changes + asr_changes, "disputed": disputed}
    (OUT / "conversion-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    install(OUT, DEST)
    counts = {}
    for item in report["changes"]:
        counts.setdefault((item["group"], item["decision"]), 0)
        counts[(item["group"], item["decision"])] += 1
    print(json.dumps({f"{g}/{d}": n for (g, d), n in sorted(counts.items(), key=lambda kv: str(kv[0]))}, ensure_ascii=False))
    return 0


def relabel_asr() -> list[dict]:
    """Group 11 on asr_reference: ground_truth.json and the per-call files it is built from."""
    out: list[dict] = []
    path = OUT / "asr_reference" / "ground_truth.json"
    truth = json.loads(path.read_text(encoding="utf-8"))
    timeline = json.dumps(json.loads((BTC / "catalog" / "inventory_timeline.json").read_text(encoding="utf-8")))
    per_call: dict[Path, dict] = {}

    def turn_file(key: str):
        sid, call, t = re.match(r"(SCN-\w+-\d+)-(call_\d+)-t(\d+)$", key).groups()
        file = OUT / "asr_reference" / f"scenarios_{sid}" / f"{call}.json"
        if file not in per_call:
            per_call[file] = json.loads(file.read_text(encoding="utf-8"))
        return next(x for x in per_call[file]["turns"] if x["idx"] == int(t))

    def change(d, field, new, why, approved, rename=None):
        old = d["entities"][field]
        targets = [d["entities"], d["turns"][0]["entities"], turn_file(d["id"])["entities"]]
        for entities in targets:
            if entities.get(field) != old:
                continue  # a per-call label that already differs is not this one
            del entities[field]
            if new is not None:
                entities[rename or field] = new
        out.append({"scenario_id": d["id"], "call": "asr_reference", "field": f"entities.{field}", "source": old,
                    "proposed": "<bỏ>" if new is None else ({rename: new} if rename else new),
                    "evidence": f"{AUDIT} nhóm 11: \"{d['full_text'][:160]}\". {why}", "group": 11,
                    **(status_new() if approved is None else status(approved))})

    for d in truth["dialogues"]:
        e = d["entities"]
        if e.get("color") in COLOR:
            change(d, "color", COLOR[e["color"]], "Không dấu, như catalog; \"màu này\" không phải một màu.", True)
        if isinstance(e.get("order_id"), str) and e["order_id"] != e["order_id"].upper():
            change(d, "order_id", e["order_id"].upper(), "Mã đơn viết hoa như tool trả.", True)
        for field in ("size_new", "size_old"):
            value = e.get(field)
            if isinstance(value, str):
                fixed = SIZE_WORDS.get(value, value.upper())
                if fixed != value:
                    change(d, field, fixed, "Size số bằng chữ số, size chữ viết hoa như catalog.", True)
        if d["id"] in SIZE_OLD_NOT_EXCHANGE and "size_old" in e:
            change(d, "size_old", e["size_old"], "Câu chỉ nêu/hỏi size, không có ý đổi.", True, rename="size_new")
        if d["id"] in RETURN_NOT_DELIVERY and "delivery_days" in e:
            change(d, "delivery_days", e["delivery_days"], "Đây là hạn đổi trả.", True, rename="return_days")
        if isinstance(e.get("restock_date"), str) and e["restock_date"].startswith("2024-"):
            if d["id"] in RESTOCK_CALLBACK:
                change(d, "restock_date", None, "Câu nói lịch gọi lại, không nói ngày có hàng (đề xuất của Claude).", False)
            else:
                fixed = "2026" + e["restock_date"][4:]
                assert fixed in timeline, fixed
                change(d, "restock_date", fixed, "Năm theo inventory_timeline.json.", True)
        if "promo_expiry" in e:
            change(d, "promo_expiry", None, "Câu nói ngày hẹn gọi lại, ngày có hàng hoặc ngày bắt đầu sale 11/11, không "
                   "nói hạn khuyến mãi; sửa năm sẽ tạo một hạn khuyến mãi không có thật (đề xuất của Claude, khác đề "
                   "xuất gốc là sửa năm).", False)
        if "phone" in e and (len(re.sub(r"\D", "", str(e["phone"]))) != 10
                             or re.search(r"tài khoản|c c c d|căn cước", d["full_text"])):
            change(d, "phone", None, "Số CCCD hoặc số tài khoản, không phải SĐT liên hệ (Phụ lục A.5); entity_schema "
                   "không có id_number/bank_account nên bỏ thay vì đổi tên (đề xuất của Claude).", False)
        for field in ("budget_vnd", "competitor_price_vnd", "price_vnd"):
            if (d["id"], field) in MONEY and field in e:
                target = MONEY[(d["id"], field)]
                if target and target in e:
                    change(d, field, None, f"Đã có {target}; nhãn trùng.", False)
                elif target:
                    change(d, field, e[field], "Giá shop báo, khách nhắc lại; không phải ngân sách hay giá nơi khác "
                           "(đề xuất của Claude).", False, rename=target)
                else:
                    change(d, field, None, "Tổng đơn hoặc giá đã mua: không có trường tương ứng (đề xuất của Claude).", False)
        if d["id"] in BLOCKER and "blocker" in e:
            change(d, "blocker", BLOCKER[d["id"]], "Đọc từng câu: câu không nêu rào cản này (đề xuất của Claude).", False)
        if d["id"] in BLOCKER_BUDGET_ONLY and e.get("blocker") == "vuot ngan sach":
            change(d, "blocker", None, f"{REVIEWER_RAISED}, nhóm 11c: câu chỉ nói ngân sách, không nói giá vượt ngân sách "
                   "(schema: null khi câu không nêu lý do).", True)
        if d["id"] in BLOCKER_CUE and "blocker" in e:
            change(d, "blocker", BLOCKER_CUE[d["id"]], f"{NEW_SOURCE}, nhóm 11b: đọc câu có từ gợi ý; câu không nêu lý do "
                   "chưa mua, lý do đã xong, hoặc là chê giá chứ không so với nơi khác (đề xuất của Claude).", None)
    path.write_text(json.dumps(truth, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for file, data in per_call.items():
        file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    sys.exit(main())
