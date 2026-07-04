"""ATS-style scoring: keyword coverage + embedding similarity."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

import ollama

KEYWORD_WEIGHT = 0.7
EMBED_WEIGHT = 0.3


@dataclass(frozen=True)
class Score:
    keyword_coverage: float  # 0..1
    embedding_similarity: float  # 0..1
    matched: list[str]
    missing: list[str]

    @property
    def combined(self) -> float:
        return KEYWORD_WEIGHT * self.keyword_coverage + EMBED_WEIGHT * self.embedding_similarity

    @property
    def percent(self) -> int:
        return round(self.combined * 100)


def _normalize(text: str) -> str:
    """Lowercase and collapse separators so 'CI/CD' matches 'ci cd' etc."""
    return re.sub(r"[^a-z0-9+#.]+", " ", text.lower()).strip()


def _keyword_present(keyword: str, normalized_doc: str) -> bool:
    kw = _normalize(keyword)
    if not kw:
        return False
    return f" {kw} " in f" {normalized_doc} "


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


class Scorer:
    def __init__(self, host: str, model: str):
        self._client = ollama.Client(host=host)
        self._model = model

    def _embed(self, text: str) -> list[float]:
        return self._client.embeddings(model=self._model, prompt=text)["embedding"]

    def score(self, resume_md: str, jd_text: str, keywords: list[str]) -> Score:
        normalized_resume = _normalize(resume_md)
        matched = [k for k in keywords if _keyword_present(k, normalized_resume)]
        missing = [k for k in keywords if k not in matched]
        coverage = len(matched) / len(keywords) if keywords else 0.0

        similarity = _cosine(self._embed(resume_md), self._embed(jd_text))
        # Cosine on embeddings of any two English documents rarely drops below
        # ~0.4, so rescale to spread the useful range over 0..1.
        similarity = max(0.0, min(1.0, (similarity - 0.4) / 0.6))

        return Score(
            keyword_coverage=coverage,
            embedding_similarity=similarity,
            matched=matched,
            missing=missing,
        )
