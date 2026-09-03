import json
import logging
import uuid
from time import perf_counter

# Structured fields a log call may attach via `extra`; anything else is dropped
# so an unreviewed value cannot leak into logs by accident.
_EXTRA_FIELDS = (
    "request_id",
    "method",
    "path",
    "duration_ms",
    "status_code",
    "reason",
    "expected_destination",
    "signed_destination",
    "job_kind",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "level": record.levelname,
                "message": record.getMessage(),
                "logger": record.name,
                "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
                **{key: getattr(record, key) for key in _EXTRA_FIELDS if hasattr(record, key)},
            },
            ensure_ascii=False,
        )


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def new_request_id() -> str:
    return str(uuid.uuid4())


def request_duration(start: float) -> int:
    return round((perf_counter() - start) * 1000)
