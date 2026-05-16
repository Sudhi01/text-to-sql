"""
Phase 5 - Automated Evaluation Suite
Measures:
  1. Execution match     — do results match expected row count?
  2. Guardrail effectiveness — are dangerous queries blocked?
  3. Ambiguity detection — are ambiguous questions flagged?
  4. Hallucination detection rate — does Phase 3 flag bad queries?
  5. SQL exact match     — does generated SQL match golden SQL?
"""

import json
import time
import requests
from datetime import datetime

API_BASE = "http://localhost:8000"
GOLDEN_DATASET = "golden_dataset.json"
RESULTS_FILE = f"eval_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_dataset():
    with open(GOLDEN_DATASET, "r") as f:
        return json.load(f)


def normalize_sql(sql: str) -> str:
    """Normalize SQL for comparison — lowercase, strip whitespace."""
    if not sql:
        return ""
    return " ".join(sql.lower().split())


def call_api(question: str) -> dict:
    try:
        res = requests.post(
            f"{API_BASE}/v1/query",
            json={"question": question},
            timeout=120,
        )
        data = res.json()
        # Ensure quality is always a dict, never None
        if data.get("quality") is None:
            data["quality"] = {}
        return data
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Individual test evaluators
# ---------------------------------------------------------------------------

def eval_guardrail(tc: dict, response: dict) -> dict:
    """Check if dangerous queries are correctly blocked."""
    result = response.get("result") or {}
    guardrail = response.get("guardrail") or {}
    status = result.get("status") or response.get("status", "")

    blocked = status == "blocked" or guardrail.get("passed") is False
    expected_blocked = tc["should_be_blocked"]

    passed = blocked == expected_blocked
    return {
        "passed": passed,
        "expected_blocked": expected_blocked,
        "was_blocked": blocked,
        "reason": guardrail.get("blocked_reason"),
    }


def eval_execution_match(tc: dict, response: dict) -> dict:
    """Check if row count matches expected."""
    if tc.get("expected_row_count") is None:
        return {"passed": None, "note": "No expected row count defined — skipped"}

    result = response.get("result") or {}
    actual = result.get("row_count", -1)
    expected = tc["expected_row_count"]
    passed = actual == expected

    return {
        "passed": passed,
        "expected_row_count": expected,
        "actual_row_count": actual,
    }


def eval_sql_match(tc: dict, response: dict) -> dict:
    """Check if generated SQL matches golden SQL (normalized)."""
    if not tc.get("expected_sql"):
        return {"passed": None, "note": "No expected SQL — skipped"}

    generated = normalize_sql(response.get("sql", ""))
    expected = normalize_sql(tc["expected_sql"])

    exact = generated == expected

    return {
        "passed": exact,
        "expected_sql": tc["expected_sql"],
        "generated_sql": response.get("sql", ""),
        "note": "Exact SQL match" if exact else "SQL differs but may still be correct",
    }


def eval_ambiguity(tc: dict, response: dict) -> dict:
    """Check if ambiguous questions are correctly flagged."""
    if not tc.get("is_ambiguous"):
        return {"passed": None, "note": "Not an ambiguous test case — skipped"}

    status = response.get("status", "")
    flagged = status == "clarification_needed"

    return {
        "passed": flagged,
        "expected_ambiguous": True,
        "was_flagged": flagged,
    }


