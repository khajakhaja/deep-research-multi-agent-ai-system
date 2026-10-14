"""Streamlit frontend - light themed, clean UI.

Connects to the FastAPI backend to run research, poll for progress, and
display the final report with citations and expandable sources.
"""
import json
import os
import time
from datetime import datetime

import requests
import streamlit as st

BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://localhost:8000")


def ensure_api_host() -> str:
    """Return the API base URL with no trailing slash."""
    return BACKEND_BASE_URL.rstrip("/")


def call_api(method: str, path: str, **kwargs) -> requests.Response:
    url = f"{ensure_api_host()}{path}"
    return requests.request(method, url, timeout=kwargs.pop("timeout", 60), **kwargs)


st.set_page_config(
    page_title="Deep Research AI - Multi-Agent Research Assistant",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Light, clean theme
st.markdown(
    """
    <style>
    :root {
        --bg: #f8fafc;
        --panel: #ffffff;
        --border: #e5e7eb;
        --text: #111827;
        --muted: #475569;
        --accent: #2563eb;
    }
    .stApp { background-color: var(--bg); color: var(--text); }
    .stButton > button { background-color: var(--accent); color: white; border: none; padding: 0.6rem 1.2rem; border-radius: 8px; }
    .stButton > button:hover { opacity: 0.9; }
    .block-container { padding-top: 1.2rem; padding-bottom: 2rem; }
    .metric-card { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 1rem; }
    code { background: #f1f5f9; padding: 2px 4px; border-radius: 4px; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Deep Research AI — Multi-Agent Research Assistant")
st.markdown(
    "Enter a complex research question. Specialised agents collaborate to produce a structured, "
    "evidence-backed report with verifiable citations."
)

with st.sidebar:
    st.header("Configuration")
    st.text_input("Backend URL", value=ensure_api_host(), key="backend_url")
    if st.session_state.backend_url:
        os.environ["BACKEND_BASE_URL"] = st.session_state.backend_url.rstrip("/")

    try:
        resp = call_api("get", "/health")
        if resp.ok:
            data = resp.json()
            st.success("Backend healthy")
            st.caption(
                f"LLM: {'✓' if data.get('llm_configured') else '✗'} "
                f"| Search: {'✓' if data.get('search_configured') else '✗'}"
            )
        else:
            st.warning("Backend not responding")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Cannot connect to backend: {exc}")

    st.divider()
    st.header("Research History")
    try:
        resp = call_api("get", "/api/research", params={"limit": 15})
        if resp.ok:
            history = resp.json().get("items", [])
            for item in history:
                key = item["research_id"]
                label = f"{item['status'].upper()} · {item['created_at'][:10]}"
                if st.button(label, key=f"hist_{key}"):
                    st.session_state["research_id"] = key
                    st.rerun()
    except Exception:  # noqa: BLE001
        st.caption("Could not load history")

question = st.text_area(
    "Research Question",
    placeholder="e.g. Analyze the current adoption of Agentic AI in India, its impact on fresher hiring, the skills companies expect, and career opportunities over the next three years.",
    height=120,
)

example_questions = [
    "Analyze the current adoption of Agentic AI in India, its impact on fresher hiring, the skills companies expect, and career opportunities over the next three years.",
    "Compare India and the US approaches to regulating AI development and deployment in 2025-26.",
    "Assess the impact of climate change on India's agricultural productivity and adaptation strategies.",
    "Evaluate the effectiveness of India's digital public infrastructure for financial inclusion.",
    "What are the prospects and risks of green hydrogen adoption in India?",
]

cols = st.columns(len(example_questions))
for idx, q in enumerate(example_questions):
    if cols[idx].button(f"Use example {idx+1}", key=f"ex_{idx}"):
        question = q
        st.session_state["question_input"] = q
        st.rerun()

if "question_input" not in st.session_state:
    st.session_state["question_input"] = question

if st.button("Start Research", type="primary", use_container_width=True):
    payload = {"question": st.session_state.get("question_input", question)}
    try:
        resp = call_api("post", "/api/research", json=payload)
        if resp.ok:
            data = resp.json()
            st.session_state["research_id"] = data["research_id"]
            st.success(f"Research started (ID: {data['research_id']})")
            st.rerun()
        else:
            st.error(f"Failed to start research: {resp.text}")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Error starting research: {exc}")

research_id = st.session_state.get("research_id")
if research_id:
    st.header("Research Progress")
    placeholder = st.empty()
    status_data = None
    for _ in range(300):  # poll up to ~300s
        try:
            resp = call_api("get", f"/api/research/{research_id}")
            if resp.ok:
                status_data = resp.json()
                progress = status_data.get("progress", {})
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Stage", status_data.get("stage", "-"))
                col2.metric("Status", status_data.get("status", "-"))
                col3.metric("Sources", progress.get("sources_total", 0))
                col4.metric("Verified Claims", progress.get("verified_claims", 0))

                with placeholder.container():
                    st.progress(min(progress.get("tasks_completed", 0) / max(progress.get("tasks_total", 1), 1), 1.0))
                    st.write(f"Tasks: {progress.get('tasks_completed')}/{progress.get('tasks_total')} | "
                             f"Searches: {progress.get('search_requests_used')} | "
                             f"Fetches: {progress.get('page_fetches_used')}")

                if status_data.get("status") in ("completed", "insufficient_evidence", "failed"):
                    st.session_state[f"status_{research_id}"] = status_data
                    break
            time.sleep(2)
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Polling error: {exc}")
            time.sleep(2)
    else:
        st.warning("Polling timed out. Check backend status.")

    final_status = st.session_state.get(f"status_{research_id}", status_data)
    if final_status and final_status.get("status") in ("completed", "insufficient_evidence"):
        st.header("Final Report")
        try:
            resp = call_api("get", f"/api/research/{research_id}/report")
            if resp.ok:
                report = resp.json()
                if report.get("insufficient_evidence"):
                    st.warning("Limited evidence: report has stated limitations.")
                st.markdown(report.get("markdown", ""))
                st.divider()
                st.subheader("Citations")
                for c in report.get("citations", []):
                    st.markdown(f"- [{c['source_id']}] [{c['title']}]({c['url']})" if c.get("url") else f"- [{c['source_id']}] {c.get('title','')}")
                st.download_button(
                    "Download Markdown",
                    data=report.get("markdown", ""),
                    file_name=f"deep_research_{research_id}.md",
                    mime="text/markdown",
                )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Failed to fetch report: {exc}")

        try:
            resp = call_api("get", f"/api/research/{research_id}/sources")
            if resp.ok:
                srcs = resp.json()
                with st.expander("View Sources & Evidence"):
                    for s in srcs.get("sources", []):
                        st.write(f"**[{s['id']}] {s.get('title','')}**")
                        st.write(f"URL: {s['url']}")
                        if s.get("passages"):
                            st.write("Passages:")
                            for p in s["passages"]:
                                st.code(p["text"])
                        st.divider()
                    st.subheader("Evidence")
                    for e in srcs.get("evidence", []):
                        st.write(f"**[{e['id']}]** claim: {e['claim']} (status: {e['verification_status']}, source: {e['source_id']})")
                        if e.get("excerpt"):
                            st.code(e["excerpt"])
        except Exception as exc:  # noqa: BLE001
            st.caption(f"Could not load sources: {exc}")

    elif final_status and final_status.get("status") == "failed":
        st.error(f"Research failed: {final_status.get('error')}")
