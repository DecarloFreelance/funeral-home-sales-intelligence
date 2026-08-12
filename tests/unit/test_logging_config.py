import json
import logging

from canada_funeral_intel.logging_config import JsonFormatter


def test_json_formatter() -> None:
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    payload = json.loads(JsonFormatter().format(record))
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.logger"
    assert payload["message"] == "hello"
    assert payload["timestamp"].endswith("+00:00")
