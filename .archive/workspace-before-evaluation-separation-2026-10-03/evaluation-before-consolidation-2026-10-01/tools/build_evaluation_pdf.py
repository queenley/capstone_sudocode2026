"""Render the companion Markdown as a readable PDF with vector flowcharts.

Usage: PYTHONPATH=/tmp/qd-pdf-deps python3 tools/build_evaluation_pdf.py
Requires reportlab; diagram rows are the Mermaid `%% rows:` comments.
The small parser intentionally supports only the syntax used in this document.
"""
from pathlib import Path
import html
import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable, SimpleDocTemplate, Paragraph, Spacer, PageBreak,
    Table, TableStyle, KeepTogether,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "evaluation-improvement-flow.md"
OUTPUT = ROOT / "output/pdf/Evaluation_QD_v2.pdf"
FONT_DIR = Path("/System/Library/Fonts/Supplemental")
pdfmetrics.registerFont(TTFont("Arial", str(FONT_DIR / "Arial.ttf")))
pdfmetrics.registerFont(TTFont("ArialBold", str(FONT_DIR / "Arial Bold.ttf")))
pdfmetrics.registerFontFamily("Arial", normal="Arial", bold="ArialBold")

NAVY = colors.HexColor("#18334b")
INK = colors.HexColor("#25364a")
BLUE = colors.HexColor("#edf5fc")
TEAL = colors.HexColor("#e7f5f0")
AMBER = colors.HexColor("#fff3d8")
LINE = colors.HexColor("#608097")
WIDTH = A4[0] - 80
STYLES = {
    "body": ParagraphStyle("body", fontName="Arial", fontSize=10.3,
                           leading=15.3, textColor=INK, spaceAfter=9),
    "title": ParagraphStyle("title", fontName="ArialBold", fontSize=20,
                            leading=25, textColor=NAVY, spaceAfter=17),
    "node": ParagraphStyle("node", fontName="Arial", fontSize=9.6,
                           leading=12.1, alignment=TA_CENTER, textColor=NAVY),
    "label": ParagraphStyle("label", fontName="Arial", fontSize=8,
                            leading=9, alignment=TA_CENTER, textColor=INK),
    "cell": ParagraphStyle("cell", fontName="Arial", fontSize=9.5,
                           leading=13.5, textColor=INK),
}


def inline(text):
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r'<font color="#12645b">\1</font>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    return text


class Diagram(Flowable):
    def __init__(self, source):
        super().__init__()
        self.width = WIDTH
        match = re.search(r"%% rows: (.+)", source)
        if not match:
            raise ValueError("Diagram is missing explicit rows")
        self.rows = [part.strip().split(",") for part in match[1].split("|")]
        self.nodes = {}
        self.edges = []
        for line in source.splitlines():
            m = re.fullmatch(r'\s*(\w+)(\[|\{)"(.*)"(?:\]|\})\s*', line)
            if m:
                self.nodes[m[1]] = (m[3], m[2] == "{")
            m = re.fullmatch(r'\s*(\w+) -->\s*(?:\|"(.*?)"\|\s*)?(\w+)\s*', line)
            if m:
                self.edges.append((m[1], m[3], m[2] or ""))
        ids = [node for row in self.rows for node in row]
        if len(ids) != len(set(ids)) or set(ids) != set(self.nodes):
            raise ValueError(f"Diagram row/node mismatch: {ids}")
        for a, b, _ in self.edges:
            assert a in self.nodes and b in self.nodes, (a, b)
        self.gap = 24
        self.row_heights = []
        self.paragraphs = {}
        for row in self.rows:
            w = self.node_width(row)
            heights = []
            for node in row:
                label, decision = self.nodes[node]
                para = Paragraph(label, STYLES["node"])
                _, ph = para.wrap(w - 24, 200)
                self.paragraphs[node] = (para, ph)
                heights.append(max(38, ph + 17))
            self.row_heights.append(max(heights))
        self.height = sum(self.row_heights) + self.gap * (len(self.rows) - 1) + 24

    def node_width(self, row):
        return 314 if len(row) == 1 else (WIDTH - 64) / len(row)

    def draw(self):
        c = self.canv
        positions = {}
        y = self.height - 12
        for row, rh in zip(self.rows, self.row_heights):
            w = self.node_width(row)
            for j, node in enumerate(row):
                cx = WIDTH * (j + 0.5) / len(row)
                positions[node] = (cx - w / 2, y - rh, w, rh)
            y -= rh + self.gap

        def arrow(points):
            c.setStrokeColor(LINE)
            c.setFillColor(LINE)
            c.setLineWidth(1)
            p = c.beginPath()
            p.moveTo(*points[0])
            for point in points[1:]:
                p.lineTo(*point)
            c.drawPath(p)
            x0, y0 = points[-2]
            x1, y1 = points[-1]
            dx, dy = x1 - x0, y1 - y0
            length = (dx * dx + dy * dy) ** 0.5 or 1
            ux, uy = dx / length, dy / length
            p = c.beginPath()
            p.moveTo(x1, y1)
            p.lineTo(x1 - ux * 5 - uy * 2.5, y1 - uy * 5 + ux * 2.5)
            p.lineTo(x1 - ux * 5 + uy * 2.5, y1 - uy * 5 - ux * 2.5)
            p.close()
            c.drawPath(p, fill=1, stroke=0)

        for index, (a, b, label) in enumerate(self.edges):
            ax, ay, aw, ah = positions[a]
            bx, by, bw, bh = positions[b]
            sx, sy = ax + aw / 2, ay
            tx, ty = bx + bw / 2, by + bh
            if abs((ay + ah / 2) - (by + bh / 2)) < 0.1:
                # Connect facing sides directly; an outside detour crosses boxes.
                rightward = tx > sx
                ex = ax + aw if rightward else ax
                en = bx if rightward else bx + bw
                cy = ay + ah / 2
                points = [(ex, cy), (en, cy)]
                lx, ly = (ex + en) / 2, cy
            elif ty < sy:
                mid = (sy + ty) / 2
                points = [(sx, sy), (sx, mid), (tx, mid), (tx, ty)]
                lx, ly = (sx + tx) / 2, mid
            else:
                # Same-row/back edges use a dedicated outside corridor.
                right = sx >= WIDTH / 2
                lane = WIDTH - 3 - (index % 2) * 5 if right else 3 + (index % 2) * 5
                ex = ax + aw if right else ax
                en = bx + bw if right else bx
                sy, ty = ay + ah / 2, by + bh / 2
                points = [(ex, sy), (lane, sy), (lane, ty), (en, ty)]
                lx, ly = (lane + ex) / 2, sy
            arrow(points)
            if label:
                p = Paragraph(html.escape(label), STYLES["label"])
                lw = min(120, max(32, pdfmetrics.stringWidth(label, "Arial", 8) + 12))
                _, lh = p.wrap(lw, 40)
                # Label sits above the connecting segment to keep arrows visible.
                c.setFillColor(colors.white)
                c.roundRect(lx - lw / 2, ly + 1, lw, lh + 2, 2, fill=1, stroke=0)
                p.drawOn(c, lx - lw / 2, ly + 2)

        for node, (x, y, w, h) in positions.items():
            label, decision = self.nodes[node]
            c.setFillColor(AMBER if decision else TEAL if "active" in label.lower() else BLUE)
            c.setStrokeColor(LINE)
            c.setLineWidth(0.8)
            c.roundRect(x, y, w, h, 9, fill=1, stroke=1)
            if decision:
                c.setFillColor(colors.HexColor("#b77913"))
                c.circle(x + 9, y + h - 9, 2.2, fill=1, stroke=0)
            para, ph = self.paragraphs[node]
            para.drawOn(c, x + 12, y + (h - ph) / 2)


