# sokol

Private Telegram bot that tailors your resume to a job posting so it scores
higher on ATS keyword screens. Everything runs locally: the LLM work happens
in [Ollama](https://ollama.com) on your machine, and your resume lives in a
gitignored `.private/` folder that never leaves the repo.

## How it works

Send the bot a job posting URL (or paste the job description if the site
blocks scraping). It then:

1. Extracts the job description and pulls out the ranked ATS keywords
   (`qwen3:30b`)
2. Scores your current resume: keyword coverage + semantic similarity
   (`nomic-embed-text`)
3. Rewrites your resume for the role using your resume, profile notes, and
   project READMEs — rephrasing and re-emphasizing only; it is instructed to
   never invent employers, dates, degrees, or skills you don't have
4. Re-scores, revises once if coverage didn't improve, and sends back the
   **PDF** plus the source file and a `before → after` score summary

Your resume can be **LaTeX or Markdown**. With `resume.tex`, the model edits
only the bullet points in your experience/project/skill entries (preamble,
layout, headings, titles, and dates stay untouched) and the PDF is compiled
with `pdflatex` (or [tectonic](https://tectonic-typesetting.github.io) as a
fallback) — including an automatic repair pass if the edit broke compilation.
With `resume.md`, the PDF is rendered through WeasyPrint with a clean
single-column ATS-friendly stylesheet.

## Setup

Requires Python 3.13+, [uv](https://docs.astral.sh/uv/), and Ollama with the
models pulled:

```sh
ollama pull qwen3:30b
ollama pull nomic-embed-text
brew install pango      # WeasyPrint PDF rendering, for Markdown resumes (macOS)
brew install texlive    # pdflatex, for LaTeX resumes (Overleaf-style templates)
uv sync
```

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.
2. Get your numeric Telegram user id from [@userinfobot](https://t.me/userinfobot).
3. `cp .env.example .env` and fill in `TELEGRAM_BOT_TOKEN` and
   `ALLOWED_USER_IDS` — the bot ignores everyone not on that list.
4. Put your material in `.private/` (gitignored):
   - `resume.tex` **or** `resume.md` — your resume (if both exist, `.tex` wins)
   - `profile.md` — extra background notes (optional)
   - `projects/*.md` — one README per project (optional; `_`-prefixed files
     are ignored)

## Run

```sh
uv run sokol
```

Then message your bot a job posting URL. Use `/score` to re-check your
current resume against the last job without rewriting.

Generated PDFs and Markdown land in `output/` (also gitignored).
