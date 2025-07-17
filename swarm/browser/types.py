from typing import Any, TypedDict


class Command(TypedDict):
    """A unit of work the runtime executes inside the Playwright thread."""

    action: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    future: Any


__all__ = ["Command"]
