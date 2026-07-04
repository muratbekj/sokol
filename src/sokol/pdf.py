"""Render tailored resume Markdown to an ATS-friendly single-column PDF."""

from __future__ import annotations

from pathlib import Path

from markdown_it import MarkdownIt

# Single column, standard system fonts, no tables/graphics — the layout ATS
# parsers extract most reliably.
RESUME_CSS = """
@page { size: letter; margin: 1.4cm 1.6cm; }
body {
    font-family: Helvetica, Arial, sans-serif;
    font-size: 10pt;
    line-height: 1.35;
    color: #111;
}
h1 { font-size: 17pt; margin: 0 0 2pt; }
h2 {
    font-size: 11pt;
    text-transform: uppercase;
    letter-spacing: 0.5pt;
    border-bottom: 0.75pt solid #999;
    margin: 10pt 0 4pt;
    padding-bottom: 1pt;
}
h3 { font-size: 10.5pt; margin: 6pt 0 1pt; }
p { margin: 2pt 0; }
ul { margin: 2pt 0 4pt; padding-left: 14pt; }
li { margin: 1pt 0; }
a { color: #111; text-decoration: none; }
strong { font-weight: 600; }
"""


def render_pdf(resume_md: str, out_path: Path) -> Path:
    # WeasyPrint imports are slow and need pango installed, so keep them lazy.
    from weasyprint import CSS, HTML

    html_body = MarkdownIt("commonmark").render(resume_md)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html_body).write_pdf(
        out_path, stylesheets=[CSS(string=RESUME_CSS)]
    )
    return out_path
