"""Formal structural contract for LLM back-ends.

All model providers must satisfy this protocol so that the rest of the bot
can remain vendor-agnostic.  It encodes the *minimum viable* interaction with a
large-language-model API: send chat history (role + content pairs) and receive
either a full string or an async iterator of chunks.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal, Protocol, TypedDict, Unpack, runtime_checkable


class Message(TypedDict):
    role: Literal["user", "assistant", "system"]
    content: str


class GenerateOptions(TypedDict, total=False):
    model: str
    system_prompt: str
    system_instruction: str
    temperature: float
    top_p: float


@runtime_checkable
class LLMProvider(Protocol):
    """Structural interface every concrete model adapter must implement."""

    # Unique short identifier (e.g. "gemini", "openai", "anthropic").
    name: str

    async def generate(
        self,
        *,
        messages: list[Message],
        stream: bool = False,
        **options: Unpack[GenerateOptions],
    ) -> str | AsyncIterator[str]:
        """Generate a completion or an async stream of chunks.

        Arguments
        ---------
        messages:
            Complete chat history in role/content format.
        stream:
            If *True* the provider should return an *async iterator* that yields
            chunks (strings).  Otherwise it should return the *entire* string
            once ready.
        options:
            Additional model-specific parameters like *temperature* or
            *max_tokens*.  Providers should **tolerate arbitrary keys** and only
            consume the ones they recognise so that callers can pass options
            opaquely.
        """

    # NOTE: there is intentionally no `.close()` – provider implementations may
    # manage their own lifetime internally.


__all__ = ["LLMProvider", "Message", "GenerateOptions"]
