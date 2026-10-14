# Deep Research AI — Multi-Agent Research Assistant

A multi-agent research system that turns a complex question into a structured,
evidence-backed report with **verifiable citations**. Specialised agents
coordinate inside a [LangGraph](https://github.com/langchain-ai/langgraph) state
machine to plan research, search and read the web, extract and verify claims,
and write a report grounded in the sources actually retrieved.

> Built with FastAPI, LangGraph, OpenAI, Tavily and Streamlit.

![Python](https://img.shields.io/badge/python-3.13-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688)
![LangGraph](https://img.shields.io/badge/LangGraph-1.x-orange)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
[![CI](https://github.com/khajakhaja/deep-research-multi-agent-ai-system/actions/workflows/ci.yml/badge.svg)](https://github.com/khajakhaja/deep-research-multi-agent-ai-system/actions/workflows/ci.yml)

---

## Why this project

Most "research with an LLM" demos produce plausible text with invented
citations. This project treats **grounding and verification** as first-class:

- Every claim is linked to a retrieved source and an exact excerpt.
- Citations are only ever emitted for sources that were actually fetched.
- If the evidence is insufficient, the system says so instead of hallucinating.
- The whole workflow is observable, retry-bounded, and persists to a database.

---

## Features

- **Six specialised agents** — Coordinator, Researcher, Verifier, Analyst,
  Writer, Reviewer — coordinated by an explicit, conditional LangGraph workflow.
- **Real retrieval** — Tavily web search + article extraction
  (`trafilatura`, `BeautifulSoup`), with an SSRF-safe URL validator.
- **Two-stage verification** — a deterministic excerpt check *and* an LLM
  judgement; a claim is `verified` only when both agree.
- **Bounded self-correction** — follow-up research loops and report revision
  loops, each capped by configurable retry limits.
- **Grounded reports** — a References section generated programmatically from
  real sources; inline `[S#]` citations; required sections enforced by the
  reviewer.
- **Async execution + polling** — runs in a background thread pool; the API
  exposes status, progress, report and sources.
- **Persistence** — SQLAlchemy models (SQLite by default, PostgreSQL supported);
  LangGraph SQLite checkpointer for crash resilience.
- **Evaluation harness** — a small benchmark with measurable metrics.
- **Tested** — 61 unit and integration tests, using injected fakes (no network).

### Try it offline (no API keys)

Want to see it work without credentials? Run the deterministic demo — it drives
the full workflow with fakes and writes a walkthrough:

```bash
python scripts/demo.py     # writes docs/example_output.md
```

See [`docs/example_output.md`](docs/example_output.md) for the generated result.

---

## Architecture

```
validate ─▶ plan ─▶ research ─▶ verify ─▶ sufficient? ─┬─ yes ─▶ analyze ─▶ write ─▶ review ─┬─ pass ─▶ finalize
                                                 no ─────┘ (retry)                    fail ────┘ (revise) ─▶ write
```

See [`docs/architecture.md`](docs/architecture.md) for the full breakdown.

| Layer | Technology |
|-------|------------|
| API | FastAPI + Uvicorn |
| Orchestration | LangGraph (StateGraph + SQLite checkpointer) |
| LLM | OpenAI-compatible (`langchain-openai`) |
| Search | Tavily |
| Fetch/parse | httpx + trafilatura + BeautifulSoup |
| Persistence | SQLAlchemy (SQLite / PostgreSQL) |
| UI | Streamlit |
| Tests | pytest |

---

## Quickstart

### 1. Requirements

- Python 3.11+ (developed on 3.13)
- An OpenAI API key (or any OpenAI-compatible endpoint)
- A [Tavily](https://tavily.com) API key

### 2. Install

```bash
python -m venv .venv
# Windows
.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -r backend/requirements.txt
pip install -r frontend/requirements.txt
```

### 2. Configure

```bash
# PowerShell
Copy-Item .env.example .env
```

Then edit `.env` and set at least:

```env
OPENAI_API_KEY=sk-...
TAVILY_API_KEY=tvly-...
```

`.env` is git-ignored; only `.env.example` is committed.

### 3. Initialise the database

```bash
python scripts/init_db.py
```

### 4. Run the backend

```bash
uvicorn app.main:app --reload --port 8000 --app-dir backend
```

- API root: http://localhost:8000
- Interactive docs: http://localhost:8000/docs
- Health: <http://localhost:8000/health>

### 4b. Run the frontend

In a second terminal:

```bash
streamlit run frontend/app.py
```

Open <http://localhost:8501>, enter a question (or pick an example), and watch
progress until the report is ready.

---

## Configuration

All settings are environment variables (see [`.env.example`](.env.example)).
Highlights:

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | LLM key (**required** for real runs). |
| `OPENAI_MODEL` | `gpt-4o-mini` | Chat model used by all agents. |
| `OPENAI_BASE_URL` | — | Override for Azure/OpenRouter/local gateways. |
| `TAVILY_API_KEY` | — | Web search key (**required** for real runs). |
| `DATABASE_URL` | `sqlite:///./data/research.db` | SQLite or PostgreSQL DSN. |
| `MAX_RESEARCH_TASKS` | `5` | Max research tasks the coordinator creates. |
| `MAX_SEARCH_REQUESTS_PER_RUN` | `25` | Per-run search budget. |
| `MAX_PAGE_FETCHES_PER_RUN` | `30` | Per-run page-fetch budget. |
| `MAX_RESEARCH_RETRIES` | `1` | Follow-up research loops. |
| `MAX_REVIEW_RETRIES` | `1` | Report revision loops. |
| `RUN_TIMEOUT_SECONDS` | `600` | Overall wall-clock budget per run. |
| `LANGSMITH_TRACING` | `false` | Enable optional tracing. |

---

## API

Base URL: `http://localhost:8000`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health + which integrations are configured. |
| `POST` | `/api/research` | Start a research run. |
| `GET` | `/api/research` | List recent runs (history). |
| `GET` | `/api/research/{id}` | Status, stage and progress. |
| `GET` | `/api/research/{id}/report` | Final report + citations. |
| `GET` | `/api/research/{id}/sources` | Sources, passages and evidence. |

Example:

```bash
curl -X POST http://localhost:8000/api/research \
  -H "Content-Type: application/json" \
  -d '{"question": "Analyze Agentic AI adoption in India and its impact on fresher hiring."}'
```

```bash
curl http://localhost:8000/api/research/<research_id>
curl http://localhost:8000/api/research/<research_id>/report
```

Interactive docs: <http://localhost:8000/docs>.

---

## Testing

The test suite uses injected fakes and never touches the network.

```bash
python -m pytest backend/tests/ -v
```

Coverage areas: input validation, tools (search/fetch/URL safety), each agent,
the LangGraph workflow (including retry paths), the FastAPI endpoints, service +
database integration, reliability/limits, and the evaluation runner.

---

## Evaluation

Run the built-in benchmark (requires valid API keys — it performs real
research):

```bash
python scripts/run_eval.py --limit 2          # text report
python scripts/run_eval.py --json --output reports/eval.json
```

Reported metrics: citation coverage, evidence support rate, unsupported claim
rate, source retrieval success, research completion rate, review pass rate and
average execution time. Estimated API cost is reported only when provider usage
data is available. Add questions in
`backend/app/evaluation/benchmark.py`.

---

## Docker

```bash
# 1. Provide credentials
Copy-Item .env.example .env   # then edit .env

# 2. Build and start (PostgreSQL + backend + frontend)
docker compose up --build
```

- Frontend: <http://localhost:8501>
- Backend: <http://localhost:8000>
- PostgreSQL is exposed on `localhost:5432`.

---

## Project structure

```
backend/
  app/
    agents/       # six agents + shared AgentContext
    api/          # FastAPI routes and dependencies
    database/     # engine, session, ORM models
    evaluation/   # benchmark + runner
    graph/        # StateGraph, nodes, builder, recorder
    schemas/      # Pydantic models
    services/     # ResearchService (orchestration + persistence)
    tools/        # LLM, search, fetcher, URL safety
    config.py
    main.py
  tests/
frontend/
  app.py          # Streamlit UI (light theme)
scripts/
  init_db.py
  run_eval.py
docs/
  architecture.md
```

---

## Design decisions

- **Verification before generation.** Claims are extracted and checked against
  real excerpts before the writer is allowed to use them.
- **Deterministic + LLM verification.** The deterministic check catches obvious
  mismatches cheaply; the LLM judgement handles paraphrase. Both must pass.
- **Never invent references.** The references list is generated from stored
  sources; the model only chooses which IDs to cite.
- **Explicit, bounded control flow.** Retries are bounded and terminal states
  are explicit, so runs always finish.
- **Fail loudly, not silently.** Missing credentials surface as warnings at
  startup and failed runs, never as fabricated answers.

## Limitations

- Quality depends on the search provider and the LLM; verification reduces but
  does not eliminate errors.
- Large questions can consume meaningful API budget — tune the limits above.
- The default SQLite backend is single-node; use PostgreSQL for production.

## License

Released under the [MIT License](LICENSE).