def table(lines):
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines]
    rows = [row for row in rows if not all(re.fullmatch(r":?-+:?", cell) for cell in row)]
    n = len(rows[0])
    assert all(len(row) == n for row in rows)
    cells = [[Paragraph(inline(cell), STYLES["cell"]) for cell in row] for row in rows]
    widths = [WIDTH * 0.35, WIDTH * 0.65] if n == 2 else [WIDTH / n] * n
    t = Table(cells, colWidths=widths, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dceaf4")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f8fa")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, 0), (-1, 0), 0.7, LINE),
    ]))
    return t


def parse_body(body):
    lines = body.strip().splitlines()
    result = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line == "```mermaid":
            j = i + 1
            while lines[j].strip() != "```":
                j += 1
            result.extend([Diagram("\n".join(lines[i + 1:j])), Spacer(1, 12)])
            i = j + 1
        elif line.startswith("|"):
            j = i
            while j < len(lines) and lines[j].strip().startswith("|"):
                j += 1
            result.extend([table(lines[i:j]), Spacer(1, 12)])
            i = j
        else:
            j = i + 1
            if not re.match(r"(?:\d+\.|-) ", line):
                while j < len(lines) and lines[j].strip() and not lines[j].startswith(("|", "```")):
                    j += 1
            result.append(Paragraph(inline(" ".join(lines[i:j])), STYLES["body"]))
            i = j
    return result


def page_chrome(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.setFont("ArialBold", 8)
    canvas.drawString(40, A4[1] - 25, "EVALUATION / IMPROVEMENT")
    canvas.setFont("Arial", 8)
    canvas.drawRightString(A4[0] - 40, A4[1] - 25, "QD v2  ·  28/09/2026")
    canvas.setStrokeColor(colors.HexColor("#d7e1e8"))
    canvas.line(40, 34, A4[0] - 40, 34)
    canvas.setFillColor(LINE)
    canvas.setFont("Arial", 8)
    canvas.drawString(40, 21, "Thiết kế đề xuất · Bám số ô flow Bách và hợp đồng BTC")
    canvas.drawRightString(A4[0] - 40, 21, str(doc.page))
    canvas.restoreState()


def main():
    text = SOURCE.read_text(encoding="utf-8")
    sections = re.split(r"^## (.+)$", text, flags=re.MULTILINE)
    story = []
    for i in range(1, len(sections), 2):
        if story:
            story.append(PageBreak())
        title, body = sections[i], sections[i + 1]
        content = parse_body(body)
        story.append(KeepTogether([Paragraph(inline(title), STYLES["title"]), content[0]]))
        story.extend(content[1:])
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(OUTPUT), pagesize=A4, rightMargin=40, leftMargin=40,
                            topMargin=48, bottomMargin=47, title="Evaluation QD v2",
                            author="Nhóm dự án - bản thiết kế Evaluation & Improvement")
    doc.build(story, onFirstPage=page_chrome, onLaterPages=page_chrome)
    print(OUTPUT)


if __name__ == "__main__":
    main()
