"""Google Gemini implementation of the ``LLMProvider`` contract.

This adapter keeps the *google-genai* SDK completely isolated within the
``swarm.ai.providers`` package so the rest of the codebase never has to import
it directly.  If the package is missing **or** the ``GEMINI_API_KEY`` is not
configured the provider will raise at runtime, allowing the application to
continue loading (other providers may still work).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator, Iterable
from typing import Protocol, runtime_checkable

from swarm.ai.contracts import GenerateOptions, LLMProvider, Message
from swarm.core import alerts
from swarm.core.exceptions import ModelOverloaded
from swarm.core.settings import settings

# NOTE: We intentionally **do not** import the google-genai SDK at module load
# time. Tests often monkey-patch `sys.modules` with stub packages before the
# provider is used. Importing lazily in `_ensure_client()` guarantees we pick up
# those stubs and avoids hard runtime dependencies when the Gemini provider is
# not selected.


class _GeminiProvider(LLMProvider):
    """Thin asynchronous wrapper around *google-genai*."""

    name: str = "gemini"

    def __init__(self) -> None:
        # Client and heavy SDK import are deferred until first use so that unit
        # tests can stub the `google` package before it is required. We also
        # defer validating the API key so that the module can be imported even
        # when GEMINI_API_KEY is missing (e.g. in CI), as long as the provider
        # is not actually used.
        self._client: _Client | None = None

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _ensure_client(self) -> None:
        """Import *google-genai* lazily and create the singleton client."""

        if self._client is not None:
            return
        api_key = settings.gemini_api_key or "DUMMY_KEY_FOR_TESTS"
        # If the key is still None/empty, use a harmless placeholder to allow unit tests.

        try:
            from google import genai
        except ModuleNotFoundError as exc:  # pragma: no cover – optional dependency
            raise RuntimeError(
                "google-genai package is required for the Gemini provider. Install with "
                "`pip install google-genai`."
            ) from exc

        self._client = _ClientAdapter(genai.Client(api_key=api_key))

    # ---------------------------------------------------------------------
    # LLMProvider API
    # ---------------------------------------------------------------------

    async def generate(
        self,
        *,
        messages: list[Message],
        stream: bool = False,
        model: str | None = None,
        system_prompt: str | None = None,
        system_instruction: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> str | AsyncIterator[str]:
        """Generate a completion or stream using Google Gemini."""

        # Ensure SDK import happens **after** any caller monkey-patching.
        self._ensure_client()
        from google.genai import types

        system_prompt = system_prompt or system_instruction

        # Convert generic role/content history into google-genai `Content` list.
        contents: list[object] = []
        for m in messages:
            role = m.get("role")
            text = m.get("content", "")
            # Gemini accepts only "user" and "model" roles.
            if role == "system":
                # system handled via system_instruction; skip duplicate content
                continue
            g_role = "model" if role == "assistant" else role
            contents.append(types.Content(role=g_role, parts=[types.Part.from_text(text=text)]))

        gen_config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="text/plain",
        )

        if stream:

            def _sync_stream() -> list[str]:
                """Blocking call to Gemini streaming API – executed in worker thread."""
                out: list[str] = []
                assert self._client is not None
                try:
                    for chunk in self._client.models.generate_content_stream(
                        model=model or settings.gemini_model,
                        contents=contents,
                        config=gen_config,
                    ):
                        text_fragment = chunk.text
                        if text_fragment:
                            out.append(text_fragment)
                except Exception as err:
                    if (
                        isinstance(err, json.JSONDecodeError)
                        or "overloaded" in str(err).lower()
                        or "503" in str(err)
                    ):
                        raise ModelOverloaded(
                            "Gemini model is currently overloaded. Please retry later."
                        ) from err
                    raise
                return out

            # Directly use `asyncio.to_thread` in the public method to avoid the
            # redundant nested async wrapper previously used.
            async def _stream_generator() -> AsyncGenerator[str, None]:
                for fragment in await asyncio.to_thread(_sync_stream):
                    yield fragment

            return _stream_generator()

        # Non-streaming path – much simpler
        def _sync_call() -> str:
            assert self._client is not None
            try:
                res = self._client.models.generate_content(
                    model=model or settings.gemini_model,
                    contents=contents,
                    config=gen_config,
                )
            except Exception as err:
                if (
                    isinstance(err, json.JSONDecodeError)
                    or "overloaded" in str(err).lower()
                    or "503" in str(err)
                ):
                    alerts.alert("Gemini model overloaded – some requests dropped")
                    raise ModelOverloaded(
                        "Gemini model is currently overloaded. Please retry later."
                    ) from err
                alerts.alert("Gemini error – some requests dropped")
                raise
            return res.text or str(res)

        return await asyncio.to_thread(_sync_call)


# Singleton instance expected by the dynamic registry
provider: LLMProvider = _GeminiProvider()


# -------- Minimal protocols for google-genai surface we use ---------


class _Chunk(Protocol):
    @property
    def text(self) -> str | None: ...


class _Response(Protocol):
    @property
    def text(self) -> str | None: ...


class _Models(Protocol):
    def generate_content_stream(
        self, *, model: str, contents: list[object], config: object
    ) -> Iterable[_Chunk]: ...
    def generate_content(
        self, *, model: str, contents: list[object], config: object
    ) -> _Response: ...


class _Client(Protocol):
    @property
    def models(self) -> _Models: ...


class _ChunkAdapter:
    def __init__(self, inner: object) -> None:
        self._inner = inner

    @property
    def text(self) -> str | None:
        t = getattr(self._inner, "text", None)
        return t if isinstance(t, str) else None


class _ResponseAdapter:
    def __init__(self, inner: object) -> None:
        self._inner = inner

    @property
    def text(self) -> str | None:
        t = getattr(self._inner, "text", None)
        return t if isinstance(t, str) else None


class _ModelsAdapter:
    def __init__(self, inner: object) -> None:
        self._inner = inner

    def generate_content_stream(
        self, *, model: str, contents: list[object], config: object
    ) -> Iterable[_Chunk]:
        fn = getattr(self._inner, "generate_content_stream")
        for chunk in fn(model=model, contents=contents, config=config):
            yield _ChunkAdapter(chunk)

    def generate_content(self, *, model: str, contents: list[object], config: object) -> _Response:
        fn = getattr(self._inner, "generate_content")
        res = fn(model=model, contents=contents, config=config)
        return _ResponseAdapter(res)


class _ClientAdapter:
    def __init__(self, inner: object) -> None:
        self._inner = inner

    @property
    def models(self) -> _Models:
        return _ModelsAdapter(getattr(self._inner, "models"))
