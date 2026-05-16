import streamlit as st
import requests
import pandas as pd

API_URL = "http://127.0.0.1:8000/query"

st.set_page_config(page_title="Text-to-SQL", layout="wide")

st.title("🧠 Text-to-SQL Interface with Guardrails & Hallucination Detection")

# ----------------------------
# SESSION STATE (history)
# ----------------------------
if "history" not in st.session_state:
    st.session_state.history = []

# ----------------------------
# INPUT BOX
# ----------------------------
question = st.text_input("Enter your question:", placeholder="e.g. total orders per customer")

if st.button("Generate SQL"):

    if not question:
        st.warning("Please enter a question")
    else:

        # call backend
        response = requests.post(API_URL, json={"question": question})

        if response.status_code == 200:
            data = response.json()

            st.session_state.history.append(data)

            # ----------------------------
            # DISPLAY RESULTS
            # ----------------------------
            st.subheader("🧾 Generated SQL")
            st.code(data.get("sql", ""), language="sql")

            st.subheader("📊 Results")

            result = data.get("result", {})

            if result.get("status") == "success":
                df = pd.DataFrame(result["data"])
                st.dataframe(df, use_container_width=True)

                st.write("Rows:", result.get("row_count"))
                st.write("Execution Time:", result.get("execution_time"), "s")

            else:
                st.error(result.get("message", "Error executing query"))

            # ----------------------------
            # CONFIDENCE (PHASE 3 OUTPUT)
            # ----------------------------
            if "quality" in data:
                st.subheader("🎯 Confidence Score")

                st.write("Score:", data["quality"].get("confidence_score"))
                st.write("Status:", data["quality"].get("status"))

                if data["quality"].get("flags"):
                    st.write("Flags:")
                    st.write(data["quality"]["flags"])

            # ----------------------------
            # GUARDRAILS
            # ----------------------------
            st.subheader("🛡 Guardrails")
            st.write(data.get("guardrails"))

        else:
            st.error("API Error")

# ----------------------------
# HISTORY PANEL
# ----------------------------
st.sidebar.title("📜 Query History")

for item in reversed(st.session_state.history[-10:]):
    st.sidebar.write("**Q:**", item.get("question"))
    st.sidebar.code(item.get("sql", ""), language="sql")