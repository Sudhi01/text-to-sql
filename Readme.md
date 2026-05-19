 Text-to-SQL Interface with Guardrails and Hallucination Detection

I built a natural language interface that converts plain English questions into SQL queries, executes them safely against a real PostgreSQL database, and validates that the generated SQL actually answers what was asked.

The system blocks 100% of destructive operations, detects ambiguous questions before generating SQL, and uses a multi-signal confidence scoring system to catch hallucinated queries.

Live demo: https://sudhi01-text-to-sql-ui.hf.space  
API: https://goldfish-app-efei5.ondigitalocean.app/docs

---

 What it does

Type a question like "total orders per customer" and the system:
1. Extracts the database schema automatically
2. Filters only the relevant tables
3. Checks if the question is ambiguous — if so, asks for clarification
4. Generates SQL with an explanation and confidence score
5. Runs the query in a read-only sandbox
6. Validates the result using two independent SQL approaches
7. Returns the result with a confidence score and flags

---

 Screenshots

 ### Asking a question and getting results
 ![Demo](https://raw.githubusercontent.com/Sudhi01/text-to-sql/main/assests/Screenshots/demo.png)



### Guardrail blocking a dangerous query
![Guardrail](https://raw.githubusercontent.com/Sudhi01/text-to-sql/main/assests/Screenshots/guardrail.png)

### Ambiguity detection — asking for clarification instead of guessing
![Ambiguity](https://raw.githubusercontent.com/Sudhi01/text-to-sql/main/assests/Screenshots/ambiguity.png)

### API endpoints
![API](https://raw.githubusercontent.com/Sudhi01/text-to-sql/main/assests/Screenshots/api.png)

### Multi-query validation — two SQL approaches returning the same result
![Multi Query](https://raw.githubusercontent.com/Sudhi01/text-to-sql/main/assests/Screenshots/multiquery.png)
---

## Eval results

I ran 50 automated test cases covering simple lookups, multi-table JOINs, aggregations, date filters, ambiguous questions, and guardrail attacks.

| Metric | Result |
|---|---|
| Execution accuracy | 78.1% |
| Hallucination detection | 65% |
| Ambiguity detection | 100% |
| Guardrail effectiveness | 96% |
| Destructive operations executed | 0 |

---

## Safety layer

Before any query runs, it goes through a guardrail middleware that blocks:

- DDL statements (DROP, CREATE, ALTER)
- DML writes (INSERT, UPDATE, DELETE)
- SQL comment injection
- Subqueries deeper than 3 levels
- Queries estimated to scan more than 100,000 rows

Every blocked query is logged with the reason for compliance.

---

## Hallucination detection

The system validates every query from multiple angles before showing the result:

- Back-translation — sends the SQL back to the LLM and asks "what question does this answer?" then compares with the original
- Result sanity — checks for empty results, NULL-heavy columns, and impossible values
- Multi-query validation — generates a second SQL using a different approach and checks if both return the same data
- LLM consistency — asks the LLM to score whether the SQL correctly answers the question

All signals are combined into a single confidence score displayed prominently with every result.

---

## Tech stack

- Python 3.11, FastAPI, Streamlit
- PostgreSQL (Supabase), SQLAlchemy
- OpenAI GPT-4o-mini
- sqlparse for AST-based SQL validation
- Docker + docker-compose
- Deployed on DigitalOcean + Hugging Face

---

## Running locally

```bash
git clone https://github.com/Sudhi01/text-to-sql.git
cd text-to-sql

export OPENAI_API_KEY=sk-...
export DATABASE_URL=postgresql://...

docker-compose up --build
```

API runs on `http://localhost:8000/docs`  
UI runs on `http://localhost:8501`

---

## Things to try

Normal queries:

total orders per customer
top 3 customers by revenue
how many orders has Alice placed
average order amount per country

Guardrail tests:

DROP TABLE orders
DELETE FROM customers
UPDATE orders SET amount = 0

Ambiguity tests:

show me the top revenue
what is the best performance
show recent sales

