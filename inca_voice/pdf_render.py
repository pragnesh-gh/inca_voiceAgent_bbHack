from __future__ import annotations

from pathlib import Path


def render_fnol_pdf(markdown_text: str, output_path: str | Path) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()
    story = []
    for line in markdown_text.splitlines():
        clean = line.strip()
        if not clean:
            story.append(Spacer(1, 8))
            continue
        if clean.startswith("# "):
            story.append(Paragraph(_escape(clean[2:]), styles["Title"]))
        elif clean.startswith("## "):
            story.append(Paragraph(_escape(clean[3:]), styles["Heading2"]))
        elif clean.startswith("- "):
            story.append(Paragraph(f"• {_escape(clean[2:])}", styles["BodyText"]))
        elif clean.startswith("|"):
            story.append(Paragraph(_escape(clean.replace("|", " | ")), styles["Code"]))
        else:
            story.append(Paragraph(_escape(clean), styles["BodyText"]))

    doc = SimpleDocTemplate(str(path), pagesize=A4, title="FNOL Auto Loss Notice")
    doc.build(story)


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
