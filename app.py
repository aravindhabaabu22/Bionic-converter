"""
Bionic Reader - Streamlit app
Upload a .txt, .md, .pdf, or .docx file and get a Bionic Reading formatted PDF.
"""
import re
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

import streamlit as st
from reportlab.lib.pagesizes import LETTER, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

# ---------------------------------------------------------------------------
# Core bionic-reading logic
# ---------------------------------------------------------------------------
_WORD_RE = re.compile(r"^([^\w]*)([\w'\u2019-]*)([^\w]*)$", re.UNICODE)


def split_bionic(word: str, ratio: float = 0.5, min_bold: int = 1):
    match = _WORD_RE.match(word)
    if not match:
        return "", word
    lead, core, trail = match.groups()
    if not core:
        return "", word
    length = len(core)
    if length <= 3:
        bold_len = 1
    else:
        bold_len = max(min_bold, round(length * ratio))
        bold_len = min(bold_len, length - 1) if length > 1 else length
    bold_part = lead + core[:bold_len]
    rest_part = core[bold_len:] + trail
    return bold_part, rest_part


def bionic_markup(text, bold_color="#1a56db", rest_color="#000000", ratio=0.5):
    """ReportLab XML markup version (used inside the PDF)."""
    pieces = []
    for w in text.split(" "):
        if w == "":
            pieces.append("")
            continue
        bold, rest = split_bionic(w, ratio=ratio)
        bold_esc, rest_esc = escape(bold), escape(rest)
        if bold_esc:
            pieces.append(
                f'<font color="{bold_color}"><b>{bold_esc}</b></font>'
                f'<font color="{rest_color}">{rest_esc}</font>'
            )
        else:
            pieces.append(f'<font color="{rest_color}">{rest_esc}</font>')
    return " ".join(pieces)


def bionic_html(text, bold_color="#1a56db", rest_color="#000000", ratio=0.5):
    """Plain HTML version (used for the live in-browser preview)."""
    pieces = []
    for w in text.split(" "):
        if w == "":
            pieces.append("")
            continue
        bold, rest = split_bionic(w, ratio=ratio)
        bold_esc, rest_esc = escape(bold), escape(rest)
        if bold_esc:
            pieces.append(
                f'<b style="color:{bold_color}">{bold_esc}</b>'
                f'<span style="color:{rest_color}">{rest_esc}</span>'
            )
        else:
            pieces.append(f'<span style="color:{rest_color}">{rest_esc}</span>')
    return " ".join(pieces)


# ---------------------------------------------------------------------------
# Paragraph / heading chunking
# ---------------------------------------------------------------------------
_MD_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")


def looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if _MD_HEADING_RE.match(stripped):
        return True
    if len(stripped) <= 70 and not stripped.endswith((".", ",", ";", ":")):
        words = stripped.split()
        if 1 <= len(words) <= 10 and (stripped.isupper() or stripped.istitle()):
            return True
    return False


def split_blocks(text: str):
    """Return a list of (is_heading, level, content) blocks."""
    raw_blocks = re.split(r"\n\s*\n", text.strip())
    blocks = []
    for raw in raw_blocks:
        raw = raw.strip()
        if not raw:
            continue
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        buffer = []
        for line in lines:
            md_match = _MD_HEADING_RE.match(line)
            if md_match:
                if buffer:
                    blocks.append((False, 0, " ".join(buffer)))
                    buffer = []
                level = len(md_match.group(1))
                blocks.append((True, level, md_match.group(2).strip()))
            elif looks_like_heading(line) and not buffer:
                blocks.append((True, 2, line))
            else:
                buffer.append(line)
        if buffer:
            blocks.append((False, 0, " ".join(buffer)))
    return blocks


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------
def extract_text(path: str) -> str:
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in (".txt", ".md"):
        return p.read_text(encoding="utf-8", errors="ignore")
    elif suffix == ".pdf":
        import pdfplumber
        chunks = []
        with pdfplumber.open(str(p)) as pdf:
            for page in pdf.pages:
                chunks.append(page.extract_text() or "")
        return "\n\n".join(chunks)
    elif suffix == ".docx":
        import docx
        document = docx.Document(str(p))
        lines = []
        for para in document.paragraphs:
            style_name = (para.style.name or "").lower()
            text = para.text.strip()
            if not text:
                lines.append("")
                continue
            if style_name.startswith("heading"):
                try:
                    level = int(style_name.replace("heading", "").strip())
                except ValueError:
                    level = 2
                level = max(1, min(level, 3))
                lines.append(f"{'#' * level} {text}")
            else:
                lines.append(text)
        return "\n".join(lines)
    else:
        raise ValueError(f"Unsupported file type: '{suffix}'")


