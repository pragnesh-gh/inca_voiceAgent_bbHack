from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def render_fnol_pdf(markdown_text: str, output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    palette = _Palette(colors)
    styles = _build_styles(palette)
    story = _markdown_to_story(markdown_text, styles, palette, mm)

    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        title="FNOL Auto Loss Notice",
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=34 * mm,
        bottomMargin=16 * mm,
    )
    doc.build(
        story,
        onFirstPage=lambda canvas, document: _draw_page(canvas, document, palette, A4, mm, colors),
        onLaterPages=lambda canvas, document: _draw_page(canvas, document, palette, A4, mm, colors),
    )


class _Palette:
    def __init__(self, colors_module) -> None:
        self.navy = colors_module.HexColor("#0B1F3A")
        self.navy_2 = colors_module.HexColor("#12304F")
        self.gold = colors_module.HexColor("#C8A96A")
        self.stone = colors_module.HexColor("#6E6E6E")
        self.ivory = colors_module.HexColor("#F5F1E8")
        self.paper = colors_module.HexColor("#FFFDF8")
        self.line = colors_module.HexColor("#DED6C6")
        self.text = colors_module.HexColor("#1E252B")
        self.light_gold = colors_module.HexColor("#EFE3C2")


def _build_styles(palette: _Palette) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "section": ParagraphStyle(
            "MeridianSection",
            parent=base["Heading2"],
            fontName="Times-Bold",
            fontSize=11,
            leading=14,
            textColor=palette.navy,
            spaceBefore=12,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "MeridianBody",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.8,
            leading=12.2,
            textColor=palette.text,
            spaceAfter=5,
        ),
        "summary": ParagraphStyle(
            "MeridianSummary",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13.5,
            textColor=palette.text,
            leftIndent=8,
            rightIndent=8,
            spaceBefore=4,
            spaceAfter=8,
        ),
        "small": ParagraphStyle(
            "MeridianSmall",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=10,
            textColor=palette.stone,
        ),
        "bullet": ParagraphStyle(
            "MeridianBullet",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.6,
            leading=12,
            textColor=palette.text,
            leftIndent=10,
            firstLineIndent=-6,
            spaceAfter=3,
        ),
        "table": ParagraphStyle(
            "MeridianTable",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=7.7,
            leading=9.5,
            textColor=palette.text,
        ),
        "table_header": ParagraphStyle(
            "MeridianTableHeader",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7.4,
            leading=9.2,
            textColor=colors.white,
        ),
    }


def _markdown_to_story(markdown_text: str, styles: dict[str, ParagraphStyle], palette: _Palette, mm) -> list[object]:
    story: list[object] = []
    lines = markdown_text.splitlines()
    i = 0
    last_heading = ""
    while i < len(lines):
        clean = lines[i].strip()
        if not clean:
            i += 1
            continue
        if clean.startswith("# "):
            i += 1
            continue
        if clean.startswith("## "):
            last_heading = clean[3:].strip()
            story.append(_section_heading(last_heading, styles, palette, mm))
            i += 1
            continue
        if clean.startswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            table = _build_table(table_lines, styles, palette, mm, compact=(last_heading == ""))
            if table:
                story.append(table)
                story.append(Spacer(1, 7))
            continue
        if clean.startswith("- "):
            story.append(Paragraph(f"- {_escape(clean[2:])}", styles["bullet"]))
            i += 1
            continue
        style = styles["summary"] if last_heading == "Executive Summary" else styles["body"]
        story.append(Paragraph(_escape(clean), style))
        i += 1
    return story


