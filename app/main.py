from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy.orm import Session

from app.db import Base, engine, get_db
from app.repositories import JobRepository
from app.schemas import JobCreateRequest, JobResponse
from app.services import JobNotFoundError, JobService

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Async Job API")


def enqueue_process_job(job_id: int) -> None:
    from app.tasks import process_job

    process_job.delay(job_id)


def get_job_service(db: Session = Depends(get_db)) -> JobService:
    repository = JobRepository(db)
    return JobService(repository, enqueue_job=enqueue_process_job)


@app.post(
    "/jobs",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_job(
    job_create: JobCreateRequest,
    service: JobService = Depends(get_job_service),
) -> JobResponse:
    return service.create_job(job_create)


@app.get(
    "/jobs/{job_id}",
    response_model=JobResponse,
)
def get_job(
    job_id: int,
    service: JobService = Depends(get_job_service),
) -> JobResponse:
    try:
        return service.get_job(job_id)
    except JobNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )