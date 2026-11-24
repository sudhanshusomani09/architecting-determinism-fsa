"""Iteration 1 — Stage 6: GraphRAG Streamlit Prototype with Semantic Router.

Demonstrates the Neuro-Symbolic query pattern from Iteration 1:
  1. Queries Neo4j for valid FailureMode pathways bound to the selected Component.
  2. Uses a zero-temperature LLM strictly as a semantic router to map raw field
     text onto one of the deterministic FailureMode nodes.
  3. Traverses the graph to return locked Risk, Recommendation, and Standard fields.

Run locally (requires Neo4j + GEMINI_API_KEY in .env):
    streamlit run src/iteration1_graphrag/step6_agentic_ui.py
"""

from __future__ import annotations

import json
import os
from typing import Any

import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types
from neo4j import GraphDatabase

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI", "")
NEO4J_USER = os.getenv("NEO4J_USER", "")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")


@st.cache_resource
def init_clients() -> tuple[Any, genai.Client]:
    if not all([NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, GEMINI_API_KEY]):
        st.error(
            "Missing credentials. Set NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, "
            "and GEMINI_API_KEY in your .env file."
        )
        st.stop()
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
    return driver, ai_client


def get_components(driver: Any) -> list[str]:
    query = "MATCH (c:Component) RETURN c.name AS name ORDER BY name"
    with driver.session() as session:
        return [record["name"] for record in session.run(query)]


def get_failure_modes(driver: Any, component_name: str) -> list[str]:
    query = """
    MATCH (c:Component {name: $comp_name})-[:CAN_FAIL_DUE_TO]->(f:FailureMode)
    RETURN f.name AS name
    """
    with driver.session() as session:
        return [record["name"] for record in session.run(query, comp_name=component_name)]


def get_mitigation_data(
    driver: Any, component_name: str, failure_mode_name: str
) -> tuple[str | None, str | None, str | None, str | None]:
    query = """
    MATCH (c:Component {name: $comp_name})-[:CAN_FAIL_DUE_TO]->(f:FailureMode {name: $fail_name})
    MATCH (f)-[:TRIGGERS]->(m:MitigationRule)
    OPTIONAL MATCH (m)-[:GOVERNED_BY]->(s:Standard)
    RETURN m.risk_level AS risk,
           m.recommendation AS rec,
           s.full_citation AS standard,
           s.quote AS quote
    """
    with driver.session() as session:
        record = session.run(
            query, comp_name=component_name, fail_name=failure_mode_name
        ).single()
        if record:
            return record["risk"], record["rec"], record["standard"], record["quote"]
        return None, None, None, None


def semantic_match_observation(
    ai_client: genai.Client, user_text: str, valid_failure_modes: list[str]
) -> str:
    """Routes free-text auditor input onto a strict FailureMode enum from Neo4j."""
    prompt = (
        "You are a Fire Safety Engineering Assistant.\n"
        f'The user recorded this field observation: "{user_text}"\n\n'
        "Map this observation to the ONE most appropriate Failure Mode from this exact list:\n"
        f"{json.dumps(valid_failure_modes)}\n\n"
        'Respond ONLY with the exact matching Failure Mode string. If none match, respond with "Standard Defect".'
    )
    try:
        response = ai_client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.0),
        )
        return response.text.strip()
    except Exception:
        return "Standard Defect"


def main() -> None:
    st.set_page_config(page_title="Iteration 1 | GraphRAG Audit Node", layout="wide")
    st.title("Iteration 1 Archive: Neo4j Hourglass GraphRAG Audit Node")
    st.caption(
        "Historical Proof-of-Concept preserved for architectural traceability. "
        "See Section 2.5 of the whitepaper for the failure autopsy that led to Iteration 2 & 3."
    )
    st.markdown("---")

    driver, ai_client = init_clients()

    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("Field Input")
        area_input = st.text_input("Area Name (e.g., Utility Block, Pump Room):")
        components = get_components(driver)
        selected_component = st.selectbox("Inspected Component:", ["-- Select --"] + components)
        observation_input = st.text_area(
            "Engineer's Observation:",
            height=150,
            placeholder="Type physical defect observed on site...",
        )
        analyze_btn = st.button("Analyze & Auto-Fill", use_container_width=True, type="primary")

    with col2:
        st.subheader("Graph-Grounded Compliance Output")
        if analyze_btn:
            if selected_component == "-- Select --" or not observation_input.strip():
                st.warning("Please select a component and enter an observation.")
            else:
                with st.spinner("Traversing Neo4j Knowledge Graph..."):
                    valid_modes = get_failure_modes(driver, selected_component)
                    mapped_mode = semantic_match_observation(
                        ai_client, observation_input, valid_modes
                    )
                    risk, rec, standard, quote = get_mitigation_data(
                        driver, selected_component, mapped_mode
                    )

                    if risk:
                        st.success("Graph Alignment Successful")
                        st.markdown(f"**Interpreted Failure Mode:** `{mapped_mode}`")

                        if risk == "HIGH":
                            st.error(f"**Risk Category:** {risk}")
                        elif risk == "MEDIUM":
                            st.warning(f"**Risk Category:** {risk}")
                        else:
                            st.info(f"**Risk Category:** {risk}")

                        st.write(
                            f"**Location:** {area_input.upper() if area_input else 'NOT SPECIFIED'}"
                        )
                        st.text_area("Verified Recommendation:", value=rec or "", height=100)

                        if standard:
                            st.code(f"Standard Reference: {standard}\n\nExcerpt:\n{quote}")
                        else:
                            st.code("Governing Standard: General Engineering Practice")
                    else:
                        st.error(
                            "Knowledge Graph could not resolve a mitigation rule for this observation."
                        )


if __name__ == "__main__":
    main()
