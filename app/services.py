from app.models import Job
from app.repositories import JobRepository

class JobService:
    def __init__(self, repository: JobRepository) -> None:
        self.repository = repository

    def create_job(self, payload: dict) -> Job:
        return self.repository.create(payload)
    
    def get_job(self, job_id: int) -> Job | None:
        return self.repository.get_by_id(job_id)