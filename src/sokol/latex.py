"""LaTeX resume support: compile with tectonic and strip markup for scoring."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path


class CompileFailed(Exception):
    """The document could not be compiled; the log excerpt is the message."""


def _engine_command(workdir: str, tex_file: Path) -> list[str]:
    # Prefer pdflatex: common resume templates (fontawesome5, glyphtounicode)
    # are written for it, and fontawesome5 crashes tectonic's XeTeX engine.
    if shutil.which("pdflatex"):
        return [
            "pdflatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-output-directory",
            workdir,
            str(tex_file),
        ]
    if shutil.which("tectonic"):
        return ["tectonic", "--outdir", workdir, str(tex_file)]
    raise CompileFailed(
        "No LaTeX engine found — install one with `brew install texlive` "
        "(pdflatex, recommended) or `brew install tectonic`."
    )


def compile_latex(tex_src: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as workdir:
        tex_file = Path(workdir) / "resume.tex"
        tex_file.write_text(tex_src, encoding="utf-8")
        result = subprocess.run(
            _engine_command(workdir, tex_file),
            capture_output=True,
            text=True,
            timeout=300,
        )
        pdf = tex_file.with_suffix(".pdf")
        if result.returncode != 0 or not pdf.is_file():
            # Keep the tail, which has the actual TeX error, and drop the
            # progress noise above it.
            log = (result.stdout + "\n" + result.stderr).strip()
            raise CompileFailed(log[-2000:] or "compiler produced no output")
        out_path.write_bytes(pdf.read_bytes())
    return out_path


def strip_latex(tex_src: str) -> str:
    """Rough LaTeX-to-text for keyword/embedding scoring (not for display)."""
    # The preamble is markup, not resume content — score the body only.
    body = tex_src.split("\\begin{document}", 1)[-1]
    text = re.sub(r"(?<!\\)%.*", " ", body)  # comments
    text = re.sub(r"\\(?:begin|end)\{[^}]*\}", " ", text)
    text = re.sub(r"\\[a-zA-Z@]+\*?(?:\[[^\]]*\])*", " ", text)  # commands
    text = re.sub(r"[{}~$&]|\\[\\,;:!]", " ", text)
    return re.sub(r"\s+", " ", text).strip()