# ---------------------------------------------------------------------------
# PDF builder
# ---------------------------------------------------------------------------
def build_bionic_pdf(text, output_path, page_size="letter", ratio=0.5,
                      bold_color="#1a56db", rest_color="#000000",
                      heading_color="#0b3d91", font_size=11,
                      line_spacing=1.5, paragraph_space=14):
    size = A4 if page_size.lower() == "a4" else LETTER
    doc = SimpleDocTemplate(
        output_path, pagesize=size,
        leftMargin=0.9 * inch, rightMargin=0.9 * inch,
        topMargin=0.9 * inch, bottomMargin=0.9 * inch,
        title="Bionic Reading Document",
    )
    styles = getSampleStyleSheet()

    body_style = ParagraphStyle(
        "BionicBody", parent=styles["Normal"], fontName="Helvetica",
        fontSize=font_size, leading=font_size * line_spacing,
        spaceAfter=paragraph_space, alignment=TA_LEFT,
    )
    heading_styles = {
        1: ParagraphStyle("BionicH1", parent=styles["Heading1"], textColor=heading_color,
                           fontName="Helvetica-Bold", fontSize=20, spaceBefore=18, spaceAfter=12),
        2: ParagraphStyle("BionicH2", parent=styles["Heading2"], textColor=heading_color,
                           fontName="Helvetica-Bold", fontSize=16, spaceBefore=14, spaceAfter=10),
        3: ParagraphStyle("BionicH3", parent=styles["Heading3"], textColor=heading_color,
                           fontName="Helvetica-Bold", fontSize=13, spaceBefore=12, spaceAfter=8),
    }

    story = []
    for is_heading, level, content in split_blocks(text):
        if not content:
            continue
        if is_heading:
            level = level if level in heading_styles else 2
            story.append(Paragraph(content, heading_styles[level]))
        else:
            markup = bionic_markup(content, bold_color=bold_color, rest_color=rest_color, ratio=ratio)
            story.append(Paragraph(markup, body_style))
            story.append(Spacer(1, 4))

    doc.build(story)
    return output_path


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Bionic Reader", page_icon="📖", layout="wide")

st.sidebar.title("📖 Bionic Reader")
st.sidebar.caption("Turn any document into a Bionic Reading formatted PDF.")

uploaded_file = st.sidebar.file_uploader(
    "Upload a document", type=["txt", "md", "pdf", "docx"],
    help="Supported formats: .txt, .md, .pdf, .docx",
)

st.sidebar.subheader("Bionic settings")
ratio = st.sidebar.slider("Bold ratio", 0.2, 0.8, 0.5, 0.05,
                           help="Fraction of each word's letters to bold.")
bold_color = st.sidebar.color_picker("Bold word-start color", "#1a56db")
rest_color = st.sidebar.color_picker("Remaining letters color", "#000000")
heading_color = st.sidebar.color_picker("Heading / topic color", "#0b3d91")

st.sidebar.subheader("Layout")
font_size = st.sidebar.slider("Body font size", 8, 18, 11)
page_size = st.sidebar.selectbox("Page size", ["letter", "a4"], index=0)

st.title("Bionic Reading Converter")
st.write(
    "Upload a document on the left. The start of each word is bolded and "
    "colored, the rest stays plain — a fixation-point trick that can help "
    "you read faster. Headings are auto-detected so topics stay easy to spot."
)

if not uploaded_file:
    st.info("👈 Upload a .txt, .md, .pdf, or .docx file to get started.")
    with st.expander("What does the output look like?"):
        demo_text = (
            "Bionic Reading guides your eyes through text using bold "
            "fixation points, so your brain can fill in the rest of each "
            "word automatically."
        )
        st.markdown(
            bionic_html(demo_text, bold_color=bold_color, rest_color=rest_color, ratio=ratio),
            unsafe_allow_html=True,
        )
    st.stop()

suffix = Path(uploaded_file.name).suffix.lower()
with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
    tmp.write(uploaded_file.getvalue())
    tmp_path = tmp.name

try:
    with st.spinner("Extracting text..."):
        raw_text = extract_text(tmp_path)
except Exception as e:
    st.error(f"Couldn't read this file: {e}")
    st.stop()

if not raw_text.strip():
    st.warning("No extractable text was found in this file.")
    st.stop()

st.subheader("Live preview")

preview_html_parts = []
for is_heading, level, content in split_blocks(raw_text):
    if not content:
        continue
    if is_heading:
        size = {1: "1.6em", 2: "1.3em", 3: "1.1em"}.get(level, "1.3em")
        preview_html_parts.append(
            f'<div style="font-weight:700;color:{heading_color};'
            f'font-size:{size};margin:0.9em 0 0.4em 0;">{content}</div>'
        )
    else:
        html_chunk = bionic_html(content, bold_color=bold_color, rest_color=rest_color, ratio=ratio)
        preview_html_parts.append(
            f'<p style="font-size:{font_size}px;line-height:1.6;margin:0 0 14px 0;">{html_chunk}</p>'
        )

preview_html = (
    '<div style="max-width:800px;font-family:Helvetica,Arial,sans-serif;">'
    + "".join(preview_html_parts) + "</div>"
)
st.markdown(preview_html, unsafe_allow_html=True)

st.divider()
col1, col2 = st.columns([1, 3])
with col1:
    generate = st.button("Generate PDF", type="primary", use_container_width=True)

if generate:
    with st.spinner("Building your Bionic Reading PDF..."):
        out_path = str(Path(tempfile.gettempdir()) / f"{Path(uploaded_file.name).stem}_bionic.pdf")
        build_bionic_pdf(
            raw_text, out_path, page_size=page_size, ratio=ratio,
            bold_color=bold_color, rest_color=rest_color,
            heading_color=heading_color, font_size=font_size,
        )
        pdf_bytes = Path(out_path).read_bytes()

    st.success("Your PDF is ready.")
    st.download_button(
        "⬇️ Download Bionic PDF", data=pdf_bytes,
        file_name=f"{Path(uploaded_file.name).stem}_bionic.pdf",
        mime="application/pdf", use_container_width=True,
    )
