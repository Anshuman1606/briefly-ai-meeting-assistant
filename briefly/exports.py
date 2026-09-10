"""Portable JSON, UTF-8 text and Unicode PDF reports."""

import json
from pathlib import Path

from fpdf import FPDF


def _text(report):
    lines = [report["title"], "BRIEFLY · MEETING REPORT", f"Analysis mode: {report['analysis_mode']}", "", "SUMMARY"]
    lines.extend("• " + value for value in report.get("summary", []))
    lines.extend(["", "ACTION ITEMS"])
    for action in report.get("actions", []):
        lines.append(f"[{action['status']}] {action['text']}")
        lines.append(f"Owner: {action['owner']} | Due: {action['deadline']}")
        lines.append(f"Source: {action['evidence']}")
    for heading, key in [("DECISIONS", "decisions"), ("OPEN QUESTIONS", "questions")]:
        lines.extend(["", heading])
        lines.extend("• " + value for value in report.get(key, []))
    lines.extend(["", "TRANSCRIPT", report["transcript"], "", "Generated from source evidence. Review action owners and dates before relying on them."])
    return "\n".join(lines)


def export_report(report, fmt):
    if fmt == "json":
        allowed = {key: report[key] for key in ("id", "title", "source_type", "source_url", "language", "created_at", "analysis_mode", "summary", "decisions", "questions", "transcript", "actions", "chunks")}
        return json.dumps(allowed, ensure_ascii=False, indent=2, default=str).encode()
    content = _text(report)
    if fmt == "txt":
        return content.encode("utf-8")
    if fmt != "pdf":
        raise ValueError("Choose TXT, PDF, or JSON export.")
    assets = Path(__file__).resolve().parent.parent / "assets" / "fonts"
    font = assets / "NotoSans-Regular.ttf"
    if not font.exists():
        raise ValueError("PDF fonts are missing. Restore the bundled assets/fonts directory, or use TXT/JSON.")
    pdf = FPDF()
    pdf.set_title(report["title"])
    pdf.set_author("Briefly")
    pdf.set_margins(20, 20, 20)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_font("Noto", fname=str(font))
    devanagari = assets / "NotoSansDevanagari-Regular.ttf"
    if devanagari.exists():
        pdf.add_font("Devanagari", fname=str(devanagari))
        pdf.set_fallback_fonts(["Devanagari"])
    pdf.set_text_shaping(True)
    pdf.add_page()
    for i, line in enumerate(content.splitlines()):
        is_heading = line in {"SUMMARY", "ACTION ITEMS", "DECISIONS", "OPEN QUESTIONS", "TRANSCRIPT"}
        pdf.set_font("Noto", size=20 if i == 0 else 11 if is_heading else 9)
        pdf.set_text_color(18, 55, 55) if is_heading or i == 0 else pdf.set_text_color(47, 56, 63)
        pdf.multi_cell(0, 6 if i else 10, line or " ", new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")
    return bytes(pdf.output())
