"""
main.py — FastAPI Application
Phase 4: Full API with all endpoints
  POST /v1/query   — generate SQL, run guardrails, execute, validate
  GET  /v1/schema  — return live DB schema
  GET  /v1/history — return session query history
  POST /v1/feedback — mark a result correct/incorrect
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import json
import os
from datetime import datetime, timezone

from llm import generate_sql
from db import run_query, engine, execute_fn
from schema import get_schema, format_schema_for_prompt
from phase3 import run_quality_checks

app = FastAPI(title="Text-to-SQL API", version="1.0.0")

# ---------------------------------------------------------------------------
# In-memory history store (per server session)
# For production, replace with a database table
# ---------------------------------------------------------------------------
HISTORY = []
FEEDBACK_LOG = "feedback.jsonl"


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    question: str
    expected_tables: Optional[list[str]] = None


class FeedbackRequest(BaseModel):
    query_id: str
    correct: bool
    comment: Optional[str] = ""


# ---------------------------------------------------------------------------
# POST /v1/query
# ---------------------------------------------------------------------------

@app.post("/v1/query")
def query(req: QueryRequest):
    question = req.question

    # ------------------------------------------------------------------
    # Phase 1: Generate SQL (schema-aware, ambiguity-checked)
    # ------------------------------------------------------------------
    try:
        gen = generate_sql(question, engine)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Ambiguity — return clarification options instead of guessing
    if gen.clarification_needed:
        return {
            "status": "clarification_needed",
            "question": question,
            "message": gen.clarification.message,
            "interpretations": [
                {
                    "label": i.label,
                    "description": i.description,
                    "example_sql": i.example_sql,
                }
                for i in gen.clarification.interpretations
            ],
        }

    sql = gen.sql

    # ------------------------------------------------------------------
    # Phase 2: Run query (guardrails + EXPLAIN + execution inside db.py)
    # ------------------------------------------------------------------
    result = run_query(sql, question=question)

    # Blocked by guardrails
    if result["status"] == "blocked":
        entry = _make_history_entry(
            question=question,
            sql=sql,
            result=result,
            quality=None,
            gen=gen,
        )
        HISTORY.append(entry)
        return entry

    # ------------------------------------------------------------------
    # Phase 3: Hallucination detection + confidence scoring
    # ------------------------------------------------------------------
    quality_input = {
        "status": result["status"],
        "row_count": result["row_count"],
        "sample_data": result.get("data", [])[:5],
    }

    quality = run_quality_checks(
        question=question,
        sql=sql,
        result=quality_input,
        execute_fn=execute_fn,
        expected_tables=req.expected_tables or gen.tables_used,
    )

    # ------------------------------------------------------------------
    # Build standardized response
    # ------------------------------------------------------------------
    entry = _make_history_entry(
        question=question,
        sql=sql,
        result=result,
        quality=quality,
        gen=gen,
    )
    HISTORY.append(entry)
    return entry


def _make_history_entry(question, sql, result, quality, gen):
    return {
        "query_id": f"q{len(HISTORY) + 1}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "question": question,
        "sql": sql,
        "explanation": gen.explanation if gen else "",
        "result": {
            "status": result["status"],
            "data": result.get("data", []),
            "row_count": result.get("row_count", 0),
            "execution_time": result.get("execution_time", 0),
            "explain_plan": result.get("explain_plan", []),
        },
        "guardrail": result.get("guardrail", {}),
        "quality": quality,
        "feedback": None,   # filled by /v1/feedback
    }


# ---------------------------------------------------------------------------
# GET /v1/schema
# ---------------------------------------------------------------------------

@app.get("/v1/schema")
def schema():
    """Return live DB schema extracted via SQLAlchemy."""
    try:
        full_schema = get_schema(engine)
        return {
            "status": "success",
            "schema": full_schema,
            "formatted": format_schema_for_prompt(full_schema),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# GET /v1/history
# ---------------------------------------------------------------------------

@app.get("/v1/history")
def history(limit: int = 20):
    """Return past queries for this session, newest first."""
    return {
        "status": "success",
        "count": len(HISTORY),
        "queries": list(reversed(HISTORY))[:limit],
    }


# ---------------------------------------------------------------------------
# POST /v1/feedback
# ---------------------------------------------------------------------------

@app.post("/v1/feedback")
def feedback(req: FeedbackRequest):
    """
    Mark a query result as correct or incorrect.
    - Correct results → saved as few-shot examples
    - Incorrect results → saved as eval test cases
    """
    # Find the history entry
    entry = next((h for h in HISTORY if h["query_id"] == req.query_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Query ID {req.query_id} not found")

    # Update in-memory history
    entry["feedback"] = {
        "correct": req.correct,
        "comment": req.comment,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Persist feedback to JSONL file
    record = {
        "query_id": req.query_id,
        "question": entry["question"],
        "sql": entry["sql"],
        "correct": req.correct,
        "comment": req.comment,
        "timestamp": entry["feedback"]["timestamp"],
        # Tag for downstream use
        "use_as": "few_shot" if req.correct else "eval_test_case",
    }

    try:
        with open(FEEDBACK_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to save feedback: {e}")

    return {
        "status": "success",
        "query_id": req.query_id,
        "correct": req.correct,
        "use_as": record["use_as"],
        "message": (
            "Saved as few-shot example for future SQL generation"
            if req.correct
            else "Saved as eval test case for regression suite"
        ),
    }