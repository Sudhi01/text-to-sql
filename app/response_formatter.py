def format_response(sql, db_result):
    """
    Converts raw DB output into clean structured response
    for frontend / API use
    """

    return {
        "query": sql,
        "status": db_result.get("status"),

        "data": db_result.get("data", []),
        "row_count": db_result.get("row_count", 0),

        "execution_time": db_result.get("execution_time", 0),

        "explain_plan": db_result.get("explain_plan", []),

        "guardrail_status": db_result.get("guardrails", "unknown"),

        "error": db_result.get("error"),
        "block_reason": db_result.get("reason")
    }