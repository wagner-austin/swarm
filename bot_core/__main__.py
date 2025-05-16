import logging.config
from bot_core.logger_setup import DEFAULT_LOGGING_CONFIG
import asyncio  # <-- restored import


def cli() -> None:
    logging.config.dictConfig(DEFAULT_LOGGING_CONFIG)
    from bot_core.main import main  # delayed to honour logging first

    asyncio.run(main())


if __name__ == "__main__":  # pragma: no cover
    cli()
