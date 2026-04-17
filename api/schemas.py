from enum import Enum
from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class GenerateRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=50_000)
    filename: str = Field(default="module.py")
    target_coverage: float = Field(default=0.8, ge=0.0, le=1.0)


class GenerateResponse(BaseModel):
    job_id: str
    status: JobStatus


class JobResult(BaseModel):
    job_id: str
    status: JobStatus
    generated_tests: str | None = None
    coverage: float | None = None
    error: str | None = None
