"""
resume/build_templates.py — one-time (re-runnable) generator for the two
.docx style templates used by resume/docx_builder.py (plan section 6):

  resume/templates/resume_template.docx
  resume/templates/cover_letter_template.docx

Rather than hand-authoring these in an external tool (Word/LibreOffice),
they're built programmatically with python-docx so the whole pipeline is
reproducible from code. Both templates define the same six named styles
(resume and cover-letter generation share one visual identity):

  Title          - candidate's full name, top of the document
  ContactLine    - email / phone / location / links line under the name
  SectionHeading - "EXPERIENCE", "SKILLS", "Dear Hiring Manager" etc.
  JobTitleLine   - "Title, Company — Location (Start - End)" sub-heading
  BulletPoint    - resume bullet items ("- Did X, resulting in Y")
  BodyText       - plain paragraph prose (summary, cover-letter paragraphs)

`new_document_from_template` (docx_builder.py) opens whichever template and
clears its body paragraphs, keeping these named styles intact to apply to
freshly generated content.

Run from the repo root to (re)generate both files:
    python resume/build_templates.py
"""
import os

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor, Inches

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

# Simple, professional, readable palette -- nothing fancy.
_DARK_NAVY = RGBColor(0x1F, 0x2D, 0x3D)
_ACCENT_BLUE = RGBColor(0x2A, 0x4D, 0x69)
_BODY_GRAY = RGBColor(0x33, 0x33, 0x33)
_MUTED_GRAY = RGBColor(0x5A, 0x5A, 0x5A)

_FONT_NAME = "Calibri"


def _define_styles(document: Document) -> None:
    """Defines the six named styles this app's document generation relies
    on, on top of whatever Document() starts with. "Title" and "Body Text"
    already exist as built-in Word styles, so those two are modified in
    place rather than re-added (python-docx raises if you add_style() a
    name that already exists); the rest are new custom styles."""
    styles = document.styles

    # --- Title (built-in style, modified in place) -----------------------
    title = styles["Title"]
    title.font.name = _FONT_NAME
    title.font.size = Pt(22)
    title.font.bold = True
    title.font.color.rgb = _DARK_NAVY
    title.paragraph_format.space_after = Pt(2)
    title.paragraph_format.space_before = Pt(0)
    title.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT

    # --- ContactLine -------------------------------------------------------
    contact = styles.add_style("ContactLine", WD_STYLE_TYPE.PARAGRAPH)
    contact.base_style = styles["Normal"]
    contact.font.name = _FONT_NAME
    contact.font.size = Pt(10)
    contact.font.color.rgb = _MUTED_GRAY
    contact.paragraph_format.space_after = Pt(12)
    contact.paragraph_format.space_before = Pt(0)

    # --- SectionHeading ------------------------------------------------------
    section = styles.add_style("SectionHeading", WD_STYLE_TYPE.PARAGRAPH)
    section.base_style = styles["Normal"]
    section.font.name = _FONT_NAME
    section.font.size = Pt(13)
    section.font.bold = True
    section.font.color.rgb = _ACCENT_BLUE
    section.font.all_caps = True
    section.paragraph_format.space_before = Pt(14)
    section.paragraph_format.space_after = Pt(6)
    section.paragraph_format.keep_with_next = True

    # --- JobTitleLine --------------------------------------------------------
    job_title = styles.add_style("JobTitleLine", WD_STYLE_TYPE.PARAGRAPH)
    job_title.base_style = styles["Normal"]
    job_title.font.name = _FONT_NAME
    job_title.font.size = Pt(11)
    job_title.font.bold = True
    job_title.font.color.rgb = _DARK_NAVY
    job_title.paragraph_format.space_before = Pt(8)
    job_title.paragraph_format.space_after = Pt(2)

    # --- BulletPoint -----------------------------------------------------
    bullet = styles.add_style("BulletPoint", WD_STYLE_TYPE.PARAGRAPH)
    bullet.base_style = styles["Normal"]
    bullet.font.name = _FONT_NAME
    bullet.font.size = Pt(10.5)
    bullet.font.color.rgb = _BODY_GRAY
    bullet.paragraph_format.left_indent = Inches(0.25)
    bullet.paragraph_format.first_line_indent = Inches(-0.15)
    bullet.paragraph_format.space_after = Pt(3)
    bullet.paragraph_format.line_spacing = 1.08

    # --- BodyText (new custom style; "Body Text" built-in is left alone) -
    # NOTE: add_style() auto-derives a style_id from the name by stripping
    # spaces, which collides with the pre-existing built-in "Body Text"
    # style (style_id "BodyText", display name "Body Text") -- Word doesn't
    # allow two styles sharing a style_id, so without this explicit
    # reassignment the file ends up with a corrupt duplicate-id pair and
    # paragraphs silently resolve to the wrong ("Body Text") style on
    # reload. Giving it a distinct style_id keeps the display name exactly
    # "BodyText" as the plan specifies while avoiding the collision.
    body = styles.add_style("BodyText", WD_STYLE_TYPE.PARAGRAPH)
    body.style_id = "AppBodyText"
    body.base_style = styles["Normal"]
    body.font.name = _FONT_NAME
    body.font.size = Pt(10.5)
    body.font.color.rgb = _BODY_GRAY
    body.paragraph_format.space_after = Pt(8)
    body.paragraph_format.line_spacing = 1.15


