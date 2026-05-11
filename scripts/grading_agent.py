"""
grading_agent.py — GradeOps Agentic Grading Pipeline
Uses LangGraph + an LLM to evaluate OCR transcripts against rubrics,
awarding partial credit with structured justifications.

Graph nodes:
  plan_grading  →  grade_criterion (loop over criteria)  →  aggregate  →  END

Usage:
    agent = GradingAgent(llm_provider="openai", model_name="gpt-4o")
    result = agent.grade(ocr_result, rubric)
"""

import uuid
import json
import logging
from typing import Any, TypedDict

from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END

from models import (
    OCRResult, Rubric, RubricCriterion,
    GradeResult, CriterionScore, GradeStatus
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# LLM factory
# ─────────────────────────────────────────────

def build_llm(provider: str, model_name: str, temperature: float = 0.0):
    """
    Returns a LangChain chat model.
    Supported providers: "openai" | "anthropic" | "together" | "mock"
    """
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model_name, temperature=temperature)

    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model_name, temperature=temperature)

    elif provider == "together":
        from langchain_together import ChatTogether
        return ChatTogether(model=model_name, temperature=temperature)

    elif provider == "mock":
        return _MockLLM()

    raise ValueError(f"Unknown LLM provider: {provider}")


class _MockLLM:
    """Deterministic mock LLM — no API key needed for unit tests."""
    def invoke(self, messages):
        class _R:
            content = json.dumps({
                "awarded_points": 3.5,
                "justification": "Correct concept, minor notation error."
            })
        return _R()


# ─────────────────────────────────────────────
# LangGraph state
# ─────────────────────────────────────────────

class GradingState(TypedDict):
    ocr_result:       OCRResult
    rubric:           Rubric
    criterion_index:  int                  # which criterion we are currently grading
    criterion_scores: list[CriterionScore]
    error:            str | None


# ─────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are a strict, fair university exam grader.
You will be given:
  - A student's handwritten answer (already transcribed via OCR)
  - A single grading criterion with a description, max points, and required keywords

Your task:
1. Read the student's answer carefully.
2. Decide how many points (0 to max) to award for this criterion.
3. Write one concise justification sentence.

Rules:
- Award partial credit only if partial_credit is True.
- If partial_credit is False, award either full marks or 0.
- Required keywords must appear (even approximately) to earn full marks.
- Be strict but fair — do not penalise minor spelling errors.

