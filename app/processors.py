class RetryableJobError(Exception):
    pass


class NonRetryableJobError(Exception):
    pass


class DemoJobProcessor:
    def process(self, payload: dict) -> dict:
        if payload.get("fail") is True:
            raise NonRetryableJobError("Forced failure requested by payload")

        if payload.get("transient_fail") is True:
            raise RetryableJobError("Transient failure requested by payload")

        return {
            "processed": True,
            "input_size": len(str(payload)),
            "message": "Job completed successfully",
        }
