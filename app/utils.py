import re

def clean_sql(sql: str) -> str:
    # remove markdown code blocks
    sql = re.sub(r"```sql", "", sql)
    sql = re.sub(r"```", "", sql)

    return sql.strip()