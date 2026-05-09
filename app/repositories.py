from sqlalchemy.orm import Session

from app.models import Job, JobStatus


class JobRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, payload: dict) -> Job:
        job = Job(
            payload=payload,
            status = JobStatus.QUEUED,
            )
        
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        
        return job

    def get_by_id(self, job_id: int) -> Job | None:
        return self.db.query(Job).filter(Job.id == job_id).first()

