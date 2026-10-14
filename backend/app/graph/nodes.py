"""LangGraph node implementations.

Each node is a small function that reads the shared state, performs one
agent's work through the read-only tools, records progress, and returns a
partial state update. Conditional routing functions are also defined here.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable, Dict

from app.agents import (
    AgentError,
    AgentContext,
    AnalysisAgent,
    CoordinatorAgent,
    EvidenceVerificationAgent,
    ReportWriterAgent,
    ResearchAgent,
    ReviewerAgent,
)
from app.agents.context import TimeoutExceeded
from app.constants import RunStatus, Stage, TaskStatus
from app.graph.recorder import NullRecorder, RunRecorder
from app.graph.state import ResearchState
from app.schemas.research import ResearchTask


class Nodes:
    """Builds and holds the workflow node callables."""

    def __init__(self, ctx: AgentContext, recorder: RunRecorder | None = None):
        self.ctx = ctx
        self.recorder: RunRecorder = recorder or NullRecorder()
        self.coordinator = CoordinatorAgent(ctx)
        self.researcher = ResearchAgent(ctx)
        self.verifier = EvidenceVerificationAgent(ctx)
        self.analyst = AnalysisAgent(ctx)
        self.writer = ReportWriterAgent(ctx)
        self.reviewer = ReviewerAgent(ctx)

    # ------------------------------------------------------------------
    def _timed(self, agent: str, stage: str, fn: Callable, **record_kwargs) -> object:
        start = time.perf_counter()
        try:
            result = fn()
            duration = int((time.perf_counter() - start) * 1000)
            self.recorder.record_execution(
                agent=agent, stage=stage, status="completed",
                duration_ms=duration, **record_kwargs
            )
            return result
        except Exception as exc:  # noqa: BLE001
            duration = int((time.perf_counter() - start) * 1000)
            self.recorder.record_execution(
                agent=agent, stage=stage, status="failed",
                summary=str(exc), duration_ms=duration
            )
            raise

    # ------------------------------------------------------------------
    def validate(self, state: ResearchState) -> Dict:
        """Validate the research question before planning."""
        question = (state.get("question") or "").strip()
        min_len = self.ctx.settings.min_question_length
        max_len = self.ctx.settings.max_question_length

        self.recorder.set_stage(Stage.VALIDATING, RunStatus.RUNNING)
        if len(question) < min_len or len(question) > max_len:
            message = (
                f"Research question must be between {min_len} and {max_len} "
                "characters."
            )
            self.ctx.logger.warning(message, extra={"research_id": self.ctx.research_id})
            self.recorder.set_status(RunStatus.FAILED)
            self.recorder.set_error(message)
            return {
                "status": RunStatus.FAILED,
                "stage": Stage.FAILED,
                "errors": list(state.get("errors", [])) + [message],
            }

        self._timed("validator", Stage.VALIDATING, lambda: True, summary="Question valid")
        return {"status": RunStatus.RUNNING, "stage": Stage.PLANNING}

    def plan(self, state: ResearchState) -> Dict:
        """Run the coordinator to produce a research plan."""
        self.recorder.set_stage(Stage.PLANNING, RunStatus.RUNNING)
        try:
            plan = self._timed(
                "coordinator", Stage.PLANNING,
                lambda: self.coordinator.create_plan(state["question"]),
            )
        except (AgentError, TimeoutExceeded) as exc:
            self.recorder.set_status(RunStatus.FAILED)
            self.recorder.set_error(str(exc))
            return {
                "status": RunStatus.FAILED,
                "stage": Stage.FAILED,
                "errors": list(state.get("errors", [])) + [str(exc)],
            }

        self.recorder.save_plan(plan)
        self.recorder.set_objective(plan.objective, plan.scope, plan.information_needs)
        return {
            "plan": plan,
            "tasks": list(plan.tasks),
            "stage": Stage.RESEARCHING,
        }

    def research(self, state: ResearchState) -> Dict:
        """Run the research agent over every not-yet-completed task."""
        self.recorder.set_stage(Stage.RESEARCHING, RunStatus.RUNNING)
        tasks = list(state.get("tasks", []))
        errors = list(state.get("errors", []))

        for task in tasks:
            if task.status == TaskStatus.COMPLETED:
                continue
            task.status = TaskStatus.IN_PROGRESS
            try:
                result = self.researcher.research_task(task, state["question"])
            except TimeoutExceeded as exc:
                task.status = TaskStatus.FAILED
                errors.append(str(exc))
                break

            task.sources_found = len(result["source_ids"])
            task.status = (
                TaskStatus.COMPLETED if result["source_ids"] else TaskStatus.FAILED
            )
            errors.extend(result["errors"])

        all_sources = self.ctx.registry.all()
        self.recorder.save_sources(all_sources)
        self.recorder.set_budget(self.ctx.budget.searches_used, self.ctx.budget.fetches_used)

        return {
            "tasks": tasks,
            "sources": all_sources,
            "errors": errors,
            "stage": Stage.VERIFYING,
        }

    def verify(self, state: ResearchState) -> Dict:
        """Verify claims and assess evidence sufficiency."""
        self.recorder.set_stage(Stage.VERIFYING, RunStatus.RUNNING)
        sources = list(state.get("sources", []))
        tasks = list(state.get("tasks", []))
        errors = list(state.get("errors", []))

        try:
            evidence, verify_errors, _stats = self._timed(
                "verifier", Stage.VERIFYING,
                lambda: self.verifier.verify(sources, state["question"]),
            )
        except TimeoutExceeded as exc:
            evidence, verify_errors = [], [str(exc)]

        errors.extend(verify_errors)
        self.recorder.save_evidence(evidence)

        retries_exhausted = state.get("research_retries", 0) >= self.ctx.settings.max_research_retries
        sufficiency = self.verifier.assess_sufficiency(
            evidence, tasks, sources, retries_exhausted=retries_exhausted
        )
        self.recorder.record_execution(
            agent="verifier", stage=Stage.VERIFYING, status="completed",
            summary=sufficiency["reason"],
            details={"verified": sufficiency["verified"], "coverage": sufficiency["coverage"]},
        )

        return {
            "evidence": evidence,
            "sources": sources,
            "errors": errors,
            "sufficiency": sufficiency,
            "stage": Stage.VERIFYING,
        }

    def followup(self, state: ResearchState) -> Dict:
        """Create a targeted follow-up research task and bump the retry count."""
        self.recorder.set_stage(Stage.FOLLOWUP, RunStatus.RUNNING)
        tasks = list(state.get("tasks", []))
        sufficiency = state.get("sufficiency", {})
        retry = state.get("research_retries", 0) + 1
        year = datetime.now(timezone.utc).year

        existing_queries = {q for task in tasks for q in task.queries}
        queries = []
        for task in tasks:
            if task.sources_found == 0:
                candidate = f"{task.title} statistics report {year}"
                if candidate not in existing_queries:
                    queries.append(candidate)
        if not queries:
            queries = [f"{state['question']} latest evidence {year}"]

        followup_task = ResearchTask(
            id=f"TF{retry}",
            title=f"Targeted follow-up research (pass {retry})",
            description=(
                "Fill evidence gaps identified during verification: "
                + sufficiency.get("reason", "")
            ),
            rationale="Additional evidence requested after insufficient coverage.",
            queries=queries[:3],
            status=TaskStatus.PENDING,
        )
        tasks.append(followup_task)

        self.recorder.set_retries(retry, state.get("review_retries", 0))
        self.recorder.record_execution(
            agent="coordinator", stage=Stage.FOLLOWUP, status="completed",
            summary=sufficiency.get("reason", ""),
            details={"queries": queries[:3], "retry": retry},
        )
        return {
            "tasks": tasks,
            "research_retries": retry,
            "followup_queries": queries,
            "stage": Stage.RESEARCHING,
        }

    def analyze(self, state: ResearchState) -> Dict:
        """Synthesize findings from verified evidence."""
        self.recorder.set_stage(Stage.ANALYZING, RunStatus.RUNNING)
        sufficiency = state.get("sufficiency", {})
        insufficient = not sufficiency.get("sufficient", False)

        analysis = self._timed(
            "analyst", Stage.ANALYZING,
            lambda: self.analyst.analyze(
                state["question"],
                state["plan"],
                list(state.get("evidence", [])),
                list(state.get("sources", [])),
                insufficient=insufficient,
            ),
        )
        if insufficient:
            self.recorder.set_insufficient(True)

        return {
            "analysis": analysis,
            "insufficient_evidence": insufficient,
            "stage": Stage.WRITING,
        }

    def write(self, state: ResearchState) -> Dict:
        """Generate the report using the writer agent."""
        self.recorder.set_stage(Stage.WRITING, RunStatus.RUNNING)
        review = state.get("review")
        feedback = list(review.feedback) if review else []

        report = self._timed(
            "writer", Stage.WRITING,
            lambda: self.writer.write(
                state["question"],
                state["plan"],
                state["analysis"],
                list(state.get("evidence", [])),
                list(state.get("sources", [])),
                feedback=feedback,
                insufficient=state.get("insufficient_evidence", False),
            ),
        )
        self.recorder.save_report(report)
        return {"report": report, "stage": Stage.REVIEWING}

    def review(self, state: ResearchState) -> Dict:
        """Review the generated report."""
        self.recorder.set_stage(Stage.REVIEWING, RunStatus.RUNNING)
        report = state["report"]
        attempt = state.get("review_retries", 0) + 1

        review = self._timed(
            "reviewer", Stage.REVIEWING,
            lambda: self.reviewer.review(
                report.markdown,
                list(state.get("sources", [])),
                list(state.get("evidence", [])),
                state["question"],
            ),
        )
        self.recorder.save_review(review, attempt)
        return {"review": review, "stage": Stage.REVIEWING}

    def revise(self, state: ResearchState) -> Dict:
        """Bump the review retry count so the report is rewritten."""
        self.recorder.set_stage(Stage.REVISING, RunStatus.RUNNING)
        retry = state.get("review_retries", 0) + 1
        self.recorder.set_retries(state.get("research_retries", 0), retry)
        return {"review_retries": retry, "stage": Stage.WRITING}

    def finalize(self, state: ResearchState) -> Dict:
        """Mark the run complete and persist the final status."""
        insufficient = state.get("insufficient_evidence", False)
        review = state.get("review")

        if insufficient:
            status = RunStatus.INSUFFICIENT_EVIDENCE
        elif review is not None and not review.passed:
            # Review retries exhausted without approval: still deliver, but flag.
            status = RunStatus.INSUFFICIENT_EVIDENCE
        else:
            status = RunStatus.COMPLETED

        self.recorder.set_status(status)
        self.recorder.set_stage(Stage.COMPLETED, status)
        self.recorder.set_retries(
            state.get("research_retries", 0), state.get("review_retries", 0)
        )
        self.recorder.record_execution(
            agent="system", stage=Stage.FINALIZING, status="completed",
            summary=f"Final status: {status}",
        )
        return {"status": status, "stage": Stage.COMPLETED}

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------
    def route_after_validate(self, state: ResearchState) -> str:
        return "end" if state.get("status") == RunStatus.FAILED else "plan"

    def route_after_plan(self, state: ResearchState) -> str:
        return "end" if state.get("status") == RunStatus.FAILED else "research"

    def route_evidence(self, state: ResearchState) -> str:
        sufficiency = state.get("sufficiency", {})
        if sufficiency.get("sufficient"):
            return "analyze"
        if state.get("research_retries", 0) < self.ctx.settings.max_research_retries:
            return "followup"
        return "analyze"

    def route_review(self, state: ResearchState) -> str:
        review = state.get("review")
        if review is not None and review.passed:
            return "finalize"
        max_retries = self.ctx.settings.max_review_retries
        if state.get("review_retries", 0) < max_retries:
            return "revise"
        return "finalize"
