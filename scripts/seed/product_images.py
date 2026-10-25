"""Photos for the storefront's products: openly licensed pictures found on Openverse, kept with their credit.

    py -3.12 scripts/seed/product_images.py                     # every product without a photo yet
    py -3.12 scripts/seed/product_images.py --only SKU-AP-X --skip 2   # another picture for one product
    py -3.12 scripts/seed/product_images.py --sheet             # contact sheet to review the picks

The catalogue (BTC's ``products.json``) has no photos, and half its products are
made up (AirPure, RunLite...), so a photo is an *illustration* of the kind of
product, never the model itself; the shop says so under it. Pictures come from
Openverse (api.openverse.org: Flickr, Wikimedia Commons...), only under a
licence that allows a shop to use them (CC0, public domain, CC BY, CC BY-SA),
and each keeps its title, author, licence and source link: CC BY asks for that
credit wherever the picture is shown.

What it writes:

- ``apps/web/public/products/<product>.jpg``: the picture, at most 900 px wide
  (Pillow, when installed, resizes it; otherwise the original is kept);
- ``data/seed/catalog/product_images.json``: per product, the file and its
  credit. ``scripts.seed.catalog`` stores it in ``commerce.products``
  (``image_url``, ``image_credit``) on its next run; ``"locked": true`` keeps a
  reviewed pick from being replaced.

Standard library only (plus Pillow if present), so it runs with any Python 3.10+.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "apps/ai-agent-service/data/btc/catalog/products.json"
PICTURES = ROOT / "apps/web/public/products"
MANIFEST = ROOT / "data/seed/catalog/product_images.json"
API = "https://api.openverse.org/v1/images/"
LICENSES = "cc0,pdm,by,by-sa"
AGENT = "telesales-shop-demo/1.0 (product illustrations; openverse)"
WIDTH = 900

#: What to look for, most specific first. A real brand is asked for by name; a made-up one by its kind.
QUERIES = {
    "SKU-AP-X": ["air purifier", "HEPA air purifier"],
    "SKU-AP-Y": ["air purifier", "air purifier home"],
    "SKU-AP-MINI": ["small air purifier", "desktop air purifier", "air purifier"],
    "SKU-AP-PRO": ["air purifier", "air cleaner"],
    "SKU-XM-4L": ["Xiaomi air purifier", "air purifier"],
    "SKU-XM-4P": ["Xiaomi Mi air purifier", "air purifier"],
    "SKU-SS-AX40": ["Samsung air purifier", "air purifier", "air purifier room"],
    "SKU-WF-RO9": ["reverse osmosis water purifier", "water purifier", "under sink water filter"],
    "SKU-WF-RO10": ["reverse osmosis", "water filtration system", "water purifier"],
    "SKU-WF-UF": ["water filter", "water filter pitcher", "faucet water filter"],
    "SKU-FAN-DC1": ["Panasonic electric fan", "standing fan", "electric fan"],
    "SKU-FAN-SEN": ["standing fan", "electric fan"],
    "SKU-FAN-TWR": ["tower fan", "Xiaomi fan"],
    "SKU-AF-4L": ["air fryer", "air fryer kitchen", "air fryer appliance"],
    "SKU-AF-6L": ["Philips airfryer", "Philips air fryer", "air fryer appliance"],
    "SKU-AF-XM": ["Xiaomi air fryer", "air fryer", "air fryer kitchen"],
    "SKU-SN-RUN1": ["running shoes"],
    "SKU-SN-RUN2": ["running shoe", "running shoes"],
    "SKU-SN-CAS": ["sneakers", "white sneakers", "canvas sneakers"],
    "SKU-SN-TRK": ["hiking boots"],
    "SKU-JK-WND": ["windbreaker jacket", "windbreaker"],
    "SKU-JK-DWN": ["down jacket", "puffer jacket"],
    "SKU-MB-PUMP1": ["Spectra breast pump", "breast pump"],
    "SKU-MB-PUMP2": ["Medela breast pump", "breast pump"],
    "SKU-MB-STR1": ["Joie stroller", "baby stroller"],
    "SKU-MB-STR2": ["Combi stroller", "baby stroller", "pram"],
    "SKU-MB-MON": ["baby bottle warmer", "bottle warmer", "baby bottles"],
    "SKU-MB-STER": ["baby bottle sterilizer", "bottle sterilizer", "baby bottles drying rack"],
    "SKU-MB-BOT": ["Pigeon baby bottle", "baby bottle"],
    "SKU-MB-CAR": ["Chicco car seat", "child car seat", "infant car seat"],
    "SKU-AP-X-2024": ["air purifier"],
    "SKU-SN-RUN1-OLD": ["running shoes"],
    "SKU-BDL-AIR": ["air purifier"],
    "SKU-BDL-MOM": ["breast pump"],
    "SKU-AP-FLT-X": ["HEPA filter", "air purifier filter", "air filter"],
    "SKU-AP-FLT-P": ["HEPA filter", "air filter"],
    "SKU-XM-FLT": ["Xiaomi air purifier filter", "HEPA filter"],
    "SKU-WF-CORE": ["water filter cartridge", "water filter"],
    "SKU-SN-SOCK": ["sports socks", "socks", "white socks"],
    "SKU-MB-BAG": ["breast milk storage bag", "breast milk bags", "breast milk"],
}


def _get(url: str, *, attempts: int = 3) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(3 * (attempt + 1))
    raise AssertionError


def search(query: str) -> list[dict]:
    """Openverse photos for *query* a shop may use, large enough to show."""
    params = {"q": query, "license": LICENSES, "category": "photograph", "page_size": 20, "mature": "false"}
    body = json.loads(_get(API + "?" + urllib.parse.urlencode(params)))
    return [r for r in body.get("results", []) if (r.get("width") or 0) >= 500 and (r.get("height") or 0) >= 375
            and r.get("url", "").lower().split("?")[0].endswith((".jpg", ".jpeg", ".png"))]


def _save(data: bytes, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image, ImageOps
    except ImportError:
        target.write_bytes(data)
        return
    # Phones store a photo sideways with an EXIF orientation; turn it upright before dropping the EXIF.
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    if image.width > WIDTH:
        image = image.resize((WIDTH, round(image.height * WIDTH / image.width)), Image.LANCZOS)
    image.save(target, "JPEG", quality=82, optimize=True, progressive=True)


def credit(result: dict) -> dict:
    license_name = "CC0" if result["license"] == "cc0" else (
        "Public domain" if result["license"] == "pdm" else f"CC {result['license'].upper()} {result.get('license_version') or ''}".strip())
    return {"title": result.get("title") or "", "author": result.get("creator") or "",
            "author_url": result.get("creator_url") or "", "license": license_name,
            "license_url": result.get("license_url") or "", "source_url": result.get("foreign_landing_url") or "",
            "provider": result.get("provider") or "", "openverse_id": result["id"]}


def pick(product: str, skip: int, taken: set[str]) -> tuple[dict, bytes] | None:
    """The first picture (after *skip*) for *product* that downloads and no other product uses."""
    seen = 0
    for query in QUERIES[product]:
        for result in search(query):
            if result["id"] in taken:
                continue
            if seen < skip:
                seen += 1
                continue
            try:
                return result, _get(result["url"])
            except OSError:
                continue
        time.sleep(1)
    return None


def fetch(only: list[str], skip: int, force: bool) -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    products = {p["sku"]: p for p in json.loads(PRODUCTS.read_text(encoding="utf-8"))["products"]}
    unknown = sorted(set(products) - set(QUERIES))
    if unknown:
        sys.exit(f"No query for {unknown}: add them to QUERIES")
    done, missing = [], []
    for ref in only or sorted(products):
        entry = manifest.get(ref)
        if entry and ((entry.get("locked") and ref not in only) or (not force and not only)):
            continue
        taken = {e["credit"]["openverse_id"] for key, e in manifest.items() if key != ref}
        found = pick(ref, skip, taken)
        if found is None:
            missing.append(ref)
            continue
        result, data = found
        _save(data, PICTURES / f"{ref}.jpg")
        manifest[ref] = {"image_url": f"/products/{ref}.jpg", "credit": credit(result), "query": QUERIES[ref],
                         "locked": bool(entry and entry.get("locked"))}
        done.append(ref)
        print(f"{ref}: {result.get('title', '')[:60]} | {manifest[ref]['credit']['license']} | {result.get('provider')}")
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps(dict(sorted(manifest.items())), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        time.sleep(1)
    return {"fetched": done, "missing": missing, "manifest": str(MANIFEST.relative_to(ROOT))}


def candidates(refs: list[str], out: Path, per: int = 12) -> Path:
    """A numbered sheet of the first *per* candidates of each product, and their ids next to it (.json),
    so a person picks the picture that shows the product (``--use PRODUCT=ID``)."""
    from PIL import Image, ImageDraw
    cell, listing = 170, {}
    canvas = Image.new("RGB", (cell * per, (cell + 22) * len(refs)), "white")
    draw = ImageDraw.Draw(canvas)
    for row, ref in enumerate(refs):
        found, seen = [], set()
        for query in QUERIES[ref] + [q + " product" for q in QUERIES[ref][-1:]]:
            for result in search(query):
                if result["id"] not in seen:
                    seen.add(result["id"])
                    found.append(result)
            time.sleep(1)
        listing[ref] = [r["id"] for r in found[:per]]
        draw.text((4, row * (cell + 22) + cell + 4), ref, fill="black")
        for column, result in enumerate(found[:per]):
            try:
                thumb = Image.open(io.BytesIO(_get(f"{API}{result['id']}/thumb/"))).convert("RGB")
            except OSError:
                continue
            thumb.thumbnail((cell - 6, cell - 6))
            x, y = column * cell, row * (cell + 22)
            canvas.paste(thumb, (x + 3, y + 3))
            draw.rectangle((x + 3, y + 3, x + 24, y + 18), fill="black")
            draw.text((x + 7, y + 5), str(column), fill="white")
    canvas.save(out, "JPEG", quality=80)
    out.with_suffix(".json").write_text(json.dumps(listing, indent=2), encoding="utf-8")
    return out


def use(choices: list[str]) -> list[str]:
    """``PRODUCT=OPENVERSE_ID``: download that picture for the product and lock it (a reviewed pick)."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    done = []
    for choice in choices:
        ref, _, image_id = choice.partition("=")
        if ref not in QUERIES:
            sys.exit(f"Unknown product {ref}")
        if any(e["credit"]["openverse_id"] == image_id for key, e in manifest.items() if key != ref):
            sys.exit(f"{ref}: picture {image_id} is already another product's")
        result = json.loads(_get(f"{API}{image_id}/"))
        if result["license"] not in LICENSES.split(","):
            sys.exit(f"{ref}: licence {result['license']} is not one a shop may use")
        _save(_get(result["url"]), PICTURES / f"{ref}.jpg")
        manifest[ref] = {"image_url": f"/products/{ref}.jpg", "credit": credit(result), "query": QUERIES[ref], "locked": True}
        done.append(f"{ref}: {result.get('title', '')[:60]} | {manifest[ref]['credit']['license']}")
        time.sleep(1)
    MANIFEST.write_text(json.dumps(dict(sorted(manifest.items())), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return done


def sheet(out: Path) -> Path:
    """One image with every picked photo and its product, to review the picks at a glance."""
    from PIL import Image, ImageDraw
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    cell, columns = 220, 6
    rows = (len(manifest) + columns - 1) // columns
    canvas = Image.new("RGB", (cell * columns, (cell + 28) * rows), "white")
    draw = ImageDraw.Draw(canvas)
    for index, (ref, entry) in enumerate(sorted(manifest.items())):
        x, y = index % columns * cell, index // columns * (cell + 28)
        picture = Image.open(PICTURES / f"{ref}.jpg")
        picture.thumbnail((cell - 8, cell - 8))
        canvas.paste(picture, (x + 4, y + 4))
        draw.text((x + 4, y + cell), ref.replace("SKU-", ""), fill="black")
    canvas.save(out, "JPEG", quality=80)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", action="append", default=[], metavar="PRODUCT", help="This product (repeatable); replaces its picture")
    parser.add_argument("--skip", type=int, default=0, help="Skip the first N candidates (to get another picture)")
    parser.add_argument("--force", action="store_true", help="Pick again for every product that is not locked")
    parser.add_argument("--sheet", type=Path, nargs="?", const=PICTURES.parent / "products-sheet.jpg",
                        help="Write a contact sheet of the picks instead of fetching")
    parser.add_argument("--candidates", nargs="+", metavar="PRODUCT", help="Sheet of numbered candidates to choose from")
    parser.add_argument("--use", nargs="+", metavar="PRODUCT=ID", help="Take this Openverse picture for the product, locked")
    parser.add_argument("--out", type=Path, default=PICTURES.parent / "products-candidates.jpg")
    args = parser.parse_args()
    if args.candidates:
        print(candidates(args.candidates, args.out))
        return
    if args.use:
        print("\n".join(use(args.use)))
        return
    if args.sheet:
        print(sheet(args.sheet))
        return
    print(json.dumps(fetch(args.only, args.skip, args.force), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
