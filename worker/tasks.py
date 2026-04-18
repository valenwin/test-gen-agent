"""Celery task: analyze source → generate tests via LLM → validate in sandbox."""

from analyzer.parser import AnalysisError, CodeAnalyzer
from config import get_settings
from core.logging import logger
from core.validator import TestValidator
from llm.client import LLMClient, LLMError
from worker.celery_app import celery_app


@celery_app.task(bind=True, name="generate_tests")
def generate_tests_task(
    self,
    code: str,
    filename: str,
    target_coverage: float,
) -> dict:
    log = logger.bind(job_id=self.request.id, filename=filename)
    settings = get_settings()
    log.info("generation_started", code_length=len(code))

    # Step 1: AST analysis
    try:
        analysis = CodeAnalyzer().analyze(code, filename)
    except AnalysisError as exc:
        log.error("analysis_failed", error=str(exc))
        raise

    log.info(
        "analysis_done",
        functions=len(analysis.functions),
        classes=len(analysis.classes),
        gaps=len(analysis.coverage_gaps),
    )

    # Step 2: LLM generation + validator retry loop
    llm = LLMClient()
    validator = TestValidator(timeout=60)

    previous_error: str | None = None
    last_result = None
    last_validation = None

    for attempt in range(1, settings.max_retries + 1):
        log.info("llm_attempt", attempt=attempt)

        try:
            gen_result = llm.generate_tests(code, analysis, previous_error=previous_error)
        except LLMError as exc:
            log.error("llm_failed", attempt=attempt, error=str(exc))
            raise

        last_result = gen_result

        # Step 3: Validate in subprocess sandbox
        validation = validator.validate(code, gen_result.tests, filename)
        last_validation = validation

        if validation.success:
            log.info(
                "generation_completed",
                attempt=attempt,
                coverage=validation.coverage,
                input_tokens=gen_result.input_tokens,
                output_tokens=gen_result.output_tokens,
            )
            return {
                "tests": gen_result.tests,
                "coverage": validation.coverage,
                "attempts": attempt,
                "model": gen_result.model,
                "input_tokens": gen_result.input_tokens,
                "output_tokens": gen_result.output_tokens,
            }

        log.warning(
            "validation_failed",
            attempt=attempt,
            coverage=validation.coverage,
            error=(validation.error or "")[:500],
        )
        previous_error = validation.error

    # All retries exhausted — return last generated tests regardless
    log.warning(
        "max_retries_exhausted",
        coverage=last_validation.coverage if last_validation else 0.0,
    )
    return {
        "tests": last_result.tests if last_result else "",
        "coverage": last_validation.coverage if last_validation else 0.0,
        "attempts": settings.max_retries,
        "validation_error": "Tests did not pass after max retries",
    }
