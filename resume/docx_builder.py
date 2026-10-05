"""
resume/docx_builder.py — shared python-docx helpers used by resume/tailor.py
and resume/cover_letter.py (plan section 6).

Both document types are built the same way: open one of the pre-authored
style templates in resume/templates/ (see resume/build_templates.py for how
those are generated), strip out the template's own placeholder body
paragraphs, and repopulate it with freshly generated content using the
named styles the template defines (Title, ContactLine, SectionHeading,
JobTitleLine, BulletPoint, BodyText) -- so every generated document shares
one consistent, readable visual identity without needing an external
design tool at generation time.
"""
from docx import Document
from docx.document import Document as DocumentObject
from docx.text.paragraph import Paragraph


def new_document_from_template(template_path: str) -> DocumentObject:
    """Opens the .docx at `template_path` and removes all of its existing
    body content (the template's placeholder paragraphs), leaving the
    named paragraph styles it defines (Title, ContactLine, SectionHeading,
    JobTitleLine, BulletPoint, BodyText) intact and ready to apply to newly
    added content. Returns the resulting (now-empty-bodied) Document.

    Styles live in the document's style part, not in individual body
    paragraphs, so clearing the body does not remove them -- this is what
    makes "template" the right word here rather than just "a file we
    happen to overwrite from scratch each time".
    """
    document = Document(template_path)
    body = document.element.body
    for child in list(body):
        # Keep the trailing <w:sectPr> (section properties: page size,
        # margins, etc.) -- removing it would leave the document without
        # valid page setup.
        if child.tag.endswith("}sectPr"):
            continue
        body.remove(child)
    return document


def add_heading(document: DocumentObject, text: str, style: str = "SectionHeading") -> Paragraph:
    """Adds a section-heading paragraph (default style: SectionHeading,
    e.g. "EXPERIENCE", "SKILLS", "Dear Hiring Manager,") and returns it."""
    return document.add_paragraph(text, style=style)


def add_bullet(document: DocumentObject, text: str, style: str = "BulletPoint") -> Paragraph:
    """Adds a bullet-point paragraph (default style: BulletPoint). A plain
    dash/bullet marker is prefixed if the caller hasn't already included
    one, since this style sets hanging indentation to line up with it but
    doesn't auto-generate a Word numbering bullet."""
    marker_text = text if text.lstrip().startswith(("-", "•", "*")) else f"• {text}"
    return document.add_paragraph(marker_text, style=style)


def add_title(document: DocumentObject, text: str, style: str = "Title") -> Paragraph:
    """Adds the document's top title paragraph (default style: Title --
    e.g. the candidate's full name)."""
    return document.add_paragraph(text, style=style)


def add_contact_line(document: DocumentObject, text: str, style: str = "ContactLine") -> Paragraph:
    """Adds the contact-details line under the title (default style:
    ContactLine -- e.g. email | phone | location | links)."""
    return document.add_paragraph(text, style=style)


def add_job_title_line(document: DocumentObject, text: str, style: str = "JobTitleLine") -> Paragraph:
    """Adds an experience-entry sub-heading (default style: JobTitleLine --
    e.g. "Senior Engineer, Acme Corp — Berlin (2021-03 - Present)")."""
    return document.add_paragraph(text, style=style)


def add_body_text(document: DocumentObject, text: str, style: str = "BodyText") -> Paragraph:
    """Adds a plain prose paragraph (default style: BodyText -- resume
    summary line, cover-letter paragraphs, salutations/signoffs)."""
    return document.add_paragraph(text, style=style)


def save_document(document: DocumentObject, path: str) -> str:
    """Saves `document` to `path` and returns `path` for convenient
    chaining into the S3 upload step."""
    document.save(path)
    return path
