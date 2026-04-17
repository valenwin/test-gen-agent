from celery import Celery
from config import get_settings

settings = get_settings()

celery_app = Celery(
    "test_gen_agent",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["test_gen_agent.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=settings.generation_timeout_seconds,
    task_soft_time_limit=settings.generation_timeout_seconds - 30,
    worker_prefetch_multiplier=1,
)
