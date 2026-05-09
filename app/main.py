from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy.orm import Session

from app.db import Base, engine, get_db
from app.repositories import JobRepository
from app.schemas import JobCreateRequest, JobResponse
from app.services import JobService 

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Async Job API")

def get_job_service(db: Session = Depends(get_db)) -> JobService:
    repository = JobRepository(db)
    return JobService(repository)

@app.post(
    "/jobs", 
    response_model=JobResponse, 
    status_code=status.HTTP_201_CREATED
)
def create_job(
    request: JobCreateRequest,
    service: JobService = Depends(get_job_service),
) -> JobResponse:
    job = service.create_job(payload=request.payload)
    return job


@app.get(
    "/jobs/{job_id}", 
    response_model=JobResponse
)
def get_job(
    job_id: int,
    service: JobService = Depends(get_job_service),
) -> JobResponse:
    job = service.get_job(job_id=job_id)

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Job not found"
        )
    return job

