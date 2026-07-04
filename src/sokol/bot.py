"""Telegram bot: send a job URL (or paste a JD), get back a tailored resume PDF."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path

from telegram import Update
from telegram.constants import ChatAction, ChatType
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .ats import Score, Scorer
from .config import Config
from .jd_fetcher import FetchFailed, fetch_job_description
from .knowledge import Knowledge, load_knowledge
from .latex import CompileFailed, compile_latex, restore_preamble, strip_latex
from .pdf import render_pdf
from .tailor import JobAnalysis, Tailor

logger = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://\S+")

HELP_TEXT = (
    "Send me a job posting URL and I'll tailor your resume for it.\n\n"
    "What I do:\n"
    "1. Fetch and analyze the job description\n"
    "2. Score your current resume against its ATS keywords\n"
    "3. Rewrite the resume (no fabrication — only your real material)\n"
    "4. Send back a PDF + Markdown and the before/after ATS score\n\n"
    "Commands:\n"
    "/score — re-score your current resume against the last job\n"
    "/help — this message\n\n"
    "If a site blocks me (LinkedIn usually does), I'll ask you to paste the "
    "job description text instead."
)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "resume"


def _score_block(label: str, score: Score) -> str:
    return (
        f"{label}: {score.percent}% "
        f"(keywords {round(score.keyword_coverage * 100)}%, "
        f"semantic {round(score.embedding_similarity * 100)}%)"
    )


class SokolBot:
    def __init__(self, config: Config):
        self.config = config
        self.tailor = Tailor(config.ollama_host, config.chat_model)
        self.scorer = Scorer(config.ollama_host, config.embed_model)

    # -- helpers ------------------------------------------------------------

    def _authorized(self, update: Update) -> bool:
        user = update.effective_user
        chat = update.effective_chat
        return (
            user is not None
            and user.id in self.config.allowed_user_ids
            and chat is not None
            and chat.type == ChatType.PRIVATE
        )

    async def _status(self, update: Update, text: str) -> None:
        await update.effective_chat.send_action(ChatAction.TYPING)
        await update.effective_message.reply_text(text)

    # -- handlers -----------------------------------------------------------

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        await update.effective_message.reply_text(HELP_TEXT)

    async def cmd_score(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        jd_text = context.user_data.get("jd_text")
        analysis: JobAnalysis | None = context.user_data.get("analysis")
        if not jd_text or analysis is None:
            await update.effective_message.reply_text(
                "No job on file yet — send me a job posting URL first."
            )
            return
        try:
            knowledge = load_knowledge(self.config.private_dir)
        except (FileNotFoundError, ValueError) as exc:
            await update.effective_message.reply_text(str(exc))
            return
        await self._status(update, f"Scoring your resume against: {analysis.summary_line()}")
        score = await asyncio.to_thread(
            self.scorer.score, knowledge.resume_plain, jd_text, analysis.keywords
        )
        missing = ", ".join(score.missing[:15]) or "none"
        await update.effective_message.reply_text(
            f"{_score_block('Current resume', score)}\nMissing keywords: {missing}"
        )

    async def on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            logger.warning(
                "Rejected message from unauthorized user %s", update.effective_user
            )
            return
        text = (update.effective_message.text or "").strip()
        if not text:
            return

        if context.user_data.get("busy"):
            await update.effective_message.reply_text(
                "Still working on the previous job — hold on."
            )
            return

        url_match = URL_RE.search(text)
        if url_match:
            await self._run_guarded(update, context, url=url_match.group(0))
        elif context.user_data.get("awaiting_jd") or len(text) >= self.config.min_jd_chars:
            context.user_data["awaiting_jd"] = False
            await self._run_guarded(update, context, jd_text=text)
        else:
            await update.effective_message.reply_text(
                "Send me a job posting URL, or paste the full job description text."
            )

    async def _run_guarded(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        url: str | None = None,
        jd_text: str | None = None,
    ) -> None:
        context.user_data["busy"] = True
        try:
            await self._run_pipeline(update, context, url=url, jd_text=jd_text)
        except Exception:
            logger.exception("Pipeline failed")
            await update.effective_message.reply_text(
                "Something went wrong while processing that — check the bot logs."
            )
        finally:
            context.user_data["busy"] = False

    # -- the pipeline ---------------------------------------------------------

    async def _run_pipeline(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        url: str | None,
        jd_text: str | None,
    ) -> None:
        try:
            knowledge = load_knowledge(self.config.private_dir)
        except (FileNotFoundError, ValueError) as exc:
            await update.effective_message.reply_text(str(exc))
            return

        if url is not None:
            await self._status(update, "Fetching the job post…")
            try:
                jd_text = await asyncio.to_thread(
                    fetch_job_description, url, self.config.min_jd_chars
                )
            except FetchFailed as exc:
                context.user_data["awaiting_jd"] = True
                await update.effective_message.reply_text(
                    f"{exc}\n\nPaste the job description text here and I'll use that."
                )
                return

        assert jd_text is not None

        await self._status(
            update, "Analyzing the role and its ATS keywords… (local model, takes a bit)"
        )
        analysis = await asyncio.to_thread(self.tailor.analyze_job, jd_text)
        context.user_data["jd_text"] = jd_text
        context.user_data["analysis"] = analysis

        before = await asyncio.to_thread(
            self.scorer.score, knowledge.resume_plain, jd_text, analysis.keywords
        )

        await self._status(
            update,
            f"Role: {analysis.summary_line()}\n"
            f"Current ATS match: {before.percent}%\n\n"
            "Tailoring your resume — this is the slow part…",
        )
        tailored_src = await asyncio.to_thread(
            self.tailor.tailor_resume, knowledge, jd_text, analysis
        )

        def plain(src: str) -> str:
            return strip_latex(src) if knowledge.resume_format == "latex" else src

        after = await asyncio.to_thread(
            self.scorer.score, plain(tailored_src), jd_text, analysis.keywords
        )

        # One bounded revision pass if tailoring didn't move keyword coverage.
        if after.keyword_coverage <= before.keyword_coverage and after.missing:
            await self._status(update, "First pass didn't improve coverage — revising once…")
            tailored_src = await asyncio.to_thread(
                self.tailor.revise_resume,
                knowledge,
                jd_text,
                analysis,
                tailored_src,
                after.missing,
            )
            after = await asyncio.to_thread(
                self.scorer.score, plain(tailored_src), jd_text, analysis.keywords
            )

        # The model must not touch the preamble, but small models drop packages
        # from it anyway — enforce the rule instead of trusting it.
        if knowledge.resume_format == "latex":
            tailored_src = restore_preamble(tailored_src, knowledge.resume_src)

        await self._status(update, "Rendering the PDF…")
        stamp = time.strftime("%Y%m%d-%H%M%S")
        base = self.config.output_dir / f"{_slug(analysis.summary_line())}-{stamp}"
        src_ext = ".tex" if knowledge.resume_format == "latex" else ".md"
        src_path = base.with_suffix(src_ext)
        src_path.parent.mkdir(parents=True, exist_ok=True)
        src_path.write_text(tailored_src, encoding="utf-8")

        pdf_path = await self._render(update, knowledge, tailored_src, base, src_path)
        if pdf_path is None:
            return  # compile failed twice; _render already sent the .tex + error

        await self._send_results(update, analysis, before, after, pdf_path, src_path)

    async def _render(
        self,
        update: Update,
        knowledge: Knowledge,
        tailored_src: str,
        base: Path,
        src_path: Path,
    ) -> Path | None:
        pdf_path = base.with_suffix(".pdf")
        if knowledge.resume_format == "markdown":
            return await asyncio.to_thread(render_pdf, tailored_src, pdf_path)

        try:
            return await asyncio.to_thread(compile_latex, tailored_src, pdf_path)
        except CompileFailed as exc:
            await self._status(
                update, "LaTeX compile failed — asking the model to repair it…"
            )
            fixed = await asyncio.to_thread(self.tailor.fix_latex, tailored_src, str(exc))
            fixed = restore_preamble(fixed, knowledge.resume_src)
            src_path.write_text(fixed, encoding="utf-8")
            try:
                return await asyncio.to_thread(compile_latex, fixed, pdf_path)
            except CompileFailed as exc2:
                await update.effective_message.reply_document(
                    src_path.open("rb"),
                    filename=src_path.name,
                    caption=(
                        "Couldn't get the tailored LaTeX to compile even after a "
                        "repair pass — here's the .tex to fix by hand.\n\n"
                        f"Last error:\n{str(exc2)[-800:]}"
                    ),
                )
                return None

    async def _send_results(
        self,
        update: Update,
        analysis: JobAnalysis,
        before: Score,
        after: Score,
        pdf_path: Path,
        src_path: Path,
    ) -> None:
        message = update.effective_message
        await message.reply_document(pdf_path.open("rb"), filename=pdf_path.name)
        await message.reply_document(
            src_path.open("rb"),
            filename=src_path.name,
            caption="Source file — tweak it by hand if you want before applying.",
        )

        gained = [k for k in before.missing if k in after.matched]
        lines = [
            analysis.summary_line(),
            f"ATS match: {before.percent}% → {after.percent}%",
            _score_block("Before", before),
            _score_block("After", after),
        ]
        if gained:
            lines.append(f"Keywords added: {', '.join(gained[:15])}")
        if after.missing:
            lines.append(
                f"Still missing (you may genuinely lack these): {', '.join(after.missing[:15])}"
            )
        await message.reply_text("\n".join(lines))


def build_application(config: Config) -> Application:
    bot = SokolBot(config)
    app = ApplicationBuilder().token(config.telegram_token).build()
    app.add_handler(CommandHandler(["start", "help"], bot.cmd_start))
    app.add_handler(CommandHandler("score", bot.cmd_score))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.on_message))
    return app