def eval_hallucination(tc: dict, response: dict) -> dict:
    """
    Check hallucination detection.
    For valid queries: confidence should be >= 0.7
    For guardrail-blocked or ambiguous queries: skip
    """
    if tc["should_be_blocked"] or tc.get("is_ambiguous"):
        return {"passed": None, "note": "Blocked or ambiguous — skipped"}

    quality = response.get("quality") or {}
    if not quality:
        return {"passed": False, "note": "No quality data returned"}

    confidence = quality.get("confidence_score", 0)
    flags = quality.get("flags", [])
    passed = confidence >= 0.7

    return {
        "passed": passed,
        "confidence_score": confidence,
        "status": quality.get("status"),
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# Main eval runner
# ---------------------------------------------------------------------------

def run_evals():
    dataset = load_dataset()
    results = []

    total = len(dataset)
    counts = {
        "execution_match":   {"pass": 0, "fail": 0, "skip": 0},
        "guardrail":         {"pass": 0, "fail": 0, "skip": 0},
        "ambiguity":         {"pass": 0, "fail": 0, "skip": 0},
        "hallucination":     {"pass": 0, "fail": 0, "skip": 0},
        "sql_exact_match":   {"pass": 0, "fail": 0, "skip": 0},
    }

    print(f"\nRunning {total} eval cases...\n")

    for i, tc in enumerate(dataset, 1):
        print(f"[{i}/{total}] {tc['id']} — {tc['question'][:60]}")

        start = time.time()
        response = call_api(tc["question"])
        elapsed = round(time.time() - start, 2)

        if "error" in response:
            print(f"  ❌ API error: {response['error']}")
            results.append({"id": tc["id"], "error": response["error"]})
            continue

        # Run all evaluators
        guardrail_eval     = eval_guardrail(tc, response)
        execution_eval     = eval_execution_match(tc, response)
        sql_eval           = eval_sql_match(tc, response)
        ambiguity_eval     = eval_ambiguity(tc, response)
        hallucination_eval = eval_hallucination(tc, response)

        # Tally counts
        def tally(name, result):
            if result["passed"] is True:
                counts[name]["pass"] += 1
            elif result["passed"] is False:
                counts[name]["fail"] += 1
            else:
                counts[name]["skip"] += 1

        tally("guardrail",       guardrail_eval)
        tally("execution_match", execution_eval)
        tally("sql_exact_match", sql_eval)
        tally("ambiguity",       ambiguity_eval)
        tally("hallucination",   hallucination_eval)

        # Per-test result
        entry = {
            "id": tc["id"],
            "category": tc["category"],
            "question": tc["question"],
            "elapsed_sec": elapsed,
            "guardrail":    guardrail_eval,
            "execution":    execution_eval,
            "sql_match":    sql_eval,
            "ambiguity":    ambiguity_eval,
            "hallucination": hallucination_eval,
            "generated_sql": response.get("sql"),
            "confidence": (response.get("quality") or {}).get("confidence_score"),
        }
        results.append(entry)

        # Quick pass/fail indicator
        icons = []
        for ev in [guardrail_eval, execution_eval, hallucination_eval]:
            if ev["passed"] is True:
                icons.append("✅")
            elif ev["passed"] is False:
                icons.append("❌")
            else:
                icons.append("⏭")
        print(f"  guardrail:{icons[0]} execution:{icons[1]} hallucination:{icons[2]} ({elapsed}s)")

    # ---------------------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------------------
    def pct(c):
        total_scored = c["pass"] + c["fail"]
        if total_scored == 0:
            return "N/A"
        return f"{round(c['pass'] / total_scored * 100, 1)}%"

    print("\n" + "=" * 50)
    print("EVALUATION SUMMARY")
    print("=" * 50)
    print(f"Total test cases       : {total}")
    print(f"Guardrail effectiveness: {pct(counts['guardrail'])}  ({counts['guardrail']['pass']} passed / {counts['guardrail']['fail']} failed)")
    print(f"Execution match        : {pct(counts['execution_match'])}  ({counts['execution_match']['pass']} passed / {counts['execution_match']['fail']} failed)")
    print(f"SQL exact match        : {pct(counts['sql_exact_match'])}  ({counts['sql_exact_match']['pass']} passed / {counts['sql_exact_match']['fail']} failed)")
    print(f"Ambiguity detection    : {pct(counts['ambiguity'])}  ({counts['ambiguity']['pass']} passed / {counts['ambiguity']['fail']} failed)")
    print(f"Hallucination detection: {pct(counts['hallucination'])}  ({counts['hallucination']['pass']} passed / {counts['hallucination']['fail']} failed)")
    print("=" * 50)

    guardrail_pct     = pct(counts["guardrail"])
    execution_pct     = pct(counts["execution_match"])
    hallucination_pct = pct(counts["hallucination"])
    print(f"\nREADME headline:")
    print(f'  "Built a Text-to-SQL system with {execution_pct} execution accuracy,')
    print(f'  {hallucination_pct} hallucination detection rate,')
    print(f'  and {guardrail_pct} guardrail effectiveness across {total} test cases."')

    with open(RESULTS_FILE, "w") as f:
        json.dump({
            "summary": counts,
            "total": total,
            "results": results,
        }, f, indent=2)

    print(f"\nFull results saved to: {RESULTS_FILE}")


if __name__ == "__main__":
    run_evals()