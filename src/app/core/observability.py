import json
import logging
import uuid
from time import perf_counter


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "level": record.levelname,
                "message": record.getMessage(),
                "logger": record.name,
                "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
                **{
                    key: getattr(record, key)
                    for key in ("request_id", "method", "path", "duration_ms", "status_code")
                    if hasattr(record, key)
                },
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
