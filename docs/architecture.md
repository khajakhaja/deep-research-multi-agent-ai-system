# Architecture

Deep Research AI is a multi-agent research assistant. A user submits a complex
question; a set of specialised agents collaborate inside a **LangGraph** state
machine to search the web, fetch and read pages, extract and verify claims, and
produce a structured report whose citations are grounded in real retrieved
sources.

## High-level components

```
                 ┌────────────────────────────┐
   Browser  ───▶ │  Streamlit frontend (:8501) │
                 └──────────────┬─────────────┘
                                │ HTTP (requests)
                 ┌──────────────▼─────────────┐
                 │  FastAPI backend (:8000)    │
                 │  /api/research ...          │
                 └──────────────┬─────────────┘
                                │
                 ┌──────────────▼─────────────┐
                 │  ResearchService            │
                 │  (thread pool, DB, run)     │
                 └──────────────┬─────────────┘
                                │
        ┌───────────────────────▼───────────────────────┐
        │            LangGraph workflow                  │
        │  validate → plan → research → verify → ...     │
        └───────┬───────────────┬───────────────┬───────┘
                │               │               │
        ┌───────▼─────┐ ┌───────▼─────┐ ┌───────▼──────┐
        │ OpenAI LLM  │ │ Tavily search│ │ Page fetcher │
        └─────────────┘ └─────────────┘ └──────────────┘
```

## Agents

| Agent | Responsibility |
|-------|----------------|
| **Coordinator** | Decomposes the question into 1..N focused research tasks with priorities. |
| **Researcher** | Runs web search for each task and fetches page content; stores sources + passages. |
| **Verifier** | Extracts atomic claims and verifies each against the retrieved excerpt using both a deterministic excerpt check and an LLM judgement. Also assesses overall evidence sufficiency. |
| **Analyst** | Synthesises verified evidence into themes, findings, and gaps. |
| **Writer** | Produces a structured markdown report with inline `[S#]` citations. The references section is built programmatically from real sources. |
| **Reviewer** | Checks the report for required sections and citation coverage; may request one revision. |

## Workflow (LangGraph)

Nodes and conditional routing live in `backend/app/graph/builder.py` and
`backend/app/graph/nodes.py`.

```
validate ──▶ plan ──▶ research ──▶ verify ──▶ (sufficient?) ──┬── yes ──▶ analyze ──▶ write ──▶ review ──┬── pass ──▶ finalize
                                                        no ────┘ (retries left)                    fail ────┘ (retries left) ──▶ revise ──▶ write
```

- **Bounded retries.** `MAX_RESEARCH_RETRIES` re-triggers targeted follow-up
  research when evidence is insufficient. `MAX_REVIEW_RETRIES` lets the
  reviewer send the draft back once.
- **Terminal states.** `completed`, `insufficient_evidence`, `failed`.
  Insufficient evidence never fabricates; it produces a report that clearly
  states the uncertainty.
- **Checkpointing.** A SQLite checkpointer persists graph state so partial
  progress survives a restart. Interrupted runs are marked `failed` on recovery.

## Reliability and safety

- **SSRF guard.** `backend/app/tools/url_utils.py` validates every URL before
  fetching, resolving DNS and rejecting private / loopback / link-local ranges.
- **Budget enforcement.** Per-run caps on searches, page fetches, requests and
  an overall wall-clock timeout are enforced in `AgentContext`.
- **Secret hygiene.** API keys are never logged; configuration is validated at
  startup and missing credentials downgrade to warnings so `/health` still works.
- **No invented citations.** Reference entries are generated from stored sources
  (`S1`, `S2`, ...); the LLM is instructed to cite only provided evidence IDs.

## Data model

SQLAlchemy models in `backend/app/database/models.py`:

- `ResearchSession` — one research run (question, status, stage, error, timings).
- `SourceRecord` — a retrieved web source with passages.
- `EvidenceRecord` — an extracted claim with verification status and excerpt.
- `ReportRecord` — the final markdown report and review metadata.

SQLite is the default; PostgreSQL (`psycopg`) is supported via `DATABASE_URL`.

## Configuration

All configuration is environment-driven (`backend/app/config.py`). See
`.env.example` for the full list. Key variables:

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_BASE_URL` | LLM provider. |
| `TAVILY_API_KEY`, `SEARCH_MAX_RESULTS` | Web search. |
| `DATABASE_URL` | `sqlite:///...` or `postgresql+psycopg://...`. |
| `MAX_RESEARCH_TASKS`, `MAX_*_RETRIES`, `RUN_TIMEOUT_SECONDS` | Limits. |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY` | Optional tracing. |

## Evaluation

`backend/app/evaluation/` defines a small, extensible benchmark. The runner
executes each question and reports measurable metrics (citation coverage,
evidence support rate, unsupported claim rate, source retrieval success,
completion rate, review pass rate, average execution time). Estimated API cost
is reported only when provider usage data is available, otherwise `None`.

Run it with:

```bash
python scripts/run_eval.py --limit 2
```

## Repository layout

```
backend/
  app/
    agents/       # the six specialised agents + shared AgentContext
    api/          # FastAPI routes and dependencies
    database/     # SQLAlchemy engine, session, models
    evaluation/   # benchmark + runner
    graph/        # LangGraph state, nodes, builder, recorder
    schemas/      # Pydantic request/response models
    services/     # ResearchService (orchestration + persistence)
    tools/        # LLM client, web search, page fetcher, URL safety
    config.py     # settings
    main.py       # FastAPI app factory
  tests/          # pytest suite (unit + integration)
frontend/
  app.py          # Streamlit UI (light theme)
scripts/
  init_db.py
  run_eval.py
docs/
  architecture.md
```
