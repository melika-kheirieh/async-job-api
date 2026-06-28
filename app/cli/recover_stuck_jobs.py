import argparse
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.repositories import JobRepository
from app.services import DEFAULT_STUCK_JOB_TIMEOUT_MINUTES, JobService


@dataclass(frozen=True)
class RecoveryCliResult:
    recovered_count: int
    recovered_job_ids: list[int]


def recover_stuck_jobs_for_session(
    db: Session,
    timeout_minutes: int = DEFAULT_STUCK_JOB_TIMEOUT_MINUTES,
) -> RecoveryCliResult:
    repository = JobRepository(db)
    service = JobService(repository)

    recovered_jobs = service.recover_stuck_jobs(timeout_minutes=timeout_minutes)

    return RecoveryCliResult(
        recovered_count=len(recovered_jobs),
        recovered_job_ids=[job.id for job in recovered_jobs],
    )


def run_recovery(
    timeout_minutes: int = DEFAULT_STUCK_JOB_TIMEOUT_MINUTES,
) -> RecoveryCliResult:
    db = SessionLocal()

    try:
        return recover_stuck_jobs_for_session(
            db=db,
            timeout_minutes=timeout_minutes,
        )
    finally:
        db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Recover stuck running jobs by marking old running jobs as failed.",
    )
    parser.add_argument(
        "--timeout-minutes",
        type=int,
        default=DEFAULT_STUCK_JOB_TIMEOUT_MINUTES,
        help="Recover running jobs older than this many minutes.",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    result = run_recovery(timeout_minutes=args.timeout_minutes)

    print(f"Recovered {result.recovered_count} stuck job(s).")

    if result.recovered_job_ids:
        recovered_ids = ", ".join(str(job_id) for job_id in result.recovered_job_ids)
        print(f"Recovered job IDs: {recovered_ids}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())