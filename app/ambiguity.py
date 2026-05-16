"""
Phase 1 - Component 3: Ambiguity Handler
Detects when a question has multiple valid interpretations
and returns a structured clarification request instead of guessing.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional

from openai import OpenAI, OpenAIError
import os

logger = logging.getLogger(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


@dataclass
class Interpretation:
    label: str          # e.g. "Gross revenue (before discounts)"
    example_sql: str    # e.g. "SELECT SUM(gross_amount) FROM orders"
    description: str    # short plain-English explanation


@dataclass
class ClarificationRequest:
    question: str
    interpretations: List[Interpretation]
    message: str = "Your question has multiple possible interpretations. Please choose one:"


@dataclass
class AmbiguityResult:
    is_ambiguous: bool
    clarification: Optional[ClarificationRequest] = None


# ---------------------------------------------------------------------------
# Known ambiguous terms — extend this list for your domain
# ---------------------------------------------------------------------------
AMBIGUOUS_TERMS = {
    "revenue":      ["gross revenue", "net revenue", "revenue after discounts"],
    "profit":       ["gross profit", "net profit", "operating profit"],
    "sales":        ["order count", "revenue", "units sold"],
    "performance":  ["revenue", "order count", "growth rate"],
    "recent":       ["last 7 days", "last 30 days", "last 90 days"],
    "top":          ["by revenue", "by order count", "by quantity"],
    "best":         ["by revenue", "by order count", "by rating"],
}


def _contains_ambiguous_term(question: str) -> List[str]:
    """Return list of ambiguous terms found in the question."""
    q = question.lower()
    return [term for term in AMBIGUOUS_TERMS if term in q]


def check_ambiguity(question: str, schema_text: str) -> AmbiguityResult:
    """
    Check if the question is ambiguous.
    First does a fast keyword check, then asks the LLM for interpretations.

    Returns AmbiguityResult with is_ambiguous=True and a ClarificationRequest
    if ambiguous, or is_ambiguous=False if the question is clear.
    """
    ambiguous_terms = _contains_ambiguous_term(question)

    # If no ambiguous terms found, skip LLM call — question is clear
    if not ambiguous_terms:
        return AmbiguityResult(is_ambiguous=False)

    # Ask LLM to generate interpretations
    prompt = f"""
A user asked this question about a database:
"{question}"

The question contains potentially ambiguous terms: {", ".join(ambiguous_terms)}

Schema:
{schema_text}

If the question has multiple valid SQL interpretations, list them as JSON.
If it's clear enough, return {{"ambiguous": false}}.

Return JSON only, no explanation:
{{
  "ambiguous": true,
  "interpretations": [
    {{
      "label": "short label",
      "description": "plain English explanation",
      "example_sql": "SELECT ..."
    }}
  ]
}}
"""

    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=512,
            temperature=0,
        )
        raw = res.choices[0].message.content.strip()

        # Strip markdown fences if present
        import re
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)

        data = json.loads(raw)

        if not data.get("ambiguous", False):
            return AmbiguityResult(is_ambiguous=False)

        interpretations = [
            Interpretation(
                label=i["label"],
                description=i["description"],
                example_sql=i["example_sql"],
            )
            for i in data.get("interpretations", [])
        ]

        if not interpretations:
            return AmbiguityResult(is_ambiguous=False)

        return AmbiguityResult(
            is_ambiguous=True,
            clarification=ClarificationRequest(
                question=question,
                interpretations=interpretations,
            ),
        )

    except (OpenAIError, json.JSONDecodeError, KeyError) as e:
        logger.warning("Ambiguity check failed: %s", e)
        # On failure, treat as unambiguous so we don't block the user
        return AmbiguityResult(is_ambiguous=False)