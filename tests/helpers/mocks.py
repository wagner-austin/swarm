__all__: list[str] = ["MockCtx"]
from typing import Any, List


class MockCtx:
    """
    A *very* small stand-in for `discord.ext.commands.Context`.
    The only things the unit-tests use are `.send()` and `.sent`.
    """

    sent: List[str]

    def __init__(self) -> None:
        self.sent = []

    async def send(
        self,
        content: str | None = None,
        **_: Any,
    ) -> None:
        if content is not None:
            self.sent.append(content)

        # a single awaited no-op keeps the signature async while
        # guaranteeing nothing is left un-awaited
        async def _noop() -> None:
            return None

        await _noop()
        return None
