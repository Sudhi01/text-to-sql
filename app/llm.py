"""
Phase 1 - Component 4: Structured Prompt Builder + SQL Generator
Replaces the old simple llm.py with:
- Dynamic schema context (from schema extractor)
- Schema filtering (only relevant tables)
- Ambiguity detection (clarify before generating)
- Few-shot examples
- Structured output (SQL + explanation + confidence + tables used)
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

from openai import OpenAI, OpenAIError
import os

from schema import get_schema, format_schema_for_prompt
from schema_filter import filter_relevant_tables
from ambiguity import check_ambiguity, ClarificationRequest

logger = logging.getLogger(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------

@dataclass
class SQLGenerationResult:
    sql: str
    explanation: str                    # plain English: what the SQL does
    confidence: float                   # 0.0 – 1.0
    tables_used: List[str]
    columns_used: List[str]
    clarification_needed: bool = False
    clarification: Optional[ClarificationRequest] = None


# ---------------------------------------------------------------------------
# Few-shot examples — add more pairs specific to your schema
# ---------------------------------------------------------------------------

FEW_SHOT_EXAMPLES = [
    {
        "question": "total orders per customer",
        "sql": (
            "SELECT c.id, c.name, COUNT(o.id) AS total_orders "
            "FROM customers c "
            "LEFT JOIN orders o ON c.id = o.customer_id "
            "GROUP BY c.id, c.name"
        ),
    },
    {
        "question": "list all customers",
        "sql": "SELECT id, name, email FROM customers",
    },
    {
        "question": "top 5 customers by number of orders",
        "sql": (
            "SELECT c.id, c.name, COUNT(o.id) AS total_orders "
            "FROM customers c "
            "LEFT JOIN orders o ON c.id = o.customer_id "
            "GROUP BY c.id, c.name "
            "ORDER BY total_orders DESC "
            "LIMIT 5"
        ),
    },
]


def _build_few_shot_block() -> str:
    lines = ["Examples:"]
    for ex in FEW_SHOT_EXAMPLES:
        lines.append(f'Q: {ex["question"]}')
        lines.append(f'SQL: {ex["sql"]}')
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def build_prompt(question: str, schema_text: str) -> str:
    few_shot = _build_few_shot_block()
    return f"""You are an expert SQL assistant.

Given a database schema and a question, return a JSON object with:
- "sql": valid SELECT SQL query
- "explanation": plain English description of what the SQL does
- "confidence": float 0.0 to 1.0 representing how confident you are
- "tables_used": list of table names used
- "columns_used": list of column names used

Rules:
- Only SELECT queries — never INSERT, UPDATE, DELETE, DROP, ALTER, CREATE
- Always use correct JOINs based on foreign keys in the schema
- Add LIMIT 1000 if no limit is specified
- Return ONLY the JSON object, no markdown, no explanation outside JSON

Schema:
{schema_text}

{few_shot}

Question: {question}
"""


# ---------------------------------------------------------------------------
# SQL generator
# ---------------------------------------------------------------------------

def generate_sql(question: str, engine) -> SQLGenerationResult:
    """
    Full Phase 1 pipeline:
    1. Extract schema
    2. Filter to relevant tables
    3. Check for ambiguity
    4. Build prompt and generate structured SQL output

    Args:
        question : Natural language question from the user.
        engine   : SQLAlchemy engine connected to your database.

    Returns:
        SQLGenerationResult with sql, explanation, confidence, tables_used etc.
        If ambiguous, returns with clarification_needed=True and no SQL.
    """

    # Step 1: Extract full schema
    full_schema = get_schema(engine)

    # Step 2: Filter to relevant tables only
    filtered_schema = filter_relevant_tables(question, full_schema)
    schema_text = format_schema_for_prompt(filtered_schema)

    # Step 3: Check for ambiguity before generating
    ambiguity_result = check_ambiguity(question, schema_text)
    if ambiguity_result.is_ambiguous:
        return SQLGenerationResult(
            sql="",
            explanation="",
            confidence=0.0,
            tables_used=[],
            columns_used=[],
            clarification_needed=True,
            clarification=ambiguity_result.clarification,
        )

    # Step 4: Build prompt and call LLM
    prompt = build_prompt(question, schema_text)

    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=512,
            temperature=0,
        )
        raw = res.choices[0].message.content.strip()

        # Strip markdown fences if LLM adds them
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)

        data = json.loads(raw)

        return SQLGenerationResult(
            sql=_clean_sql(data.get("sql", "")),
            explanation=data.get("explanation", ""),
            confidence=float(data.get("confidence", 0.5)),
            tables_used=data.get("tables_used", []),
            columns_used=data.get("columns_used", []),
        )

    except (OpenAIError, json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error("SQL generation failed: %s", e)
        raise RuntimeError(f"SQL generation failed: {e}") from e


def _clean_sql(sql: str) -> str:
    """Strip any remaining markdown or whitespace from SQL."""
    sql = sql.strip()
    sql = re.sub(r"^```sql\s*", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\s*```$", "", sql)
    return sql.strip()