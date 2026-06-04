from app.celery_app import celery_app
from app.db import SessionLocal
from app.repositories import JobRepository


@celery_app.task(name="process_job")
def process_job(job_id: int) -> None:
    db = SessionLocal()
    repository = JobRepository(db)

    try:
        job = repository.mark_running(job_id)
        payload = job.payload

        if payload.get("fail") is True:
            raise ValueError("Forced failure requested by payload")

        result = {
            "processed": True,
            "input_size": len(str(payload)),
            "message": "Job completed successfully",
        }

        repository.mark_completed(job_id, result)

    except Exception as exc:
        repository.mark_failed(job_id, str(exc))
        raise

    finally:
        db.close()