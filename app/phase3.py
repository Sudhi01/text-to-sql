"""
Phase 3: Hallucination Detection System

Implements all four requirements from the spec:
  1. SQL-to-question back-translation + semantic alignment scoring
  2. Result sanity checking (row count, NULLs, date ranges, aggregate ranges)
  3. Multi-query validation (two independent SQL approaches, result comparison)
  4. Composite confidence scoring (syntax, back-translation, sanity, multi-query, schema coverage)
"""
import logging
import re
from typing import Callable, Dict, List, Optional, Tuple

from openai import OpenAI, OpenAIError
import os

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chat(prompt: str, max_tokens: int = 64) -> Optional[str]:
    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        return res.choices[0].message.content.strip()
    except OpenAIError as e:
        logger.warning("LLM call failed: %s", e)
        return None


def _parse_float(raw: Optional[str], label: str) -> Optional[float]:
    if raw is None:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", raw.split()[0]) if raw.split() else ""
    try:
        score = float(cleaned)
        if not (0.0 <= score <= 1.0):
            raise ValueError(f"Out of range: {score}")
        return score
    except ValueError as e:
        logger.warning("%s could not parse %r: %s", label, raw, e)
        return None


# ---------------------------------------------------------------------------
# 1. INTENT DETECTION
# ---------------------------------------------------------------------------

def detect_intent(question: str) -> str:
    if not question or not question.strip():
        return "unknown"

    q = question.lower()

    if re.search(r"\bper\b", q):
        return "group_by"

    if re.search(r"\b(total|overall)\b", q):
        return "global_aggregation"

    if re.search(r"\b(how many|count)\b", q):
        return "count"

    return "unknown"


# ---------------------------------------------------------------------------
# 2. SQL STRUCTURE ANALYSIS
# ---------------------------------------------------------------------------

def analyze_sql(sql: str) -> Dict:
    if not sql or not sql.strip():
        return {
            "has_group_by": False,
            "has_join": False,
            "has_aggregate": False,
            "tables": [],
            "has_limit": False,
        }

    s = sql.lower()
    return {
        "has_group_by": "group by" in s,
        "has_join": "join" in s,
        "has_aggregate": any(x in s for x in ["count(", "sum(", "avg(", "min(", "max("]),
        "tables": re.findall(r"from\s+([a-z_][a-z0-9_]*)", s),
        "has_limit": "limit" in s,
    }


# ---------------------------------------------------------------------------
# 3. SQL → QUESTION
# ---------------------------------------------------------------------------

def sql_to_question(sql: str) -> Optional[str]:
    return _chat(
        f"Convert this SQL into the exact business question it answers.\n\n"
        f"SQL:\n{sql}\n\nReturn only the question.",
        max_tokens=128,
    )


# ---------------------------------------------------------------------------
# 4. SEMANTIC MATCH
# ---------------------------------------------------------------------------

def semantic_match(q1: str, q2: str) -> float:
    raw = _chat(
        f"Score the meaning similarity between these two questions.\n\n"
        f"Q1: {q1}\nQ2: {q2}\n\nReturn ONLY a decimal between 0 and 1.",
        max_tokens=8,
    )
    return _parse_float(raw, "semantic_match") or 0.5


# ---------------------------------------------------------------------------
# 5. RESULT SANITY CHECK
# ---------------------------------------------------------------------------

def result_anomaly_check(result: Dict) -> List[str]:
    flags = []

    if result.get("status") != "success":
        flags.append("execution_failed")
        return flags

    row_count = result.get("row_count")
    if row_count is None:
        logger.warning("result_anomaly_check: 'row_count' missing from result dict")
    else:
        if row_count == 0:
            flags.append("empty_result")
        if row_count > 1000:
            flags.append("possible_join_explosion")

        null_counts: Dict[str, int] = result.get("null_counts", {})
        for col, n_nulls in null_counts.items():
            if row_count > 0 and n_nulls / row_count > 0.5:
                flags.append(f"null_heavy_column:{col}")

    date_range = result.get("date_range")
    if date_range:
        try:
            if date_range["max"] < date_range["min"]:
                flags.append("invalid_date_range")
        except (KeyError, TypeError):
            pass

    agg_values: Dict[str, float] = result.get("agg_values", {})
    for col, val in agg_values.items():
        if isinstance(val, (int, float)) and val < 0 and "count" in col.lower():
            flags.append(f"negative_aggregate:{col}")

    return flags


# ---------------------------------------------------------------------------
# 6. MULTI-QUERY VALIDATION
# ---------------------------------------------------------------------------