def _set_page_margins(document: Document) -> None:
    for section in document.sections:
        section.top_margin = Inches(0.6)
        section.bottom_margin = Inches(0.6)
        section.left_margin = Inches(0.75)
        section.right_margin = Inches(0.75)


def _build_resume_template(path: str) -> None:
    document = Document()
    _define_styles(document)
    _set_page_margins(document)

    # Minimal placeholder content so the template is a valid, previewable
    # document; the real pipeline (docx_builder.new_document_from_template)
    # clears all of this before writing generated content.
    document.add_paragraph("Full Name", style="Title")
    document.add_paragraph(
        "email@example.com | +1 555 0100 | City, Country | linkedin.com/in/example",
        style="ContactLine",
    )
    document.add_paragraph("Summary", style="SectionHeading")
    document.add_paragraph(
        "Brief professional summary goes here.", style="BodyText"
    )
    document.add_paragraph("Experience", style="SectionHeading")
    document.add_paragraph(
        "Job Title, Company — Location (Start - End)", style="JobTitleLine"
    )
    document.add_paragraph("- Example bullet point.", style="BulletPoint")
    document.add_paragraph("Skills", style="SectionHeading")
    document.add_paragraph("Skill A, Skill B, Skill C", style="BodyText")

    document.save(path)


def _build_cover_letter_template(path: str) -> None:
    document = Document()
    _define_styles(document)
    _set_page_margins(document)

    document.add_paragraph("Full Name", style="Title")
    document.add_paragraph(
        "email@example.com | +1 555 0100 | City, Country", style="ContactLine"
    )
    document.add_paragraph("Dear Hiring Manager,", style="SectionHeading")
    document.add_paragraph(
        "Opening paragraph introducing interest in the role goes here.",
        style="BodyText",
    )
    document.add_paragraph(
        "Body paragraph connecting experience to the role goes here.",
        style="BodyText",
    )
    document.add_paragraph("Sincerely,", style="BodyText")
    document.add_paragraph("Full Name", style="BodyText")

    document.save(path)


def main():
    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    resume_path = os.path.join(TEMPLATES_DIR, "resume_template.docx")
    cover_letter_path = os.path.join(TEMPLATES_DIR, "cover_letter_template.docx")
    _build_resume_template(resume_path)
    _build_cover_letter_template(cover_letter_path)
    print(f"Wrote {resume_path}")
    print(f"Wrote {cover_letter_path}")


if __name__ == "__main__":
    main()
