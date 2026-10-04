"""Check page content/bounds and render proof sheets for visual review."""
from pathlib import Path
import re
import pymupdf
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "output/pdf/Evaluation_QD_v2.pdf"
OUT = ROOT / "tmp/pdfs/evaluation-review"
OUT.mkdir(parents=True, exist_ok=True)
doc = pymupdf.open(PDF)
assert len(doc) == 27, f"Unexpected pagination: {len(doc)} pages"
errors = []
images = []
for i, page in enumerate(doc):
    text = page.get_text()
    if not re.search(rf"\b{i + 1:02d}\. ", text):
        errors.append(f"Page {i+1}: missing section title")
    if "\ufffd" in text or "```" in text or "%% rows" in text:
        errors.append(f"Page {i+1}: broken text or unrendered source")
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                x0, y0, x1, y1 = span["bbox"]
                if x0 < 0 or y0 < 0 or x1 > page.rect.width + .5 or y1 > page.rect.height + .5:
                    errors.append(f"Page {i+1}: text outside page: {span['text']}")
    pix = page.get_pixmap(matrix=pymupdf.Matrix(1.25, 1.25), alpha=False)
    target = OUT / f"page-{i+1:02d}.png"
    pix.save(target)
    im = Image.open(target).convert("RGB")
    im.thumbnail((330, 468))
    images.append(im)
for start in range(0, len(images), 6):
    sheet = Image.new("RGB", (1020, 990), "#cbd5df")
    draw = ImageDraw.Draw(sheet)
    for offset, im in enumerate(images[start:start + 6]):
        col, row = offset % 3, offset // 3
        x, y = col * 340 + 5, row * 495 + 20
        sheet.paste(im, (x, y))
        draw.text((x + 3, y - 16), f"PAGE {start + offset + 1}", fill="black")
    sheet.save(OUT / f"sheet-{start//6 + 1}.png")
assert not errors, "\n".join(errors)
print(f"PASS: {len(doc)} pages; section titles, text bounds and encoding checked.")
print(f"Visual proofs: {OUT}")
