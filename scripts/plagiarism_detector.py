"""
plagiarism_detector.py — GradeOps Plagiarism Detection
Detects suspiciously similar logic/structure across student answers
using TF-IDF cosine similarity + optional sentence-transformer embeddings.

Usage:
    detector = PlagiarismDetector(threshold=0.82)
    flags    = detector.scan_question(ocr_results_for_q1)
    report   = detector.full_report(all_ocr_results)
"""

import logging
import itertools
from dataclasses import dataclass, field

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from models import OCRResult, PlagiarismMatch

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────

@dataclass
class PlagiarismConfig:
    threshold: float = 0.82          # cosine similarity above this → flagged
    use_embeddings: bool = False      # use sentence-transformers (slower, better)
    embedding_model: str = "all-MiniLM-L6-v2"
    min_answer_length: int = 20      # ignore very short answers
    ngram_range: tuple[int, int] = (1, 2)  # TF-IDF n-gram range


# ─────────────────────────────────────────────
# Text preprocessing
# ─────────────────────────────────────────────

def _preprocess(text: str) -> str:
    """Lowercase, strip punctuation, normalize whitespace."""
    import re
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_key_phrases(text: str, top_n: int = 5) -> list[str]:
    """
    Heuristic: extract the most 'unique' multi-word phrases (bigrams).
    Used to surface matched evidence in the PlagiarismMatch report.
    """
    import re
    words = re.findall(r"\b\w{4,}\b", text.lower())
    bigrams = [f"{words[i]} {words[i+1]}" for i in range(len(words) - 1)]
    # Return most frequent bigrams as likely shared phrases
    from collections import Counter
    return [phrase for phrase, _ in Counter(bigrams).most_common(top_n)]


# ─────────────────────────────────────────────
# TF-IDF similarity engine
# ─────────────────────────────────────────────

class _TFIDFEngine:
    def compute_matrix(self, texts: list[str], ngram_range: tuple) -> np.ndarray:
        vectorizer = TfidfVectorizer(
            ngram_range=ngram_range,
            analyzer="word",
            min_df=1,
            sublinear_tf=True,
        )
        tfidf_matrix = vectorizer.fit_transform(texts)
        return cosine_similarity(tfidf_matrix)


# ─────────────────────────────────────────────
# Embedding similarity engine (optional)
# ─────────────────────────────────────────────

class _EmbeddingEngine:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer
        logger.info("Loading sentence-transformer: %s", model_name)
        self.model = SentenceTransformer(model_name)

    def compute_matrix(self, texts: list[str]) -> np.ndarray:
        embeddings = self.model.encode(texts, normalize_embeddings=True)
        return np.dot(embeddings, embeddings.T)


# ─────────────────────────────────────────────
# PlagiarismDetector
# ─────────────────────────────────────────────

class PlagiarismDetector:
    """
    Detects suspiciously similar answers across a set of students.

    Args:
        config: PlagiarismConfig instance (or uses defaults).
    """

    def __init__(self, config: PlagiarismConfig | None = None):
        self.cfg = config or PlagiarismConfig()
        self._tfidf_engine = _TFIDFEngine()
        self._emb_engine   = (
            _EmbeddingEngine(self.cfg.embedding_model)
            if self.cfg.use_embeddings else None
        )

    # ── public ────────────────────────────────

    def scan_question(self, ocr_results: list[OCRResult]) -> list[PlagiarismMatch]:
        """
        Check all pairs of students for one question.

        Args:
            ocr_results: All OCRResult objects for a single question number.

        Returns:
            List of PlagiarismMatch (all pairs, flagged or not).
        """
        # Filter too-short answers
        valid = [r for r in ocr_results if len(r.raw_text.strip()) >= self.cfg.min_answer_length]
        if len(valid) < 2:
            return []

        texts       = [_preprocess(r.raw_text) for r in valid]
        sim_matrix  = self._similarity_matrix(texts)
        matches: list[PlagiarismMatch] = []

        for i, j in itertools.combinations(range(len(valid)), 2):
            score = float(sim_matrix[i, j])
            flagged = score >= self.cfg.threshold

            # Gather overlapping phrases as evidence
            phrases_i = set(_extract_key_phrases(valid[i].raw_text))
            phrases_j = set(_extract_key_phrases(valid[j].raw_text))
            matched   = list(phrases_i & phrases_j)

            match = PlagiarismMatch(
                student_a=valid[i].student_id,
                student_b=valid[j].student_id,
                exam_id=valid[i].exam_id,
                question_number=valid[i].question_number,
                similarity_score=round(score, 4),
                matched_phrases=matched,
                flagged=flagged,
            )
            matches.append(match)

            if flagged:
                logger.warning(
                    "PLAGIARISM FLAG | exam=%s q=%d | %s <-> %s | sim=%.3f",
                    valid[i].exam_id, valid[i].question_number,
                    valid[i].student_id, valid[j].student_id, score,
                )

        return matches

    def full_report(
        self,
        all_ocr_results: list[OCRResult],
    ) -> dict[int, list[PlagiarismMatch]]:
        """
        Run plagiarism scan across all questions in an exam.

        Args:
            all_ocr_results: Flat list of OCRResult for ALL students and questions.

        Returns:
            Dict mapping question_number → list[PlagiarismMatch].
        """
        # Group by question number
        by_question: dict[int, list[OCRResult]] = {}
        for r in all_ocr_results:
            by_question.setdefault(r.question_number, []).append(r)

        report: dict[int, list[PlagiarismMatch]] = {}
        for q_num, results in sorted(by_question.items()):
            logger.info("Scanning plagiarism for question %d (%d students)…", q_num, len(results))
            report[q_num] = self.scan_question(results)

        total_flags = sum(
            1 for matches in report.values() for m in matches if m.flagged
        )
        logger.info("Plagiarism scan complete. Flagged pairs: %d", total_flags)
        return report

    def flagged_pairs(
        self,
        report: dict[int, list[PlagiarismMatch]],
    ) -> list[PlagiarismMatch]:
        """Return only flagged matches from a full report."""
        return [m for matches in report.values() for m in matches if m.flagged]

    # ── private ───────────────────────────────

    def _similarity_matrix(self, texts: list[str]) -> np.ndarray:
        if self._emb_engine:
            return self._emb_engine.compute_matrix(texts)
        return self._tfidf_engine.compute_matrix(texts, self.cfg.ngram_range)
