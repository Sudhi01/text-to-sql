"""
app.py — Streamlit Frontend
Phase 4: Full UI with:
  - Auto SQL generation from question (Phase 1)
  - Editable SQL before execution
  - Tabs layout (Results / Quality / History)
  - Feedback buttons (Correct / Incorrect)
  - History panel
  - Multi-query validation
  - Guardrail warnings
"""

import streamlit as st
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
API_BASE = "https://sudhi01-text-to-sql.hf.space"

st.set_page_config(page_title="Text-to-SQL", layout="wide")
st.title("Text-to-SQL Interface")

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "history" not in st.session_state:
    st.session_state.history = []

if "generated_sql" not in st.session_state:
    st.session_state.generated_sql = ""

if "last_query_id" not in st.session_state:
    st.session_state.last_query_id = None

if "last_output" not in st.session_state:
    st.session_state.last_output = None


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_query, tab_history, tab_schema = st.tabs(["Query", "History", "Schema"])


# ===========================================================================
# TAB 1: QUERY
# ===========================================================================
with tab_query:

    col_left, col_right = st.columns([2, 1])

    with col_left:
        question = st.text_input(
            "Ask a question in plain English",
            placeholder="e.g. total orders per customer",
        )

        generate_btn = st.button("Generate SQL", type="secondary")

        # Auto-generate SQL from question via API
        if generate_btn and question:
            with st.spinner("Generating SQL..."):
                try:
                    res = requests.post(
                        f"{API_BASE}/v1/query",
                        json={"question": question},
                        timeout=60,
                    )
                    data = res.json()

                    # Ambiguity — show clarification options
                    if data.get("status") == "clarification_needed":
                        st.warning(data["message"])
                        for i, opt in enumerate(data["interpretations"], 1):
                            st.info(
                                f"**Option {i}: {opt['label']}**\n\n"
                                f"{opt['description']}\n\n"
                                f"```sql\n{opt['example_sql']}\n```"
                            )
                        st.stop()

                    st.session_state.generated_sql = data.get("sql", "")
                    st.session_state.last_query_id = data.get("query_id")
                    st.session_state.last_output = data
                    st.session_state.history.insert(0, data)

                except requests.exceptions.ConnectionError:
                    st.error("Cannot connect to API. Make sure FastAPI is running on port 8000.")

        # Editable SQL box — power users can modify before running
        sql = st.text_area(
            "SQL Query (editable)",
            value=st.session_state.generated_sql,
            height=150,
            placeholder="SQL will appear here after generation, or paste your own...",
        )

        expected_tables = st.text_input(
            "Expected Tables (comma separated, optional)",
            placeholder="e.g. customers, orders",
        )

        run_btn = st.button("Run & Validate", type="primary")

    with col_right:
        st.markdown("### How to use")
        st.markdown(
            "1. Type your question\n"
            "2. Click **Generate SQL**\n"
            "3. Edit the SQL if needed\n"
            "4. Click **Run & Validate**\n"
            "5. Mark result as ✅ Correct or ❌ Incorrect"
        )

    # -----------------------------------------------------------------------
    # Run & Validate
    # -----------------------------------------------------------------------
    if run_btn and question and sql:

        tables = [t.strip() for t in expected_tables.split(",")] if expected_tables else []

        with st.spinner("Running query and validating..."):
            try:
                res = requests.post(
                    f"{API_BASE}/v1/query",
                    json={"question": question, "expected_tables": tables or None},
                    timeout=120,
                )
                data = res.json()
                st.session_state.last_query_id = data.get("query_id")
                st.session_state.last_output = data
                st.session_state.history.insert(0, data)

            except requests.exceptions.ConnectionError:
                st.error("Cannot connect to API. Make sure FastAPI is running on port 8000.")
                st.stop()

        output = st.session_state.last_output
        result = output.get("result", {})
        quality = output.get("quality", {})
        guardrail = output.get("guardrail", {})

        # Blocked
        if result.get("status") == "blocked":
            st.error(f"🚫 Query blocked: {guardrail.get('blocked_reason')}")
            st.stop()

        # Error
        if result.get("status") == "error":
            st.error(f"❌ Query error: {result.get('error')}")
            st.stop()

        # Guardrail warnings
        for warning in guardrail.get("warnings", []):
            st.warning(f"⚠️ {warning}")

        # -------------------------------------------------------------------
        # Metrics row
        # -------------------------------------------------------------------
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Rows Returned", result.get("row_count", 0))
        c2.metric("Execution Time", f"{result.get('execution_time', 0)}s")
        c3.metric("Confidence Score", quality.get("confidence_score", "—"))
        conf_status = quality.get("status", "")
        c4.metric("Status", conf_status.upper() if conf_status else "—")

        # Confidence badge
        if conf_status == "high":
            st.success(f"✅ Confidence: HIGH ({quality.get('confidence_score')})")
        elif conf_status == "medium":
            st.warning(f"⚠️ Confidence: MEDIUM ({quality.get('confidence_score')})")
        elif conf_status == "low":
            st.error(f"❌ Confidence: LOW ({quality.get('confidence_score')})")

        # -------------------------------------------------------------------
        # Results table
        # -------------------------------------------------------------------
        st.subheader("Query Results")
        st.dataframe(result.get("data", []), use_container_width=True)

        # -------------------------------------------------------------------
        # Flags
        # -------------------------------------------------------------------
        flags = quality.get("flags", [])
        if flags:
            st.subheader("Flags")
            for flag in flags:
                st.warning(f"⚠️ {flag}")
        else:
            st.info("✅ No flags — query looks correct")

        # -------------------------------------------------------------------
        # Signal breakdown
        # -------------------------------------------------------------------
        st.subheader("Confidence Signal Breakdown")
        breakdown = quality.get("signal_breakdown", {})
        if breakdown:
            cols = st.columns(len(breakdown))
            for col, (signal, value) in zip(cols, breakdown.items()):
                col.metric(
                    label=signal.replace("_", " ").title(),
                    value=f"{value:+.2f}",
                    delta=value,
                    delta_color="normal",
                )

        # -------------------------------------------------------------------
        # Multi-query validation
        # -------------------------------------------------------------------
        st.subheader("Multi-Query Validation")
        alt_sql = quality.get("alternative_sql")
        multi_score = breakdown.get("multi_query", 0)

        if alt_sql:
            if multi_score > 0:
                st.success("✅ Both SQL approaches returned the same result")
            else:
                st.error("❌ The two SQL approaches returned different results — review carefully")

            with st.expander("View Alternative SQL"):
                st.code(alt_sql, language="sql")
        else:
            st.info("Alternative SQL was not generated")

        # -------------------------------------------------------------------
        # EXPLAIN plan
        # -------------------------------------------------------------------
        with st.expander("View EXPLAIN Plan"):
            for line in result.get("explain_plan", []):
                st.text(line)

        # -------------------------------------------------------------------
        # Feedback buttons
        # -------------------------------------------------------------------
        st.subheader("Was this result correct?")
        query_id = st.session_state.last_query_id
        fb_col1, fb_col2 = st.columns(2)

        with fb_col1:
            if st.button("✅ Correct", use_container_width=True):
                _send_feedback(query_id, correct=True)

        with fb_col2:
            if st.button("❌ Incorrect", use_container_width=True):
                _send_feedback(query_id, correct=False)


