__all__: list[str] = ["MockCtx", "MockMessage"]
from typing import Any


class MockMessage:
    """A mock discord.Message object with an edit method."""

    def __init__(self, content: str | None = None, **kwargs: Any):
        self.content = content
        self.kwargs = kwargs  # Store original send kwargs
        self.edit_history: list[
            dict[str, Any]
        ] = []  # To track edits, if needed for assertions

    async def edit(self, content: str | None = None, **kwargs: Any) -> "MockMessage":
        """Mock the edit method of a discord.Message."""
        edit_details = {}
        if content is not None:
            self.content = content
            edit_details["content"] = content

        # Update message's kwargs with edit's kwargs
        self.kwargs.update(kwargs)
        edit_details.update(kwargs)
        self.edit_history.append(edit_details)

        async def _noop() -> None:  # Keep the async nature
            pass

        await _noop()
        return self


class MockCtx:
    """
    A *very* small stand-in for `discord.ext.commands.Context`.
    The unit-tests use `.send()` (which returns a `MockMessage`) and `.sent` (list of initial contents).
    """

    sent: list[str]  # Using built-in list

    def __init__(self) -> None:
        self.sent = []

    async def send(
        self,
        content: str | None = None,
        **kwargs: Any,  # Capture other arguments like embeds, views, etc.
    ) -> "MockMessage":  # Return MockMessage
        if content is not None:
            self.sent.append(content)

        # a single awaited no-op keeps the signature async while
        # guaranteeing nothing is left un-awaited
        async def _noop() -> None:
            pass

        await _noop()

        return MockMessage(
            content=content, **kwargs
        )  # Return an instance of MockMessage
