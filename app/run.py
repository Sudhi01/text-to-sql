import os
from db import run_query
from phase3 import run_quality_checks


# ----------------------------
# Wrap your run_query to match
# the shape execute_fn expects
# ----------------------------
def execute_fn(sql: str) -> dict:
    result = run_query(sql)
    return {
        "status": result.get("status"),
        "row_count": result.get("row_count", 0),
        "sample_data": result.get("data", [])[:5],  # first 5 rows for comparison
    }


# ----------------------------
# Your question + SQL
# ----------------------------
question = "total orders per customer"

sql = """
SELECT c.id AS customer_id, c.name, COUNT(o.id) AS total_orders
FROM customers c
LEFT JOIN orders o ON c.id = o.customer_id
GROUP BY c.id, c.name
"""

# Run it once to get the actual result
raw_result = run_query(sql)

result = {
    "status": raw_result.get("status"),
    "row_count": raw_result.get("row_count", 0),
    "sample_data": raw_result.get("data", [])[:5],
}


# ----------------------------
# Run all Phase 3 checks
# ----------------------------
output = run_quality_checks(
    question=question,
    sql=sql,
    result=result,
    execute_fn=execute_fn,                        # enables multi-query validation
    expected_tables=["customers", "orders"],      # enables schema coverage
)


# ----------------------------
# Print report
# ----------------------------
print("\n====== QUALITY REPORT ======")
print(f"Confidence Score : {output['confidence_score']}")
print(f"Status           : {output['status']}")
print(f"Intent Detected  : {output['intent_detected']}")
print(f"Flags            : {output['flags'] or 'none'}")
print("\n--- Signal Breakdown ---")
for signal, value in output['signal_breakdown'].items():
    print(f"  {signal:<25} {value:+.3f}")
print(f"\nAlternative SQL:\n{output['alternative_sql'] or 'not generated'}")