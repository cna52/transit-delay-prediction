import json
import logging

from transit_delay.logging import JsonFormatter, configure_logging


def test_http_client_request_urls_are_not_logged_at_info() -> None:
    configure_logging("INFO")
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING


def test_formatter_redacts_apikey_query_parameters() -> None:
    record = logging.LogRecord(
        "test",
        logging.ERROR,
        "",
        1,
        "GET https://example.test/feed?apikey=do-not-print&x=1",
        (),
        None,
    )
    value = json.loads(JsonFormatter().format(record))
    assert "do-not-print" not in value["message"]
    assert "apikey=[REDACTED]" in value["message"]
