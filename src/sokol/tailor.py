"""Ollama-backed job description analysis and resume tailoring."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import ollama

from .knowledge import Knowledge

THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
FENCE_RE = re.compile(r"^```[a-zA-Z]*\n|\n```$")


def _clean(text: str) -> str:
    """Strip qwen3 <think> blocks and surrounding markdown fences."""
    text = THINK_RE.sub("", text).strip()
    text = FENCE_RE.sub("", text).strip()
    return text


@dataclass(frozen=True)
class JobAnalysis:
    role_title: str
    company: str
    keywords: list[str]  # ranked, most important first

    def summary_line(self) -> str:
        if self.company:
            return f"{self.role_title} @ {self.company}"
        return self.role_title


ANALYZE_SYSTEM = """\
You are an ATS (applicant tracking system) analyst. Given a job posting, extract
the information a recruiter's keyword screen would look for. Respond with JSON
only, matching this schema:
{
  "role_title": string,
  "company": string (empty string if not stated),
  "keywords": [string, ...]
}
"keywords" must be the ranked list (most important first, max 30) of concrete
skills, tools, technologies, methodologies, certifications and domain terms an
ATS would match on. Use the exact phrasing from the posting (e.g. "CI/CD",
"PostgreSQL"), no duplicates, no generic filler like "team player".\
"""

TAILOR_SYSTEM = """\
You are an expert resume writer optimizing a real person's resume for a specific
job posting and its ATS keyword screen.

Hard rules — violating these makes the resume fraudulent:
- NEVER invent employers, job titles, dates, degrees, certifications, or metrics.
- NEVER claim experience with a skill or tool unless it appears in the provided
  resume, profile, or project material.
- You may only rephrase, reorder, re-emphasize, cut, and surface genuinely
  relevant details from the provided material.

Guidelines:
- Mirror the job posting's exact terminology for skills the candidate genuinely
  has (e.g. write "PostgreSQL" if the posting says PostgreSQL and the resume
  says "Postgres").
- Lead bullets with the most role-relevant achievements; trim irrelevant ones.
- Pull in relevant projects from the project material if they strengthen the fit.
- Keep roughly one page of content.
- A skills section is fine; do not stuff it with keywords the candidate lacks.

{format_rules}\
"""

FORMAT_RULES = {
    "markdown": (
        "Format: plain Markdown — '#' for the name, '##' for sections, '-' "
        "bullets. No tables, no images, no columns.\n\n"
        "Output the complete tailored resume as Markdown only — no commentary "
        "before or after it."
    ),
    "latex": (
        "Format: the resume is a LaTeX document. The ONLY thing you may change "
        "is the bullet points (\\item lines) inside the experience, project and skill sections "
        "entries: rephrase them to mirror the posting's terminology, reorder "
        "them within an entry, or add a few new bullets for genuinely supported "
        "skills or projects. Everything else — preamble, custom commands, "
        "section structure, headings, contact info, job titles, company names, "
        "dates, education, skills lists — must be reproduced character-for-"
        "character as given. Escape special characters in new text properly "
        "(\\%, \\&, \\#, \\_). The document must compile as-is.\n\n"
        "Output the complete tailored .tex document only — from \\documentclass "
        "to \\end{document}, no commentary, no markdown fences."
    ),
}

FIX_LATEX_SYSTEM = """\
You are a LaTeX expert. The document below fails to compile. Fix the errors
with the smallest possible change — do not rewrite content, only repair the
LaTeX (escaping, braces, environments, undefined commands). Output the complete
corrected .tex document only, no commentary, no markdown fences.\
"""

REVISE_INSTRUCTION = """\
Revise the tailored resume above. These job-posting keywords are still missing
and the candidate DOES have supporting material for some of them — work in the
ones that are genuinely supported by the resume/profile/projects, using the
posting's exact phrasing. Skip any the candidate truly lacks. Keywords missing:
{missing}

Output the complete revised resume in the same format as before, nothing else.\
"""


class Tailor:
    def __init__(self, host: str, model: str):
        self._client = ollama.Client(host=host)
        self._model = model

    def _chat(self, messages: list[dict], json_mode: bool = False) -> str:
        response = self._client.chat(
            model=self._model,
            messages=messages,
            format="json" if json_mode else None,
            options={"temperature": 0.3, "num_ctx": 16384},
        )
        return _clean(response["message"]["content"])

    def analyze_job(self, jd_text: str) -> JobAnalysis:
        raw = self._chat(
            [
                {"role": "system", "content": ANALYZE_SYSTEM},
                {"role": "user", "content": f"Job posting:\n\n{jd_text}"},
            ],
            json_mode=True,
        )
        data = json.loads(raw)
        keywords = [str(k).strip() for k in data.get("keywords", []) if str(k).strip()]
        return JobAnalysis(
            role_title=str(data.get("role_title", "")).strip() or "Unknown role",
            company=str(data.get("company", "")).strip(),
            keywords=keywords[:30],
        )

    def _tailor_user_prompt(
        self, knowledge: Knowledge, jd_text: str, analysis: JobAnalysis
    ) -> str:
        sections = [
            f"## Job posting ({analysis.summary_line()})\n\n{jd_text}",
            f"## ATS keywords to target\n\n{', '.join(analysis.keywords)}",
            f"## Current resume ({knowledge.resume_format})\n\n{knowledge.resume_src}",
        ]
        if knowledge.profile_md:
            sections.append(f"## Candidate background notes\n\n{knowledge.profile_md}")
        if knowledge.projects:
            sections.append(f"## Candidate's projects\n\n{knowledge.projects_blob()}")
        return "\n\n".join(sections)

    def _tailor_system(self, knowledge: Knowledge) -> str:
        return TAILOR_SYSTEM.format(format_rules=FORMAT_RULES[knowledge.resume_format])

    def tailor_resume(
        self, knowledge: Knowledge, jd_text: str, analysis: JobAnalysis
    ) -> str:
        return self._chat(
            [
                {"role": "system", "content": self._tailor_system(knowledge)},
                {
                    "role": "user",
                    "content": self._tailor_user_prompt(knowledge, jd_text, analysis),
                },
            ]
        )

    def fix_latex(self, tex_src: str, compile_errors: str) -> str:
        return self._chat(
            [
                {"role": "system", "content": FIX_LATEX_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"## Compile errors\n\n{compile_errors}\n\n"
                        f"## Document\n\n{tex_src}"
                    ),
                },
            ]
        )

    def revise_resume(
        self,
        knowledge: Knowledge,
        jd_text: str,
        analysis: JobAnalysis,
        tailored_md: str,
        missing_keywords: list[str],
    ) -> str:
        return self._chat(
            [
                {"role": "system", "content": self._tailor_system(knowledge)},
                {
                    "role": "user",
                    "content": self._tailor_user_prompt(knowledge, jd_text, analysis),
                },
                {"role": "assistant", "content": tailored_md},
                {
                    "role": "user",
                    "content": REVISE_INSTRUCTION.format(
                        missing=", ".join(missing_keywords)
                    ),
                },
            ]
        )
