from app.llm import generate_sql
from app.db import run_query
from app.response_formatter import format_response

def main():
    question = "total orders per customer"

    print("\n🧠 QUESTION:")
    print(question)

    # Step 1: Generate SQL
    prompt = f"""
    Convert this question into SQL.

    Tables:
    customers(id, name)
    orders(id, customer_id, amount)

    Question: {question}
    """

    sql = generate_sql(prompt)

    print("\n🟢 GENERATED SQL:")
    print(sql)

    # Step 2: Execute SQL
    db_result = run_query(sql)

    # Step 3: Format response (NEW IMPROVEMENT)
    final_output = format_response(sql, db_result)

    # Step 4: Pretty output
    print("\n📊 FINAL RESPONSE:\n")

    print("STATUS:", final_output["status"])
    print("ROWS:", final_output["row_count"])
    print("TIME:", final_output["execution_time"], "sec")

    print("\n📄 DATA:")
    for row in final_output["data"]:
        print(row)

    print("\n🧠 EXPLAIN PLAN:")
    for line in final_output["explain_plan"]:
        print(line)


if __name__ == "__main__":
    main()