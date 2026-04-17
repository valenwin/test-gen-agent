from fastapi import APIRouter, HTTPException
from api.schemas import (
    GenerateRequest,
    GenerateResponse,
    JobResult,
    JobStatus,
)
from worker.tasks import generate_tests_task

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/generate", response_model=GenerateResponse, status_code=202)
async def generate(request: GenerateRequest) -> GenerateResponse:
    task = generate_tests_task.delay(
        code=request.code,
        filename=request.filename,
        target_coverage=request.target_coverage,
    )
    return GenerateResponse(job_id=task.id, status=JobStatus.PENDING)


@router.get("/jobs/{job_id}", response_model=JobResult)
async def get_job(job_id: str) -> JobResult:
    task = generate_tests_task.AsyncResult(job_id)

    if task.state == "PENDING":
        return JobResult(job_id=job_id, status=JobStatus.PENDING)
    if task.state == "STARTED":
        return JobResult(job_id=job_id, status=JobStatus.RUNNING)
    if task.state == "SUCCESS":
        result = task.result
        return JobResult(
            job_id=job_id,
            status=JobStatus.SUCCESS,
            generated_tests=result.get("tests"),
            coverage=result.get("coverage"),
        )
    if task.state == "FAILURE":
        return JobResult(
            job_id=job_id,
            status=JobStatus.FAILED,
            error=str(task.info),
        )

    raise HTTPException(500, f"Unknown task state: {task.state}")
