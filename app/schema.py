"""
Phase 1 - Component 1: Schema Extractor
Extracts tables, columns, types, primary keys, foreign keys,
and sample values for categorical columns using SQLAlchemy.
"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def get_schema(engine: Engine, sample_limit: int = 5) -> dict:
    """
    Introspect the database and return a structured schema dict.

    Returns:
        {
            "table_name": {
                "columns": [
                    {
                        "name": str,
                        "type": str,
                        "primary_key": bool,
                        "nullable": bool,
                        "foreign_key": "other_table.other_col" | None,
                        "sample_values": [...]   # only for text columns
                    }
                ]
            }
        }
    """
    inspector = inspect(engine)
    schema = {}

    for table_name in inspector.get_table_names():

        # Primary keys
        pk_cols = set(
            inspector.get_pk_constraint(table_name).get("constrained_columns", [])
        )

        # Foreign keys — map local col → "referred_table.referred_col"
        fk_map = {}
        for fk in inspector.get_foreign_keys(table_name):
            for local_col, ref_col in zip(
                fk["constrained_columns"], fk["referred_columns"]
            ):
                fk_map[local_col] = f"{fk['referred_table']}.{ref_col}"

        columns = []
        with engine.connect() as conn:
            for col in inspector.get_columns(table_name):
                col_name = col["name"]
                col_type = str(col["type"])

                # Sample values only for text/categorical columns
                sample_values = []
                try:
                    if any(t in col_type.upper() for t in ("VARCHAR", "TEXT", "CHAR")):
                        rows = conn.execute(
                            text(
                                f'SELECT DISTINCT "{col_name}" '
                                f'FROM "{table_name}" '
                                f'WHERE "{col_name}" IS NOT NULL '
                                f'LIMIT :n'
                            ),
                            {"n": sample_limit},
                        ).fetchall()
                        sample_values = [str(r[0]) for r in rows]
                except Exception:
                    pass

                columns.append({
                    "name": col_name,
                    "type": col_type,
                    "primary_key": col_name in pk_cols,
                    "nullable": col.get("nullable", True),
                    "foreign_key": fk_map.get(col_name),
                    "sample_values": sample_values,
                })

        schema[table_name] = {"columns": columns}

    return schema


def format_schema_for_prompt(schema: dict) -> str:
    """
    Convert schema dict into a clean text block for LLM prompts.

    Example output:
        Table: customers
          - id (INTEGER) [PK]
          - name (VARCHAR)
          - email (VARCHAR) | samples: alice@x.com, bob@x.com

        Table: orders
          - id (INTEGER) [PK]
          - customer_id (INTEGER) [FK -> customers.id]
          - total (NUMERIC)
    """
    lines = []
    for table_name, table_info in schema.items():
        lines.append(f"Table: {table_name}")
        for col in table_info["columns"]:
            parts = [f"  - {col['name']} ({col['type']})"]
            if col["primary_key"]:
                parts.append("[PK]")
            if col["foreign_key"]:
                parts.append(f"[FK -> {col['foreign_key']}]")
            if col["sample_values"]:
                samples = ", ".join(col["sample_values"][:3])
                parts.append(f"| samples: {samples}")
            lines.append(" ".join(parts))
        lines.append("")  # blank line between tables
    return "\n".join(lines)