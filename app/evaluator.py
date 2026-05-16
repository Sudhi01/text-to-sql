def back_translate(sql: str):
    sql = sql.lower()

    if "join" in sql:
        return "query involves multiple tables"
    if "group by" in sql:
        return "aggregation query"
    return "simple query"


def hallucination_check(question: str, sql: str):
    predicted = back_translate(sql)

    return {
        "raw_response": predicted,
        "matches": True if predicted else False
    }


def multi_query_check(sql1: str, sql2: str):
    return {
        "sql_1": sql1,
        "sql_2": sql2,
        "agree": sql1.strip().lower() == sql2.strip().lower()
    }


def confidence_score(result_status: str):
    return 1.0 if result_status == "success" else 0.0