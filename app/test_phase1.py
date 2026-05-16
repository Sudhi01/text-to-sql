from db import engine
from llm import generate_sql

# ----------------------------
# Test 1: Simple clear question
# ----------------------------
print("\n====== TEST 1: Clear Question ======")
result = generate_sql("total orders per customer", engine)

print(f"SQL         : {result.sql}")
print(f"Explanation : {result.explanation}")
print(f"Confidence  : {result.confidence}")
print(f"Tables Used : {result.tables_used}")
print(f"Columns Used: {result.columns_used}")
print(f"Needs Clarification: {result.clarification_needed}")

# ----------------------------
# Test 2: Ambiguous question
# ----------------------------
print("\n====== TEST 2: Ambiguous Question ======")
result2 = generate_sql("show me the top revenue", engine)

if result2.clarification_needed:
    print("Clarification needed!")
    print(f"Message: {result2.clarification.message}")
    for i, interp in enumerate(result2.clarification.interpretations, 1):
        print(f"\n  Option {i}: {interp.label}")
        print(f"  Description: {interp.description}")
        print(f"  SQL: {interp.example_sql}")
else:
    print(f"SQL: {result2.sql}")

# ----------------------------
# Test 3: Schema filtering
# ----------------------------
print("\n====== TEST 3: Schema Filtering ======")
from db import engine
from schema import get_schema, format_schema_for_prompt
from schema_filter import filter_relevant_tables

full_schema = get_schema(engine)
print(f"Total tables in DB   : {len(full_schema)}")

filtered = filter_relevant_tables("total orders per customer", full_schema)
print(f"Tables after filter  : {list(filtered.keys())}")

print("\nFormatted schema sent to LLM:")
print(format_schema_for_prompt(filtered))