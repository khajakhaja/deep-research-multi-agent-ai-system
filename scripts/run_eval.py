"""Run the evaluation benchmark against the research system.

By default this performs real research and therefore requires valid
``OPENAI_API_KEY`` and ``TAVILY_API_KEY`` credentials and will incur API cost.

Usage (from the repository root):

    python scripts/run_eval.py
    python scripts/run_eval.py --limit 1 --json
    python scripts/run_eval.py --output reports/eval.json --json

The benchmark is extensible: edit ``backend/app/evaluation/benchmark.py``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import get_settings, validate_startup_settings  # noqa: E402
from app.database.session import init_db  # noqa: E402
from app.evaluation import BENCHMARK, Evaluator, format_report  # noqa: E402
from app.evaluation.runner import report_to_json  # noqa: E402
from app.logging_config import configure_logging, get_logger  # noqa: E402
from app.services.research_service import ResearchService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the deep research evaluation benchmark.")
    parser.add_argument("--limit", type=int, default=0, help="Only run the first N questions.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    parser.add_argument("--output", type=str, default=None, help="Write the report to a file.")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    logger = get_logger("scripts.run_eval")

    problems = validate_startup_settings(settings)
    for problem in problems:
        logger.warning("Configuration issue: %s", problem)
    if problems:
        logger.warning(
            "Evaluation requires real LLM and search credentials. Set "
            "OPENAI_API_KEY and TAVILY_API_KEY in your .env file."
        )

    init_db()
    service = ResearchService(settings)

    questions = BENCHMARK[: args.limit] if args.limit else BENCHMARK
    evaluator = Evaluator(service, questions)
    result = evaluator.run()

    output = report_to_json(result) if args.json else format_report(result)
    print(output)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")
        logger.info("Wrote evaluation report to %s", output_path)

    service.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
