import pytest

from app.processors import (
    DemoJobProcessor,
    NonRetryableJobError,
    RetryableJobError,
)


def test_demo_processor_returns_success_result():
    payload = {"text": "hello backend"}
    processor = DemoJobProcessor()

    result = processor.process(payload)

    assert result == {
        "processed": True,
        "input_size": len(str(payload)),
        "message": "Job completed successfully",
    }


def test_demo_processor_raises_non_retryable_error_for_forced_failure():
    processor = DemoJobProcessor()

    with pytest.raises(
        NonRetryableJobError,
        match="Forced failure requested by payload",
    ):
        processor.process({"text": "fail case", "fail": True})


def test_demo_processor_raises_retryable_error_for_transient_failure():
    processor = DemoJobProcessor()

    with pytest.raises(
        RetryableJobError,
        match="Transient failure requested by payload",
    ):
        processor.process(
            {"text": "temporary problem", "transient_fail": True}
        )