# ===========================================================================
# TAB 2: HISTORY
# ===========================================================================
with tab_history:
    st.subheader("Query History")

    if not st.session_state.history:
        st.info("No queries yet — run a query to see history here.")
    else:
        for entry in st.session_state.history:
            quality = entry.get("quality") or {}
            conf = quality.get("confidence_score", "—")
            status = quality.get("status", "")
            feedback = entry.get("feedback")

            icon = "✅" if status == "high" else "⚠️" if status == "medium" else "❌"
            fb_icon = " 👍" if feedback and feedback["correct"] else " 👎" if feedback else ""

            with st.expander(f"{icon} {entry.get('question', '—')}  |  Confidence: {conf}{fb_icon}"):
                st.code(entry.get("sql", ""), language="sql")
                result = entry.get("result", {})
                st.write(f"Rows: {result.get('row_count', 0)} | Time: {result.get('execution_time', 0)}s")
                if feedback:
                    st.write(f"Feedback: {'✅ Correct' if feedback['correct'] else '❌ Incorrect'}")
                    if feedback.get("comment"):
                        st.write(f"Comment: {feedback['comment']}")


# ===========================================================================
# TAB 3: SCHEMA
# ===========================================================================
with tab_schema:
    st.subheader("Live Database Schema")

    if st.button("Load Schema"):
        try:
            res = requests.get(f"{API_BASE}/v1/schema", timeout=15)
            data = res.json()
            st.text(data.get("formatted", "No schema returned"))
        except requests.exceptions.ConnectionError:
            st.error("Cannot connect to API.")


# ===========================================================================
# Helper
# ===========================================================================
def _send_feedback(query_id: str, correct: bool, comment: str = ""):
    try:
        res = requests.post(
            f"{API_BASE}/v1/feedback",
            json={"query_id": query_id, "correct": correct, "comment": comment},
            timeout=15,
        )
        data = res.json()
        if correct:
            st.success(f"✅ {data['message']}")
        else:
            st.warning(f"📝 {data['message']}")
    except requests.exceptions.ConnectionError:
        st.error("Could not save feedback — API not reachable.")