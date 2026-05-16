"""
Phase 2 - Test Suite
Tests all guardrail scenarios:
  1. Valid SELECT — should pass + LIMIT injected
  2. DROP TABLE — should be blocked
  3. INSERT — should be blocked
  4. SQL injection via comment — should be blocked
  5. Deep subquery — should be blocked
  6. Valid query without LIMIT — LIMIT should be auto-injected
"""

from db import run_query

TESTS = [
    {
        "name": "Valid SELECT with GROUP BY",
        "question": "total orders per customer",
        "sql": "SELECT c.id, c.name, COUNT(o.id) AS total_orders FROM customers c LEFT JOIN orders o ON c.id = o.customer_id GROUP BY c.id, c.name",
        "expect": "success",
    },
    {
        "name": "DROP TABLE attack",
        "question": "drop the orders table",
        "sql": "DROP TABLE orders",
        "expect": "blocked",
    },
    {
        "name": "INSERT injection",
        "question": "add a new customer",
        "sql": "INSERT INTO customers (name) VALUES ('hacker')",
        "expect": "blocked",
    },
    {
        "name": "Comment injection",
        "question": "get all users",
        "sql": "SELECT * FROM customers -- DROP TABLE orders",
        "expect": "blocked",
    },
    {
        "name": "Deep subquery",
        "question": "nested query test",
        "sql": "SELECT * FROM (SELECT * FROM (SELECT * FROM (SELECT * FROM (SELECT * FROM customers)))) AS t",
        "expect": "blocked",
    },
    {
        "name": "SELECT without LIMIT — should auto-inject",
        "question": "list all customers",
        "sql": "SELECT * FROM customers",
        "expect": "success",
    },
    {
        "name": "UPDATE attempt",
        "question": "update customer name",
        "sql": "UPDATE customers SET name='hacker' WHERE id=1",
        "expect": "blocked",
    },
]


def run_tests():
    passed = 0
    failed = 0

    for test in TESTS:
        result = run_query(test["sql"], question=test["question"])
        status = result["status"]
        expected = test["expect"]

        ok = (
            (expected == "success" and status == "success") or
            (expected == "blocked" and status == "blocked")
        )

        icon = "✅" if ok else "❌"
        if ok:
            passed += 1
        else:
            failed += 1

        print(f"\n{icon} {test['name']}")
        print(f"   Expected : {expected}")
        print(f"   Got      : {status}")

        if status == "blocked":
            print(f"   Reason   : {result['guardrail']['blocked_reason']}")

        if status == "success":
            print(f"   SQL      : {result['sql']}")
            print(f"   Rows     : {result['row_count']}")
            if result['guardrail']['warnings']:
                print(f"   Warnings : {result['guardrail']['warnings']}")

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"Audit log written to: audit.log")


if __name__ == "__main__":
    run_tests()