def _section_heading(title: str, styles: dict[str, ParagraphStyle], palette: _Palette, mm) -> Table:
    label = Paragraph(_escape(title.upper()), styles["section"])
    table = Table([[label]], colWidths=[174 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), palette.ivory),
                ("LINEBELOW", (0, 0), (-1, -1), 0.7, palette.gold),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _build_table(
    table_lines: list[str],
    styles: dict[str, ParagraphStyle],
    palette: _Palette,
    mm,
    compact: bool = False,
) -> Table | None:
    rows = []
    for line in table_lines:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells and all(set(cell) <= {"-"} for cell in cells if cell):
            continue
        rows.append(cells)
    if not rows:
        return None

    col_count = max(len(row) for row in rows)
    normalized = [row + [""] * (col_count - len(row)) for row in rows]
    data = []
    for row_index, row in enumerate(normalized):
        style_name = "table_header" if row_index == 0 else "table"
        data.append([Paragraph(_escape(cell), styles[style_name]) for cell in row])

    if col_count == 2:
        col_widths = [46 * mm, 128 * mm]
    elif col_count == 3:
        col_widths = [49 * mm, 101 * mm, 24 * mm]
    elif col_count == 4:
        col_widths = [24 * mm, 33 * mm, 28 * mm, 89 * mm]
    else:
        col_widths = [174 * mm / col_count] * col_count

    table = Table(data, colWidths=col_widths, repeatRows=1 if len(data) > 2 else 0)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), palette.navy),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (-1, -1), palette.paper if compact else colors.white),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, palette.ivory]),
                ("GRID", (0, 0), (-1, -1), 0.25, palette.line),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _draw_page(canvas, doc, palette: _Palette, page_size, mm, colors_module) -> None:
    width, height = page_size
    canvas.saveState()
    canvas.setFillColor(palette.paper)
    canvas.rect(0, 0, width, height, fill=1, stroke=0)

    header_h = 25 * mm
    canvas.setFillColor(palette.navy)
    canvas.rect(0, height - header_h, width, header_h, fill=1, stroke=0)
    canvas.setFillColor(palette.navy_2)
    canvas.rect(0, height - header_h, width, 3 * mm, fill=1, stroke=0)
    canvas.setStrokeColor(palette.gold)
    canvas.setLineWidth(0.75)
    canvas.line(18 * mm, height - header_h, width - 18 * mm, height - header_h)

    _draw_monogram(canvas, 20 * mm, height - 14 * mm, palette, mm)

    canvas.setFillColor(colors_module.white)
    canvas.setFont("Times-Bold", 15)
    canvas.drawString(39 * mm, height - 12 * mm, "MERIDIAN MUTUAL")
    canvas.setFillColor(palette.gold)
    canvas.setFont("Helvetica", 7.2)
    canvas.drawString(39 * mm, height - 17 * mm, "AUTO LOSS NOTICE")
    canvas.setFillColor(colors_module.white)
    canvas.setFont("Helvetica", 7)
    canvas.drawRightString(width - 18 * mm, height - 12 * mm, "FNOL DOCUMENTATION")
    canvas.setFillColor(palette.light_gold)
    canvas.drawRightString(width - 18 * mm, height - 17 * mm, "Internal claims record - redacted copy")

    canvas.setStrokeColor(palette.line)
    canvas.setLineWidth(0.4)
    canvas.line(18 * mm, 12 * mm, width - 18 * mm, 12 * mm)
    canvas.setFillColor(palette.stone)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(18 * mm, 7.2 * mm, "Meridian Mutuals - Insurance for Generations")
    canvas.drawRightString(width - 18 * mm, 7.2 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _draw_monogram(canvas, x: float, y: float, palette: _Palette, mm) -> None:
    canvas.saveState()
    canvas.setStrokeColor(palette.gold)
    canvas.setFillColor(palette.gold)
    canvas.setLineWidth(0.8)
    canvas.circle(x + 6 * mm, y - 1 * mm, 7 * mm, fill=0, stroke=1)
    canvas.setFont("Times-Bold", 16)
    canvas.drawCentredString(x + 6 * mm, y - 5.2 * mm, "M")
    canvas.setLineWidth(0.55)
    canvas.line(x + 1.2 * mm, y - 9 * mm, x + 10.8 * mm, y + 4.2 * mm)
    canvas.line(x + 10.8 * mm, y - 9 * mm, x + 1.2 * mm, y + 4.2 * mm)
    canvas.restoreState()


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
