"""Loads the user's private material: resume, profile, and project READMEs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .latex import strip_latex

ResumeFormat = Literal["latex", "markdown"]


@dataclass(frozen=True)
class Knowledge:
    resume_src: str  # LaTeX or Markdown source, whatever the user maintains
    resume_format: ResumeFormat
    profile_md: str
    projects: dict[str, str]  # filename stem -> README content

    @property
    def resume_plain(self) -> str:
        """Resume as plain-ish text, for ATS keyword/embedding scoring."""
        if self.resume_format == "latex":
            return strip_latex(self.resume_src)
        return self.resume_src

    def projects_blob(self) -> str:
        """All project READMEs concatenated with headers, for prompt context."""
        parts = [
            f"### Project: {name}\n\n{content.strip()}"
            for name, content in self.projects.items()
        ]
        return "\n\n---\n\n".join(parts)


def _read_resume(private_dir: Path) -> tuple[str, ResumeFormat]:
    tex_path = private_dir / "resume.tex"
    md_path = private_dir / "resume.md"
    if tex_path.is_file():
        src, fmt = tex_path.read_text(encoding="utf-8").strip(), "latex"
        path = tex_path
    elif md_path.is_file():
        src, fmt = md_path.read_text(encoding="utf-8").strip(), "markdown"
        path = md_path
    else:
        raise FileNotFoundError(
            f"No resume found. Put your resume at {tex_path} (LaTeX) "
            f"or {md_path} (Markdown)."
        )
    if not src:
        raise ValueError(f"{path} is empty — add your resume content first.")
    return src, fmt


def load_knowledge(private_dir: Path) -> Knowledge:
    resume_src, resume_format = _read_resume(private_dir)

    profile_path = private_dir / "profile.md"
    profile_md = (
        profile_path.read_text(encoding="utf-8").strip()
        if profile_path.is_file()
        else ""
    )

    projects: dict[str, str] = {}
    projects_dir = private_dir / "projects"
    if projects_dir.is_dir():
        for md in sorted(projects_dir.glob("*.md")):
            if md.name.startswith("_"):  # instructions/scratch files, not projects
                continue
            content = md.read_text(encoding="utf-8").strip()
            if content:
                projects[md.stem] = content

    return Knowledge(
        resume_src=resume_src,
        resume_format=resume_format,
        profile_md=profile_md,
        projects=projects,
    )
