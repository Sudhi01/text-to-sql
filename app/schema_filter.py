"""
Phase 1 - Component 2: Schema Filter
Filters only relevant tables for a given question using
OpenAI embeddings + cosine similarity.
Prevents sending the entire schema to the LLM unnecessarily.
"""

import logging
from typing import Optional

import numpy as np
from openai import OpenAI, OpenAIError
import os

logger = logging.getLogger(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def _embed(text: str) -> Optional[np.ndarray]:
    """Get embedding vector for a text string."""
    try:
        res = client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )
        return np.array(res.data[0].embedding, dtype=np.float32)
    except OpenAIError as e:
        logger.warning("Embedding failed: %s", e)
        return None


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors."""
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom else 0.0


def filter_relevant_tables(
    question: str,
    schema: dict,
    threshold: float = 0.30,
    max_tables: int = 6,
) -> dict:
    """
    Return only the tables most relevant to the question.

    Args:
        question   : The user's natural language question.
        schema     : Full schema dict from schema.get_schema().
        threshold  : Minimum cosine similarity to include a table (0–1).
        max_tables : Hard cap on number of tables returned.

    Returns:
        Filtered schema dict with only relevant tables.
    """
    if not schema:
        return schema

    question_emb = _embed(question)

    # If embedding fails, return full schema as fallback
    if question_emb is None:
        logger.warning("schema_filter: embedding failed, returning full schema")
        return schema

    scored = []
    for table_name, table_info in schema.items():
        # Build a description of the table from its columns
        col_descriptions = ", ".join(
            col["name"] for col in table_info["columns"]
        )
        table_description = f"Table {table_name}: {col_descriptions}"

        table_emb = _embed(table_description)
        if table_emb is None:
            # Can't score this table — include it to be safe
            scored.append((1.0, table_name, table_info))
            continue

        score = _cosine_similarity(question_emb, table_emb)
        scored.append((score, table_name, table_info))

    # Sort by similarity descending
    scored.sort(key=lambda x: x[0], reverse=True)

    # Apply threshold, then cap
    relevant = [
        (name, info)
        for score, name, info in scored
        if score >= threshold
    ]

    # Always include at least the top table even if below threshold
    if not relevant:
        _, top_name, top_info = scored[0]
        relevant = [(top_name, top_info)]

    relevant = relevant[:max_tables]

    return {name: info for name, info in relevant}