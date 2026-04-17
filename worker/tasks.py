import time
from core.logging import logger
from worker.celery_app import celery_app


@celery_app.task(bind=True, name="generate_tests")
def generate_tests_task(
    self,
    code: str,
    filename: str,
    target_coverage: float,
) -> dict:
    log = logger.bind(job_id=self.request.id, filename=filename)
    log.info("generation_started", code_length=len(code))

    # TODO: День 2 — AST analysis
    # TODO: День 3 — LLM call
    # TODO: День 5 — validator loop
    time.sleep(2)

    log.info("generation_completed")
    return {
        "tests": "# TODO: generated tests will be here\n",
        "coverage": 0.0,
    }
