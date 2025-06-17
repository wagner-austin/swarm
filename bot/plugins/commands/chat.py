import discord
from discord import app_commands
from discord.ext import commands  # For commands.Bot, commands.Cog
from bot.core.settings import settings  # fully typed alias
from bot.ai.personas import (
    PERSONALITIES,
    prompt as persona_prompt,
    visible as persona_visible,
)
from typing import cast

# Centralized interaction helpers
from bot.utils.discord_interactions import safe_followup, safe_send
from bot.plugins.commands.decorators import background_app_command
import asyncio
from bot.history.backends import HistoryBackend
from bot.history.in_memory import MemoryBackend
from bot.ai import providers as _providers
from bot.core.exceptions import ModelOverloaded


INTERNAL_ERROR = "An internal error occurred. Please try again later."


# Static fallback list for autocomplete defaults
_ALL_CHOICES = [
    app_commands.Choice(name=k.capitalize(), value=k) for k in PERSONALITIES.keys()
]

# Global system instruction applied to every persona
DEFAULT_SYSTEM_PROMPT = "Always include your name at the beginning of a response."


class Chat(commands.Cog):
    def __init__(
        self, bot: commands.Bot, history_backend: HistoryBackend | None = None
    ) -> None:
        super().__init__()  # <-- no args
        self.bot = bot  # keep ref for future use
        # Remember last selected personality per channel
        self._channel_persona: dict[int, str] = {}
        # Conversation history backend (pluggable)
        if history_backend is None:
            # Fallback to in-memory if DI not wired (e.g. in tests)
            history_backend = MemoryBackend(settings.conversation_max_turns)
        self._history: HistoryBackend = history_backend

    async def cog_unload(self) -> None:
        """Clean up resources when the cog is unloaded."""
        # Nothing to clean up – providers manage their own lifecycle.
        return

    @app_commands.command(
        name="chat", description="Chat with the configured LLM (or clear history)"
    )
    @app_commands.describe(
        prompt="What should I ask?",
        clear="If true, reset conversation history instead",
        personality="Pick a persona",
    )
    @background_app_command(defer_ephemeral=False)
    async def chat(
        self,
        interaction: discord.Interaction,
        prompt: str | None = None,
        clear: bool = False,
        personality: str | None = None,
    ) -> None:
        # Handle clearing history first
        if clear:
            chan_id_clear: int = interaction.channel_id or 0
            if personality is not None and not persona_visible(
                personality, interaction.user.id
            ):
                await safe_send(
                    interaction,
                    "You are not allowed to use that persona.",
                    ephemeral=True,
                )
                return

            await self._history.clear(chan_id_clear, personality)
            target = f" for **{personality}**" if personality else ""
            await safe_followup(
                interaction,
                f"Chat history{target} cleared.",
                ephemeral=True,
            )
            return

        # Select provider configured in settings
        provider_name: str = getattr(settings, "llm_provider", "gemini")
        try:
            provider = _providers.get(provider_name)
        except KeyError:
            await safe_send(
                interaction,
                f"LLM provider '{provider_name}' is not available.",
                ephemeral=True,
            )
            return

        if prompt is None:
            prompt = "Hello!"

        # Determine which personality prompt to use
        channel_id_int: int = int(
            (
                getattr(interaction, "channel_id", None)
                or (interaction.channel.id if interaction.channel else 0)
            )
            or 0
        )

        if personality is not None and persona_visible(
            personality, interaction.user.id
        ):
            # Explicit valid choice – remember it for this channel
            self._channel_persona[channel_id_int] = personality
        else:
            # Either no choice or invalid/stale choice – fall back
            # Fallback to default persona
            personality = self._channel_persona.get(channel_id_int, "Default")
            if personality not in PERSONALITIES:
                personality = "Default"

        # Visibility check
        if not persona_visible(personality, interaction.user.id):
            await safe_send(
                interaction, "You are not allowed to use that persona.", ephemeral=True
            )
            return

        persona_prompt_str: str = persona_prompt(personality)

        final_system_prompt = DEFAULT_SYSTEM_PROMPT + "\n\n" + persona_prompt_str

        # Inform Discord we are processing (shows typing indicator)

        # Build chat history (excluding the system prompt – passed separately)
        messages: list[dict[str, str]] = [
            {"role": role, "content": content}
            for u, a in await self._history.recent(channel_id_int, personality)
            for role, content in (("user", u), ("assistant", a))
        ]
        messages.append({"role": "user", "content": prompt})

        # Call the provider and collect its reply
        model: str | None = getattr(settings, f"{provider_name}_model", None)
        try:
            raw_reply = await provider.generate(
                messages=messages,
                stream=True,
                model=model,
                system_prompt=final_system_prompt,
            )
        except ModelOverloaded:
            await safe_followup(
                interaction,
                "The language model is currently overloaded. Please try again in a moment.",
                ephemeral=True,
            )
            return
        except Exception as exc:
            await safe_followup(interaction, f"LLM error: {exc}")
            return

        # Providers may still return an async iterator – normalise to a string
        if isinstance(raw_reply, str):
            response_text = raw_reply
        else:
            parts: list[str] = []
            try:
                async for fragment in raw_reply:
                    parts.append(fragment)
            except ModelOverloaded:
                await safe_followup(
                    interaction,
                    "The language model is currently overloaded. Please try again in a moment.",
                    ephemeral=True,
                )
                return
            except Exception as exc:  # handle unforeseen provider errors mid-stream
                await safe_followup(interaction, f"LLM error: {exc}")
                return
            response_text = "".join(parts)

        # Handle Discord's character limit by splitting into chunks
        if not response_text:
            await safe_followup(interaction, "[No response]")
            return

        DISCORD_CHAR_LIMIT: int = settings.discord_chunk_size
        if len(response_text) <= DISCORD_CHAR_LIMIT:
            await safe_followup(interaction, response_text)
        else:
            chunks = [
                response_text[i : i + DISCORD_CHAR_LIMIT]
                for i in range(0, len(response_text), DISCORD_CHAR_LIMIT)
            ]
            for idx, chunk in enumerate(chunks):
                if len(chunks) > 1:
                    prefix = f"[Part {idx + 1}/{len(chunks)}] "
                    if len(prefix) + len(chunk) > DISCORD_CHAR_LIMIT:
                        chunk = chunk[: DISCORD_CHAR_LIMIT - len(prefix)]
                    chunk = prefix + chunk
                await safe_followup(interaction, chunk)

        # Record the turn in history
        await self._history.record(
            channel_id_int, personality, (prompt or "", response_text)
        )

    @chat.autocomplete("personality")
    async def personality_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        visible = [
            app_commands.Choice(name=k.capitalize(), value=k)
            for k in PERSONALITIES.keys()
            if persona_visible(k, interaction.user.id)
        ]
        if not current:
            return visible[:25]
        lowered = current.lower()
        return [c for c in visible if lowered in c.name.lower()][:25]

    # ------------------------------------------------------------------
    # /chat round-table
    # ------------------------------------------------------------------

    @app_commands.command(
        name="roundtable",
        description="Ask the same question to every available persona.",
    )
    @app_commands.describe(
        prompt="What should I ask?",
    )
    @background_app_command(defer_ephemeral=False)
    async def round_table(
        self,
        interaction: discord.Interaction,
        prompt: str | None = None,
    ) -> None:
        """Send the prompt to *all* personas and stream their replies."""

        if prompt is None:
            prompt = "Hello!"

        # Select provider based on settings
        provider_name: str = getattr(settings, "llm_provider", "gemini")
        try:
            provider = _providers.get(provider_name)
        except KeyError:
            await safe_send(
                interaction,
                f"LLM provider '{provider_name}' is not available.",
                ephemeral=True,
            )
            return

        async def _ask_persona(
            name: str, persona_prompt: str
        ) -> tuple[str, str | None, Exception | None]:
            """Generate a reply for *name* using the shared provider."""
            try:
                chan_id: int = interaction.channel_id or 0
                history_pairs = await self._history.recent(chan_id, name)
                messages = [
                    {
                        "role": "system",
                        "content": DEFAULT_SYSTEM_PROMPT + "\n\n" + persona_prompt,
                    },
                    *(
                        {"role": r, "content": c}
                        for pair in history_pairs
                        for r, c in (("user", pair[0]), ("assistant", pair[1]))
                    ),
                    {"role": "user", "content": prompt},
                ]
                response_text = await provider.generate(messages=messages)
                return (name, cast(str, response_text), None)
            except Exception as exc:
                return (name, None, exc)

        # launch tasks only for visible personas
        visible_items = [
            (n, p["prompt"])
            for n, p in PERSONALITIES.items()
            if persona_visible(n, interaction.user.id)
        ]
        if not visible_items:
            await safe_send(interaction, "No personas available.", ephemeral=True)
            return

        tasks = [
            asyncio.create_task(_ask_persona(n, prompt_str))
            for n, prompt_str in visible_items
        ]

        for coro in asyncio.as_completed(tasks):
            name, text, err = await coro

            # Convert Optional[str] -> str for static typing safety
            safe_text: str = text or ""

            title = f"**{name.capitalize()}**"
            if err is not None:
                await safe_followup(
                    interaction, f"{title} (error): {err}", ephemeral=True
                )
                continue

            # Discord limit handling (2000 chars). Wrap each chunk in its own code block.
            DISCORD_CHAR_LIMIT = settings.discord_chunk_size  # margin for title/prefix

            if len(safe_text) + len(title) + 10 <= DISCORD_CHAR_LIMIT:
                await safe_followup(interaction, f"{title}\n```text\n{safe_text}\n```")
            else:
                raw_chunks = [
                    safe_text[
                        i : i + DISCORD_CHAR_LIMIT - 10
                    ]  # 10 for code fences and margin
                    for i in range(0, len(safe_text), DISCORD_CHAR_LIMIT - 10)
                ]
                for idx, chunk in enumerate(raw_chunks):
                    part_prefix = (
                        f"{title} [Part {idx + 1}/{len(raw_chunks)}]\n"
                        if len(raw_chunks) > 1
                        else f"{title}\n"
                    )
                    await safe_followup(
                        interaction, part_prefix + f"```text\n{chunk}\n```"
                    )

            # record turn in history
            chan_id: int = interaction.channel_id or 0
            await self._history.record(chan_id, name, (prompt or "", safe_text))

    # ------------------------------------------------------------------
    # /chat round-table
    # ------------------------------------------------------------------


async def setup(bot: commands.Bot) -> None:
    """Load the Chat cog, resolving the history backend from the DI container.

    Falls back to the in-memory backend if the container is not wired or
    mis-configured so the bot can still start in development.
    """
    backend = None
    if hasattr(bot, "container"):
        try:
            backend = bot.container.history_backend()
        except Exception:  # pragma: no cover – mis-configuration should not kill bot
            backend = None
    await bot.add_cog(Chat(bot, backend))
