from bot_core.logger_setup import setup_logging


def test_setup_logging_smoke() -> None:
    setup_logging()  # should not raise
    setup_logging({"root": {"level": "DEBUG"}})
