from bot_core.logger_setup import setup_logging, DEFAULT_LOGGING_CONFIG

def test_setup_logging_smoke():
    setup_logging()          # should not raise
    setup_logging({"root": {"level": "DEBUG"}})