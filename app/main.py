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
from contextlib import asynccontextmanager
from sqlalchemy import text
import asyncio
import json
import os
from datetime import datetime, timezone

from app.llm import generate_sql
from app.db import run_query, engine, execute_fn
from app.schema import get_schema, format_schema_for_prompt
from app.phase3 import run_quality_checks


# ---------------------------------------------------------------------------
# Keep-alive task — pings DB every 5 minutes to prevent Supabase timeout
# ---------------------------------------------------------------------------

async def keep_alive():
    while True:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:
            pass
        await asyncio.sleep(300)


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(keep_alive())
    yield


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Text-to-SQL API", version="1.0.0", lifespan=lifespan)

# ---------------------------------------------------------------------------
# In-memory history store (per server session)
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

    # Phase 1: Generate SQL
    try:
        gen = generate_sql(question, engine)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

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

    # Phase 2: Run query
    result = run_query(sql, question=question)

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

    # Phase 3: Hallucination detection
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
        "feedback": None,
    }


# ---------------------------------------------------------------------------
# GET /v1/schema
# ---------------------------------------------------------------------------

@app.get("/v1/schema")
def schema():
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
    entry = next((h for h in HISTORY if h["query_id"] == req.query_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Query ID {req.query_id} not found")

    entry["feedback"] = {
        "correct": req.correct,
        "comment": req.comment,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    record = {
        "query_id": req.query_id,
        "question": entry["question"],
        "sql": entry["sql"],
        "correct": req.correct,
        "comment": req.comment,
        "timestamp": entry["feedback"]["timestamp"],
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