Respond ONLY with valid JSON, no extra text:
{
  "awarded_points": <float>,
  "justification": "<one sentence>"
}"""

def _build_criterion_prompt(
    answer: str,
    criterion: RubricCriterion,
    strict_mode: bool,
) -> str:
    kw = ", ".join(criterion.required_keywords) if criterion.required_keywords else "none"
    return (
        f"STUDENT ANSWER:\n{answer}\n\n"
        f"CRITERION: {criterion.description}\n"
        f"MAX POINTS: {criterion.max_points}\n"
        f"REQUIRED KEYWORDS: {kw}\n"
        f"PARTIAL CREDIT ALLOWED: {criterion.partial_credit and not strict_mode}\n\n"
        "Grade this criterion."
    )


# ─────────────────────────────────────────────
# Graph nodes
# ─────────────────────────────────────────────

def make_grade_criterion_node(llm):
    """Returns a node function that grades one criterion per call."""

    def grade_criterion(state: GradingState) -> GradingState:
        idx     = state["criterion_index"]
        rubric  = state["rubric"]
        criteria = rubric.criteria

        if idx >= len(criteria):
            return state  # no-op — graph router will redirect to aggregate

        criterion = criteria[idx]
        answer    = state["ocr_result"].raw_text

        prompt = _build_criterion_prompt(answer, criterion, rubric.strict_mode)
        messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)]

        try:
            response = llm.invoke(messages)
            parsed   = json.loads(response.content)
            awarded  = float(parsed["awarded_points"])
            # clamp to [0, max_points]
            awarded  = max(0.0, min(awarded, criterion.max_points))
            justification = parsed.get("justification", "")
        except Exception as exc:
            logger.error("LLM grading error on criterion %s: %s", criterion.criterion_id, exc)
            awarded, justification = 0.0, f"Grading error: {exc}"

        score = CriterionScore(
            criterion_id=criterion.criterion_id,
            awarded_points=awarded,
            justification=justification,
        )

        new_scores = state["criterion_scores"] + [score]
        logger.debug(
            "Graded criterion %s → %.1f/%.1f",
            criterion.criterion_id, awarded, criterion.max_points
        )
        return {**state, "criterion_scores": new_scores, "criterion_index": idx + 1}

    return grade_criterion


def aggregate_node(state: GradingState) -> GradingState:
    """Final node — state already complete, just passes through."""
    return state


# ─────────────────────────────────────────────
# Graph router
# ─────────────────────────────────────────────

def should_continue(state: GradingState) -> str:
    idx   = state["criterion_index"]
    total = len(state["rubric"].criteria)
    return "grade_criterion" if idx < total else "aggregate"


# ─────────────────────────────────────────────
# GradingAgent
# ─────────────────────────────────────────────

class GradingAgent:
    """
    LangGraph-powered agentic grader.

    Args:
        llm_provider: "openai" | "anthropic" | "together" | "mock"
        model_name:   Provider-specific model name.
    """

    def __init__(
        self,
        llm_provider: str = "openai",
        model_name: str = "gpt-4o",
        temperature: float = 0.0,
    ):
        self.llm = build_llm(llm_provider, model_name, temperature)
        self.graph = self._build_graph()

    # ── public ────────────────────────────────

    def grade(self, ocr_result: OCRResult, rubric: Rubric) -> GradeResult:
        """
        Grade a single student answer against a rubric.

        Returns:
            GradeResult with per-criterion scores and overall justification.
        """
        initial_state: GradingState = {
            "ocr_result":       ocr_result,
            "rubric":           rubric,
            "criterion_index":  0,
            "criterion_scores": [],
            "error":            None,
        }

        final_state = self.graph.invoke(initial_state)
        return self._build_grade_result(ocr_result, rubric, final_state)

    def grade_batch(
        self,
        ocr_results: list[OCRResult],
        rubric_map: dict[int, Rubric],   # {question_number: Rubric}
    ) -> list[GradeResult]:
        """Grade a list of OCR results (all questions for all students)."""
        results = []
        for ocr in ocr_results:
            rubric = rubric_map.get(ocr.question_number)
            if rubric is None:
                logger.warning("No rubric for question %d — skipping", ocr.question_number)
                continue
            results.append(self.grade(ocr, rubric))
        return results

    # ── private ───────────────────────────────

    def _build_graph(self) -> StateGraph:
        grade_criterion_node = make_grade_criterion_node(self.llm)

        graph = StateGraph(GradingState)
        graph.add_node("grade_criterion", grade_criterion_node)
        graph.add_node("aggregate", aggregate_node)

        graph.set_entry_point("grade_criterion")
        graph.add_conditional_edges("grade_criterion", should_continue, {
            "grade_criterion": "grade_criterion",
            "aggregate":       "aggregate",
        })
        graph.add_edge("aggregate", END)

        return graph.compile()

    def _build_grade_result(
        self,
        ocr: OCRResult,
        rubric: Rubric,
        state: GradingState,
    ) -> GradeResult:
        scores   = state["criterion_scores"]
        total    = sum(s.awarded_points for s in scores)
        possible = rubric.total_points

        justifications = "; ".join(
            f"[{s.criterion_id}] {s.justification}" for s in scores
        )
        overall = f"Total: {total:.1f}/{possible:.1f}. {justifications}"

        return GradeResult(
            grade_id=str(uuid.uuid4()),
            student_id=ocr.student_id,
            exam_id=ocr.exam_id,
            question_number=ocr.question_number,
            ocr_text=ocr.raw_text,
            rubric_id=rubric.rubric_id,
            criterion_scores=scores,
            total_awarded=round(total, 2),
            total_possible=possible,
            overall_justification=overall,
            status=GradeStatus.AI_GRADED,
        )