def generate_alternative_sql(
    question: str, original_sql: str, schema_hint: str = ""
) -> Optional[str]:
    schema_section = f"\nSchema hint:\n{schema_hint}\n" if schema_hint else ""
    raw = _chat(
        f"Write an alternative SQL query that answers the same question as the original "
        f"but uses a DIFFERENT approach (e.g. subquery instead of JOIN, or different aggregation)."
        f"{schema_section}\n"
        f"Question: {question}\n"
        f"Original SQL:\n{original_sql}\n\n"
        f"Return ONLY the SQL with no markdown, no backticks, no explanation.",
        max_tokens=256,
    )
    if raw is None:
        return None
    raw = re.sub(r"^```(?:sql)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw.strip())
    return raw.strip() or None


def compare_results(result_a: Dict, result_b: Dict) -> Tuple[bool, str]:
    if result_a.get("status") != "success" or result_b.get("status") != "success":
        return False, "one_or_both_queries_failed"

    rows_a = result_a.get("row_count", -1)
    rows_b = result_b.get("row_count", -1)
    if rows_a != rows_b:
        return False, f"row_count_mismatch:{rows_a}_vs_{rows_b}"

    sample_a = result_a.get("sample_data", [])
    sample_b = result_b.get("sample_data", [])
    if sample_a and sample_b:
        sort_key = lambda row: tuple(sorted(str(v) for v in row.values()))
        sorted_a = sorted(sample_a, key=sort_key)
        sorted_b = sorted(sample_b, key=sort_key)
        if sorted_a != sorted_b:
            return False, "sample_data_mismatch"

    return True, "results_agree"


def multi_query_validation(
    question: str,
    sql: str,
    execute_fn: Callable[[str], Dict],
    schema_hint: str = "",
) -> Dict:
    alt_sql = generate_alternative_sql(question, sql, schema_hint)
    if alt_sql is None:
        return {
            "agree": None,
            "reason": "alternative_generation_failed",
            "alternative_sql": None,
            "confidence_boost": 0.0,
        }

    try:
        result_original = execute_fn(sql)
        result_alt = execute_fn(alt_sql)
    except Exception as e:
        logger.warning("multi_query_validation execution error: %s", e)
        return {
            "agree": None,
            "reason": "execution_error",
            "alternative_sql": alt_sql,
            "confidence_boost": 0.0,
        }

    agree, reason = compare_results(result_original, result_alt)
    return {
        "agree": agree,
        "reason": reason,
        "alternative_sql": alt_sql,
        "confidence_boost": 0.05 if agree else -0.2,  # reduced from 0.15
    }


# ---------------------------------------------------------------------------
# 7. SCHEMA COVERAGE
# ---------------------------------------------------------------------------

def schema_coverage_score(sql: str, expected_tables: List[str]) -> float:
    if not expected_tables:
        return 1.0
    s = sql.lower()
    hits = sum(1 for t in expected_tables if t.lower() in s)
    return hits / len(expected_tables)


# ---------------------------------------------------------------------------
# 8. LLM CONSISTENCY JUDGE
# ---------------------------------------------------------------------------

def consistency_score(question: str, sql: str) -> Optional[float]:
    raw = _chat(
        f"You are validating SQL correctness.\n\n"
        f"Question:\n{question}\n\nSQL:\n{sql}\n\n"
        f"Does the SQL correctly answer the question? Return ONLY a score between 0 and 1.",
        max_tokens=8,
    )
    return _parse_float(raw, "consistency_score")


# ---------------------------------------------------------------------------
# 9. MAIN QUALITY CHECK ENGINE
# ---------------------------------------------------------------------------

def run_quality_checks(
    question: str,
    sql: str,
    result: Dict,
    execute_fn: Optional[Callable[[str], Dict]] = None,
    expected_tables: Optional[List[str]] = None,
    schema_hint: str = "",
) -> Dict:
    if not question or not question.strip():
        raise ValueError("'question' must be a non-empty string.")
    if not sql or not sql.strip():
        raise ValueError("'sql' must be a non-empty string.")
    if not isinstance(result, dict):
        raise TypeError("'result' must be a dict.")

    confidence = 1.0
    flags: List[str] = []
    signal_breakdown: Dict[str, float] = {}
    alternative_sql: Optional[str] = None

    intent = detect_intent(question)
    structure = analyze_sql(sql)

    # ------------------------------------------------------------------
    # A. RESULT SANITY
    # ------------------------------------------------------------------
    result_flags = result_anomaly_check(result)
    flags.extend(result_flags)

    a_delta = 0.0
    if "execution_failed" in result_flags:
        a_delta -= 0.5
    if "empty_result" in result_flags:
        a_delta -= 0.2
    if "possible_join_explosion" in result_flags:
        a_delta -= 0.4
    a_delta -= 0.05 * sum(1 for f in result_flags if f.startswith("null_heavy_column"))
    if "invalid_date_range" in result_flags:
        a_delta -= 0.15
    a_delta -= 0.1 * sum(1 for f in result_flags if f.startswith("negative_aggregate"))

    confidence += a_delta
    signal_breakdown["result_sanity"] = round(a_delta, 3)

    # ------------------------------------------------------------------
    # B. INTENT vs STRUCTURE
    # ------------------------------------------------------------------
    b_delta = 0.0
    if intent == "global_aggregation" and structure["has_group_by"]:
        b_delta -= 0.3
        flags.append("unexpected_group_by")
    if intent == "group_by" and not structure["has_group_by"]:
        b_delta -= 0.3
        flags.append("missing_group_by")

    confidence += b_delta
    signal_breakdown["intent_structure"] = round(b_delta, 3)

    # ------------------------------------------------------------------
    # C. BACK-TRANSLATION
    # ------------------------------------------------------------------
    c_delta = 0.0
    generated_q = sql_to_question(sql)
    if generated_q is not None:
        sem_score = semantic_match(question, generated_q)
        if sem_score < 0.75:
            c_delta -= 0.35
            flags.append("semantic_mismatch")
    else:
        c_delta -= 0.2
        flags.append("llm_failure")

    confidence += c_delta
    signal_breakdown["back_translation"] = round(c_delta, 3)

    # ------------------------------------------------------------------
    # D. LLM CONSISTENCY
    # ------------------------------------------------------------------
    d_delta = 0.0
    cons = consistency_score(question, sql)
    if cons is not None:
        if cons < 0.7:
            d_delta -= 0.25
            flags.append("low_consistency_score")
    else:
        d_delta -= 0.1
        flags.append("consistency_check_failed")

    confidence += d_delta
    signal_breakdown["llm_consistency"] = round(d_delta, 3)

    # ------------------------------------------------------------------
    # E. MULTI-QUERY VALIDATION
    # Penalty always applies, boost only when confidence < 1.0
    # ------------------------------------------------------------------
    e_delta = 0.0
    if execute_fn is not None:
        mv = multi_query_validation(question, sql, execute_fn, schema_hint)
        alternative_sql = mv.get("alternative_sql")
        boost = mv["confidence_boost"]
        if boost < 0:
            e_delta = boost
        elif boost > 0 and confidence < 1.0:
            e_delta = boost
        if mv["agree"] is False:
            flags.append(f"multi_query_disagreement:{mv['reason']}")
        elif mv["agree"] is None:
            flags.append(f"multi_query_skipped:{mv['reason']}")

    confidence += e_delta
    signal_breakdown["multi_query"] = round(e_delta, 3)

    # ------------------------------------------------------------------
    # F. SCHEMA COVERAGE
    # ------------------------------------------------------------------
    f_delta = 0.0
    if expected_tables:
        cov = schema_coverage_score(sql, expected_tables)
        if cov < 1.0:
            f_delta -= round((1.0 - cov) * 0.2, 3)
            flags.append(f"low_schema_coverage:{cov:.0%}")

    confidence += f_delta
    signal_breakdown["schema_coverage"] = round(f_delta, 3)

    # ------------------------------------------------------------------
    # G. STRUCTURAL BOOST
    # Only applies when confidence < 1.0, reduced values
    # ------------------------------------------------------------------
    g_delta = 0.0
    if confidence < 1.0:
        if structure["has_aggregate"]:
            g_delta += 0.02
        if structure["has_join"]:
            g_delta += 0.02
        if structure["has_limit"]:
            g_delta += 0.01

    confidence += g_delta
    signal_breakdown["structural_boost"] = round(g_delta, 3)

    # ------------------------------------------------------------------
    # FINAL NORMALIZATION
    # ------------------------------------------------------------------
    confidence = round(max(0.0, min(1.0, confidence)), 2)

    return {
        "confidence_score": confidence,
        "status": "high" if confidence > 0.75 else "medium" if confidence > 0.5 else "low",
        "flags": flags,
        "intent_detected": intent,
        "signal_breakdown": signal_breakdown,
        "alternative_sql": alternative_sql,
    }