from app.schema import get_schema

def build_prompt(question: str):
    schema = get_schema()

    return f"""
You are a SQL expert.

Rules:
- Only generate PostgreSQL SELECT queries
- Use ONLY given schema
- Do NOT hallucinate columns
- Return ONLY SQL (no explanation)

Schema:
{schema}

Question:
{question}

SQL:
"""